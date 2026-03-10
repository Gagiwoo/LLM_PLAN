"""
경로탐색 엔진 - 2D/3D A* 통합 (Radar Shadow 지원)
"""
import math
import heapq
import numpy as np
from scipy.interpolate import splprep, splev
from typing import List, Tuple, Optional
from modules.xai_utils import XAIUtils
from modules.config import GRID_SIZE, MAP_BOUNDS, SMOOTHING_FACTOR, ALTITUDE_LEVELS, ALTITUDE_MIN, ALTITUDE_MAX, MIN_ALTITUDE_AGL, THREAT_ALT_ENVELOPE
from modules.fuel_model import fuel_risk_modifiers

# [핵심] 레이더 음영 계산 모듈 임포트
try:
    from modules.radar_shadow import check_line_of_sight
except ImportError:
    # 파일이 없을 경우를 대비한 더미 함수 (에러 방지용)
    def check_line_of_sight(*args, **kwargs): return True

LAT_TO_KM=110.57

def _risk_penalty(
    risk_score: float,
    safety_margin: float,
    fuel_state: float = 1.0,
    refuel_count: int = 0,
) -> float:
    """Continuous threat cost used by A* variants."""
    if risk_score <= 0.0:
        return 0.0
    margin_weight = 1.0 + max(0.0, float(safety_margin)) / 5.0
    risk_penalty_scale, _ = fuel_risk_modifiers(fuel_state, refuel_count)
    return (risk_score ** 2) * 20.0 * margin_weight * risk_penalty_scale


def _risk_block_threshold(
    safety_margin: float,
    fuel_state: float = 1.0,
    refuel_count: int = 0,
) -> float:
    base = max(0.28, 0.45 - 0.01 * max(0.0, float(safety_margin)))
    _, threshold_bias = fuel_risk_modifiers(fuel_state, refuel_count)
    return max(0.22, min(0.92, base + threshold_bias))


def _is_in_threat_core(
    lat: float,
    lon: float,
    target_alt_msl: float,
    threats: List[dict],
    margin: float,
) -> bool:
    for t in threats:
        t_type = t.get("type")
        if t_type not in ("SAM", "RADAR"):
            continue
        if t.get("lat") is None or t.get("lon") is None:
            continue

        threat_alt_msl = float(t.get("alt", 0.0))
        rel_alt_m = float(target_alt_msl) - threat_alt_msl
        env = THREAT_ALT_ENVELOPE.get(t_type, {})
        min_alt_m = float(t.get("min_alt_m", env.get("min_alt_m", -1e9)))
        max_alt_m = float(t.get("max_alt_m", env.get("max_alt_m", 1e9)))
        if rel_alt_m < min_alt_m or rel_alt_m > max_alt_m:
            continue

        d2d = math.sqrt(
            ((lat - float(t["lat"])) * LAT_TO_KM) ** 2
            + ((lon - float(t["lon"])) * LAT_TO_KM * math.cos(math.radians(lat))) ** 2
        )
        radius = float(t.get("radius_km", 0.0))
        if radius <= 0.0:
            continue

        core_ratio = 0.45 if t_type == "SAM" else 0.30
        core_radius = min(radius + margin, max(5.0, radius * core_ratio + 0.4 * margin))
        if d2d < core_radius:
            return True
    return False


