"""
중앙 설정 파일 - v2.0 (qwen3:14b + 교리 맥락 추가)
"""

# LLM 설정
# 우선순위: qwen3:14b > llama3.2:3b > llama3.1 > llama3.2
# 빠른 응답을 위해 로컬 설치된 가장 작은 모델 우선 사용 가능
LLM_MODEL = "qwen3:14b"          # 기본: qwen3:14b (고품질)
LLM_MODEL_FALLBACK = "llama3.1"  # 폴백: llama3.1 (없으면 llama3.2 시도)
LLM_TEMPERATURE = 0.1
LLM_TIMEOUT = 45                  # 14b 모델 타임아웃 (45초로 단축)
LLM_ENABLE_REASONING = True

# 맵 설정
GRID_SIZE = 100
MAP_BOUNDS = {
    "min_lat": 33.0,
    "max_lat": 43.0,
    "min_lon": 124.0,
    "max_lon": 132.0
}

# 3D 설정
ENABLE_3D = True
ALTITUDE_LEVELS = 20
ALTITUDE_MIN = 0
ALTITUDE_MAX = 5000
TERRAIN_FOLLOWING = True
MIN_ALTITUDE_AGL = 200  # 지상 200m 위 비행

# 데이터 경로
SRTM_DATA_DIR = "data/terrain"
SRTM_RESOLUTION = 90

# 경로 설정
DEFAULT_SAFETY_MARGIN = 5.0
DEFAULT_STPT_GAP = 5
SMOOTHING_FACTOR = 0.0002

# XAI 설정
ENABLE_HEATMAP = True
HEATMAP_RESOLUTION = 200
RISK_THRESHOLD_HIGH = 0.7
RISK_THRESHOLD_MEDIUM = 0.4

# 공항 데이터
AIRPORTS = {
    "서산(Seosan)":   {"coords": [36.776, 126.493], "elevation": 20},
    "오산(Osan)":     {"coords": [37.090, 127.030], "elevation": 38},
    "원주(Wonju)":    {"coords": [37.342, 127.920], "elevation": 90},
    "강릉(Gangneung)":{"coords": [37.751, 128.876], "elevation": 6},
    "충주(Chungju)":  {"coords": [36.991, 127.926], "elevation": 114},
    "청주(Cheongju)": {"coords": [36.642, 127.489], "elevation": 57},
    "대구(Daegu)":    {"coords": [35.871, 128.601], "elevation": 35},
    "광주(Gwangju)":  {"coords": [35.159, 126.852], "elevation": 39},
    "부산(Busan)":    {"coords": [35.179, 129.075], "elevation": 3},
    "수원(Suwon)":    {"coords": [37.240, 127.000], "elevation": 25},
    "사천(Sacheon)":  {"coords": [35.088, 128.070], "elevation": 5},
    "서울(Seoul)":    {"coords": [37.463, 126.924], "elevation": 48}
}

# UI 설정
MAP_CENTER = [37.5, 127.5]
MAP_ZOOM = 7
CHAT_CONTAINER_HEIGHT = 350

# 알고리즘 선택
AVAILABLE_ALGORITHMS = ["A*", "A* 3D", "RRT", "RRT*"]
DEFAULT_ALGORITHM = "A* 3D"

# 로깅
LOG_DIR = "logs"
ENABLE_LOGGING = True

# ================================================================
# 교리 맥락 (Doctrine Context) - LLM 프롬프트용
# 출처: JP3-30 Joint Air Operations, AFDP3-03 Counterland,
#       AFDP5-0 Planning, FMI3-04.155 UAS Operations
# ================================================================

# 임무 유형 정의 (AFDP3-03 기반)
MISSION_TYPES = {
    "ISR": {
        "description": "Intelligence, Surveillance, Reconnaissance - 정보·감시·정찰",
        "priority": 1,
        "assets": ["정찰UAV"],
        "doctrine": "적 활동·자원·지형 정보 수집. 타격 임무 전 선행 수행."
    },
    "SEAD": {
        "description": "Suppression of Enemy Air Defenses - 적 방공망 제압",
        "priority": 2,
        "assets": ["자폭UAV", "전투기"],
        "doctrine": "적 SAM·레이더 무력화. Strike 임무 전 공역 안전 확보."
    },
    "STRIKE": {
        "description": "Air Interdiction Strike - 공중 타격",
        "priority": 3,
        "assets": ["전투기", "자폭UAV"],
        "doctrine": "적 핵심 표적 파괴. SEAD 완료 후 실시."
    },
    "CAS": {
        "description": "Close Air Support - 근접항공지원",
        "priority": 3,
        "assets": ["전투기"],
        "doctrine": "아군 지상군 근접 지원. JTAC 통제 하 실시."
    }
}

# 전술 키워드 → 파라미터 매핑 힌트 (LLM 보조용)
TACTICAL_HINTS = {
    "저고도": {"enable_3d": True, "altitude_hint": "low"},
    "고고도": {"enable_3d": True, "altitude_hint": "high"},
    "지형추종": {"enable_3d": True},
    "레이더회피": {"enable_3d": True, "margin_increase": True},
    "안전": {"margin_increase": True},
    "빠르게": {"margin_decrease": True, "algorithm": "A*"},
    "정밀": {"algorithm": "A* 3D"},
    "복귀": {"rtb": True},
    "RTB": {"rtb": True},
    "왕복": {"rtb": True},
}

