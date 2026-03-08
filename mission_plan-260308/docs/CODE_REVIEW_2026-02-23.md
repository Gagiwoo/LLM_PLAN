# 코드 리뷰 보고서 — 위협 유형/점수 계산 신규 기능
**작성일**: 2026-02-23  
**대상 파일**: `mission_plan-mid_present.zip` (팀원 제출)  
**기준 브랜치**: `genspark_ai_developer` (v13.0, 커밋 `9e36a41`)  
**리뷰어**: AI 코드 리뷰 시스템

---

## 1. 요약 (Executive Summary)

팀원이 제출한 코드는 **v10.5 베이스**이며, 주요 신규 기능은 아래 두 가지다.

| 신규 기능 | 포함 파일 |
|---|---|
| 적성국 방공망 DB (`THREAT_DB`) 및 위협 정밀 제원(XAI) 파라미터 | `modules/mission_state.py` |
| SNR 기반 탐지확률(P_D) + SSKP 피격확률(P_K) 결합 위험도 계산 | `modules/xai_utils.py` |

현재 운영 중인 **v13.0**에는 이 두 기능이 **아직 미포함** 상태이며,  
`formation_optimizer`, `validator`, LLM Brain v2.1 등 v13.0 전용 기능은 팀원 제출본에 **없음**.

> **결론**: 팀원 신규 코드는 기술적으로 우수하며 통합 가치가 높다.  
> 단, 직접 파일 덮어쓰기(overwrite) 방식의 머지는 **불가** — 충돌 지점이 존재한다.  
> 아래 통합 가이드에 따라 **선택적 병합(cherry-pick merge)** 방식을 권장한다.

---

## 2. 팀원 코드 상세 분석

### 2-A. `modules/mission_state.py` — THREAT_DB + XAI 파라미터

#### 2-A-1. 신규 추가: `THREAT_DB` 딕셔너리

```python
THREAT_DB = {
    "S-400 Triumf (SA-21)": {"type":"SAM","radius_km":250.0,"loss":6.0,"rcs_m2":2.5,
                               "pd_k":0.50,"sskp":0.90,"peak_ratio":0.32,"sigma_ratio":0.25},
    "S-300 PMU2 (SA-20)":   {"type":"SAM","radius_km":195.0,"loss":7.0,"rcs_m2":2.5,
                               "pd_k":0.45,"sskp":0.85,"peak_ratio":0.33,"sigma_ratio":0.20},
    "Buk-M2 (SA-17)":       {"type":"SAM","radius_km":45.0, "loss":8.0,"rcs_m2":2.5,
                               "pd_k":0.40,"sskp":0.80,"peak_ratio":0.33,"sigma_ratio":0.20},
    "Pantsir-S1 (SA-22)":   {"type":"SAM","radius_km":18.0, "loss":9.0,"rcs_m2":2.5,
                               "pd_k":0.35,"sskp":0.70,"peak_ratio":0.33,"sigma_ratio":0.15},
    "S-75 Dvina (SA-2)":    {"type":"SAM","radius_km":45.0, "loss":12.0,"rcs_m2":2.5,
                               "pd_k":0.20,"sskp":0.40,"peak_ratio":0.44,"sigma_ratio":0.15},
    "조기경보 레이더":        {"type":"RADAR","radius_km":400.0,"loss":5.0,"rcs_m2":2.5,
                               "pd_k":0.30,"sskp":0.0,"peak_ratio":0.0,"sigma_ratio":0.0},
}
```

**평가**: ✅ 잘 구성됨
- F-16 전투기 대응 기준의 현실적 파라미터 설정
- SAM 5종 + 조기경보 레이더 1종 수록
- `peak_ratio`, `sigma_ratio`를 radius_km의 비율로 저장해 `pk_peak_km`, `pk_sigma_km` 계산 용이
- `조기경보 레이더`의 `sskp=0.0`, `peak_ratio=0.0` 설정으로 P_K=0 처리 → ZeroDivisionError 방지됨

**주의사항**:
- 현재 v13.0의 `mission_state.py`에는 `THREAT_DB`가 없으므로, 팀원 코드의 `streamlit_app.py`는 `THREAT_DB` import가 필요함 (`from modules.mission_state import MissionState, Threat, THREAT_DB`)
- v13.0 `streamlit_app.py`에서는 `THREAT_DB`를 import하지 않아 **직접 통합 시 ImportError 발생**

