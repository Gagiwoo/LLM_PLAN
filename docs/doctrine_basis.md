# IMPS 시스템 설계 교리 근거

**프로젝트**: LLM 기반 MUM-T 자율 임무계획 시스템 (IMPS)  
**작성일**: 2026-02-21  
**버전**: v1.0

---

## 목차

1. [참조 교범 목록](#1-참조-교범-목록)
2. [시스템 파이프라인 교리 근거](#2-시스템-파이프라인-교리-근거)
3. [임무 유형 정의](#3-임무-유형-정의)
4. [자산 구성 및 MUM-T 팀 구조](#4-자산-구성-및-mum-t-팀-구조)
5. [MILP 제약 조건 근거](#5-milp-제약-조건-근거)
6. [LLM 교리 파싱 근거](#6-llm-교리-파싱-근거)
7. [경로계획 및 위협 회피 근거](#7-경로계획-및-위협-회피-근거)
8. [안전 마진 기준](#8-안전-마진-기준)
9. [검증기 규칙 근거](#9-검증기-규칙-근거)
10. [RL 비채택 근거](#10-rl-비채택-근거)

---

## 1. 참조 교범 목록

| 교범 | 발행처 | 연도 | 활용 모듈 |
|---|---|---|---|
| **JP 3-30** Joint Air Operations | US Joint Chiefs of Staff | 2019 | `llm_brain.py`, `formation_optimizer.py` |
| **AFDP 3-03** Counterland Operations | US Air Force | 2024 | `llm_brain.py`, `formation_optimizer.py` |
| **AFDP 5-0** Planning | US Air Force | - | `formation_optimizer.py`, `validator.py` |
| **FMI 3-04.155** Army UAS Operations | US Army | 2006 | `formation_optimizer.py`, `mission_state.py` |
| **DoD UAS Roadmap 2011-2036** | US DoD | 2011 | 시스템 설계 전반 |
| **Navy Unmanned Campaign Framework** | US Navy | 2021 | MUM-T 개념 |
| **DAFMAN 11-260** Tactics Development | US Air Force | 2023 | `validator.py` |
| **SDP 3-99** Joint All-Domain Operations | US Space Force | 2021 | 시스템 설계 전반 |
| **Pelosi et al. (2012)** Range-Limited UAV Trajectory | Applied AI Journal | 2012 | `radar_shadow.py` |

---

## 2. 시스템 파이프라인 교리 근거

### 전체 파이프라인
```
[입력] 자연어 명령
  ↓
① LLM: 교리·ROE 파싱          ← JP 3-30 JPPA Step 1-2 (Mission Analysis)
  ↓
② LLM: 임무 분류·시퀀싱        ← AFDP 3-03 임무유형 + JP 3-30 MAAP 순서
  ↓
③ MILP: 편대 구성 최적화        ← JP 3-30 Apportionment/Allocation 원칙
  ↓
④ 헝가리안: 자산↔목표 배정      ← JP 3-30 Tasking by Effect 원칙
  ↓
⑤ A*/D*Lite: 3D 경로 계획      ← Pelosi et al. (2012) A* + Terrain Masking
  ↓
⑥ 위협 모델: P_D×P_K           ← Pelosi et al. (2012) Probabilistic Detection
  ↓
⑦ 규칙 기반 검증기              ← AFDP 5-0 COA Analysis & Wargaming
  ↓
⑧ 다목적 평가                   ← JP 3-30 COA Comparison Criteria
  ↓
[출력] XAI 설명 + 지도
```

### 근거 원문
> *"The JFACC uses the joint planning process for air (JPPA) to develop a JAOP...  
> Step 1: Initiation → Step 2: Mission Analysis → Step 3: COA Development →  
> Step 4: COA Analysis and Wargaming → Step 5: COA Comparison →  
> Step 6: COA Approval → Step 7: Plan or Order Development"*  
> — JP 3-30, p.III-1

---

## 3. 임무 유형 정의

### 3.1 ISR (Intelligence, Surveillance, Reconnaissance)
**정의**: 적 활동·자원·지형에 대한 정보 수집  
**수행 시점**: 모든 임무의 선행 단계 (항상 최우선)  
**근거**:
> *"The JFACC will normally be the supported commander for the airborne ISR effort...  
> ISRD collection managers build a daily collection plan"*  
> — JP 3-30, p.III-28

### 3.2 SEAD (Suppression of Enemy Air Defenses)
**정의**: 적 SAM·레이더 등 방공 시스템 무력화  
**수행 시점**: STRIKE 임무 전 반드시 선행  
**근거**:
> *"SEAD is treated as a supporting requirement for the Master Air Attack Plan (MAAP).  
> Planners must account for SEAD assets to protect strike packages"*  
> — JP 3-30, p.III-24

### 3.3 STRIKE (Air Interdiction)
**정의**: 적 핵심 표적 파괴 (Air Interdiction)  
**수행 시점**: SEAD 완료 후 실시  
**근거**:
> *"Air Interdiction: air operations conducted to divert, disrupt, delay, or destroy  
> the enemy's military potential before it can be brought to bear effectively  
> against friendly forces"*  
> — AFDP 3-03, Ch.1

### 3.4 CAS (Close Air Support)
**정의**: 아군 지상군 근접 지원  
**수행 시점**: 지상군 요청 시 (선택적)  
**근거**:
> *"CAS involves employing ordnance within close proximity of friendly ground troops  
> and requires detailed integration to prevent friendly fire incidents"*  
> — AFDP 3-03, Ch.1

### 임무 수행 순서 (교리 기반)
```
ISR → SEAD → STRIKE → CAS (필요 시)
```
> *"The completed MAAP matches available resources to the prioritized target list,  
> and accounts for... suppression of enemy air defenses requirements, ISR,  
> and other factors affecting the plan"*  
> — JP 3-30, p.III-24

---

## 4. 자산 구성 및 MUM-T 팀 구조

### 4.1 3가지 자산 정의

| 자산 | 기호 | 역할 | 주요 임무 |
|---|---|---|---|
| 전투기 (Fighter) | `x_f` | 유인 전투기, 팀 리더 | STRIKE, CAS, SEAD 지원 |
| 정찰UAV | `x_r` | 무인 정찰, 센서 플랫폼 | ISR, BDA |
| 자폭UAV (Loitering Munition) | `x_k` | 무인 타격, 고위협 침투 | SEAD, STRIKE 지원 |

### 4.2 MUM-T 팀 구조 (FMI 3-04.155 기반)

**기본 원칙**: Lead/Wingman 구조
```
전투기 (Lead) ──────── 자폭/정찰UAV (Wingman)
     │                        │
  통제·타격               정보수집·선행침투
```

> *"A MUM team is a lead/wingman team operating with control of one or more UA.  
> In many cases, using unmanned systems in high threat areas will reduce  
> the exposure of manned systems to hostile fire or effects."*  
> — FMI 3-04.155

**권장 팀 비율**: 유인기 1 : 무인기 2
> *"The teaming of UAS with manned systems brings a synergy to the battlespace  
> allowing each platform to use its combat systems in the most efficient manner"*  
> — FMI 3-04.155

### 4.3 임무별 권장 팀 구성

| 임무 | 팀 구성 | 역할 분담 |
|---|---|---|
| ISR | 정찰UAV ≥ 2 | 로테이션 정찰 (교대 운용) |
| SEAD | 자폭UAV ≥ 1 + 전투기 ≥ 1 | UAV 선행침투 + 전투기 후속타격 |
| STRIKE | 전투기 ≥ 1 (+ 자폭UAV 선택) | 전투기 주타격, UAV 레이저 지정 |
| CAS | 전투기 ≥ 1 | JTAC 통제 하 근접지원 |

**근거**:
> *"Composition (Strike Support): A UAS equipped with a tri-sensor payload teamed  
> with rotary-wing aircraft. The UAS detects the target and provides laser designation.  
> The manned aircraft maneuvers into position to fire laser-guided munitions."*  
> — FMI 3-04.155

---

## 5. MILP 제약 조건 근거

### 5.1 수식 설계

**결정 변수**
```
x_f : 전투기 대수 (정수, ≥ 0)
x_r : 정찰UAV 대수 (정수, ≥ 0)
x_k : 자폭UAV 대수 (정수, ≥ 0)
```

**목적 함수** (비용 최소화)
```
min Z = c_f·x_f + c_r·x_r + c_k·x_k
```

**제약 조건 (교리 기반)**

| 제약 | 수식 | 근거 교범 |
|---|---|---|
| ISR 수행 시 | x_r ≥ 2 | FMI3-04.155 팀 로테이션 |
| SEAD 수행 시 | x_k ≥ 1, x_f ≥ 1 | JP3-30 MAAP SEAD 요구 |
| STRIKE 수행 시 | x_f ≥ 1 | AFDP3-03 AI 임무 |
| CAS 수행 시 | x_f ≥ 1 | AFDP3-03 CAS 요구 |
| MUM-T 비율 | x_r + x_k ≥ 2·x_f | FMI3-04.155 Lead/Wingman |
| 총 자산 제한 | x_f + x_r + x_k ≤ N_max | 작전 운용 한계 |
| 비음수 조건 | x_f, x_r, x_k ≥ 0 | 수학적 요건 |

### 5.2 자산 배정 원칙 (헝가리안 알고리즘)

> *"Units requesting support should not request a specific asset  
> but rather the 'desired effect,' allowing JAOC planners to determine  
> the best force composition from available joint assets."*  
> — JP 3-30 (Tasking by Effect 원칙)

→ 헝가리안 알고리즘으로 자산↔목표 최적 1:1 배정 구현

---

## 6. LLM 교리 파싱 근거

### 6.1 LLM 역할 제한 원칙
**LLM은 번역기만 담당** — 수치 계산은 절대 하지 않음

```
사용자 자연어 명령
    ↓ (LLM)
구조화된 제약 JSON
    ↓ (MILP/A*/헝가리안)
최적 계획 결과
```

### 6.2 ROE (교전규칙) 파싱
> *"All components must adhere to the Joint Force Commander's approved guidance,  
> which includes the Rules of Engagement (ROE), Airspace Control Plan (ACP),  
> Airspace Control Order (ACO)"*  
> — JP 3-30

**구현**: `llm_brain.py` → `LLMResponse.action` 타입으로 ROE 제약 추출

### 6.3 Constraints vs Restraints 구분
> *"Constraints: HHQ requirements that DICTATE action (해야 하는 것)  
> Restraints: HHQ requirements that PROHIBIT action (하면 안 되는 것)"*  
> — AFDP 5-0

**구현**: `validator.py`에서 Constraint/Restraint 구분 검증

---

## 7. 경로계획 및 위협 회피 근거

### 7.1 A* + 지형 음영 (Terrain Masking)

> *"The problem was formulated as one of constrained optimization in three dimensions;  
> advantageous solutions were identified using Algorithm A*.  
> Topographical features were exploited by the algorithm to avoid radar detection."*  
> — Pelosi, Kopp & Brown (2012), Applied AI, 26(8), 743-759

**구현**: `pathfinder.py` + `radar_shadow.py`

### 7.2 레이더 탐지 확률 모델

> *"Uses a mathematical model to calculate the instantaneous probability of detection  
> based on range and Radar Cross Section (RCS), integrating multiple radar sources  
> into a cumulative risk assessment."*  
> — Pelosi et al. (2012)

**구현**: `xai_utils.py` → P_D × P_K 위험도 계산

### 7.3 Ray-Casting 음영 계산

> *"A ray-casting technique was used to determine cell radar visibility.  
> If solid terrain existed in the LOS between the radar and any cell,  
> the cell visibility (detection) was set to zero."*  
> — Pelosi et al. (2012)

**구현**: `radar_shadow.py` → Line-of-Sight 음영 계산

---

## 8. 안전 마진 기준

| 수준 | 마진 | 적용 상황 | 근거 |
|---|---|---|---|
| 최소 | 2km | 위험 감수, 속도 우선 | 전술적 판단 |
| 표준 | 5km | 기본 운용 | JP3-30 기본값 |
| 안전 | 15km | 연료 여유, 안전 우선 | JP3-30 Restraints |
| 최대 | 30km | 최대 위협 회피 | AFDP5-0 Risk Mitigation |

### 전술 키워드 → 마진 매핑
```
"저고도" / "지형추종"  → enable_3d=True, A* 3D
"안전하게" / "연료여유" → margin +10~15km
"빠르게" / "직선"      → margin -3km, A* 2D
"레이더 회피"          → enable_3d=True, margin +5km
```

---

## 9. 검증기 규칙 근거 (validator.py - 구현 예정)

### 9.1 검증 항목

| 검증 항목 | 규칙 | 근거 |
|---|---|---|
| 공역 충돌 | 경로가 NFZ 통과 금지 | JP3-30 ACO |
| 최소 고도 | AGL 200m 이상 | FMI3-04.155 |
| 자산 충돌 | 동일 시간대 동일 공역 금지 | FMI3-04.155 분리 원칙 |
| LOS 확보 | 통신 가능 거리 이내 | FMI3-04.155 LOI |
| 임무 순서 | ISR → SEAD → STRIKE 순서 준수 | JP3-30 MAAP |
| 연료 제한 | 총 경로 거리 ≤ 최대 항속거리 | DAFMAN 11-260 |

> *"COA Analysis and Wargaming: Each COA is tested against the adversary's  
> most likely and dangerous COAs to identify strengths and weaknesses."*  
> — AFDP 5-0, Step 4

---

## 10. RL 비채택 근거

강화학습(RL) 대신 결정론적 알고리즘(MILP + A*)을 채택한 이유:

| 이유 | 설명 | 교리 근거 |
|---|---|---|
| **재현성** | 동일 입력 → 동일 출력 필수 | AFDP5-0 COA 문서화 요건 |
| **설명 가능성** | 왜 이 경로인지 설명 필요 (XAI) | JP3-30 지휘관 브리핑 요건 |
| **Sim-to-Real Gap** | 훈련 환경 ≠ 실제 환경 | DAFMAN11-260 검증 요건 |
| **예측 불가능성** | RL 정책의 불규칙 행동 위험 | JP3-30 ROE 준수 요건 |

> *"Highly sensitive strike missions against long-range strategic targets  
> will generally require a higher level of detailed planning and  
> more centralized control."*  
> — JP 3-30, p.I-3

---

## 변경 이력

| 버전 | 날짜 | 내용 |
|---|---|---|
| v1.0 | 2026-02-21 | 최초 작성 - 교리 근거 전체 정리 |

---

*본 문서는 IMPS 시스템의 모든 설계 결정에 대한 교리적 근거를 기록합니다.*  
*새로운 모듈 추가 시 반드시 해당 섹션에 근거를 추가해주세요.*
