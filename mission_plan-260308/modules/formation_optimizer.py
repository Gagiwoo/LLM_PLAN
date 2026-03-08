"""
Formation Optimizer v1.0
편대 구성 최적화 - MILP + 헝가리안 알고리즘

[MILP] 몇 대를 쓸지 결정
[헝가리안] 누가 뭘 할지 배정

교리 근거:
- JP3-30: Apportionment → Allocation → Tasking by Effect
- AFDP3-03: ISR→SEAD→STRIKE 순서
- FMI3-04.155: MUM-T Lead/Wingman (유인1:무인2)
"""
import time
from typing import List, Dict, Tuple, Optional
import numpy as np

try:
    from pulp import (
        LpProblem, LpMinimize, LpVariable, LpInteger,
        lpSum, value, LpStatus, PULP_CBC_CMD
    )
    PULP_AVAILABLE = True
except ImportError:
    PULP_AVAILABLE = False

from scipy.optimize import linear_sum_assignment

from modules.config import (
    ASSET_COST, ASSET_MAX, FORMATION_MAX_TOTAL,
    MISSION_ASSET_REQUIREMENTS, MUMT_RATIO,
    ASSET_PERFORMANCE, AIRPORTS
)
from modules.mission_state import Asset, FormationResult


# ================================================================
# MILP 편대 구성 최적화
# ================================================================