#### 2-A-2. 신규 추가: `Threat` dataclass XAI 파라미터

팀원이 기존 `Threat` 클래스에 추가한 7개 필드:

| 필드 | 기본값 | 의미 |
|------|--------|------|
| `loss` | `8.0` | 시스템 손실 (대기 감쇠, 기계적 손실 dB) |
| `rcs_m2` | `2.5` | F-16 평균 RCS (m²) |
| `pd_k` | `0.4` | 탐지 곡선 가파름 계수 (Steepness) |
| `sskp` | `0.75` | 단발 격추 확률 (Single-Shot Kill Probability) |
| `pk_peak_km` | `0.0` | No Escape Zone 최대 치명 거리 (km) |
| `pk_sigma_km` | `0.0` | 교전 구역 폭 σ (km) |
| `weight` | `1.0` | 위협 가중치 |

**평가**: ✅ 우수
- 기존 `Threat` 필드와 충돌 없이 **하위 호환** — 기존 코드가 생성한 `Threat` 객체도 그대로 동작
- 모든 필드에 기본값이 있으므로 기존 `Threat(name=..., type=..., ...)` 호출 코드 수정 불필요
- `to_dict()` / `from_dict()` 메서드는 `asdict()` 기반이므로 새 필드 자동 포함

**주의사항**:
- v13.0 `mission_state.py`에는 추가로 `Asset`, `FormationResult` 클래스와 `MissionState.set_formation()` 메서드가 존재 — 팀원 버전에는 이것이 없어 **직접 교체 시 FormationOptimizer가 동작 불가**

#### 2-A-3. `MissionState` 클래스 차이

| 항목 | 팀원 v10.5 | 현재 v13.0 |
|------|------------|------------|
| `self.formation` | ❌ 없음 | ✅ `Optional[FormationResult]` |
| `set_formation()` | ❌ 없음 | ✅ 있음 |
| `save_to_file()` 포맷 | formation 미포함 | formation 포함 |

---

### 2-B. `modules/xai_utils.py` — 위험도 계산 고도화

#### 2-B-1. 핵심 알고리즘 차이: 누적 생존 확률 vs 단순 최대값

| 구분 | 팀원 코드 | 현재 코드 |
|------|-----------|-----------|
| 위험도 집계 방식 | **독립 시행 결합 확률** `survival *= (1 - risk_i)` | **단순 최대값** `max_risk = max(max_risk, risk_i)` |
| 수식 | `total_risk = 1 - Π(1 - risk_i)` | `total_risk = max(risk_i)` |
| 여러 위협 중첩 | 각 위협이 독립적으로 생존 확률에 곱해짐 | 가장 위험한 위협 하나만 반영 |

**평가**: ✅ 팀원 방식이 수학적으로 더 정확  
복수 위협 환경(예: SAM + 레이더 중첩 구역)에서 실제 위험도를 더 현실적으로 반영한다.  
단, 히트맵이 전반적으로 더 진하게(높게) 표시될 수 있어 UX 변화 주의.

#### 2-B-2. P_K 계산: SSKP 반영

**팀원 코드 (신규)**:
```python
sskp = float(t.get("sskp", 0.75))
if sigma <= 0.0 or sskp <= 0.0:
    P_K = 0.0  # ← ZeroDivisionError 방지 패치
else:
    P_K = sskp * math.exp(-((dist_km - d0) ** 2) / (2.0 * sigma ** 2))
```

**현재 코드**:
```python
# sskp 파라미터 없음
P_K = math.exp(-((dist_km - d0) ** 2) / (2.0 * sigma ** 2))
```

**평가**: ✅ 팀원 방식이 현실적
- 현재 코드는 `sigma=0`이면 ZeroDivisionError 발생 가능 — 팀원이 패치함
- 조기경보 레이더처럼 `sskp=0.0`인 경우를 올바르게 처리

#### 2-B-3. `analyze_path_risk()` — 3D 경로 지원

**팀원 코드 (신규)**:
```python
for i, p in enumerate(path):
    lat, lon = p[0], p[1]
    target_alt = p[2] if len(p) == 3 else None   # ← 3D 경로(3-tuple) 지원
    risk = XAIUtils.calculate_risk_score(lat, lon, threats, margin, terrain_loader, target_alt=target_alt)
```

