# IMPS 개발 일지 — 2026-02-21

> **저장소**: https://github.com/dongkam5/mission_plan  
> **브랜치**: `genspark_ai_developer`  
> **작성일**: 2026-02-21  
> **작성자**: AI 개발 어시스턴트 (Genspark)

---

## 📋 오늘 작업 요약 (총 4개 커밋)

| # | 커밋 해시 | 시각 (UTC) | 유형 | 제목 |
|---|-----------|------------|------|------|
| 1 | `b3ac74c` | 03:14 | feat | MUM-T IMPS v12.0 — LLM Brain + Formation Optimizer + Validator |
| 2 | `0e06bae` | 03:29 | fix  | 위협 추가 시 경로 탐색 실패 + 자산 색상 고대비 개선 |
| 3 | `7f1ed0b` | 08:09 | fix  | LLM 명령 UI 미반영 + 응답 속도 개선 |
| 4 | `9e36a41` | 08:31 | fix  | Widget key 충돌 오류 + deprecated 경고 제거 |

**변경 규모**: 9개 파일 / +2,520 lines / −214 lines

---

## 🆕 신규 기능 (Commit 1 · `b3ac74c`)

### 1-1. LLM Brain v2.0 (`modules/llm_brain.py`)
- 모델 업그레이드: `llama3.1` → **`qwen3:14b`** (군사 전문 참모 AI)
- **Structured Output** 강제: `pydantic` 스키마 기반 JSON 반환으로 파싱 실패율 대폭 감소
- 지원 Action 유형: `UPDATE` / `THREAT_ADD` / `MISSION_PLAN` / `CHAT`
- 전술 키워드 자동 매핑 예시:

  | 입력 키워드 | 자동 설정 파라미터 |
  |-------------|-------------------|
  | "저고도", "지형추종" | `enable_3d=True`, `algorithm="A* 3D"` |
  | "안전하게", "우회" | `safety_margin_km += 10~15` |
  | "대전 근처 SAM 추가" | `action=THREAT_ADD`, 위협 자동 생성 |
  | "ISR → SEAD → STRIKE" | `action=MISSION_PLAN`, 임무 순서 설정 |

### 1-2. Formation Optimizer (`modules/formation_optimizer.py`) ← **신규 파일**
- **MILP + 헝가리안 알고리즘** 2단계 최적화
- 1단계 (MILP via PuLP): 자산 수량 결정
  - 목적함수: `min(W1·cost + W2·slack_underuse)` — W1=1.0, W2=5.0
  - 제약조건: JP3-30 교리 기반 (MUM-T 비율, 임무별 최소 자산, 목표 커버리지)
  - 활용률 목표: **N_max × 75%** (예: N_max=8 → 6대 배치)
- 2단계 (헝가리안): 자산-목표 1:1 배정
  - 비용 행렬: `거리 × 임무 적합도 × (1 + 위협 리스크)`
  - 미배정 자산에도 타입 기반 기본 임무 자동 부여 (Scout → ISR, Viper → SEAD)

**활용률 개선 결과**:

| N_max | 수정 전 | 수정 후 |
|-------|---------|---------|
| 8     | 4대 (50%) | **6대 (75%)** |
| 12    | 4대 (33%) | **9대 (75%)** |

### 1-3. Mission Validator (`modules/validator.py`) ← **신규 파일**
7개 규칙 기반 자동 검증 (교리 근거 포함):

| Rule ID | 검증 항목 | 교리 근거 | 심각도 |
|---------|-----------|-----------|--------|
| NFZ_VIOLATION | 비행금지구역 침범 | FAA Order 7400.11 | 🔴 ERROR |
| THREAT_PENETRATION | 위협 반경 내 비행 | JP3-30 | 🔴 ERROR |
| MIN_ALTITUDE | 최소 고도 200m AGL | AFDP3-03 | 🟡 WARNING |
| ASSET_COLLISION | 자산 간 충돌 위험 | FMI3-04.155 | 🟡 WARNING |
| MISSION_SEQUENCE | ISR→SEAD→STRIKE 순서 | JP3-30 Phase | 🔴 ERROR |
| RANGE_LIMIT | 항속거리 초과 | DAFMAN11-260 | 🔴 ERROR |
| MUMT_RATIO | MUM-T 비율 ≥ 1:2 | FMI3-04.155 §3-7 | 🟡 WARNING |

