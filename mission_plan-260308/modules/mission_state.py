"""
미션 상태 관리 v2.1
- Asset, Formation 데이터클래스 추가
- 편대 구성 결과 상태 관리
- [통합] 적성국 방공망 DB (THREAT_DB) + Threat XAI 정밀 파라미터
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
import json
from datetime import datetime
from modules.config import (
    DEFAULT_SAFETY_MARGIN, DEFAULT_STPT_GAP,
    LOG_DIR, ENABLE_LOGGING, DEFAULT_ALGORITHM, ENABLE_3D,
    THREAT_ALT_ENVELOPE
)
import os


# ================================================================
# [통합] 적성국 방공망/레이더 제원 데이터베이스 (F-16 전투기 대응 기준)
# 출처: 팀원 코드 (mission_plan-mid_present) 통합 — 2026-02-23
# ================================================================
# 위 자료는 북한 지대공 미사일 요격체계(번개 1~5)에 대한 자료를 장입.
# 번개 6~7(별찌1/2) 에 대한 정보는 찾을 수 없어 제외.
THREAT_DB = {

# -------------------------- SAM 시작 --------------------------
    "S-75 (번개-1)": {
        "type": "SAM", "radius_km": 30.0,
        "loss": 0, "rcs_m2": 0, "pd_k": 0.40,
        "sskp": 0.40, "peak_ratio": 0.35, "sigma_ratio": 0.2
    # https://www.segye.com/newsView/20130717025043 S-75(SA-2, 번개-1) 관련 보도자료 , 사거리 30km
    # https://odin.tradoc.army.mil/Search/WEG/S-75 - S-75관련 자료 (미 육군 교육사령부)
    },
    "SA-13 (번개-2)": {
        "type": "SAM", "radius_km": 5.0,
        "loss": 0, "rcs_m2": 0, "pd_k": 0.40,
        "sskp": 0.40, "peak_ratio": 0.35, "sigma_ratio": 0.2
    # https://odin.tradoc.army.mil/Search/WEG/9K35 - SA-13관련 자료 (미 육군 교육사령부), 사거리 5km
    },
    "S-125 (번개-3)": {
        "type": "SAM", "radius_km": 35.0,
        "loss": 0, "rcs_m2": 0, "pd_k": 0.40,
        "sskp": 0.70, "peak_ratio": 0.35, "sigma_ratio": 0.2
    # https://odin.tradoc.army.mil/Search/WEG/S-125 - SA-125관련 자료 (미 육군 교육사령부), 사거리 35km / 발사 시, 전투기 격추확률(sskp)이 70%로 확인
    },
    "SA-5 (번개-4)": {
        "type": "SAM", "radius_km": 250.0,
        "loss": 0, "rcs_m2": 0, "pd_k": 0.40,
        "sskp": 0.80, "peak_ratio": 0.35, "sigma_ratio": 0.2
    # https://odin.tradoc.army.mil/Search/WEG/S-200 - S-200관련 자료 (미 육군 교육사령부), 사거리 250km
    },
    "KN-06 (번개-5)": {
        "type": "SAM", "radius_km": 150.0,
        "loss": 0, "rcs_m2": 0, "pd_k": 0.40,
        "sskp": 0.80, "peak_ratio": 0.35, "sigma_ratio": 0.2
    # https://odin.tradoc.army.mil/Search/WEG/KN-06 - KN-06관련 자료 (미 육군 교육사령부), 사거리 150km
    # https://www.thessen-lig.com:10010/svcShowWebZinDetail.do?contentsSeq=80 - KN-06관련 자료 LIG 넥스원 매거진 뉴스레터, 사거리 150km 확인
    },
# -------------------------- SAM 끝 --------------------------

# -------------------------- 화력통제레이더 시작 --------------------------

    "SNR-75 (Fan Song) 화력제어 레이더": {
        "type": "RADAR", "radius_km": 60.0,
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # S-75(번개-1)와 같이 운용되는 화력통제 레이더로 사거리는 최대 145km
    # https://odin.tradoc.army.mil/Search/WEG/FAN-song - Fan Song 화력통제 레이더 관련 자료 (미 육군 교육사령부)
    # https://www.segye.com/newsView/20130717025043 S-75(SA-2, 번개-1) 관련 보도자료 Fan Song 레이더 사용 확인
    },

#--------------------------------------------------------------------------------------- 
#아래 자료부터는 북한에서 운용중인 실제 자료 확인 제한에 따라서, 
#미 육군 교육사령부에서 운용하는 사이트(ODIN)에서 북한에서 운용중인 SAM과 같이 운용한다고 확인되는 레이더를 기반으로 추가하였습니다.
#--------------------------------------------------------------------------------------- 

    "9S86 (SNAP SHOT) 탐지 레이더": {
        "type": "RADAR", "radius_km": 10.0,
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # SA-13(번개-2)에 탑재된 거리측정 레이더로 사거리는 최대 10km
    # https://odin.tradoc.army.mil/Search/WEG/9S86 - SNAP SHOT 화력통제 레이더 관련 자료(SA-13(번개-2) 자료에 포함) (미 육군 교육사령부)
    # SA-13(번개-2)는 수동/적외선 추적 방식으로 화력통제 레이더가 따로 필요 없음
    },
    "SNR-125 (LOW BLOW) 화력통제 레이더": {
        "type": "RADAR", "radius_km": 40.0,
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # S-125(번개-3)와 같이 운용되는 화력통제 레이더로 사거리는 최대 40km
    # https://odin.tradoc.army.mil/Search/WEG/S-125 - LOW BLOW 화력통제 레이더 관련 자료 (미 육군 교육사령부)
    },
    "5N62 (Square Pair) 화력통제 레이더": {
        "type": "RADAR", "radius_km": 300.0, #최대 추적거리 350km, 최대 통제거리 약 300km 
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # SA-5(번개-4)와 같이 운용되는 화력통제 레이더로 사거리는 최대 300km
    # https://odin.tradoc.army.mil/Search/WEG/5N62 - Square Pair 화력통제 레이더 관련 자료 (미 육군 교육사령부) 단, 구체적인 제원은 명시되어 있지않고, 화력제어용으로 Square Pair 레이더를 사용한다고 명시
    },
    "5N63 (Flap Lid) 화력통제 레이더": {
        "type": "RADAR", "radius_km": 300.0, #최대 추적거리 350km, 최대 통제거리 약 300km 
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # KN-06(번개-5)와 같이 운용되는 화력통제 레이더로 사거리는 최대 300km
    # https://odin.tradoc.army.mil/Search/WEG/KN-06 - KN-06 화력통제 레이더 관련 자료(KN-06(번개-5) 자료에 포함) (미 육군 교육사령부)
    },
# -------------------------- 화력통제레이더 끝 --------------------------


# -------------------------- 조기경보 및 탐지 레이더 시작 --------------------------

    "P-14 (Tall King) 조기경보 레이더": {
        "type": "RADAR", "radius_km": 400.0, 
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # SA-5(번개-4)와 주로 같이 운용되는 조기경보 레이더로 사거리는 최대 400km
    # https://odin.tradoc.army.mil/Search/WEG/P-14 - P-14 화력통제 레이더 관련 자료 (미 육군 교육사령부)
    },
    "P-18 (Spoon Rest) 조기경보 레이더": {
        "type": "RADAR", "radius_km": 250.0, 
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # SA-5(번개-4)와 주로 같이 운용되는 조기경보 레이더로 사거리는 최대 250km
    # https://odin.tradoc.army.mil/Search/WEG/P-18 - P-18 화력통제 레이더 관련 자료 (미 육군 교육사령부)
    },
    "P-35/47 (Bar Lock) 탐지 및 추적 레이더": {
        "type": "RADAR", "radius_km": 390.0, 
        "loss": 21.1, "rcs_m2": 0, "pd_k": 0.00,
        "sskp": 0.0, "peak_ratio": 0.0, "sigma_ratio": 0.0
    # SA-5(번개-4)와 주로 같이 운용되는 조기경보 레이더로 사거리는 최대 390km
    # https://odin.tradoc.army.mil/Search/WEG/P-35- P-35/37 화력통제 레이더 관련 자료 (미 육군 교육사령부)
    },
}


@dataclass
class MissionParams:
    """미션 파라미터"""
    start: str = "부산(Busan)"
    target_lat: float = 39.000
    target_lon: float = 125.700
    target_name: str = "PY-Core"
    rtb: bool = True
    margin: float = DEFAULT_SAFETY_MARGIN
    waypoint: Optional[str] = None
    stpt_gap: int = DEFAULT_STPT_GAP
    algorithm: str = DEFAULT_ALGORITHM
    enable_3d: bool = ENABLE_3D
    # Fuel-aware planning knobs (F-16 baseline policy in modules.config.FUEL_POLICY)
    fuel_state: float = 1.0      # 1.0 = full planned fuel, 0.2 = fuel-critical
    refuel_count: int = 0        # planned air-refuel events

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


@dataclass
class Threat:
    """
    위협 객체
    alt: 지형 고도 + 안테나 높이 (자동 설정됨)
    """
    name: str
    type: str  # "SAM", "RADAR", "NFZ"
    lat: Optional[float] = None
    lon: Optional[float] = None
    radius_km: Optional[float] = None
    alt: float = 0.0
    min_alt_m: Optional[float] = None
    max_alt_m: Optional[float] = None
    lat_min: Optional[float] = None
    lat_max: Optional[float] = None
    lon_min: Optional[float] = None
    lon_max: Optional[float] = None

    # [통합] XAI 정밀 파라미터 (기본값 = 일반 SAM 기준, THREAT_DB 선택 시 자동 설정)
    loss: float = 21.1          # 시스템 손실 dB (대기 감쇠 + 기계적 손실)
    rcs_m2: float = 2.5        # F-16 Combat Config 평균 RCS (m²)
    pd_k: float = 0.4          # 탐지 곡선 가파름 계수 (Steepness)
    sskp: float = 0.75         # 단발 격추 확률 (Single-Shot Kill Probability)
    pk_peak_km: float = 0.35    # No Escape Zone 최대 치명 거리 (km, 0=radius*0.35)
    pk_sigma_km: float = 0.2   # 교전 구역 폭 σ (km, 0=radius*0.20)
    weight: float = 1.0        # 위협 가중치

    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict):
        if 'alt' not in data and data.get('type') in ['SAM', 'RADAR']:
            data['alt'] = 0.0
        if data.get("type") in ["SAM", "RADAR"]:
            env = THREAT_ALT_ENVELOPE.get(data["type"], {})
            data.setdefault("min_alt_m", env.get("min_alt_m"))
            data.setdefault("max_alt_m", env.get("max_alt_m"))
        return cls(**data)


# ================================================================
# 편대 구성 관련 데이터클래스 (신규)
# ================================================================

@dataclass
class Asset:
    """
    개별 자산 (전투기 / 정찰UAV / 자폭UAV)
    근거: FMI3-04.155 UAS Operations
    """
    asset_id: str                          # 고유 ID (예: "F-01", "RUAV-01")
    asset_type: str                        # "fighter" / "recon_uav" / "attack_uav"
    callsign: str                          # 콜사인 (예: "Eagle-1")
    base: str = "부산(Busan)"             # 출발 기지
    assigned_mission: Optional[str] = None # 배정된 임무 ("ISR"/"SEAD"/"STRIKE"/"CAS")
    assigned_target_idx: Optional[int] = None  # 배정된 목표 인덱스 (헝가리안 결과)
    path: List = field(default_factory=list)   # 계산된 경로 웨이포인트

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


@dataclass
class FormationResult:
    """
    MILP + 헝가리안 편대 구성 결과
    근거: JP3-30 Apportionment/Allocation, FMI3-04.155 MUM-T
    """
    # MILP 결과 - 자산 대수
    n_fighter: int = 0      # 전투기 대수
    n_recon_uav: int = 0    # 정찰UAV 대수
    n_attack_uav: int = 0   # 자폭UAV 대수

    # 임무 시퀀스
    mission_sequence: List[str] = field(default_factory=list)  # ["ISR","SEAD","STRIKE"]

    # 헝가리안 배정 결과
    assets: List[Asset] = field(default_factory=list)

    # 최적화 메타 정보
    total_cost: float = 0.0       # 총 비용
    is_feasible: bool = False     # MILP 해 존재 여부
    solver_status: str = ""       # "Optimal" / "Infeasible" / "Error"
    solve_time_ms: float = 0.0    # 계산 시간
    utilization_pct: int = 0      # N_max 대비 자산 활용률 (%)

    def total_assets(self) -> int:
        return self.n_fighter + self.n_recon_uav + self.n_attack_uav

    def to_dict(self):
        d = asdict(self)
        d['total_assets'] = self.total_assets()
        return d

    def summary(self) -> str:
        """편대 구성 요약 문자열"""
        return (
            f"전투기 {self.n_fighter}대 | "
            f"정찰UAV {self.n_recon_uav}대 | "
            f"자폭UAV {self.n_attack_uav}대 | "
            f"총 {self.total_assets()}대"
        )


# ================================================================
# MissionState - 편대 구성 상태 추가
# ================================================================

class MissionState:
    """미션 전체 상태 관리 v2.0"""

    def __init__(self):
        self.params = MissionParams()
        self.threats: List[Threat] = [
            Threat(
                name="Default SAM",
                type="SAM",
                lat=37.200,
                lon=127.800,
                radius_km=20,
                alt=0,
                min_alt_m=THREAT_ALT_ENVELOPE["SAM"]["min_alt_m"],
                max_alt_m=THREAT_ALT_ENVELOPE["SAM"]["max_alt_m"],
            )
        ]
        self.chat_history: List[Dict[str, str]] = [
            {"role": "assistant", "content": "작전관님, 명령을 대기 중입니다.", "reasoning": ""}
        ]
        # 편대 구성 결과 (formation_optimizer 실행 후 채워짐)
        self.formation: Optional[FormationResult] = None

    def add_threat(self, threat: Threat):
        """위협 추가"""
        self.threats.append(threat)

    def remove_threat(self, name: str):
        """위협 삭제"""
        self.threats = [t for t in self.threats if t.name != name]

    def add_chat_message(self, role: str, content: str, reasoning: str = ""):
        """채팅 메시지 추가"""
        self.chat_history.append({"role": role, "content": content, "reasoning": reasoning})

    def set_formation(self, result: FormationResult):
        """편대 구성 결과 저장"""
        self.formation = result

    def save_to_file(self, filename: str):
        """상태 저장"""
        if ENABLE_LOGGING:
            os.makedirs(LOG_DIR, exist_ok=True)
            filepath = os.path.join(LOG_DIR, filename)
            data = {
                "timestamp": datetime.now().isoformat(),
                "params": self.params.to_dict(),
                "threats": [t.to_dict() for t in self.threats],
                "chat_history": self.chat_history,
                "formation": self.formation.to_dict() if self.formation else None
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_from_file(cls, filename: str):
        """저장된 상태 복원"""
        filepath = os.path.join(LOG_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)

        state = cls()
        state.params = MissionParams.from_dict(data["params"])
        state.threats = [Threat.from_dict(t) for t in data["threats"]]
        state.chat_history = data["chat_history"]
        return state
