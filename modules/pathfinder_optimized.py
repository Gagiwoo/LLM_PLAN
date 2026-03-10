"""
A* 3D Optimized Pathfinder (List 호환 수정 버전)
- TerrainCacheFast: 리스트 형태의 데이터셋 지원
- Altitude quantization + near-goal termination
"""

import math
import heapq
import numpy as np
from typing import List, Tuple
from modules.xai_utils import XAIUtils
from modules.config import MAP_BOUNDS, GRID_SIZE, ALTITUDE_MIN, ALTITUDE_MAX, MIN_ALTITUDE_AGL, THREAT_ALT_ENVELOPE
from modules.fuel_model import fuel_risk_modifiers

LAT_TO_KM = 110.57


class TerrainCacheFast:
    """RAM 기반 고속 DEM 캐시"""

    def __init__(self, terrain_loader):
        self.terrain = terrain_loader
        self.cache = terrain_loader.cache
        self.grids = {}
        self.bounds = {}
        self.pixel_size = {}

        # [수정] 딕셔너리(.items())가 아닌 리스트 순회로 변경
        # TerrainLoader.datasets는 [(bounds, ds_obj), ...] 형태임
        if isinstance(terrain_loader.datasets, list):
            for i, (bounds, ds) in enumerate(terrain_loader.datasets):
                name = f"tile_{i}"  # 임의의 타일 이름 생성
                try:
                    data = ds.read(1)  # numpy array 전체 로드
                    self.grids[name] = data
                    self.bounds[name] = bounds
                    self.pixel_size[name] = (
                        (bounds.right - bounds.left) / ds.width,
                        (bounds.top - bounds.bottom) / ds.height,
                    )
                except Exception as e:
                    print(f"⚠️ 타일 캐싱 실패 ({name}): {e}")
        
        # 만약 딕셔너리라면 (구버전 호환)
        elif isinstance(terrain_loader.datasets, dict):
            for name, ds in terrain_loader.datasets.items():
                data = ds.read(1)
                self.grids[name] = data
                self.bounds[name] = ds.bounds
                self.pixel_size[name] = (
                    (ds.bounds.right - ds.bounds.left) / ds.width,
                    (ds.bounds.top - ds.bounds.bottom) / ds.height,
                )

        print(f"✅ TerrainCacheFast 초기화 완료 ({len(self.grids)} tiles loaded)")

    def get(self, lat: float, lon: float) -> float:
        """빠른 DEM 조회"""
        key = (round(lat, 3), round(lon, 3))
        if key in self.cache:
            return self.cache[key]

        # 메모리에 로드된 그리드에서 검색
        for name, b in self.bounds.items():
            if b.bottom <= lat <= b.top and b.left <= lon <= b.right:
                pw, ph = self.pixel_size[name]
                
                # 좌표 -> 픽셀 인덱스
                col = int((lon - b.left) / pw)
                row = int((b.top - lat) / ph)
                
                # 배열 범위 체크
                h, w = self.grids[name].shape
                if 0 <= row < h and 0 <= col < w:
                    elev = float(self.grids[name][row, col])
                    # NoData 처리
                    if elev < -100: elev = 0.0
                    
                    self.cache[key] = elev
                    return elev
        
        # 데이터가 없으면 기본값 (또는 가상 지형 생성 로직 연결 가능)
        self.cache[key] = 100.0
        return 100.0