**현재 코드**:
```python
for i, (lat, lon) in enumerate(path):   # ← 2D만 지원, 3D 경로면 ValueError
    risk = XAIUtils.calculate_risk_score(lat, lon, threats, margin)
```

**평가**: ✅ 팀원 방식이 버그 수정 포함  
현재 `analyze_path_risk()`는 A* 3D로 계산된 `(lat, lon, alt)` 3-tuple 경로를 입력하면 **ValueError**가 발생한다. 팀원 코드가 이를 수정했다.

#### 2-B-4. `calculate_risk_score()` — target_alt 파라미터

팀원 코드는 `target_alt` 인자를 추가해 실제 비행 고도를 반영한 LOS 체크를 수행한다.  
`generate_heatmap_data()`는 기존처럼 `target_alt=None` (기본 500m 가정)으로 호출.

---

### 2-C. `modules/config.py` — 차이점

팀원과 현재 v13.0의 config.py 차이는 **실질적 내용 충돌 없음**.

| 항목 | 팀원 | 현재 v13.0 |
|------|------|------------|
| LLM_MODEL | `"llama3.1"` | `"qwen3:14b"` |
| LLM_TIMEOUT | 30초 | 45초 |
| 교리 맥락 상수 (`MISSION_TYPES` 등) | ❌ 없음 | ✅ 추가됨 |
| 기타 상수 | 동일 | 동일 |

> `config.py`는 현재 v13.0 버전 유지 — 교체 불필요.

---

### 2-D. `streamlit_app.py` — 버전 차이 (v10.5 vs v13.0)

팀원 제출본의 `streamlit_app.py`는 **v10.5 기반**이며, v13.0에는 없는 구조를 포함한다:

| 기능 | 팀원 v10.5 | 현재 v13.0 |
|------|------------|------------|
| 탭 구성 | 작전통제, 위협관리, AI판단, 디버그 (4개) | 작전통제, 위협관리, 편대구성, 임무검증, AI판단, 디버그 (6개) |
| 위협 추가 UI | **군사 DB 선택** + 수동 설정 (3방식) | 수동 설정만 (3방식) |
| THREAT_DB 연동 | ✅ `THREAT_DB` 선택 → 자동 파라미터 입력 | ❌ 미구현 |
| Formation Optimizer | ❌ 없음 | ✅ MILP + Hungarian |
| Mission Validator | ❌ 없음 | ✅ 7개 교리 규칙 검증 |
| LLM Widget 동기화 | ❌ st.form 내부 (미반영 버그) | ✅ session_state 직접 갱신 |
| 위젯 키 충돌 | ❌ 있음 (`index=`와 `key=` 동시 사용) | ✅ 수정됨 |

> ⚠️ **팀원 `streamlit_app.py` 직접 적용 불가** — v13.0의 formation/validator 기능이 소실된다.

---

## 3. 통합 권장 방안

### ✅ 채택 (v13.0에 통합 권장)

#### STEP 1: `modules/mission_state.py` — THREAT_DB + XAI 파라미터 추가

**추가 내용**:
1. 파일 상단에 `THREAT_DB` 딕셔너리 추가
2. `Threat` dataclass에 XAI 파라미터 7개 필드 추가 (`loss`, `rcs_m2`, `pd_k`, `sskp`, `pk_peak_km`, `pk_sigma_km`, `weight`)
3. v13.0의 `Asset`, `FormationResult`, `MissionState.set_formation()` 는 **그대로 유지**

**호환성**: ✅ 완전 하위 호환 (기존 `Threat()` 호출 코드 수정 불필요)

---

#### STEP 2: `modules/xai_utils.py` — 고도화된 위험도 계산 통합

**통합 내용**:
1. `calculate_risk_score()`: `target_alt` 파라미터 추가, 누적 생존 확률 방식으로 전환, P_K에 `sskp` 반영
2. `analyze_path_risk()`: 3D 경로(3-tuple) 지원 추가, `terrain_loader` 파라미터 추가

**주의**: 히트맵 색상이 변경될 수 있음 (단순 최대 → 누적 확률이므로 전반적으로 위험도 수치 상승)

---

#### STEP 3: `streamlit_app.py` — 위협 추가 UI 업그레이드

