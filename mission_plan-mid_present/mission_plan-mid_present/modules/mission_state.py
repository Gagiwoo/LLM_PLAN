"""
미션 상태 관리 - 위협 DB 내장 및 정밀 제원(XAI) 속성 포함
"""
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
import json
from datetime import datetime
from modules.config import DEFAULT_SAFETY_MARGIN, DEFAULT_STPT_GAP, LOG_DIR, ENABLE_LOGGING, DEFAULT_ALGORITHM, ENABLE_3D
import os

# 💡 [NEW] 적성국 방공망/레이더 제원 데이터베이스 (F-16 전투기 대응 기준)
THREAT_DB = {
    "S-400 Triumf (SA-21)": {"type": "SAM", "radius_km": 250.0, "loss": 6.0, "rcs_m2": 2.5, "pd_k": 0.50, "sskp": 0.90, "peak_ratio": 0.32, "sigma_ratio": 0.25},
    "S-300 PMU2 (SA-20)":   {"type": "SAM", "radius_km": 195.0, "loss": 7.0, "rcs_m2": 2.5, "pd_k": 0.45, "sskp": 0.85, "peak_ratio": 0.33, "sigma_ratio": 0.20},
    "Buk-M2 (SA-17)":       {"type": "SAM", "radius_km": 45.0,  "loss": 8.0, "rcs_m2": 2.5, "pd_k": 0.40, "sskp": 0.80, "peak_ratio": 0.33, "sigma_ratio": 0.20},
    "Pantsir-S1 (SA-22)":   {"type": "SAM", "radius_km": 18.0,  "loss": 9.0, "rcs_m2": 2.5, "pd_k": 0.35, "sskp": 0.70, "peak_ratio": 0.33, "sigma_ratio": 0.15},
    "S-75 Dvina (SA-2)":    {"type": "SAM", "radius_km": 45.0,  "loss": 12.0,"rcs_m2": 2.5, "pd_k": 0.20, "sskp": 0.40, "peak_ratio": 0.44, "sigma_ratio": 0.15},
    "조기경보 레이더":        {"type": "RADAR","radius_km": 400.0, "loss": 5.0, "rcs_m2": 2.5, "pd_k": 0.30, "sskp": 0.0,  "peak_ratio": 0.0,  "sigma_ratio": 0.0}
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
    alt: float = 0.0  # 해발고도 (m)
    lat_min: Optional[float] = None
    lat_max: Optional[float] = None
    lon_min: Optional[float] = None
    lon_max: Optional[float] = None
    
    # 💡 [NEW] 정밀 XAI 파라미터 (기본값 설정)
    loss: float = 8.0
    rcs_m2: float = 2.5
    pd_k: float = 0.4
    sskp: float = 0.75
    pk_peak_km: float = 0.0
    pk_sigma_km: float = 0.0
    weight: float = 1.0
    
    def to_dict(self):
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: dict):
        if 'alt' not in data and data.get('type') in ['SAM', 'RADAR']:
            data['alt'] = 0.0
        return cls(**data)


class MissionState:
    """미션 전체 상태 관리"""
    
    def __init__(self):
        self.params = MissionParams()
        self.threats: List[Threat] = [
            Threat(name="Default SAM", type="SAM", lat=37.200, lon=127.800, radius_km=20, alt=0)
        ]
        self.chat_history: List[Dict[str, str]] = [
            {"role": "assistant", "content": "작전관님, 명령을 대기 중입니다.", "reasoning": ""}
        ]
        
    def add_threat(self, threat: Threat):
        self.threats.append(threat)
        
    def remove_threat(self, name: str):
        self.threats = [t for t in self.threats if t.name != name]
        
    def add_chat_message(self, role: str, content: str, reasoning: str = ""):
        self.chat_history.append({"role": role, "content": content, "reasoning": reasoning})
        
    def save_to_file(self, filename: str):
        if ENABLE_LOGGING:
            os.makedirs(LOG_DIR, exist_ok=True)
            filepath = os.path.join(LOG_DIR, filename)
            data = {
                "timestamp": datetime.now().isoformat(),
                "params": self.params.to_dict(),
                "threats": [t.to_dict() for t in self.threats],
                "chat_history": self.chat_history
            }
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load_from_file(cls, filename: str):
        filepath = os.path.join(LOG_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        state = cls()
        state.params = MissionParams.from_dict(data["params"])
        state.threats = [Threat.from_dict(t) for t in data["threats"]]
        state.chat_history = data["chat_history"]
        return state