class AStarPathfinder3DOptimized:
    """고속 A* 3D 경로탐색"""

    def __init__(self, terrain_cache, grid_size: int = GRID_SIZE, altitude_levels: int = 20):
        self.terrain = terrain_cache
        self.grid_size = grid_size
        self.altitude_levels = altitude_levels
        self.bounds = [
            MAP_BOUNDS["min_lat"],
            MAP_BOUNDS["max_lat"],
            MAP_BOUNDS["min_lon"],
            MAP_BOUNDS["max_lon"],
        ]

    # --- 좌표 변환 ---
    def to_grid_3d(self, lat, lon, alt):
        min_lat, max_lat, min_lon, max_lon = self.bounds
        y = int((lat - min_lat) / ((max_lat - min_lat) / self.grid_size))
        x = int((lon - min_lon) / ((max_lon - min_lon) / self.grid_size))
        z = int((alt - ALTITUDE_MIN) / ((ALTITUDE_MAX - ALTITUDE_MIN) / self.altitude_levels))
        return max(0, min(self.grid_size - 1, x)), max(0, min(self.grid_size - 1, y)), max(0, min(self.altitude_levels - 1, z))

    def to_latlonalt(self, x, y, z):
        min_lat, max_lat, min_lon, max_lon = self.bounds
        lat = min_lat + (y * ((max_lat - min_lat) / self.grid_size))
        lon = min_lon + (x * ((max_lon - min_lon) / self.grid_size))
        alt = ALTITUDE_MIN + (z * ((ALTITUDE_MAX - ALTITUDE_MIN) / self.altitude_levels))
        return lat, lon, alt

    # --- 유틸 ---
    def heuristic(self, a, b, alt_weight=0.1):
        dx, dy, dz = abs(a[0]-b[0]), abs(a[1]-b[1]), abs(a[2]-b[2])
        return math.sqrt(dx**2 + dy**2 + (dz * alt_weight)**2)

    def distance(self, a, b):
        return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

    def reconstruct(self, came_from, current):
        path = []
        while current in came_from:
            path.append(self.to_latlonalt(*current))
            current = came_from[current]
        return path[::-1]

    # [수정 부분] is_collision_3d 함수 내부
    def is_collision_3d(
        self,
        lat,
        lon,
        alt,
        threats,
        margin,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ):
        """
        3D 위협 충돌 검사:
        - NFZ: 마진 포함 조금이라도 겹치면 즉시 충돌 (Strict)
        - SAM/RADAR: XAI 위협 점수가 0.5 이상일 때만 충돌로 간주
        """
        # 1. NFZ: 절대 진입 금지 (Strict Collision)
        margin_deg = margin / LAT_TO_KM
        for t in threats:
            if t.get("type") == "NFZ":
                if ((t["lat_min"] - margin_deg <= lat <= t["lat_max"] + margin_deg) and
                    (t["lon_min"] - margin_deg <= lon <= t["lon_max"] + margin_deg)):
                    return True
        
        # 2. 전술 위협: 위험 점수 기반 충돌 판단 (Threshold 0.5)
        # XAIUtils를 호출하여 3D 거리와 음영을 모두 고려한 점수 확인
        if self.is_in_threat_core(lat, lon, alt, threats, margin):
            return True

        risk_score = XAIUtils.calculate_risk_score(
            lat, lon, threats, margin, 
            terrain_loader=self.terrain, target_alt=alt
        )
        return risk_score >= self.risk_block_threshold(margin, fuel_state, refuel_count)

    def risk_penalty(
        self,
        risk_score: float,
        safety_margin: float,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ) -> float:
        """
        Apply continuous threat penalty so planner prefers low-risk detours.
        Penalty grows with both risk score and requested safety margin.
        """
        if risk_score <= 0.0:
            return 0.0
        margin_weight = 1.0 + max(0.0, float(safety_margin)) / 5.0
        risk_penalty_scale, _ = fuel_risk_modifiers(fuel_state, refuel_count)
        return (risk_score ** 2) * 20.0 * margin_weight * risk_penalty_scale

    def risk_block_threshold(
        self,
        safety_margin: float,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ) -> float:
        """
        Lower threshold for larger margins so planner avoids threat-dense corridors.
        """
        base = max(0.28, 0.45 - 0.01 * max(0.0, float(safety_margin)))
        _, threshold_bias = fuel_risk_modifiers(fuel_state, refuel_count)
        return max(0.22, min(0.92, base + threshold_bias))

    def is_in_threat_core(self, lat: float, lon: float, alt: float, threats: List[dict], margin: float) -> bool:
        """
        Hard-block threat centers so path does not cut through obvious high-danger zones.
        """
        for t in threats:
            t_type = t.get("type")
            if t_type not in ("SAM", "RADAR"):
                continue
            if t.get("lat") is None or t.get("lon") is None:
                continue

            # Altitude envelope gating
            threat_alt_msl = float(t.get("alt", 0.0))
            rel_alt_m = float(alt) - threat_alt_msl
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

    # --- 메인 경로탐색 ---
    def find_path_3d_fast(
        self,
        start,
        end,
        threats,
        safety_margin,
        fuel_state: float = 1.0,
        refuel_count: int = 0,
    ):
        # 2D 좌표면 고도 자동 할당
        if len(start) == 2:
            s_elev = self.terrain.get(*start)
            start = [*start, s_elev + 500]
        if len(end) == 2:
            e_elev = self.terrain.get(*end)
            end = [*end, e_elev + 500]

        start_grid = self.to_grid_3d(*start)
        end_grid = self.to_grid_3d(*end)
        
        open_set = [(0, start_grid)]
        came_from, g_score = {}, {start_grid: 0}
        
        # 26방향 (상하좌우대각선)
        directions = [(dx, dy, dz) for dx in [-1,0,1] for dy in [-1,0,1] for dz in [-1,0,1] if not (dx==dy==dz==0)]

        nodes_explored = 0
        best_dist = float('inf')  # 탐색 중 목표에 가장 가까운 노드
        best_node = start_grid
        risk_cache = {}

        while open_set:
            current = heapq.heappop(open_set)[1]
            nodes_explored += 1
            
            # 목표까지 거리
            d = self.distance(current, end_grid)
            if d < best_dist:
                best_dist = d
                best_node = current

            # 근접 도달 허용 (Grid 단위 3칸 이내로 완화)
            if d < 3:
                return self.reconstruct(came_from, current)

            if nodes_explored > 100000:  # 탐색 한도 100k로 확장
                print(f"⚠️ 탐색 제한 초과 (100k nodes), 최근접 노드 반환")
                # 탐색 실패 시 지금까지 가장 가까이 간 경로 반환 (부분 경로)
                return self.reconstruct(came_from, best_node)
                break

            for dx, dy, dz in directions:
                neighbor = (current[0]+dx, current[1]+dy, current[2]+dz)
                
                # 범위 체크
                if not (0 <= neighbor[0] < self.grid_size and 
                        0 <= neighbor[1] < self.grid_size and 
                        0 <= neighbor[2] < self.altitude_levels):
                    continue

                n_lat, n_lon, n_alt = self.to_latlonalt(*neighbor)
                
                # 지형 충돌 (AGL)
                elev = self.terrain.get(n_lat, n_lon)
                if n_alt < elev + MIN_ALTITUDE_AGL:
                    continue
                
                # 위협 충돌
                if neighbor in risk_cache:
                    risk_score = risk_cache[neighbor]
                else:
                    if self.is_in_threat_core(n_lat, n_lon, n_alt, threats, safety_margin):
                        risk_cache[neighbor] = 1.0
                        continue
                    risk_score = XAIUtils.calculate_risk_score(
                        n_lat, n_lon, threats, safety_margin,
                        terrain_loader=self.terrain, target_alt=n_alt
                    )
                    risk_cache[neighbor] = risk_score
                if risk_score >= self.risk_block_threshold(safety_margin, fuel_state, refuel_count):
                    continue

                # 비용 계산
                move_cost = math.sqrt(dx**2 + dy**2 + (dz * 0.5)**2)
                risk_cost = self.risk_penalty(risk_score, safety_margin, fuel_state, refuel_count)
                tentative_g = g_score[current] + move_cost + risk_cost
                
                if neighbor not in g_score or tentative_g < g_score[neighbor]:
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    f = tentative_g + self.heuristic(neighbor, end_grid)
                    heapq.heappush(open_set, (f, neighbor))

        # open_set 소진 → 지금까지 가장 가까운 노드까지의 부분 경로 반환
        if best_node != start_grid and best_node in came_from:
            print(f"⚠️ 경로 탐색 부분 성공 (목표거리: {best_dist:.1f} 그리드)")
            return self.reconstruct(came_from, best_node)
        print("❌ 경로 탐색 실패")
        return []
