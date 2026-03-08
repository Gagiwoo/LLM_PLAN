"""
RRT / RRT* 경로탐색 알고리즘 (lat, lon 기반)

핵심 수정사항
1) sample_random_node(): goal bias 시 goal 객체를 그대로 반환하지 않고 복사본을 반환
2) steer(): to_node를 그대로 반환하지 않고 항상 새 노드를 반환
3) goal 도달 판정/step 단위 혼동 최소화: step_size_deg는 degree, distance()는 km로 일관 사용
"""

import math
import random
from typing import List, Tuple, Optional
from modules.xai_utils import XAIUtils

# NOTE: 사용 중인 설정값들
from modules.config import GRID_SIZE, MAP_BOUNDS, ALTITUDE_MIN, ALTITUDE_MAX  # noqa: F401


class RRTNode:
    """RRT 노드"""

    def __init__(self, lat: float, lon: float, alt: float = 0.0):
        self.lat = lat
        self.lon = lon
        self.alt = alt
        self.parent: Optional["RRTNode"] = None
        self.cost: float = 0.0  # RRT*용


class RRTPathfinder:
    """RRT 경로탐색"""

    def __init__(self, max_iterations: int = 5000, step_size_deg: float = 0.1):
        self.max_iterations = max_iterations
        self.step_size_deg = step_size_deg  # degree 단위
        self.bounds = [
            MAP_BOUNDS["min_lat"],
            MAP_BOUNDS["max_lat"],
            MAP_BOUNDS["min_lon"],
            MAP_BOUNDS["max_lon"],
        ]

    @staticmethod
    def _deg_to_km_lat(deg: float) -> float:
        return deg * 111.0

    def distance(self, node1: RRTNode, node2: RRTNode) -> float:
        """두 노드 간 거리 (km) - 위경도 근사"""
        return math.sqrt(
            ((node1.lat - node2.lat) * 111.0) ** 2
            + ((node1.lon - node2.lon) * 111.0 * math.cos(math.radians(node1.lat))) ** 2
        )

    # [수정 부분] is_collision 함수 내부
    def is_collision(self, node: RRTNode, threats: List[dict], margin_km: float) -> bool:
        """충돌 체크 (NFZ Strict + 위협 점수 0.5 적용)"""
        # 1. NFZ 충돌 체크 (Strict)
        margin_deg = margin_km / 111.0
        for t in threats:
            if t["type"] == "NFZ":
                if ((t["lat_min"] - margin_deg <= node.lat <= t["lat_max"] + margin_deg) and
                    (t["lon_min"] - margin_deg <= node.lon <= t["lon_max"] + margin_deg)):
                    return True

        # 2. SAM/RADAR 충돌 체크 (Risk Score >= 0.5)
        # 3D 고도 정보를 포함하여 XAI 위협 점수 산출
        risk_score = XAIUtils.calculate_risk_score(
            node.lat, node.lon, threats, margin_km, 
            target_alt=node.alt if node.alt > 0 else None
        )
        return risk_score >= 0.5

    def is_path_clear(
        self, node1: RRTNode, node2: RRTNode, threats: List[dict], margin_km: float, steps: int = 10
    ) -> bool:
        """두 노드 사이 선분이 안전한지 체크(샘플링)"""
        for i in range(steps + 1):
            u = i / steps
            lat = node1.lat + u * (node2.lat - node1.lat)
            lon = node1.lon + u * (node2.lon - node1.lon)
            if self.is_collision(RRTNode(lat, lon), threats, margin_km):
                return False
        return True

    def sample_random_node(self, goal: RRTNode, goal_bias: float = 0.1) -> RRTNode:
        """랜덤 노드 샘플링 (goal bias)

        중요: goal 노드를 그대로 반환하면 tree에 goal 객체가 섞여 parent/cost가 꼬일 수 있으니
        항상 '복사본'을 반환한다. [web:16]
        """
        if random.random() < goal_bias:
            return RRTNode(goal.lat, goal.lon, goal.alt)  # 복사본

        lat = random.uniform(self.bounds[0], self.bounds[1])
        lon = random.uniform(self.bounds[2], self.bounds[3])
        return RRTNode(lat, lon)

    def get_nearest_node(self, tree: List[RRTNode], target: RRTNode) -> RRTNode:
        """트리에서 가장 가까운 노드 찾기"""
        return min(tree, key=lambda node: self.distance(node, target))

    def steer(self, from_node: RRTNode, to_node: RRTNode) -> RRTNode:
        """from_node에서 to_node 방향으로 step_size_deg만큼 간 새 노드 생성

        중요: to_node를 그대로 반환하지 말고 항상 새 노드 반환. [web:16]
        """
        dist_km = self.distance(from_node, to_node)
        max_step_km = self.step_size_deg * 111.0

        if dist_km <= max_step_km:
            # to_node를 그대로 쓰면 객체 재사용 문제가 생길 수 있으므로 복사본 생성
            return RRTNode(to_node.lat, to_node.lon, to_node.alt)

        ratio = max_step_km / dist_km
        new_lat = from_node.lat + ratio * (to_node.lat - from_node.lat)
        new_lon = from_node.lon + ratio * (to_node.lon - from_node.lon)
        return RRTNode(new_lat, new_lon, to_node.alt)

    def _reconstruct_path(self, goal_node: RRTNode) -> List[Tuple[float, float]]:
        path: List[Tuple[float, float]] = []
        cur: Optional[RRTNode] = goal_node
        while cur is not None:
            path.append((cur.lat, cur.lon))
            cur = cur.parent
        return path[::-1]

    def find_path(
        self,
        start: List[float],
        end: List[float],
        threats: List[dict],
        safety_margin_km: float,
        goal_bias: float = 0.1,
        goal_reach_km: float = 5.0,
    ) -> List[Tuple[float, float]]:
        """RRT 경로탐색"""
        start_node = RRTNode(start[0], start[1])
        goal_node = RRTNode(end[0], end[1])

        if self.is_collision(start_node, threats, safety_margin_km):
            print("⚠️ 시작점이 위험영역 내부입니다.")
            return []
        if self.is_collision(goal_node, threats, safety_margin_km):
            print("⚠️ 목표점이 위험영역 내부입니다.")
            return []

        tree = [start_node]

        for i in range(self.max_iterations):
            rand_node = self.sample_random_node(goal_node, goal_bias=goal_bias)

            nearest = self.get_nearest_node(tree, rand_node)

            new_node = self.steer(nearest, rand_node)

            if self.is_collision(new_node, threats, safety_margin_km):
                continue
            if not self.is_path_clear(nearest, new_node, threats, safety_margin_km):
                continue

            new_node.parent = nearest
            tree.append(new_node)

            # 목표 도달 체크 (distance()는 km)
            if self.distance(new_node, goal_node) < goal_reach_km:
                if self.is_path_clear(new_node, goal_node, threats, safety_margin_km):
                    # goal_node도 트리에 넣되, 이미 tree에 섞이지 않도록 여기서만 parent 설정
                    goal_attach = RRTNode(goal_node.lat, goal_node.lon, goal_node.alt)
                    goal_attach.parent = new_node
                    tree.append(goal_attach)

                    path = self._reconstruct_path(goal_attach)
                    print(f"✅ RRT 성공: {i+1}회 반복, 경로 길이 {len(path)}")
                    return path

        print("⚠️ RRT 탐색 실패 (최대 반복 도달)")
        return []


