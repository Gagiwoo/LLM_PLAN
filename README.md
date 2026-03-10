# IMPS (Intelligent Mission Planning System)

IMPS는 다음 기능을 하나의 파이프라인으로 통합한 로컬 기반 전술 임무계획 데모 시스템입니다.

- LLM 명령 해석
- 교리 기반 RAG(Doctrine Retrieval)
- 3D 경로탐색(지형 반영)
- 위협/위험도 모델링(SAM, RADAR, NFZ)
- 규칙 기반 임무 검증(Validator)
- 연료 기반 위험-우회 의사결정

메인 실행 파일은 `streamlit_app.py`입니다.

---

## 구현 범위

### 1) LLM 명령 인터페이스

- 자연어 명령으로 임무 파라미터(안전마진, RTB, 목표좌표, 알고리즘 등)를 변경합니다.
- Ollama 로컬 모델을 사용합니다.
- 파서 구현 위치: `modules/llm_brain.py`

### 2) Doctrine RAG

- 소스 경로: `data/doctrine/*.(pdf|md|txt)`
- 교리 파일이 없으면 `doctrine_basis.md`를 fallback으로 사용합니다.
- 검색 모듈: `modules/doctrine_rag.py`
- 정책 생성: `modules/doctrine_policy.py`

### 3) 경로탐색

- 지원 알고리즘: `A*`, `A* 3D`, `RRT`, `RRT*`
- 3D 경로는 DEM 지형 데이터를 반영합니다.
- A* 계열에는 위협 core 회피와 동적 위험 임계치가 적용되어 있습니다.
- 관련 파일:
  - `modules/pathfinder.py`
  - `modules/pathfinder_optimized.py`
  - `modules/pathfinder_rrt.py`

### 4) 위협 및 위험도 분석

- 위협 유형: `SAM`, `RADAR`, `NFZ`
- 경로 위험도/히트맵 분석:
  - `modules/xai_utils.py`
- 레이더 가시선(LoS) 마스킹:
  - `modules/radar_shadow.py`

### 5) Validator

- 주요 검증 항목:
  - 임무 시퀀스 순서
  - 위협 침투
  - NFZ 위반
  - 최소 고도
  - 항속거리 초과
  - MUM-T 비율
  - 자산 간 충돌 위험
- 구현 위치: `modules/validator.py`

### 6) 연료 기반 계획 (F-16 기준)

- 미션 파라미터:
  - `fuel_state` (0.20 ~ 1.00)
  - `refuel_count` (0 ~ 2)
- 저연료일수록 단거리/위험 감수 경향,
- 연료 여유/급유 지원이 있을수록 우회/안전 경향으로 동작합니다.
- 관련 파일:
  - `modules/fuel_model.py`
  - `modules/config.py` (`FUEL_POLICY`)

근거 링크는 코드 주석(`FUEL_POLICY`)에 명시되어 있습니다.

- USAF F-16 Fact Sheet
  - https://www.af.mil/About-Us/Fact-Sheets/Display/Article/104505/f-16-fighting-falcon/
- Boeing KC-46
  - https://www.boeing.com/defense/tankers-and-transports/kc-46-pegasus

---

## 저장소 구조

```text
mission_plan-260308/
|-- streamlit_app.py
|-- run_simulation_mission.py
|-- requierments.txt
|-- mission_export.json
|-- doctrine_basis.md
|-- docs/
|   |-- CHANGELOG_2026-02-21.md
|   |-- CHANGELOG_2026-03-08.md
|   `-- CODE_REVIEW_2026-02-23.md
|-- data/
|   |-- doctrine/
|   `-- terrain/
|-- modules/
|   |-- config.py
|   |-- llm_brain.py
|   |-- doctrine_rag.py
|   |-- doctrine_policy.py
|   |-- mission_state.py
|   |-- fuel_model.py
|   |-- pathfinder.py
|   |-- pathfinder_optimized.py
|   |-- pathfinder_rrt.py
|   |-- terrain_loader.py
|   |-- radar_shadow.py
|   |-- xai_utils.py
|   |-- formation_optimizer.py
|   `-- validator.py
`-- sim_utils/
    `-- sim_mission_bridge.py
```

---

## 설치

### 사전 요구사항

- Python 3.10+
- Ollama 설치 및 실행

### 의존성 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requierments.txt
```

주의: 현재 저장소 파일명은 `requirements.txt`가 아니라 `requierments.txt`입니다.

### Ollama 모델 다운로드

```powershell
ollama pull qwen3:14b
ollama pull llama3.1
```

기본 모델 설정 위치: `modules/config.py`

---

## 데이터 준비

### 1) 교리 데이터 (RAG)

- 경로: `data/doctrine/`
- 지원 형식: `.pdf`, `.md`, `.txt`

### 2) 지형 데이터 (DEM)

- 경로: `data/terrain/`
- 지원 형식: `.tif`, `.tiff`, `.hgt`
- DEM 또는 `rasterio`가 없으면 synthetic terrain fallback을 사용합니다.

---

## 실행

```powershell
streamlit run streamlit_app.py
```

브라우저 접속:

- `http://localhost:8501`

---

## 선택 기능: AirSim 연동

- 경로 JSON을 이용해 시뮬레이션 브리지 실행 가능
- 관련 파일:
  - `run_simulation_mission.py`
  - `sim_utils/sim_mission_bridge.py`
- 별도 AirSim Python 환경(`airsim` 패키지)이 필요합니다.

---

## 참고 문서

- `docs/CHANGELOG_2026-03-08.md`
- `docs/CHANGELOG_2026-02-21.md`
- `docs/CODE_REVIEW_2026-02-23.md`

---

## Contact

- ksain1@ajou.ac.kr

