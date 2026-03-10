# IMPS 개발 일지 - 2026-03-08

> 작성일: 2026-03-08  
> 범위: LLM 명령해석 + Doctrine RAG + 3D 경로탐색 + 위협모델 + Validator + 연료기반 의사결정

---

## 1) 오늘 목표

- 데모에서 보이던 핵심 불일치(경로/위험점수/UI 반영)를 줄이고,
- 실전 운용 맥락(교리 + 연료상태)에 맞는 경로 의사결정 파이프라인으로 정리.

---

## 2) 주요 이슈와 처리 내용

### A. 위협 중심부 관통 경로 문제

- 증상: 위협이 명확한데도 A* 3D 경로가 위험권 중심을 통과하는 케이스 발생.
- 조치:
  - SAM/RADAR에 대해 `threat core` 하드 차단 로직 추가.
  - 위험 페널티 강화 및 위험 차단 임계치 동적화(안전마진 연동).
  - 2D/3D/optimized 경로기 모두 동일 정책 반영.
- 대상 파일:
  - `modules/pathfinder.py`
  - `modules/pathfinder_optimized.py`

### B. 위험지역인데 점수 0 또는 과소평가 문제

- 증상: 경로가 위험권 내부로 보이는데 지배적 위험점수/평균위험이 0에 가깝게 표기.
- 원인 축:
  - 고도 하한/LoS 조건에서 위험이 과도하게 0으로 소거되는 분기.
  - 결합식이 일부 상황에서 직관 대비 낮은 값 생성.
- 조치:
  - LoS 불가/고도 불리 조건을 “즉시 0”이 아니라 감쇠 방식으로 변경.
  - 근접도 기반 하한 반영.
  - 다중 위협 결합 시 Dominant Risk 의미에 맞는 보정.
- 대상 파일:
  - `modules/xai_utils.py`

### C. 편대 경로와 위험 메트릭 불일치

- 증상: 지도에는 다수 자산 경로가 그려지는데 위험 메트릭은 일부 경로 기준으로 계산.
- 조치:
  - 자산별 ingress/egress를 각각 분석 후 전체 집계(max/avg/length/high-risk)하도록 변경.
- 대상 파일:
  - `streamlit_app.py`

### D. LLM 반영값-위젯 상태 불일치

- 증상: LLM 응답 문구는 “변경 완료”인데 UI 위젯/실제 파라미터 반영이 어긋나는 케이스.
- 조치:
  - `_pending_widget_updates` 기반 동기화 경로 정리.
  - 파라미터 sanitize 후 session_state 반영.
- 대상 파일:
  - `streamlit_app.py`

### E. F-16 기준 연료기반 경로 트레이드오프 도입

- 요구: 연료 부족 시 위험 감수/단거리, 연료 여유 시 우회/안전.
- 구현:
  - 미션 파라미터에 `fuel_state`, `refuel_count` 추가.
  - 연료 endurance factor를 경로 위험비용/임계치에 반영.
  - UI에 연료 슬라이더 및 급유 횟수 추가.
  - F-16 기준 근거 주석을 코드에 명시(논문 추적성 목적).
- 대상 파일:
  - `modules/mission_state.py`
  - `modules/fuel_model.py` (신규)
  - `modules/pathfinder.py`
  - `modules/pathfinder_optimized.py`
  - `modules/config.py`
  - `streamlit_app.py`

---

## 3) F-16 근거(코드 주석 반영)

- 근거 위치: `modules/config.py`의 `FUEL_POLICY` 블록.
- 반영한 참고:
  - USAF F-16 Fact Sheet  
    https://www.af.mil/About-Us/Fact-Sheets/Display/Article/104505/f-16-fighting-falcon/
  - Boeing KC-46 (공중급유 운용 맥락)  
    https://www.boeing.com/defense/tankers-and-transports/kc-46-pegasus
- 비고:
  - 데모용으로 `refuel_gain_per_event`는 가정값(튜닝 파라미터)으로 두었고,
    주석에 명시함.

---

## 4) 오늘 생성/수정 파일 요약

- 신규:
  - `modules/fuel_model.py`
  - `docs/CHANGELOG_2026-03-08.md`
- 주요 수정:
  - `streamlit_app.py`
  - `modules/xai_utils.py`
  - `modules/pathfinder.py`
  - `modules/pathfinder_optimized.py`
  - `modules/mission_state.py`
  - `modules/config.py`

---

## 5) 검증 결과(요약)

- 정적 검증:
  - `python -m py_compile`로 관련 파일 컴파일 통과.
- 동작 검증:
  - 위협 core 관통 완화 확인.
  - 위험점수 0 고정/과소 구간 완화 확인.
  - 연료 상태 변화에 따라 경로 위험-거리 트레이드오프가 나타나는지 샘플 시나리오 확인.

---

## 6) 남은 과제 (다음 세션 권장)

- 연료 모델 고도화:
  - 자산별(BADA/공개 성능표 기반) 연료소모율로 확장.
  - speed/altitude/profile에 따른 소비 모델 분리.
- 위험 점수 투명성:
  - 웨이포인트별 “위협 기여도 분해(SAM/RADAR/NFZ)” 디버그 패널 추가.
- 실험 설계:
  - 발표용 시나리오 3종(저연료/표준/급유지원) 고정 후 정량표 자동 생성.