# 안전 마진 기준 (JP3-30 기반)
MARGIN_LEVELS = {
    "최소": 2.0,    # 위험 감수, 속도 우선
    "표준": 5.0,    # 기본값
    "안전": 15.0,   # 안전 우선
    "최대": 30.0,   # 최대 회피
}

# 위협 타입별 기본 반경 (FMI3-04.155 기반)
THREAT_DEFAULT_RADIUS = {
    "SAM":   30.0,  # km - 지대공 미사일
    "RADAR": 80.0,  # km - 탐지 레이더
    "NFZ":   0.0,   # 비행금지구역 (사각형)
}

# 위협 타입별 기본 고도 envelope (미사일/레이더 사이트 기준 상대고도, m)
THREAT_ALT_ENVELOPE = {
    "SAM": {
        "min_alt_m": 30.0,       # 초저고도 교전 한계
        "max_alt_m": 25000.0,    # 고고도 교전 한계
    },
    "RADAR": {
        "min_alt_m": 0.0,
        "max_alt_m": 30000.0,
    },
}

# ================================================================
# 편대 구성 (Formation) 설정 - MILP + 헝가리안
# 출처: FMI3-04.155 UAS Operations, JP3-30 Joint Air Operations
# ================================================================

# 자산별 운용 비용 (상대적 비용 지수)
# 전투기 > 자폭UAV > 정찰UAV 순서 (유인기 비용 최고)
ASSET_COST = {
    "fighter":   10.0,  # 전투기 - 유인, 고비용
    "recon_uav":  2.0,  # 정찰UAV - 무인, 저비용
    "attack_uav": 4.0,  # 자폭UAV - 무인, 중비용
}

# 자산별 최대 보유 가능 수량 (시뮬레이션 기본값)
ASSET_MAX = {
    "fighter":    8,
    "recon_uav":  8,
    "attack_uav": 8,
}

# 총 자산 최대 제한 (N_max) - JP3-30 작전 운용 한계
FORMATION_MAX_TOTAL = 12

# 임무별 최소 자산 요구 (교리 기반 제약)
# 근거: JP3-30 MAAP, FMI3-04.155 MUM-T, AFDP3-03
MISSION_ASSET_REQUIREMENTS = {
    "ISR": {
        "recon_uav":  2,   # FMI3-04.155: 팀 로테이션 최소 2대
        "fighter":    0,
        "attack_uav": 0,
    },
    "SEAD": {
        "attack_uav": 1,   # JP3-30: 자폭UAV 선행 침투
        "fighter":    1,   # JP3-30: 전투기 후속 타격
        "recon_uav":  0,
    },
    "STRIKE": {
        "fighter":    1,   # AFDP3-03: 전투기 필수
        "recon_uav":  0,
        "attack_uav": 0,
    },
    "CAS": {
        "fighter":    1,   # AFDP3-03: CAS는 전투기
        "recon_uav":  0,
        "attack_uav": 0,
    },
}

# MUM-T 비율 제약: 무인기 합 ≥ 2 × 전투기 수
# 근거: FMI3-04.155 Lead/Wingman (유인1 : 무인2)
MUMT_RATIO = 2.0

# 자산 성능 파라미터 (경로 계획용)
# 근거: FMI3-04.155 UAS Operations, DAFMAN11-260 연료 계획
# recon_uav: RQ-7 Shadow 수준 (~125km 반경 → 왕복 250km, 한반도 작전은 ~1000km+)
# attack_uav: 자폭 UAV는 편도이므로 항속 = 사거리 (loitering munition ~200km+)
# 시뮬레이션 상 한반도 전역 작전 커버를 위해 현실적 수치 적용
ASSET_PERFORMANCE = {
    "fighter": {
        "speed_kmh":   900,
        "range_km":   3000,   # F-16 급 전투반경 ~800km (왕복 고려 3000km)
        "altitude_m":  5000,
        "rcs":         1.0,   # 레이더 반사 면적 (상대값)
    },
    "recon_uav": {
        "speed_kmh":   200,
        "range_km":   1500,   # RQ-7 Shadow → 한국형 정찰 UAV 수준 (작전반경 확장)
        "altitude_m":  3000,
        "rcs":         0.1,
    },
    "attack_uav": {
        "speed_kmh":   300,
        "range_km":   1200,   # 자폭 UAV (편도 사거리 기준, Harop ~1000km급)
        "altitude_m":  2000,
        "rcs":         0.2,
    },
}

# ================================================================
# Fuel policy (F-16 baseline for mission-risk tradeoff)
# ---------------------------------------------------------------
# This project uses an F-16 baseline to tune "risk vs detour":
# - Lower fuel: tolerate more risk for shorter path
# - Higher fuel/AR: prioritize safer detour
#
# Evidence references kept in-code for paper traceability:
# 1) USAF F-16 fact sheet (2,002+ mi ferry range, ~7,000 lb internal fuel)
#    https://www.af.mil/About-Us/Fact-Sheets/Display/Article/104505/f-16-fighting-falcon/
# 2) Typical "with external tanks" planning anchor ~12,000 lb (mission planning scale)
# 3) KC-46 AR capability context (receiver refuel feasibility)
#    https://www.boeing.com/defense/tankers-and-transports/kc-46-pegasus
# ================================================================
FUEL_POLICY = {
    "baseline_aircraft": "F-16",
    "f16_reference": {
        "internal_fuel_lb": 7000.0,
        "typical_mission_fuel_with_tanks_lb": 12000.0,
        "ferry_range_km": 3220.0,
    },
    # Demo-level assumption: each AR event adds +45% effective range budget.
    "refuel_gain_per_event": 0.45,
    "max_refuel_events": 2,
}