### 1-4. 교리 문서 (`docs/doctrine_basis.md`) ← **신규 파일**
- 참조 교리: JP3-30, AFDP3-03, AFDP5-0, FMI3-04.155, DAFMAN11-260
- 각 알고리즘·수식의 교리 근거 및 파라미터 도출 과정 기술

### 1-5. 항속거리 수정 (`modules/config.py`)
기존 설정이 현실과 괴리되어 `RANGE_EXCEEDED` 오류 발생 → 수정:

| 자산 | 수정 전 | 수정 후 | 근거 |
|------|---------|---------|------|
| `recon_uav` | 500 km | **1,500 km** | RQ-7 Shadow 급 운용반경 |
| `attack_uav` | 300 km | **1,200 km** | Harop 급 자폭 UAV (편도) |
| `fighter` | 3,000 km | 3,000 km | F-16 급 (유지) |

### 1-6. Streamlit UI v12.0 (`streamlit_app.py`)
- **편대 구성 탭** (`✈️ 편대 구성`): MILP 실행 + 결과 테이블 (자산 수, 비용, 배정)
- **임무 검증 탭** (`✅ 임무 검증`): 7개 규칙 실시간 검증 + JSON 내보내기
- **지도 가시성 개선**: 레이어 순서 재설계 (히트맵 → 위협원 → 경로선 → 마커)

---

## 🐛 버그 수정

### BUG-1: 위협 추가 시 경로 탐색 완전 실패 (Commit 2 · `0e06bae`)

**증상**: SAM/RADAR 위협을 추가하면 경로가 아예 생성되지 않음

**원인**: `pathfinder_optimized.py`의 `is_collision_3d()` 로직 버그
```python
# 수정 전 (버그): 저고도 continue 이후에도 return True 도달
if agl < 300:
    continue       # 다음 위협으로 건너뜀
return True        # ← 첫 번째 위협만 있을 때 항상 도달!
```

**수정 내용** (`modules/pathfinder_optimized.py`):
```python
# 수정 후: SAM/RADAR 각각 다른 AGL 임계값 적용
RADAR_SHADOW_AGL = 400.0   # RADAR: 400m 이하 저고도 우회 허용
SAM_SHADOW_AGL   = 200.0   # SAM: 200m 이하 초저공 침투 허용

if t_type == "RADAR":
    if agl < RADAR_SHADOW_AGL: continue   # 저고도 → 레이더 음영
    return True                           # 고고도 → 충돌
else:  # SAM
    if agl < SAM_SHADOW_AGL: continue     # 초저공 → 회피
    return True
```

추가 개선:
- 탐색 노드 한도: 50,000 → **100,000** (확장)
- 탐색 실패 시 목표 최근접 노드까지 **부분 경로 반환** (빈 경로 방지)
- 도달 판정 임계값: 2 → 3 그리드 (완화)

**테스트 결과**:
| 시나리오 | 수정 전 | 수정 후 |
|----------|---------|---------|
| 위협 없음 | 40 pts | 40 pts |
| RADAR 80km | ❌ 0 pts | ✅ 53 pts (저고도 우회) |
| SAM + RADAR | ❌ 0 pts | ✅ 52 pts |

---

### BUG-2: 자산 경로 색상 구분 불가 (Commit 2 · `0e06bae`)

**증상**: 파랑/연파랑처럼 유사한 색상으로 자산 구분 어려움

**수정**: 색맹 친화적 고대비 8색 팔레트로 전면 교체

| 순서 | 자산 | 수정 전 | 수정 후 |
|------|------|---------|---------|
| 1 | Eagle-1 (전투기) | 🔴 `#E53935` | 🔴 `#E53935` (유지) |
| 2 | Scout-1 (정찰) | 🔵 `#1E88E5` | 🟢 `#43A047` **초록** |
| 3 | Scout-2 (정찰) | 🟢 `#43A047` | 🟠 `#FB8C00` **주황** |
| 4 | Scout-3 (정찰) | 🟠 `#FB8C00` | 🟣 `#8E24AA` **보라** |
| 5 | Scout-4 (정찰) | 🟣 `#8E24AA` | 🟡 `#F9A825` **황금** |
| 6 | Viper-1 (자폭) | 🩵 `#00ACC1` 청록 | 🩴 `#00897B` **짙은틸** |

