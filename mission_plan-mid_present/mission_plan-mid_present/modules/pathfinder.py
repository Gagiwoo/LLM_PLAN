"""
경로탐색 엔진 - 2D/3D A* 통합 (Radar Shadow 지원)
"""
import math
import heapq
import numpy as np
from scipy.interpolate import splprep, splev
from typing import List, Tuple, Optional
from modules.config import GRID_SIZE, MAP_BOUNDS, SMOOTHING_FACTOR, ALTITUDE_LEVELS, ALTITUDE_MIN, ALTITUDE_MAX, MIN_ALTITUDE_AGL

# [핵심] 레이더 음영 계산 모듈 임포트
try:
    from modules.radar_shadow import check_line_of_sight
except ImportError:
    # 파일이 없을 경우를 대비한 더미 함수 (에러 방지용)
    def check_line_of_sight(*args, **kwargs): return True

LAT_TO_KM=110.57


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
    
    def is_collision(self, lat: float, lon: float, threats: List[dict], margin: float) -> bool:
        margin_deg = margin / LAT_TO_KM
        for t in threats:
            if t['type'] in ["SAM", "RADAR"]: # 2D에서는 레이더도 반경으로 처리
                dist_km = math.sqrt(
                    ((lat - t['lat']) * LAT_TO_KM) ** 2 + 
                    ((lon - t['lon']) * LAT_TO_KM * math.cos(math.radians(lat))) ** 2
                )
                if dist_km < (t['radius_km'] + margin):
                    return True
            elif t['type'] == "NFZ":
                if ((t['lat_min'] - margin_deg <= lat <= t['lat_max'] + margin_deg) and
                    (t['lon_min'] - margin_deg <= lon <= t['lon_max'] + margin_deg)):
                    return True
        return False
    
    def find_path(self, start: List[float], end: List[float], threats: List[dict], safety_margin: float) -> List[Tuple[float, float]]:
        start_grid = self.to_grid(start[0], start[1])
        end_grid = self.to_grid(end[0], end[1])
        if start_grid == (-1, -1) or end_grid == (-1, -1): return []
        
        open_set = []
        heapq.heappush(open_set, (0, start_grid))
        came_from = {}
        g_score = {start_grid: 0}
        
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
                if self.is_collision(n_lat, n_lon, threats, safety_margin): continue
                
                tentative_g = g_score[current] + math.sqrt(dx**2 + dy**2)
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
    
    def is_collision_3d(self, lat: float, lon: float, alt: float, threats: List[dict], margin: float) -> bool:
        """3D 충돌 체크 (SAM / RADAR / NFZ 분기)"""
        
        # 현재 위치의 지형 고도 (AGL 계산용)
        try:
            terrain_h = self.terrain.get_elevation(lat, lon)
        except:
            terrain_h = 0
        agl = alt - terrain_h  # AGL (Above Ground Level)
        margin_deg = margin / LAT_TO_KM

        for t in threats:
            # 1. NFZ (비행금지구역) - 고도 불문 금지
            if t['type'] == "NFZ":
                if ((t['lat_min'] - margin_deg <= lat <= t['lat_max'] + margin_deg) and
                    (t['lon_min'] - margin_deg <= lon <= t['lon_max'] + margin_deg)):
                    return True

            # 2. SAM (미사일) 및 RADAR (레이더)
            elif t['type'] in ["SAM", "RADAR"]:
                dist_km = math.sqrt(
                    ((lat - t['lat']) * LAT_TO_KM) ** 2 + 
                    ((lon - t['lon']) * LAT_TO_KM * math.cos(math.radians(lat))) ** 2
                )
                threat_radius = t['radius_km'] + margin
                
                # 반경 밖이면 안전
                if dist_km >= threat_radius:
                    continue

                # --- [A] SAM 특수 로직 (Kill Zone) ---
                if t['type'] == "SAM":
                    # SAM 바로 위(30%)는 광학 조준되므로 무조건 위험
                    kill_zone = t['radius_km'] * 0.3
                    if dist_km < kill_zone:
                        return True

                # --- [B] 공통 로직 (Radar Line-of-Sight) ---
                # 위협의 안테나 높이 (설정 없으면 지형 + 10m)
                threat_alt = t.get('alt', 0)
                if threat_alt == 0:
                    threat_alt = self.terrain.get_elevation(t['lat'], t['lon']) + 10

                # 레이더 음영 체크 (Shadow Check)
                is_visible = check_line_of_sight(
                    radar_pos=(t['lat'], t['lon'], threat_alt),
                    aircraft_pos=(lat, lon, alt),
                    terrain_loader=self.terrain
                )
                
                if not is_visible:
                    # 산에 가려짐 -> 탐지 안 됨 -> 안전
                    continue 
                
                # 레이더에 보임. 하지만 초저고도(AGL < 200m)면 지형 클러터로 회피 인정
                if agl < 200:
                    continue

                # 여기까지 오면 탐지/격추됨
                return True
        
        return False
    
    def is_terrain_collision(self, lat: float, lon: float, alt: float) -> bool:
        """지형 충돌 체크"""
        terrain_elevation = self.terrain.get_elevation(lat, lon)
        if alt < terrain_elevation + MIN_ALTITUDE_AGL:
            return True
        return False
    
    def find_path_3d(self, start: List[float], end: List[float], threats: List[dict], safety_margin: float) -> List[Tuple[float, float, float]]:
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
                
                if self.is_collision_3d(n_lat, n_lon, n_alt, threats, safety_margin): continue
                if self.is_terrain_collision(n_lat, n_lon, n_alt): continue
                
                # 비용 함수: 거리 + 고도(낮을수록 유리)
                move_cost = math.sqrt(dx**2 + dy**2 + (dz * 0.5)**2)
                alt_penalty = (n_alt / 5000.0) * 2.0  # 고도가 높을수록 비용 증가 (저고도 유도)
                
                tentative_g = g_score[current] + move_cost + alt_penalty
                
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