class AStarPathfinder:
    """2D A* 알고리즘 (기존 유지)"""
    
    def __init__(self, grid_size: int = GRID_SIZE):
        self.grid_size = grid_size
        self.bounds = [
            MAP_BOUNDS["min_lat"],
            MAP_BOUNDS["max_lat"],
            MAP_BOUNDS["min_lon"],
            MAP_BOUNDS["max_lon"]
        ]
        
    def to_grid(self, lat: float, lon: float) -> Tuple[int, int]:
        min_lat, max_lat, min_lon, max_lon = self.bounds
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            return -1, -1
        y = int((lat - min_lat) / ((max_lat - min_lat) / self.grid_size))
        x = int((lon - min_lon) / ((max_lon - min_lon) / self.grid_size))
        return max(0, min(self.grid_size - 1, x)), max(0, min(self.grid_size - 1, y))
    
    def to_latlon(self, x: int, y: int) -> Tuple[float, float]:
        min_lat, max_lat, min_lon, max_lon = self.bounds
        lat = min_lat + (y * ((max_lat - min_lat) / self.grid_size))
        lon = min_lon + (x * ((max_lon - min_lon) / self.grid_size))
        return lat, lon
    
    def is_collision(
        self,
        lat: float,
        lon: float,
        threats: List[dict],
        margin: float,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ) -> bool:
            """
            2D 충돌 검사 로직 (v2.8)
            - NFZ: 엄격한 차단 (Strict)
            - SAM/RADAR: 위협 점수 0.5 이상일 때만 충돌로 간주
            """
            # 1. NFZ: 마진 포함 조금이라도 겹치면 무조건 충돌
            margin_deg = margin / LAT_TO_KM
            for t in threats:
                if t.get("type") == "NFZ":
                    if ((t["lat_min"] - margin_deg <= lat <= t["lat_max"] + margin_deg) and
                        (t["lon_min"] - margin_deg <= lon <= t["lon_max"] + margin_deg)):
                        return True
            
            # 2. SAM/RADAR: 위협 점수 0.5 이상일 때만 충돌로 간주
            # 2D 알고리즘이라도 리스크 계산은 3D(지형+500m)로 수행하여 정확성 유지
            if _is_in_threat_core(lat, lon, 500.0, threats, margin):
                return True
            risk_score = XAIUtils.calculate_risk_score(lat, lon, threats, margin)
            return risk_score >= _risk_block_threshold(margin, fuel_state, refuel_count)
    
    def find_path(
        self,
        start: List[float],
        end: List[float],
        threats: List[dict],
        safety_margin: float,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ) -> List[Tuple[float, float]]:
        start_grid = self.to_grid(start[0], start[1])
        end_grid = self.to_grid(end[0], end[1])
        if start_grid == (-1, -1) or end_grid == (-1, -1): return []
        
        open_set = []
        heapq.heappush(open_set, (0, start_grid))
        came_from = {}
        g_score = {start_grid: 0}
        risk_cache = {}
        
        while open_set:
            current = heapq.heappop(open_set)[1]
            if current == end_grid:
                path = []
                while current in came_from:
                    path.append(self.to_latlon(current[0], current[1]))
                    current = came_from[current]
                path.append(start)
                return path[::-1]
            
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                neighbor = (current[0] + dx, current[1] + dy)
                if not (0 <= neighbor[0] < self.grid_size and 0 <= neighbor[1] < self.grid_size): continue
                
                n_lat, n_lon = self.to_latlon(neighbor[0], neighbor[1])
                if neighbor in risk_cache:
                    risk_score = risk_cache[neighbor]
                else:
                    if _is_in_threat_core(n_lat, n_lon, 500.0, threats, safety_margin):
                        risk_cache[neighbor] = 1.0
                        continue
                    risk_score = XAIUtils.calculate_risk_score(n_lat, n_lon, threats, safety_margin)
                    risk_cache[neighbor] = risk_score
                if risk_score >= _risk_block_threshold(safety_margin, fuel_state, refuel_count):
                    continue
                
                move_cost = math.sqrt(dx**2 + dy**2)
                tentative_g = g_score[current] + move_cost + _risk_penalty(
                    risk_score, safety_margin, fuel_state, refuel_count
                )
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    h = math.sqrt((neighbor[0] - end_grid[0]) ** 2 + (neighbor[1] - end_grid[1]) ** 2)
                    heapq.heappush(open_set, (tentative_g + h, neighbor))
        return []