class FormationMILP:
    """
    MILP 기반 편대 구성 최적화
    결정: 전투기 x_f대, 정찰UAV x_r대, 자폭UAV x_k대

    목적함수: min(c_f·x_f + c_r·x_r + c_k·x_k)
    제약조건: 교리 기반 (JP3-30, FMI3-04.155)
    """

    def __init__(self):
        self.c_f = ASSET_COST["fighter"]
        self.c_r = ASSET_COST["recon_uav"]
        self.c_k = ASSET_COST["attack_uav"]

    def optimize(
        self,
        mission_types: List[str],
        n_targets: int = 1,
        max_total: int = FORMATION_MAX_TOTAL,
        utilization_rate: float = 0.75,
        doctrine_policy: Optional[Dict] = None
    ) -> Dict:
        """
        MILP 실행 (v1.1 - 다목적 최적화: 비용최소화 + 전력활용 균형)

        목적함수 개선:
        - 단순 비용최소화 → 가중합 다목적 (비용최소 + 자산활용률)
        - JP3-30: "충분한 전력 집중으로 임무 성공률 극대화"
        - 슬랙 변수로 N_max의 utilization_rate 이상 활용 권장

        Args:
            mission_types: 수행할 임무 목록
            n_targets: 목표 수
            max_total: 최대 자산 수 (N_max)
            utilization_rate: N_max 권장 활용률 (기본 75%)

        Returns:
            {n_fighter, n_recon_uav, n_attack_uav, total_cost, status, solve_time_ms}
        """
        if not PULP_AVAILABLE:
            return self._heuristic_fallback(mission_types, n_targets, max_total, doctrine_policy)

        start_t = time.time()

        # ── 문제 정의 ──
        prob = LpProblem("FormationOptimizer", LpMinimize)

        # 결정 변수 (정수)
        x_f = LpVariable("x_fighter",    lowBound=0, upBound=ASSET_MAX["fighter"],    cat=LpInteger)
        x_r = LpVariable("x_recon_uav",  lowBound=0, upBound=ASSET_MAX["recon_uav"],  cat=LpInteger)
        x_k = LpVariable("x_attack_uav", lowBound=0, upBound=ASSET_MAX["attack_uav"], cat=LpInteger)

        # 슬랙 변수: 목표 활용률 미달분 (페널티용)
        # slack ≥ 0: target_total - (x_f + x_r + x_k) 가 양수면 미달
        policy = doctrine_policy or {}
        util_override = policy.get("utilization_rate")
        if util_override is not None:
            try:
                utilization_rate = float(util_override)
            except Exception:
                pass
        utilization_rate = max(0.0, min(1.0, float(utilization_rate)))

        target_total = int(max_total * utilization_rate)
        slack = LpVariable("slack_underuse", lowBound=0, cat=LpInteger)

        # ── 다목적 목적함수 (가중합) ──
        # W1=1.0: 비용 최소화 (원래 목적)
        # W2=5.0: 전력 활용 미달 페널티 (UAV 추가비용 2~4 > W2*1이므로 활용 강제)
        # 근거: JP3-30 "Mass - 결정적 지점에서 전투력 집중"
        # 수학적 근거: W2 > max(c_f, c_r, c_k) = 4 이어야 slack 감소를 항상 선호
        W1, W2 = 1.0, 5.0
        cost_term = self.c_f * x_f + self.c_r * x_r + self.c_k * x_k
        prob += W1 * cost_term + W2 * slack, "MultiObjective"

        # ── 슬랙 제약: slack ≥ target_total - (x_f+x_r+x_k) ──
        prob += slack >= target_total - (x_f + x_r + x_k), "UtilizationSlack"

        # ── 제약 1: 총 자산 수 상한 (JP3-30 운용 한계) ──
        prob += x_f + x_r + x_k <= max_total, "MaxTotal"

        # ── 제약 2: 임무별 최소 자산 요구 (교리 기반) ──
        req_f = req_r = req_k = 0
        for m_type in mission_types:
            reqs = MISSION_ASSET_REQUIREMENTS.get(m_type, {})
            req_f = max(req_f, reqs.get("fighter",    0))
            req_r = max(req_r, reqs.get("recon_uav",  0))
            req_k = max(req_k, reqs.get("attack_uav", 0))

        req_f = max(req_f, int(policy.get("min_fighter", 0) or 0))
        req_r = max(req_r, int(policy.get("min_recon_uav", 0) or 0))
        req_k = max(req_k, int(policy.get("min_attack_uav", 0) or 0))

        if req_f > 0:
            prob += x_f >= req_f, "MinFighter"
        if req_r > 0:
            prob += x_r >= req_r, "MinReconUAV"
        if req_k > 0:
            prob += x_k >= req_k, "MinAttackUAV"

        # ── 제약 3: MUM-T 비율 (FMI3-04.155: 무인 ≥ 2 × 유인) ──
        mumt_ratio = float(policy.get("mumt_ratio", MUMT_RATIO))
        if req_f > 0 or "STRIKE" in mission_types or "SEAD" in mission_types:
            prob += x_r + x_k >= mumt_ratio * x_f, "MUMTRatio"

        recon_ratio_cap = policy.get("max_recon_to_strike_ratio", None)
        if recon_ratio_cap is not None:
            try:
                recon_ratio_cap = float(recon_ratio_cap)
                if recon_ratio_cap >= 0.0:
                    allowance = int(policy.get("recon_bias_allowance", 1) or 0)
                    prob += x_r <= recon_ratio_cap * (x_f + x_k) + allowance, "ReconBiasCap"
            except Exception:
                pass

        # ── 제약 4: 목표 커버 (목표당 최소 타격 자산 1대) ──
        if "STRIKE" in mission_types or "SEAD" in mission_types:
            prob += x_f + x_k >= n_targets, "TargetCoverage"

        # ── 제약 5: ISR 다중화 (중요 임무 시 정찰 redundancy) ──
        # FMI3-04.155: ISR 로테이션을 위해 최소 2대 권장
        if "ISR" in mission_types:
            prob += x_r >= 2, "ISRRedundancy"

        # ── 제약 6: SEAD 후 STRIKE 시 추가 ISR 보강 ──
        # JP3-30 MAAP: SEAD+STRIKE 패키지는 ISR 지원 필수
        if "SEAD" in mission_types and "STRIKE" in mission_types:
            prob += x_r >= 1, "SEADSTRIKERecon"

        # ── 최소 1대 ──
        prob += x_f + x_r + x_k >= 1, "MinOne"

        # ── 풀기 ──
        prob.solve(PULP_CBC_CMD(msg=0))

        solve_time = (time.time() - start_t) * 1000
        status = LpStatus[prob.status]

        if status == "Optimal":
            n_f = int(value(x_f))
            n_r = int(value(x_r))
            n_k = int(value(x_k))
            actual_cost = self.c_f * n_f + self.c_r * n_r + self.c_k * n_k
            return {
                "n_fighter":      n_f,
                "n_recon_uav":    n_r,
                "n_attack_uav":   n_k,
                "total_cost":     round(actual_cost, 1),
                "status":         "Optimal",
                "solve_time_ms":  round(solve_time, 2),
                "is_feasible":    True,
                "utilization":    round((n_f + n_r + n_k) / max_total * 100),
            }
        else:
            result = self._heuristic_fallback(mission_types, n_targets, max_total, doctrine_policy)
            result["status"] = f"Fallback({status})"
            return result

    def _heuristic_fallback(
        self,
        mission_types: List[str],
        n_targets: int,
        max_total: int = FORMATION_MAX_TOTAL,
        doctrine_policy: Optional[Dict] = None
    ) -> Dict:
        """
        PuLP 없거나 MILP 실패 시 규칙 기반 편대 구성
        N_max 75% 이상 활용하면서 교리 요구 충족
        """
        policy = doctrine_policy or {}
        f = r = k = 0
        for m in mission_types:
            reqs = MISSION_ASSET_REQUIREMENTS.get(m, {})
            f = max(f, reqs.get("fighter",    0))
            r = max(r, reqs.get("recon_uav",  0))
            k = max(k, reqs.get("attack_uav", 0))

        f = max(f, int(policy.get("min_fighter", 0) or 0))
        r = max(r, int(policy.get("min_recon_uav", 0) or 0))
        k = max(k, int(policy.get("min_attack_uav", 0) or 0))

        # ISR 최소 2대 보장
        if "ISR" in mission_types:
            r = max(r, 2)

        # MUM-T 비율 보정
        mumt_ratio = float(policy.get("mumt_ratio", MUMT_RATIO))
        if f > 0:
            while (r + k) < mumt_ratio * f:
                if "ISR" in mission_types:
                    r += 1
                else:
                    k += 1

        # 목표 커버
        if "STRIKE" in mission_types or "SEAD" in mission_types:
            while f + k < n_targets:
                f += 1

        # N_max 75% 활용 - 남은 슬롯을 UAV로 채움
        util = float(policy.get("utilization_rate", 0.75) or 0.75)
        util = max(0.0, min(1.0, util))
        target = int(max_total * util)
        while (f + r + k) < target and (f + r + k) < max_total:
            if "ISR" in mission_types and r < ASSET_MAX["recon_uav"]:
                r += 1
            elif k < ASSET_MAX["attack_uav"]:
                k += 1
            elif f < ASSET_MAX["fighter"]:
                f += 1
            else:
                break

        recon_ratio_cap = policy.get("max_recon_to_strike_ratio", None)
        if recon_ratio_cap is not None:
            try:
                cap = float(recon_ratio_cap)
                allowance = int(policy.get("recon_bias_allowance", 1) or 0)
                max_r = int(cap * (f + k) + allowance)
                r = min(r, max_r)
            except Exception:
                pass

        cost = self.c_f * f + self.c_r * r + self.c_k * k
        return {
            "n_fighter":    f,
            "n_recon_uav":  r,
            "n_attack_uav": k,
            "total_cost":   cost,
            "status":       "Heuristic",
            "solve_time_ms": 0.0,
            "is_feasible":  True,
            "utilization":  round((f + r + k) / max_total * 100),
        }


