"""
중앙 설정 파일 - 최적화 버전 (변수 누락 수정됨)
"""

# LLM 설정
LLM_MODEL = "llama3.1"
LLM_TEMPERATURE = 0.1
LLM_TIMEOUT = 30
LLM_ENABLE_REASONING = True 

# 맵 설정
GRID_SIZE = 100  # 격자 크기
MAP_BOUNDS = {
    "min_lat": 33.0,
    "max_lat": 43.0,
    "min_lon": 124.0,
    "max_lon": 132.0
}

# 3D 설정
ENABLE_3D = True
ALTITUDE_LEVELS = 20    # 20단계 (정밀도 향상)
ALTITUDE_MIN = 0
ALTITUDE_MAX = 5000
TERRAIN_FOLLOWING = True
MIN_ALTITUDE_AGL = 200  # 지상 200m 위 비행

# 데이터 경로
SRTM_DATA_DIR = "data/terrain"  
SRTM_RESOLUTION = 90

# 경로 설정
DEFAULT_SAFETY_MARGIN = 5.0  # 기본 마진 5km
DEFAULT_STPT_GAP = 5       
SMOOTHING_FACTOR = 0.0002

# XAI 설정
ENABLE_HEATMAP = True
HEATMAP_RESOLUTION = 200
RISK_THRESHOLD_HIGH = 0.7
RISK_THRESHOLD_MEDIUM = 0.4

# 공항 데이터
AIRPORTS = {
    "서산(Seosan)": {"coords": [36.776, 126.493], "elevation": 20},
    "오산(Osan)": {"coords": [37.090, 127.030], "elevation": 38},
    "원주(Wonju)": {"coords": [37.342, 127.920], "elevation": 90},
    "강릉(Gangneung)": {"coords": [37.751, 128.876], "elevation": 6},
    "충주(Chungju)": {"coords": [36.991, 127.926], "elevation": 114},
    "청주(Cheongju)": {"coords": [36.642, 127.489], "elevation": 57},
    "대구(Daegu)": {"coords": [35.871, 128.601], "elevation": 35},
    "광주(Gwangju)": {"coords": [35.159, 126.852], "elevation": 39},
    "부산(Busan)": {"coords": [35.179, 129.075], "elevation": 3},
    "수원(Suwon)": {"coords": [37.240, 127.000], "elevation": 25},
    "사천(Sacheon)": {"coords": [35.088, 128.070], "elevation": 5},
    "서울(Seoul)": {"coords": [37.463, 126.924], "elevation": 48}
}

# UI 설정 (여기가 누락되었던 부분입니다!)
MAP_CENTER = [37.5, 127.5]
MAP_ZOOM = 7
CHAT_CONTAINER_HEIGHT = 350  # <--- 이 변수가 꼭 있어야 합니다!

# 알고리즘 선택
AVAILABLE_ALGORITHMS = ["A*", "A* 3D", "RRT", "RRT*"]
DEFAULT_ALGORITHM = "A* 3D"

# 로깅
LOG_DIR = "logs"
ENABLE_LOGGING = True