class AStarPathfinder3D:
    """3D A* 알고리즘 (지형 + 레이더 음영 고려)"""
    
    def __init__(self, terrain_loader, grid_size: int = GRID_SIZE, altitude_levels: int = ALTITUDE_LEVELS):
        self.terrain = terrain_loader
        self.grid_size = grid_size
        self.altitude_levels = altitude_levels
        self.bounds = [
            MAP_BOUNDS["min_lat"],
            MAP_BOUNDS["max_lat"],
            MAP_BOUNDS["min_lon"],
            MAP_BOUNDS["max_lon"]
        ]
        
    def to_grid_3d(self, lat: float, lon: float, alt: float) -> Tuple[int, int, int]:
        min_lat, max_lat, min_lon, max_lon = self.bounds
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            return -1, -1, -1
        y = int((lat - min_lat) / ((max_lat - min_lat) / self.grid_size))
        x = int((lon - min_lon) / ((max_lon - min_lon) / self.grid_size))
        z = int((alt - ALTITUDE_MIN) / ((ALTITUDE_MAX - ALTITUDE_MIN) / self.altitude_levels))
        return max(0, min(self.grid_size - 1, x)), max(0, min(self.grid_size - 1, y)), max(0, min(self.altitude_levels - 1, z))
    
    def to_latlonalt(self, x: int, y: int, z: int) -> Tuple[float, float, float]:
        min_lat, max_lat, min_lon, max_lon = self.bounds
        lat = min_lat + (y * ((max_lat - min_lat) / self.grid_size))
        lon = min_lon + (x * ((max_lon - min_lon) / self.grid_size))
        alt = ALTITUDE_MIN + (z * ((ALTITUDE_MAX - ALTITUDE_MIN) / self.altitude_levels))
        return lat, lon, alt
    
    def is_collision_3d(
        self,
        lat: float,
        lon: float,
        alt: float,
        threats: List[dict],
        margin: float,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ) -> bool:
            """
            3D 충돌 검사 로직 (v2.8)
            - NFZ: 엄격한 차단
            - SAM/RADAR: 3D 고도 반영 위협 점수 0.5 임계치 적용
            """
            # 1. NFZ: 엄격한 차단
            margin_deg = margin / LAT_TO_KM
            for t in threats:
                if t.get("type") == "NFZ":
                    if ((t["lat_min"] - margin_deg <= lat <= t["lat_max"] + margin_deg) and
                        (t["lon_min"] - margin_deg <= lon <= t["lon_max"] + margin_deg)):
                        return True

            # 2. SAM/RADAR: 3D 고도 반영 리스크 체크 (Threshold 0.5)
            if _is_in_threat_core(lat, lon, alt, threats, margin):
                return True
            risk_score = XAIUtils.calculate_risk_score(
                lat, lon, threats, margin, 
                terrain_loader=self.terrain, target_alt=alt
            )
            return risk_score >= _risk_block_threshold(margin, fuel_state, refuel_count)
    
    def is_terrain_collision(self, lat: float, lon: float, alt: float) -> bool:
        """지형 충돌 체크"""
        terrain_elevation = self.terrain.get_elevation(lat, lon)
        if alt < terrain_elevation + MIN_ALTITUDE_AGL:
            return True
        return False
    
    def find_path_3d(
        self,
        start: List[float],
        end: List[float],
        threats: List[dict],
        safety_margin: float,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ) -> List[Tuple[float, float, float]]:
        if len(start) == 2:
            start_elev = self.terrain.get_elevation(start[0], start[1])
            start = [start[0], start[1], start_elev + 500]
        if len(end) == 2:
            end_elev = self.terrain.get_elevation(end[0], end[1])
            end = [end[0], end[1], end_elev + 500]
        
        start_grid = self.to_grid_3d(*start)
        end_grid = self.to_grid_3d(*end)
        
        if start_grid == (-1, -1, -1) or end_grid == (-1, -1, -1):
            return []
        
        open_set = []
        heapq.heappush(open_set, (0, start_grid))
        came_from = {}
        g_score = {start_grid: 0}
        risk_cache = {}
        
        # 26방향 이동
        directions = [(dx, dy, dz) for dx in [-1,0,1] for dy in [-1,0,1] for dz in [-1,0,1] if not (dx==dy==dz==0)]
        nodes_explored = 0
        
        while open_set:
            current = heapq.heappop(open_set)[1]
            nodes_explored += 1
            if nodes_explored > 50000:
                print("⚠️ 3D 탐색 시간 초과")
                break
            
            if current == end_grid:
                path = []
                while current in came_from:
                    path.append(self.to_latlonalt(*current))
                    current = came_from[current]
                path.append(start)
                return path[::-1]
            
            for dx, dy, dz in directions:
                neighbor = (current[0] + dx, current[1] + dy, current[2] + dz)
                
                if not (0 <= neighbor[0] < self.grid_size and 
                        0 <= neighbor[1] < self.grid_size and
                        0 <= neighbor[2] < self.altitude_levels):
                    continue
                
                n_lat, n_lon, n_alt = self.to_latlonalt(*neighbor)
                
                if neighbor in risk_cache:
                    risk_score = risk_cache[neighbor]
                else:
                    if _is_in_threat_core(n_lat, n_lon, n_alt, threats, safety_margin):
                        risk_cache[neighbor] = 1.0
                        continue
                    risk_score = XAIUtils.calculate_risk_score(
                        n_lat, n_lon, threats, safety_margin,
                        terrain_loader=self.terrain, target_alt=n_alt
                    )
                    risk_cache[neighbor] = risk_score
                if risk_score >= _risk_block_threshold(safety_margin, fuel_state, refuel_count): continue
                if self.is_terrain_collision(n_lat, n_lon, n_alt): continue
                
                # 비용 함수: 거리 + 고도(낮을수록 유리)
                move_cost = math.sqrt(dx**2 + dy**2 + (dz * 0.5)**2)
                alt_penalty = (n_alt / 5000.0) * 2.0  # 고도가 높을수록 비용 증가 (저고도 유도)
                
                risk_penalty = _risk_penalty(risk_score, safety_margin, fuel_state, refuel_count)
                tentative_g = g_score[current] + move_cost + alt_penalty + risk_penalty
                
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    h = math.sqrt((neighbor[0]-end_grid[0])**2 + (neighbor[1]-end_grid[1])**2 + (neighbor[2]-end_grid[2])**2)
                    heapq.heappush(open_set, (tentative_g + h, neighbor))
        
        return []


def smooth_path(path_coords):
    return path_coords  # 2D 평탄화 생략 (안정성)

def smooth_path_3d(path_coords):
    return path_coords  # 3D 평탄화 생략 (튀는 현상 방지)