# ================================================================
# 헝가리안 알고리즘 자산 배정
# ================================================================

class AssetAssigner:
    """
    헝가리안 알고리즘으로 자산 ↔ 목표 1:1 최적 배정
    근거: JP3-30 "Tasking by Effect" 원칙

    비용 행렬 구성:
    - 자산에서 목표까지의 거리
    - 자산 타입과 임무 적합도
    - 위협 노출 위험도
    """

    # 자산 타입별 임무 적합도 (낮을수록 좋음 = 비용)
    MISSION_FIT = {
        "fighter": {
            "ISR":    5.0,  # 전투기는 ISR 비효율
            "SEAD":   1.0,  # SEAD 적합
            "STRIKE": 1.0,  # STRIKE 최적
            "CAS":    1.5,
        },
        "recon_uav": {
            "ISR":    1.0,  # ISR 최적
            "SEAD":   8.0,  # SEAD 부적합
            "STRIKE": 8.0,
            "CAS":    5.0,
        },
        "attack_uav": {
            "ISR":    5.0,
            "SEAD":   1.5,  # SEAD 적합
            "STRIKE": 2.0,  # STRIKE 가능
            "CAS":    3.0,
        },
    }

    def assign(
        self,
        assets: List[Asset],
        targets: List[Dict],
        mission_sequence: List[str],
        threats: List[Dict] = None
    ) -> List[Asset]:
        """
        헝가리안 알고리즘으로 자산↔임무 배정 (개선 v1.1)

        핵심 변경:
        - 목표 수보다 자산이 많을 때: 각 자산이 자신의 타입에 맞는 임무를 항상 가짐
        - 타격 자산(fighter, attack_uav)만 목표에 1:1 배정
        - 지원 자산(recon_uav)은 ISR 임무로 자동 배정 (대기/지원)
        - 근거: JP3-30 "각 자산은 임무 시퀀스 내 역할을 가져야 한다"

        Args:
            assets: 자산 목록
            targets: 목표 목록 [{"lat":..., "lon":..., "name":...}]
            mission_sequence: 임무 순서 (예: ["ISR","SEAD","STRIKE"])
            threats: 위협 목록 (위험도 가중치용)

        Returns:
            배정 완료된 자산 목록 (assigned_mission, assigned_target_idx 채워짐)
        """
        if not assets:
            return assets

        # ── Step 1: 모든 자산에 타입 기반 기본 임무 먼저 배정 ──
        # 근거: JP3-30 MAAP - 모든 자산은 임무 시퀀스 내 역할을 가져야 함
        for asset in assets:
            asset.assigned_mission = self._get_mission_for_asset(
                asset.asset_type, mission_sequence
            )
            asset.assigned_target_idx = None  # 기본: 목표 없음 (지원 역할)

        if not targets:
            return assets

        # ── Step 2: 타격 가능 자산만 필터링해서 목표에 헝가리안 배정 ──
        # 타격 역할 자산: fighter(STRIKE/SEAD), attack_uav(SEAD/STRIKE)
        # 지원 역할 자산: recon_uav(ISR) → 목표 배정 불필요
        STRIKE_CAPABLE = {
            "fighter":    ["STRIKE", "SEAD", "CAS"],
            "attack_uav": ["SEAD", "STRIKE"],
            "recon_uav":  [],  # ISR 전용 - 직접 타격 불가
        }

        strike_assets = [
            (i, a) for i, a in enumerate(assets)
            if any(m in mission_sequence for m in STRIKE_CAPABLE.get(a.asset_type, []))
        ]

        if not strike_assets:
            return assets

        n_strike = len(strike_assets)
        n_targets = len(targets)
        size = max(n_strike, n_targets)

        # ── 비용 행렬 구성 (strike_assets × targets) ──
        cost_matrix = np.full((size, size), 9999.0)

        for idx, (orig_i, asset) in enumerate(strike_assets):
            for j, target in enumerate(targets):
                # 1. 거리 비용
                dist = self._calc_distance(asset, target)

                # 2. 임무 적합도 (자산타입 × 임무유형)
                best_mission = self._get_mission_for_asset(asset.asset_type, mission_sequence)
                fit = self.MISSION_FIT.get(asset.asset_type, {}).get(best_mission, 3.0)

                # 3. 위협 노출 위험도
                threat_risk = self._calc_threat_risk(asset, target, threats or [])

                # 최종 비용 = 거리 × 적합도 × (1 + 위험도)
                cost_matrix[idx][j] = dist * fit * (1.0 + threat_risk)

        # ── 헝가리안 알고리즘 실행 ──
        row_idx, col_idx = linear_sum_assignment(cost_matrix)

        # ── 배정 결과 적용 (타격 자산 → 목표 연결) ──
        for idx, j in zip(row_idx, col_idx):
            if idx < n_strike and j < n_targets:
                orig_i, asset = strike_assets[idx]
                # 타격 임무로 업데이트 + 목표 인덱스 배정
                best_mission = self._get_mission_for_asset(asset.asset_type, mission_sequence)
                assets[orig_i].assigned_mission = best_mission
                assets[orig_i].assigned_target_idx = j

        # ── 타겟이 strike_assets보다 많은 경우: 남은 지원자산에도 보조 배정 ──
        assigned_targets = {
            assets[orig_i].assigned_target_idx
            for _, (orig_i, _) in enumerate(strike_assets)
            if assets[orig_i].assigned_target_idx is not None
        }
        unassigned_targets = [j for j in range(n_targets) if j not in assigned_targets]

        # 정찰 UAV는 ISR 지원 임무 (목표 감시)로 활용
        recon_assets = [(i, a) for i, a in enumerate(assets) if a.asset_type == "recon_uav"]
        for target_j in unassigned_targets:
            for i, asset in recon_assets:
                if assets[i].assigned_target_idx is None:
                    assets[i].assigned_mission = "ISR"
                    assets[i].assigned_target_idx = target_j
                    break

        return assets

    def _calc_distance(self, asset: Asset, target: Dict) -> float:
        """자산 출발기지 → 목표까지 유클리드 거리 (위경도 근사)"""
        from modules.config import AIRPORTS
        base_coords = AIRPORTS.get(asset.base, {}).get("coords", [37.0, 127.0])
        dlat = base_coords[0] - target.get("lat", 37.0)
        dlon = base_coords[1] - target.get("lon", 127.0)
        return float(np.sqrt(dlat**2 + dlon**2) * 111.0)  # 위도 1도 ≈ 111km

    def _calc_threat_risk(self, asset: Asset, target: Dict, threats: List[Dict]) -> float:
        """목표 주변 위협 노출 위험도 (0~1)"""
        if not threats:
            return 0.0
        total_risk = 0.0
        t_lat = target.get("lat", 37.0)
        t_lon = target.get("lon", 127.0)
        rcs = ASSET_PERFORMANCE.get(asset.asset_type, {}).get("rcs", 1.0)
        for threat in threats:
            if threat.get("type") in ("SAM", "RADAR") and threat.get("lat"):
                dlat = t_lat - threat["lat"]
                dlon = t_lon - threat["lon"]
                dist_km = float(np.sqrt(dlat**2 + dlon**2) * 111.0)
                radius = threat.get("radius_km", 30.0)
                if dist_km < radius:
                    # 위협 범위 내 → 위험도 = (1 - dist/radius) × RCS
                    total_risk += (1.0 - dist_km / radius) * rcs
        return min(total_risk, 1.0)

    def _get_mission_for_asset(self, asset_type: str, mission_sequence: List[str]) -> str:
        """자산 타입에 가장 적합한 임무 선택"""
        if not mission_sequence:
            return "STRIKE"
        fit_scores = self.MISSION_FIT.get(asset_type, {})
        best_mission = min(
            [m for m in mission_sequence if m in fit_scores],
            key=lambda m: fit_scores.get(m, 99),
            default=mission_sequence[0]
        )
        return best_mission