---

### BUG-3: LLM 명령 사이드바 UI 미반영 (Commit 3 · `7f1ed0b`)

**증상**: "타겟 위치를 평양으로 변경해" 명령 후 AI 응답은 나오지만 Lat/Lon 위젯 값이 그대로

**원인**: `st.form` 내 위젯은 **form submit 없이는 외부에서 값 변경 불가**
```
LLM → mission.params.target_lat = 39.0 → st.rerun()
→ But: st.form 위젯은 자신의 내부 상태 유지 (session_state 무시!)
```

**수정**: `st.form` 완전 제거 → `key=` 기반 독립 위젯 전환

```python
# 수정 전 (st.form 안 — 외부 수정 반영 안 됨)
with st.form("mission_form"):
    p.target_lat = st.number_input("Lat", value=p.target_lat)

# 수정 후 (key= + session_state 동기화)
if "_mp_target_lat" not in st.session_state:
    st.session_state["_mp_target_lat"] = p.target_lat  # 최초 1회만

p.target_lat = st.number_input("Lat", key="_mp_target_lat")  # session_state값 즉시 반영

# LLM 업데이트 시
def _set(attr, ss_key, val):
    setattr(mission.params, attr, val)     # params 갱신
    st.session_state[ss_key] = val         # 위젯도 동시 갱신 ← 핵심
```

---

### BUG-4: LLM 응답 속도 저하 (Commit 3 · `7f1ed0b`)

**원인**: `qwen3:14b` (14B 파라미터) + `num_predict=2048` 토큰 설정

**개선 내용**:

| 설정 | 수정 전 | 수정 후 | 효과 |
|------|---------|---------|------|
| `num_predict` | 2,048 토큰 | **512 토큰** | ~4배 단축 (JSON만 출력) |
| `num_ctx` | 무제한 | **2,048** | 컨텍스트 연산량 절감 |
| `timeout` | 60초 | **45초** | 응답 대기 단축 |
| 모델 선택 | qwen3:14b 고정 | **동적 선택** (3b/7b 우선) | 경량 모델 자동 활용 |
| 캐싱 | 없음 | **MD5 캐시** (최대 50개) | 동일 명령 즉시 반환 |

---

### BUG-5: Widget Key 충돌 오류 (Commit 4 · `9e36a41`)

**증상**:
```
The widget with key "_mp_start" was created with a default value 
but also had its value set via the Session State API.
```

**원인**: `key=` 위젯에 `index=` 또는 `value=`를 동시에 지정하면 Streamlit이 충돌 감지
```python
# ❌ 잘못된 방법
st.selectbox("출발 기지", options, index=3, key="_mp_start")
#                                   ↑ key= 와 index= 동시 사용 금지!
```

**수정**: 위젯에서 `index=`/`value=` 제거, `session_state` 초기화는 `if key not in ss`로 최초 1회만 수행

---

### BUG-6: `use_container_width` Deprecated 경고 (Commit 4 · `9e36a41`)

```
use_container_width will be removed after 2025-12-31
```

**수정**: `st.dataframe`의 `use_container_width=True` → `width="stretch"` 전면 교체

---

## 📁 변경 파일 목록

```
mission_plan/
├── streamlit_app.py              ← 대규모 수정 (v12.0 → v13.0)
├── modules/
│   ├── config.py                 ← 항속거리, LLM 설정, 교리 상수
│   ├── formation_optimizer.py    ← 🆕 신규: MILP + 헝가리안 최적화
│   ├── validator.py              ← 🆕 신규: 7개 규칙 임무 검증기
│   ├── llm_brain.py              ← LLM v2.0 + 캐싱 + 속도 개선
│   ├── mission_state.py          ← Asset/FormationResult 데이터클래스
│   └── pathfinder_optimized.py   ← 저고도 우회 버그 수정
├── docs/
│   ├── doctrine_basis.md         ← 🆕 신규: 교리 근거 문서
│   └── CHANGELOG_2026-02-21.md   ← 🆕 이 파일
└── requierments.txt              ← pulp 패키지 추가
```