**통합 내용 (탭 구조는 v13.0 유지, 위협 관리 탭만 업데이트)**:
```python
# 현재 코드에 아래 import 추가:
from modules.mission_state import MissionState, Threat, THREAT_DB  # THREAT_DB 추가

# tab_intel (위협 관리 탭) 내 form 교체:
add_type = st.radio('위협 입력 방식',
    ["군사 DB (SAM/RADAR)", "수동 설정 (SAM/RADAR)", "수동 설정 (NFZ)"],
    horizontal=True)

# 군사 DB 선택 시: THREAT_DB에서 파라미터 자동 입력
# 수동 설정 시: 기존 UI 유지
```

---

### ❌ 채택 불가 (v13.0 기능 유지 필요)

| 항목 | 이유 |
|------|------|
| 팀원 `streamlit_app.py` 전체 교체 | formation/validator 탭 소실 |
| 팀원 `config.py` 교체 | LLM 모델 다운그레이드 (llama3.1), 교리 상수 소실 |
| 팀원 `mission_state.py` 전체 교체 | Asset, FormationResult 클래스 소실 → FormationOptimizer 오류 |

---

## 4. 코드 품질 평가

| 항목 | 점수 | 비고 |
|------|------|------|
| 코드 가독성 | ★★★★☆ | 주석 충실, 변수명 명확 |
| 수학적 정확도 (P_D, P_K) | ★★★★★ | SNR 기반 로짓 모델, SSKP 반영 현실적 |
| 버그 패치 | ★★★★★ | ZeroDivisionError(`sigma=0`, `sskp=0`) 완전 수정 |
| 3D 경로 호환성 | ★★★★☆ | `analyze_path_risk` 3-tuple 지원 추가 |
| 하위 호환성 | ★★★★☆ | Threat 신규 필드 모두 기본값 있음 |
| v13.0 연동 준비 | ★★★☆☆ | formation/validator 탭 미포함 (별도 통합 필요) |

---

## 5. 통합 후 예상 개선 효과

### 히트맵 (위험도 시각화)
- **Before**: 여러 SAM이 중첩돼도 가장 위험한 하나만 표시
- **After**: 중첩 구역일수록 위험도가 정확히 높아짐 → 실전 경로 계획 신뢰도 향상

### 위협 추가 UI
- **Before**: 반경/타입 수동 입력 (전문 지식 필요)
- **After**: "S-400 Triumf" 선택만 해도 250km 반경, 정밀 교전 파라미터 자동 설정

### 경로 위험도 분석
- **Before**: 3D 경로(A* 3D 결과) 분석 시 ValueError 발생
- **After**: 고도 정보 포함 정밀 분석 가능

---

## 6. 통합 체크리스트

머지 전 확인 사항:

- [ ] `THREAT_DB` 추가 후 `python3 -c "from modules.mission_state import THREAT_DB; print('OK')"` 실행
- [ ] `Threat` 신규 필드 추가 후 기존 `Threat(name=..., type=..., lat=..., lon=..., radius_km=...)` 호출 정상 동작 확인
- [ ] `xai_utils.py` 교체 후 히트맵 생성 테스트 (`generate_heatmap_data` 호출)
- [ ] `analyze_path_risk`에 3D 경로(`[(lat, lon, alt), ...]`) 입력 테스트
- [ ] `streamlit_app.py`의 위협 관리 탭에 `군사 DB` 옵션 추가 후 앱 구동 테스트
- [ ] Formation 탭, Validation 탭 기존 동작 유지 확인

---

## 7. 파일별 머지 결정 요약

| 파일 | 결정 | 방식 |
|------|------|------|
| `modules/mission_state.py` | ✅ **부분 통합** | `THREAT_DB` + `Threat` XAI 필드만 추가, 나머지 v13.0 유지 |
| `modules/xai_utils.py` | ✅ **전체 교체** | 팀원 코드가 현재 코드보다 모든 면에서 개선됨 |
| `modules/config.py` | ❌ **현재 유지** | v13.0이 상위 호환 |
| `streamlit_app.py` | ✅ **부분 통합** | 위협 관리 탭 UI만 팀원 코드로 교체 |
| 기타 모듈 (`pathfinder_*.py` 등) | ❌ **현재 유지** | v13.0이 상위 버전 |

---

*본 리뷰는 `genspark_ai_developer` 브랜치 기준으로 작성되었습니다.*  
*통합 작업은 별도 피처 브랜치(`feat/threat-db-integration`)를 생성해 진행을 권장합니다.*