class RRTStarPathfinder(RRTPathfinder):
    """RRT* 경로탐색 (점진적 최적화)"""

    def __init__(self, max_iterations: int = 5000, step_size_deg: float = 0.1, rewire_radius_km: float = 20.0):
        super().__init__(max_iterations, step_size_deg)
        self.rewire_radius_km = rewire_radius_km  # km 단위로 명확화

    def get_nearby_nodes(self, tree: List[RRTNode], center: RRTNode) -> List[RRTNode]:
        """반경 내 노드들 찾기"""
        r = self.rewire_radius_km
        return [node for node in tree if self.distance(node, center) < r]

    def find_path(
        self,
        start: List[float],
        end: List[float],
        threats: List[dict],
        safety_margin_km: float,
        goal_bias: float = 0.1,
        goal_reach_km: float = 5.0,
    ) -> List[Tuple[float, float]]:
        """RRT* 경로탐색"""
        start_node = RRTNode(start[0], start[1])
        start_node.cost = 0.0
        goal_node = RRTNode(end[0], end[1])

        if self.is_collision(start_node, threats, safety_margin_km):
            print("⚠️ 시작점이 위험영역 내부입니다.")
            return []
        if self.is_collision(goal_node, threats, safety_margin_km):
            print("⚠️ 목표점이 위험영역 내부입니다.")
            return []

        tree: List[RRTNode] = [start_node]

        for i in range(self.max_iterations):
            rand_node = self.sample_random_node(goal_node, goal_bias=goal_bias)
            nearest = self.get_nearest_node(tree, rand_node)
            new_node = self.steer(nearest, rand_node)

            if self.is_collision(new_node, threats, safety_margin_km):
                continue
            if not self.is_path_clear(nearest, new_node, threats, safety_margin_km):
                continue

            # 주변 노드 탐색
            nearby = self.get_nearby_nodes(tree, new_node)

            # 최소 비용 부모 선택(choose parent) - RRT* 핵심 [web:22]
            best_parent = nearest
            best_cost = nearest.cost + self.distance(nearest, new_node)

            for near in nearby:
                cand_cost = near.cost + self.distance(near, new_node)
                if cand_cost < best_cost and self.is_path_clear(near, new_node, threats, safety_margin_km):
                    best_cost = cand_cost
                    best_parent = near

            new_node.parent = best_parent
            new_node.cost = best_cost
            tree.append(new_node)

            # Rewiring: 주변 노드들을 new_node를 통해 더 싸게 갈 수 있으면 부모 변경 [web:22]
            for near in nearby:
                new_cost = new_node.cost + self.distance(new_node, near)
                if new_cost < near.cost and self.is_path_clear(new_node, near, threats, safety_margin_km):
                    near.parent = new_node
                    near.cost = new_cost

            # 목표 도달
            if self.distance(new_node, goal_node) < goal_reach_km:
                if self.is_path_clear(new_node, goal_node, threats, safety_margin_km):
                    goal_attach = RRTNode(goal_node.lat, goal_node.lon, goal_node.alt)
                    goal_attach.parent = new_node
                    goal_attach.cost = new_node.cost + self.distance(new_node, goal_attach)
                    tree.append(goal_attach)

                    path = self._reconstruct_path(goal_attach)
                    print(
                        f"✅ RRT* 성공: {i+1}회 반복, 경로 길이 {len(path)}, 비용 {goal_attach.cost:.2f}"
                    )
                    return path

        print("⚠️ RRT* 탐색 실패")
        return []