# ================================================================
# FormationOptimizer - 통합 진입점
# ================================================================

class FormationOptimizer:
    """
    MILP + 헝가리안 통합 편대 구성 최적화 진입점

    사용법:
        optimizer = FormationOptimizer()
        result = optimizer.run(
            mission_types=["ISR","SEAD","STRIKE"],
            targets=[{"lat":39.0,"lon":125.7,"name":"PY-Core"}],
            threats=[...],
            base="부산(Busan)"
        )
    """

    def __init__(self):
        self.milp = FormationMILP()
        self.assigner = AssetAssigner()

    def run(
        self,
        mission_types: List[str],
        targets: List[Dict],
        threats: List[Dict] = None,
        base: str = "부산(Busan)",
        max_total: int = FORMATION_MAX_TOTAL,
        doctrine_policy: Optional[Dict] = None
    ) -> FormationResult:
        """
        전체 파이프라인 실행

        Step 1: MILP → 자산 대수 결정
        Step 2: 자산 객체 생성
        Step 3: 헝가리안 → 자산↔목표 배정

        Returns:
            FormationResult
        """
        start_t = time.time()

        # ── Step 1: MILP 편대 구성 ──
        milp_result = self.milp.optimize(
            mission_types=mission_types,
            n_targets=len(targets) if targets else 1,
            max_total=max_total,
            doctrine_policy=doctrine_policy
        )

        if not milp_result["is_feasible"]:
            return FormationResult(
                is_feasible=False,
                solver_status="Infeasible",
                mission_sequence=mission_types
            )

        n_f = milp_result["n_fighter"]
        n_r = milp_result["n_recon_uav"]
        n_k = milp_result["n_attack_uav"]

        # ── Step 2: 자산 객체 생성 ──
        assets = []
        for i in range(n_f):
            assets.append(Asset(
                asset_id=f"F-{i+1:02d}",
                asset_type="fighter",
                callsign=f"Eagle-{i+1}",
                base=base
            ))
        for i in range(n_r):
            assets.append(Asset(
                asset_id=f"RUAV-{i+1:02d}",
                asset_type="recon_uav",
                callsign=f"Scout-{i+1}",
                base=base
            ))
        for i in range(n_k):
            assets.append(Asset(
                asset_id=f"AUAV-{i+1:02d}",
                asset_type="attack_uav",
                callsign=f"Viper-{i+1}",
                base=base
            ))

        # ── Step 3: 헝가리안 자산 배정 ──
        if targets:
            assets = self.assigner.assign(
                assets=assets,
                targets=targets,
                mission_sequence=mission_types,
                threats=threats or []
            )

        solve_time = (time.time() - start_t) * 1000

        return FormationResult(
            n_fighter=n_f,
            n_recon_uav=n_r,
            n_attack_uav=n_k,
            mission_sequence=mission_types,
            assets=assets,
            total_cost=milp_result["total_cost"],
            is_feasible=True,
            solver_status=milp_result["status"],
            solve_time_ms=round(solve_time, 2),
            utilization_pct=milp_result.get("utilization", 0)
        )