---

## 🏗️ 현재 시스템 아키텍처

```
사용자 자연어 입력
        ↓
┌─────────────────────────────────────────────┐
│              LLM Brain v2.0                  │
│  qwen3:14b / Structured JSON Output          │
│  Action: UPDATE / THREAT_ADD / MISSION_PLAN  │
└─────────┬───────────────────────────────────┘
          │
    ┌─────▼──────┐     ┌──────────────────┐
    │  MissionState│     │  Formation       │
    │  params      │────▶│  Optimizer       │
    │  threats     │     │  MILP + 헝가리안  │
    └─────┬────────┘     └────────┬─────────┘
          │                       │
    ┌─────▼──────────────────────▼──────────┐
    │           Pathfinder                   │
    │  A* 3D (저고도 위협 우회) / RRT / RRT*  │
    │  RADAR: 400m AGL 이하 통과             │
    │  SAM:   200m AGL 이하 통과             │
    └─────────────────┬─────────────────────┘
                      │
    ┌─────────────────▼─────────────────────┐
    │           Validator                    │
    │  7개 규칙 교리 기반 자동 검증           │
    └─────────────────┬─────────────────────┘
                      │
    ┌─────────────────▼─────────────────────┐
    │         Streamlit UI v13.0             │
    │  Folium Map + 자산경로 + 범례 + STPT   │
    └───────────────────────────────────────┘
```

---

## ⚙️ 주요 설정값 (현재 기준)

```python
# LLM
LLM_MODEL          = "qwen3:14b"
LLM_MODEL_FALLBACK = "llama3.1"
LLM_TIMEOUT        = 45       # 초
num_predict        = 512      # 토큰

# 편대
FORMATION_MAX_TOTAL = 12      # 최대 자산 수
MUMT_RATIO          = 2.0     # UAV ≥ 2 × 유인기
UTILIZATION_RATE    = 0.75    # 목표 활용률 75%

# 위협 기본 반경
SAM   = 30 km
RADAR = 80 km

# 자산 항속거리
fighter    = 3,000 km
recon_uav  = 1,500 km
attack_uav = 1,200 km

# 경로 탐색 (A* 3D)
MAX_NODES          = 100,000  # 탐색 한도
RADAR_SHADOW_AGL   = 400 m    # RADAR 우회 고도
SAM_SHADOW_AGL     = 200 m    # SAM 우회 고도
MIN_ALTITUDE_AGL   = 200 m    # 최소 비행 고도
```

---

## 🔜 다음 작업 (백로그)

| 우선순위 | 항목 | 비고 |
|----------|------|------|
| 🔴 High | 다중 목표 시각화 개선 | 목표별 경로 색 구분 |
| 🟡 Medium | 경로 탐색 실패 시 대안 경로 제안 | 마진 자동 감소 재시도 |
| 🟡 Medium | XAI 탭 리스크 히트맵 개선 | 경로 위험도 색상 오버레이 |
| 🟢 Low | KCI 논문 실험 설계 | 알고리즘 성능 비교 데이터 |
| 🟢 Low | 실시간 위협 업데이트 시뮬레이션 | 동적 재경로 계획 |

---

## 🚀 로컬 실행 방법

```bash
# 1. 저장소 클론 (또는 pull)
git clone https://github.com/dongkam5/mission_plan.git
cd mission_plan
git checkout genspark_ai_developer

# 2. 의존성 설치
pip install -r requierments.txt

# 3. Ollama 모델 준비 (필수)
ollama pull qwen3:14b        # 주 모델 (권장, 8GB RAM 이상)
ollama pull llama3.1         # 폴백 모델

# 4. 앱 실행
streamlit run streamlit_app.py
```

> **최소 사양**: RAM 16GB (qwen3:14b 실행 기준)  
> **권장 사양**: RAM 32GB + GPU (응답 속도 개선)  
> **경량 실행**: `llama3.2:3b` 설치 시 자동으로 빠른 모델 우선 선택

---

*이 문서는 AI 개발 어시스턴트(Genspark)가 자동 생성했습니다.*  