🚁 Intelligent Mission Planning System (IMPS) v9.0
[![Python](https://img.shields.io/badge/Python-3.10+-(httpseamlit](https://img.shields.io/badge/Streamlit-1.28+-red.svg(httpsense](https://img.shields.io/badge/License-MIT-green.svg(LICENSE

📖 Overview
IMPS는 폐쇄망(On-Premise) 환경에서 작동하는 LLM 기반 전술 임무계획 시스템입니다.
조종사/작전관의 자연어 명령을 해석하여, 적 위협(SAM, NFZ)을 회피하는 안전한 비행 경로와 Steer Point(STPT) 리스트를 실시간으로 생성합니다.

주요 특징
✅ Hybrid Architecture: LLM(두뇌, 자연어 → 파라미터) + A* Pathfinding(계산기, 실제 경로 계산)

✅ On-premise: Ollama 기반 로컬 LLM (Llama 3.1 등) 구동, 인터넷 미사용

✅ Real-time: 위협 추가/삭제 또는 명령 변경 시 즉시 경로 재계산

✅ Reproducible: 미션 시나리오를 JSON으로 저장/복원하여 실험 재현 가능

🧱 Requirements
1. 필수 소프트웨어
OS: Windows 10/11 (Linux/macOS도 Python 3.10+면 동작)

Python: 3.10 이상

Ollama: 로컬 LLM 서버 (https://ollama.ai)

2. Python 패키지 설치
프로젝트 루트(mission_planner_v9/)에서:

bash
    # (선택) 가상환경 생성 권장
    python -m venv .venv
    .\.venv\Scripts\activate  # Windows

    # 의존성 설치
    pip install -r requirements.txt
    requirements.txt 예시:
        streamlit>=1.28.0
        folium>=0.14.0
        streamlit-folium>=0.15.0
        scipy>=1.11.0
        numpy>=1.24.0
        pandas>=2.0.0
        ollama>=0.1.0

🤖 LLM (Ollama) 설정
Ollama 설치 (공식 사이트 안내 참고).

Llama 3.1 모델 다운로드:
    ollama pull llama3.1

modules/config.py 또는 llm_brain.py에서 모델 이름 확인:
    MODEL_NAME = "llama3.1"
    (Ollama에서 사용하는 모델 태그와 동일해야 함)

🚀 How to Run
1. 프로젝트 가져오기
    git clone <YOUR-REPO-URL> mission_planner_v9
    cd mission_planner_v9
또는 ZIP 다운로드 후 mission_planner_v9/ 폴더로 압축 해제.

2. 앱 실행
    streamlit run streamlit_app.py
브라우저가 자동으로 열리지 않으면 주소창에 다음 입력:
    http://localhost:8501

🕹️ 기본 사용 방법
1. 미션 프로파일 설정
좌측 패널의 「작전 통제」 → 미션 프로파일에서:

    출발 기지: 드롭다운에서 공항 선택 (예: 부산(Busan))

    타겟 좌표: Lat / Lon 값 직접 입력

    Strike & RTB: 체크 시, 타격 후 출발 기지로 복귀 경로 자동 생성

    안전 마진(km): 위협으로부터 유지할 최소 거리

    STPT 표시 간격: 값이 클수록 STPT 개수가 줄어듦(간격 넓어짐)

설정 후 「경로 재계산」 버튼 클릭 → 지도에 경로와 STPT 리스트 표시.

2. 위협(Threat) 관리
탭 **「위협 관리」**에서:

    유형 선택: 원형(SAM) 또는 사각형(NFZ)

    좌표/반경 입력 후 「➕ SAM 추가」 / 「➕ NFZ 추가」 버튼으로 위협 생성

    하단 테이블에서 위협 이름 선택 후 **「🗑️ 삭제」**로 제거 가능

    위협을 수정하면 경로는 자동으로 재계산됨

3. 자연어 명령 (LLM 기반 제어)
채팅 입력창에 한국어로 명령 입력:

예시:

    마진 10km로 늘려줘﻿

    Steer Point 너무 많아, 줄여줘﻿

    복귀할 때 대구 경유해﻿

    복귀는 필요 없어﻿

LLM이 명령을 해석하여 다음 파라미터를 수정합니다.

    안전 마진(km)

    RTB 여부

    Waypoint(경유 공항)

    STPT 간격

변경 결과는 좌측 미션 프로파일과 우측 지도/표에 즉시 반영됩니다.

📁 Project Structure
text
mission_planner_v9/
├── modules/             # 핵심 모듈
│   ├── config.py        # 설정 상수 (모델명, GRID 크기, 지도 경계 등)
│   ├── llm_brain.py     # LLM 인터페이스 (자연어 → JSON 파라미터)
│   ├── pathfinder.py    # A* 기반 경로탐색 + B-spline smoothing
│   └── mission_state.py # 미션/위협/채팅 상태 관리, 시나리오 저장
├── tests/               # 유닛 테스트 (선택)
├── logs/                # 실험 로그 및 미션 시나리오(JSON)
├── streamlit_app.py     # 메인 UI (Streamlit + Folium)
└── README.md


🔬 Research / Experiment Use
시나리오 저장 & 재현
파이썬 코드 또는 디버그 탭에서 현재 미션 상태를 저장:
    mission.save_to_file("scenario_01.json")
저장 위치: logs/scenario_01.json

포함 내용:

    미션 파라미터 (출발 기지, 타겟 좌표, 마진, RTB 여부 등)

    위협 목록(SAM/NFZ)

    채팅 히스토리(명령 및 시스템 응답)

나중에 동일 시나리오로 경로/알고리즘을 다시 테스트할 수 있습니다.

분석 및 보고서 활용
    지도(Figure): Streamlit 앱 화면을 캡처하여 경로/위협 시각화로 사용

    STPT(Table): STPT 리스트를 CSV로 저장하여 경로 길이, 포인트 수, 위험도 등의 정량 분석에 활용

    로그(Supplementary): logs/ 폴더의 JSON 시나리오를 함께 제공하면 실험 재현성이 보장됨

🧩 자주 발생하는 이슈
브라우저가 자동으로 안 열릴 때
→ 터미널에 표시된 URL(http://localhost:8501)을 복사해서 브라우저에 직접 입력.

Ollama 관련 에러 (연결 안 됨 등)
→ Ollama 앱이 실행 중인지, ollama pull llama3.1로 모델이 설치되어 있는지 확인.
→ 모델 이름이 llama3.1로 맞는지 llm_brain.py에서 점검.

경로가 너무 이상하게 우회할 때
→ 위협 반경 또는 안전 마진이 너무 큰지 확인.
→ 필요 시 위협 개수를 줄이거나 안전 마진을 낮춰 재계산.

📧 Contact
Email: ksain1@ajou.ac.kr

