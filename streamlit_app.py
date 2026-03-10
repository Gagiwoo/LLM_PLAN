"""
통합 임무계획 시스템 v13.0 (MUM-T + Rule-based Validator)
- LLM Brain v2.1: UI 실시간 동기화 + 응답 캐싱 + 빠른 모델 자동 선택
- 경로탐색 v2.0: 위협 존재 시 저고도 우회 (RADAR 400m/SAM 200m AGL)
- 자산 색상 고대비 8색 팔레트 (색맹 친화적)
"""
import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
import pandas as pd
import time
import json
import hashlib

from modules.config import (
    AIRPORTS, MAP_CENTER, MAP_ZOOM, CHAT_CONTAINER_HEIGHT,
    AVAILABLE_ALGORITHMS, FORMATION_MAX_TOTAL, THREAT_ALT_ENVELOPE, ASSET_PERFORMANCE
)
from modules.mission_state import MissionState, Threat, THREAT_DB
from modules.llm_brain import LLMBrain
from modules.formation_optimizer import FormationOptimizer
from modules.validator import MissionValidator
from modules.pathfinder import AStarPathfinder, AStarPathfinder3D, smooth_path, smooth_path_3d
from modules.pathfinder_optimized import AStarPathfinder3DOptimized, TerrainCacheFast
from modules.pathfinder_rrt import RRTPathfinder, RRTStarPathfinder
from modules.terrain_loader import TerrainLoader
from modules.xai_utils import XAIUtils
from modules.doctrine_policy import DoctrinePolicyEngine
from modules.fuel_model import estimate_effective_range_km, fuel_endurance_factor

# ===== 페이지 설정 =====
st.set_page_config(page_title="IMPS v13.0 (MUM-T)", layout="wide", initial_sidebar_state="collapsed")
st.title("🚁 통합 임무계획 시스템 v13.0 (MUM-T + Validator)")

# ===== 상태 초기화 =====
if "mission" not in st.session_state:
    st.session_state.mission = MissionState()

if "terrain" not in st.session_state:
    with st.spinner("🌍 지형 데이터 메모리 적재 중... (최초 1회)"):
        base_loader = TerrainLoader()
        st.session_state.terrain = TerrainCacheFast(base_loader)

if "mission_sequence" not in st.session_state:
    st.session_state.mission_sequence = []

if "_doctrine_engine" not in st.session_state:
    st.session_state._doctrine_engine = DoctrinePolicyEngine()

mission = st.session_state.mission
terrain_fast = st.session_state.terrain 

if "_llm_cache_enabled" not in st.session_state:
    st.session_state["_llm_cache_enabled"] = True
LLMBrain.set_cache_enabled(st.session_state["_llm_cache_enabled"])

# 호환성 매핑
if not hasattr(terrain_fast, 'get_elevation'):
    terrain_fast.get_elevation = terrain_fast.get


def _queue_profile_widget_sync():
    p = mission.params
    st.session_state["_pending_widget_updates"] = {
        "_mp_start": p.start,
        "_mp_target_lat": float(p.target_lat),
        "_mp_target_lon": float(p.target_lon),
        "_mp_rtb": bool(p.rtb),
        "_mp_algorithm": p.algorithm,
        "_mp_enable_3d": bool(p.enable_3d),
        "_mp_margin": float(p.margin),
        "_mp_stpt_gap": int(p.stpt_gap),
        "_mp_fuel_state": float(getattr(p, "fuel_state", 1.0)),
        "_mp_refuel_count": int(getattr(p, "refuel_count", 0)),
    }


def _build_demo_threat(name: str, threat_type: str, lat: float, lon: float, radius_km: float) -> Threat:
    env = THREAT_ALT_ENVELOPE.get(threat_type, {})
    try:
        ground_elev = terrain_fast.get_elevation(lat, lon)
    except Exception:
        ground_elev = 0.0
    sam_peak = radius_km * 0.35 if threat_type == "SAM" else 0.35
    sam_sigma = radius_km * 0.20 if threat_type == "SAM" else 0.20
    return Threat(
        name=name,
        type=threat_type,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        alt=ground_elev + 10.0,
        min_alt_m=env.get("min_alt_m"),
        max_alt_m=env.get("max_alt_m"),
        pk_peak_km=sam_peak,
        pk_sigma_km=sam_sigma,
    )


def _find_base_name(keyword: str, fallback: str = None) -> str:
    keyword = (keyword or "").lower()
    for base_name in AIRPORTS.keys():
        if keyword in base_name.lower():
            return base_name
    return fallback or list(AIRPORTS.keys())[0]


def _apply_demo_preset(preset_name: str):
    p = mission.params
    p.fuel_state = 1.0
    p.refuel_count = 0
    busan_base = _find_base_name("busan")
    suwon_base = _find_base_name("suwon", fallback=busan_base)
    osan_base = _find_base_name("osan", fallback=busan_base)

    if preset_name == "baseline":
        p.start = busan_base
        p.target_lat, p.target_lon = 39.0, 125.7
        p.target_name = "PY-Core"
        p.margin = 5.0
        p.algorithm = "A* 3D"
        p.enable_3d = True
        p.rtb = True
        p.stpt_gap = 5
        p.fuel_state = 0.85
        p.refuel_count = 0
        mission.threats = [
            _build_demo_threat("Threat-SAM-01", "SAM", 37.8, 127.0, 30.0),
            _build_demo_threat("Threat-RADAR-01", "RADAR", 38.3, 126.5, 85.0),
        ]
    elif preset_name == "high_risk":
        p.start = suwon_base
        p.target_lat, p.target_lon = 40.5, 125.1
        p.target_name = "High-Risk-Test"
        p.margin = 8.0
        p.algorithm = "A* 3D"
        p.enable_3d = True
        p.rtb = True
        p.stpt_gap = 4
        p.fuel_state = 0.45
        p.refuel_count = 0
        mission.threats = [
            _build_demo_threat("Threat-RADAR-A", "RADAR", 37.9, 126.8, 120.0),
            _build_demo_threat("Threat-RADAR-B", "RADAR", 38.6, 126.9, 110.0),
            _build_demo_threat("Threat-SAM-A", "SAM", 37.6, 126.9, 35.0),
            _build_demo_threat("Threat-SAM-B", "SAM", 38.2, 126.7, 35.0),
        ]
    elif preset_name == "detour":
        p.start = osan_base
        p.target_lat, p.target_lon = 39.2, 125.8
        p.target_name = "Detour-Test"
        p.margin = 12.0
        p.algorithm = "A* 3D"
        p.enable_3d = True
        p.rtb = True
        p.stpt_gap = 5
        p.fuel_state = 0.95
        p.refuel_count = 1
        mission.threats = [
            _build_demo_threat("Threat-RADAR-Center", "RADAR", 37.9, 126.7, 140.0),
            _build_demo_threat("Threat-SAM-Center", "SAM", 37.8, 126.8, 45.0),
        ]

    mission.formation = None
    mission.chat_history = [{"role": "assistant", "content": "작전관님, 명령을 대기 중입니다.", "reasoning": ""}]
    st.session_state["mission_sequence"] = []
    st.session_state.pop("_formation_paths", None)
    st.session_state.pop("final_in", None)
    st.session_state.pop("_validation_report", None)
    st.session_state.pop("_doctrine_policy", None)
    _queue_profile_widget_sync()

# ===== 레이아웃 =====
col_left, col_right = st.columns([1, 2])

with col_left:
    tab_ops, tab_intel, tab_formation, tab_validator, tab_xai, tab_debug = st.tabs(["💬 작전 통제", "⚠️ 위협 관리", "✈️ 편대 구성", "✅ 임무 검증", "🤔 AI 판단 근거", "🔧 디버그"])

    # 1. 작전 통제
    with tab_ops:
        with st.expander("⚙️ 미션 프로파일 설정", expanded=True):
            p = mission.params

            # ── session_state 키 강제 동기화 (LLM 업데이트 반영) ──
            # LLM이 mission.params를 바꾼 뒤 st.rerun() 하면
            # 아래 session_state 키들이 이미 새 값으로 설정되어 위젯에 즉시 반영됨
            # ── session_state 초기값 설정 (최초 1회만, 이미 있으면 LLM 값 유지) ──
            # key= 위젯은 session_state 값을 그대로 표시하므로
            # 처음 렌더링 전에만 params 값으로 초기화하고, 이후는 건드리지 않음
            # LLM 업데이트 시에는 _set() 함수로 session_state를 직접 덮어씀
            _defaults = {
                "_mp_start":      p.start,
                "_mp_target_lat": p.target_lat,
                "_mp_target_lon": p.target_lon,
                "_mp_rtb":        p.rtb,
                "_mp_algorithm":  p.algorithm,
                "_mp_enable_3d":  p.enable_3d,
                "_mp_margin":     float(p.margin),
                "_mp_stpt_gap":   int(p.stpt_gap),
                "_mp_fuel_state": float(getattr(p, "fuel_state", 1.0)),
                "_mp_refuel_count": int(getattr(p, "refuel_count", 0)),
            }
            for _k, _v in _defaults.items():
                if _k not in st.session_state:
                    st.session_state[_k] = _v  # 최초 1회만 설정

            # 위젯 키는 생성 이후 직접 수정할 수 없으므로,
            # 이전 run에서 예약한 업데이트를 위젯 생성 전에 반영한다.
            _pending_widget_updates = st.session_state.pop("_pending_widget_updates", {})
            for _k, _v in _pending_widget_updates.items():
                st.session_state[_k] = _v

            # ── 위젯: key= 만 사용, index=/value= 제거 → session_state 값이 곧 표시값 ──
            p.start = st.selectbox("출발 기지", list(AIRPORTS.keys()), key="_mp_start")
            c1, c2 = st.columns(2)
            p.target_lat = c1.number_input("Lat", 33.0, 43.0, step=0.0001, format="%.4f", key="_mp_target_lat")
            p.target_lon = c2.number_input("Lon", 124.0, 132.0, step=0.0001, format="%.4f", key="_mp_target_lon")
            c_rtb, c_algo = st.columns([1, 1])
            p.rtb       = c_rtb.checkbox("Strike & RTB", key="_mp_rtb")
            p.algorithm = c_algo.selectbox("알고리즘", AVAILABLE_ALGORITHMS, key="_mp_algorithm")
            p.enable_3d = st.checkbox("3D 모드 (지형 고려)", key="_mp_enable_3d")
            p.margin    = st.slider("안전 마진(km)", 0.0, 50.0, key="_mp_margin")
            p.stpt_gap  = st.slider("STPT 표시 간격", 1, 50, key="_mp_stpt_gap")
            f1, f2 = st.columns([2, 1])
            p.fuel_state = f1.slider(
                "F-16 baseline fuel state",
                min_value=0.20,
                max_value=1.00,
                step=0.05,
                key="_mp_fuel_state",
                help="1.00=full planned fuel, 0.20=fuel-critical state",
            )
            p.refuel_count = f2.selectbox("AR count", [0, 1, 2], key="_mp_refuel_count")
            f16_base_range = float(ASSET_PERFORMANCE.get("fighter", {}).get("range_km", 3000.0))
            est_range = estimate_effective_range_km(f16_base_range, p.fuel_state, p.refuel_count)
            endu_factor = fuel_endurance_factor(p.fuel_state, p.refuel_count)
            st.caption(f"F-16 effective range budget: {est_range:.0f} km (endurance x{endu_factor:.2f})")
            if p.enable_3d and p.algorithm in ("RRT", "RRT*"):
                st.caption("ℹ️ 3D 모드에서 RRT/RRT*는 고도 선형보간 방식으로 동작합니다.")

            if st.button("🔄 설정 적용 및 경로 계산", type="primary", use_container_width=True):
                st.rerun()

        st.divider()
        chat_container = st.container(height=CHAT_CONTAINER_HEIGHT)
        for msg in mission.chat_history:
            with chat_container.chat_message(msg["role"]):
                st.write(msg["content"])

        if user_input := st.chat_input("명령 입력 (예: 적 레이더 37.5/127.8 피해서 저고도 침투 후 복귀)"):
            mission.add_chat_message("user", user_input)
            with st.spinner("🧠 AI 분석 중..."):
                brain = LLMBrain()
                path_analysis = st.session_state.get("_last_path_analysis")
                threat_sig = hashlib.md5(
                    json.dumps(
                        [t.to_dict() for t in mission.threats],
                        ensure_ascii=False,
                        sort_keys=True
                    ).encode("utf-8")
                ).hexdigest()
                result = brain.parse_tactical_command(
                    user_input,
                    mission.params.to_dict(),
                    path_analysis,
                    chat_history=mission.chat_history,
                    threat_signature=threat_sig
                )

                action = result.get("action", "CHAT")
                u = result.get("update_params", {})
                before_params = mission.params.to_dict().copy()
                before_threat_count = len(mission.threats)

                # ── UPDATE / THREAT_ADD 공통: 파라미터 변경 ──
                # mission.params 와 session_state 위젯 키를 동시에 갱신해야
                # st.rerun() 후 사이드바 위젯에 즉시 반영됨
                def _sanitize_widget_value(ss_key, val):
                    if val is None:
                        return None
                    try:
                        if ss_key == "_mp_margin":
                            return max(0.0, min(50.0, float(val)))
                        if ss_key == "_mp_stpt_gap":
                            return max(1, min(50, int(float(val))))
                        if ss_key == "_mp_fuel_state":
                            return max(0.20, min(1.00, float(val)))
                        if ss_key == "_mp_refuel_count":
                            return max(0, min(2, int(float(val))))
                        if ss_key == "_mp_target_lat":
                            return max(33.0, min(43.0, float(val)))
                        if ss_key == "_mp_target_lon":
                            return max(124.0, min(132.0, float(val)))
                        if ss_key in ("_mp_rtb", "_mp_enable_3d"):
                            if isinstance(val, str):
                                norm = val.strip().lower()
                                if norm in ("true", "1", "yes", "y", "on"):
                                    return True
                                if norm in ("false", "0", "no", "n", "off"):
                                    return False
                                return None
                            return bool(val)
                        if ss_key == "_mp_algorithm":
                            return val if val in AVAILABLE_ALGORITHMS else None
                        if ss_key == "_mp_start":
                            return val if val in AIRPORTS else None
                        return val
                    except Exception:
                        return None

                # Rebind with validation so malformed LLM values do not break widgets on rerun.
                def _set(param_attr, ss_key, val):
                    safe_val = _sanitize_widget_value(ss_key, val)
                    if safe_val is None:
                        return
                    setattr(mission.params, param_attr, safe_val)
                    pending = st.session_state.setdefault("_pending_widget_updates", {})
                    pending[ss_key] = safe_val

                if action in ("UPDATE", "THREAT_ADD", "MISSION_PLAN"):
                    if u.get("safety_margin_km") is not None:
                        _set("margin",     "_mp_margin",      u["safety_margin_km"])
                    if u.get("rtb") is not None:
                        _set("rtb",        "_mp_rtb",         u["rtb"])
                    if u.get("stpt_gap") is not None:
                        _set("stpt_gap",   "_mp_stpt_gap",    u["stpt_gap"])
                    if u.get("fuel_state") is not None:
                        _set("fuel_state", "_mp_fuel_state", u["fuel_state"])
                    if u.get("refuel_count") is not None:
                        _set("refuel_count", "_mp_refuel_count", u["refuel_count"])
                    if u.get("algorithm"):
                        _set("algorithm",  "_mp_algorithm",   u["algorithm"])
                    if u.get("enable_3d") is not None:
                        _set("enable_3d",  "_mp_enable_3d",   u["enable_3d"])
                    if u.get("target_lat") is not None:
                        _set("target_lat", "_mp_target_lat",  u["target_lat"])
                    if u.get("target_lon") is not None:
                        _set("target_lon", "_mp_target_lon",  u["target_lon"])
                    if u.get("target_name"):
                        mission.params.target_name = u["target_name"]
                    if u.get("start") and u["start"] in AIRPORTS:
                        _set("start",      "_mp_start",       u["start"])
                    if u.get("waypoint_name"):
                        mission.params.waypoint = u["waypoint_name"]

                # ── THREAT_ADD: 위협 자동 추가 ──
                if action == "THREAT_ADD":
                    for t_info in result.get("threats_to_add", []):
                        try:
                            new_threat = Threat(
                                name=t_info.get("name", f"Threat-{len(mission.threats)+1:02d}"),
                                type=t_info.get("type", "SAM"),
                                lat=t_info.get("lat"),
                                lon=t_info.get("lon"),
                                radius_km=t_info.get("radius_km", 30.0),
                                alt=0.0
                            )
                            if new_threat.type in ("SAM", "RADAR"):
                                env = THREAT_ALT_ENVELOPE.get(new_threat.type, {})
                                new_threat.min_alt_m = env.get("min_alt_m")
                                new_threat.max_alt_m = env.get("max_alt_m")
                            # 지형 고도 자동 보정
                            if new_threat.lat and new_threat.lon:
                                ground_elev = terrain_fast.get_elevation(new_threat.lat, new_threat.lon)
                                new_threat.alt = ground_elev + 10.0
                            mission.add_threat(new_threat)
                        except Exception:
                            pass

                # ── MISSION_PLAN: 임무 순서 표시 ──
                if action == "MISSION_PLAN":
                    seq = result.get("mission_sequence", [])
                    if seq:
                        st.session_state["mission_sequence"] = seq

                ai_msg = result["response_text"]

                # 적용된 실제 변경값(diff) 표시
                after_params = mission.params.to_dict().copy()
                field_labels = {
                    "start": "출발기지",
                    "target_lat": "목표위도",
                    "target_lon": "목표경도",
                    "margin": "안전마진(km)",
                    "rtb": "RTB",
                    "stpt_gap": "STPT 간격",
                    "algorithm": "알고리즘",
                    "enable_3d": "3D모드",
                    "target_name": "목표명",
                }
                applied_changes = []
                for key, label in field_labels.items():
                    b = before_params.get(key)
                    a = after_params.get(key)
                    if b != a:
                        applied_changes.append(f"- {label}: {b} → {a}")

                if len(mission.threats) != before_threat_count:
                    delta = len(mission.threats) - before_threat_count
                    applied_changes.append(f"- 위협 수: {before_threat_count} → {len(mission.threats)} (Δ {delta:+d})")

                if applied_changes:
                    ai_msg += "\n\n**적용 변경값**\n" + "\n".join(applied_changes)
                elif action in ("UPDATE", "THREAT_ADD", "MISSION_PLAN"):
                    ai_msg += "\n\n**적용 변경값**\n- 변경 없음 (동일값 또는 범위 보정으로 무시됨)"

                # RAG 출처 표시
                doctrine_refs = result.get("_doctrine_refs", []) or []
                if doctrine_refs:
                    ref_lines = []
                    for r in doctrine_refs[:4]:
                        src = r.get("source", "?")
                        page = r.get("page", 0)
                        score = r.get("score", 0.0)
                        ref_lines.append(f"- {src} p.{page} (score={score:.3f})")
                    ai_msg += "\n\n**교리 근거(RAG)**\n" + "\n".join(ref_lines)

                # 모델 정보 및 신뢰도 표시
                model_used = result.get("_model_used", "unknown")
                confidence = result.get("confidence", 0.0)
                cache_hit = result.get("_cache_hit", False)
                cache_tag = "cache-hit" if cache_hit else "live"
                ai_msg += f"\n\n`[{model_used} | {cache_tag} | 신뢰도: {confidence:.0%} | 액션: {action}]`"

                mission.add_chat_message("assistant", ai_msg, result.get("reasoning", ""))
                st.rerun()

    # 2. 위협 관리 (v2.1: 군사 DB 선택 + 수동 설정 통합)
    with tab_intel:
        st.subheader("위협 추가")

        # ── 라디오: form 바깥에 위치 (클릭 즉시 반응)
        add_type = st.radio(
            '위협 입력 방식',
            ["군사 DB (SAM/RADAR)", "수동 설정 (SAM/RADAR)", "수동 설정 (NFZ)"],
            horizontal=True
        )

        with st.form("threat_form"):
            # ── 방식 1: 군사 DB 선택 ───────────────────────────────
            if add_type == "군사 DB (SAM/RADAR)":
                selected_db = st.selectbox(
                    "적성 체계 식별명",
                    list(THREAT_DB.keys()),
                    help="F-16 전투기 대응 기준 현실화 파라미터 자동 적용"
                )
                db_preview = THREAT_DB[selected_db]
                st.caption(
                    f"▸ 유형: {db_preview['type']} "
                    f"| 반경: {db_preview['radius_km']} km "
                    f"| SSKP: {db_preview['sskp']:.0%}"
                )
                t_name = st.text_input(
                    "전술 지도 표시 명칭",
                    value=f"{selected_db.split()[0]}-{len(mission.threats)+1:02d}"
                )

            # ── 방식 2: 수동 설정 (SAM/RADAR) ─────────────────────
            elif add_type == "수동 설정 (SAM/RADAR)":
                manual_type = st.radio("위협 유형", ["SAM", "RADAR"], horizontal=True)
                t_name = st.text_input(
                    "전술 지도 표시 명칭",
                    value=f"Threat-{len(mission.threats)+1:02d}"
                )

            # ── 방식 3: NFZ ────────────────────────────────────────
            else:
                t_name = st.text_input(
                    "비행금지구역 명칭",
                    value=f"NFZ-{len(mission.threats)+1:02d}"
                )

            # ── 공통: 좌표 입력 ────────────────────────────────────
            c1, c2 = st.columns(2)
            t_lat = c1.number_input("Lat (위도)",  33.0, 43.0,  38.0, format="%.4f", key="t_lat")
            t_lon = c2.number_input("Lon (경도)", 124.0, 132.0, 127.0, format="%.4f", key="t_lon")

            # ── 수동 설정 반경 슬라이더 ────────────────────────────
            if add_type == "수동 설정 (SAM/RADAR)":
                t_rad = st.slider("반경(km)", 5, 400, 30, key="t_rad")

            # ── NFZ 범위 입력 ──────────────────────────────────────
            if add_type == "수동 설정 (NFZ)":
                l_min  = c1.number_input("Min Lat", 33.0, 43.0,  37.5, format="%.4f")
                l_max  = c2.number_input("Max Lat", 33.0, 43.0,  37.8, format="%.4f")
                ln_min = c1.number_input("Min Lon", 124.0, 132.0, 127.5, format="%.4f")
                ln_max = c2.number_input("Max Lon", 124.0, 132.0, 127.8, format="%.4f")

            if st.form_submit_button("➕ 위협 추가", type="primary"):
                ground_elev = 0.0
                try:
                    ground_elev = terrain_fast.get_elevation(t_lat, t_lon)
                except Exception:
                    pass

                # ── NFZ 추가 ──────────────────────────────────────
                if add_type == "수동 설정 (NFZ)":
                    mission.add_threat(Threat(
                        name=t_name, type="NFZ",
                        lat_min=l_min, lat_max=l_max,
                        lon_min=ln_min, lon_max=ln_max
                    ))

                # ── 군사 DB 추가 (정밀 XAI 파라미터 자동 적용) ────
                elif add_type == "군사 DB (SAM/RADAR)":
                    db_info = THREAT_DB[selected_db]
                    r_km = db_info["radius_km"]
                    env = THREAT_ALT_ENVELOPE.get(db_info["type"], {})
                    env_min = db_info.get("min_alt_m", env.get("min_alt_m"))
                    env_max = db_info.get("max_alt_m", env.get("max_alt_m"))
                    mission.add_threat(Threat(
                        name=t_name,
                        type=db_info["type"],
                        lat=t_lat,
                        lon=t_lon,
                        radius_km=r_km,
                        alt=ground_elev + 10.0,
                        min_alt_m=env_min,
                        max_alt_m=env_max,
                        loss=db_info["loss"],
                        rcs_m2=db_info["rcs_m2"],
                        pd_k=db_info["pd_k"],
                        sskp=db_info["sskp"],
                        pk_peak_km=r_km * db_info["peak_ratio"],
                        pk_sigma_km=r_km * db_info["sigma_ratio"],
                    ))

                # ── 수동 SAM/RADAR 추가 ────────────────────────────
                else:
                    if manual_type == "RADAR":
                        peak, sigma, sskp_val = 0.0, 0.0, 0.0
                    else:
                        peak      = t_rad * 0.35
                        sigma     = t_rad * 0.20
                        sskp_val  = 0.75
                    env = THREAT_ALT_ENVELOPE.get(manual_type, {})
                    mission.add_threat(Threat(
                        name=t_name,
                        type=manual_type,
                        lat=t_lat,
                        lon=t_lon,
                        radius_km=t_rad,
                        alt=ground_elev + 10.0,
                        min_alt_m=env.get("min_alt_m"),
                        max_alt_m=env.get("max_alt_m"),
                        loss=8.0,
                        rcs_m2=2.5,
                        pd_k=0.4,
                        sskp=sskp_val,
                        pk_peak_km=peak,
                        pk_sigma_km=sigma,
                    ))
                st.rerun()

        st.divider()
        if mission.threats:
            threat_df = pd.DataFrame([t.to_dict() for t in mission.threats])
            cols = [c for c in ['name', 'type', 'radius_km', 'lat', 'lon', 'sskp'] if c in threat_df.columns]
            st.dataframe(threat_df[cols], hide_index=True, width="stretch")

            c_del, c_btn = st.columns([3, 1])
            del_name = c_del.selectbox("삭제할 위협", [t.name for t in mission.threats])
            if c_btn.button("🗑️ 삭제"):
                mission.remove_threat(del_name)
                st.rerun()

    # 3. 편대 구성 (Formation Optimizer)
    with tab_formation:
        st.subheader("✈️ MUM-T 편대 구성 최적화")
        st.caption("MILP + 헝가리안 | 근거: JP3-30, AFDP3-03, FMI3-04.155")

        with st.form("formation_form"):
            st.markdown("**임무 유형 선택**")
            c1, c2, c3, c4 = st.columns(4)
            use_isr    = c1.checkbox("🔵 ISR",    value=True)
            use_sead   = c2.checkbox("🟡 SEAD",   value=True)
            use_strike = c3.checkbox("🔴 STRIKE", value=True)
            use_cas    = c4.checkbox("🟢 CAS",    value=False)

            n_targets = st.number_input("목표 수", min_value=1, max_value=10, value=1)
            max_assets = st.slider("최대 자산 수 (N_max)", 3, FORMATION_MAX_TOTAL, 8)

            run_btn = st.form_submit_button("🚀 편대 구성 최적화 실행", type="primary")

        if run_btn:
            mission_types = []
            if use_isr:    mission_types.append("ISR")
            if use_sead:   mission_types.append("SEAD")
            if use_strike: mission_types.append("STRIKE")
            if use_cas:    mission_types.append("CAS")

            if not mission_types:
                st.warning("임무 유형을 하나 이상 선택하세요.")
            else:
                with st.spinner("🧮 MILP + 헝가리안 최적화 중..."):
                    optimizer = FormationOptimizer()
                    targets = [{"lat": mission.params.target_lat,
                                "lon": mission.params.target_lon,
                                "name": mission.params.target_name}]
                    threats_dict = [t.to_dict() for t in mission.threats]
                    doctrine_policy = st.session_state._doctrine_engine.build_policy(
                        mission_types=mission_types,
                        threats=threats_dict,
                        current_margin_km=mission.params.margin,
                    ).to_optimizer_dict()
                    effective_sequence = doctrine_policy.get("mission_sequence") or mission_types
                    margin_floor = float(doctrine_policy.get("safety_margin_floor_km", 0.0) or 0.0)
                    if margin_floor > float(mission.params.margin):
                        mission.params.margin = margin_floor
                        st.session_state.setdefault("_pending_widget_updates", {})["_mp_margin"] = margin_floor

                    f_result = optimizer.run(
                        mission_types=effective_sequence,
                        targets=targets,
                        threats=threats_dict,
                        base=mission.params.start,
                        max_total=max_assets,
                        doctrine_policy=doctrine_policy,
                    )
                    mission.set_formation(f_result)
                    st.session_state["_doctrine_policy"] = doctrine_policy
                    st.session_state.mission_sequence = effective_sequence
                st.rerun()

        # 결과 표시
        if mission.formation and mission.formation.is_feasible:
            fr = mission.formation
            utilization = getattr(fr, 'utilization_pct', 0)
            st.success(f"✅ {fr.solver_status} | 계산시간: {fr.solve_time_ms:.1f}ms | 전력활용률: {utilization}%")

            # 편대 구성 요약
            col_f, col_r, col_k, col_t = st.columns(4)
            col_f.metric("✈️ 전투기",   f"{fr.n_fighter}대",    delta=None)
            col_r.metric("🔍 정찰UAV",  f"{fr.n_recon_uav}대",  delta=None)
            col_k.metric("💥 자폭UAV",  f"{fr.n_attack_uav}대", delta=None)
            col_t.metric("📊 총 비용",  f"{fr.total_cost:.0f}", delta=None)

            # 자산별 배정 테이블
            st.divider()
            st.markdown("**자산 배정 결과 (헝가리안)**")
            asset_data = []
            type_icon = {"fighter": "✈️", "recon_uav": "🔍", "attack_uav": "💥"}
            for a in fr.assets:
                asset_data.append({
                    "자산": f"{type_icon.get(a.asset_type,'?')} {a.callsign}",
                    "유형": a.asset_type,
                    "배정임무": a.assigned_mission or "-",
                    "목표번호": str(a.assigned_target_idx + 1) if a.assigned_target_idx is not None else "-",
                    "출발기지": a.base,
                })
            if asset_data:
                st.dataframe(pd.DataFrame(asset_data), hide_index=True, width="stretch")

            # MUM-T 비율 표시
            st.divider()
            total_uav = fr.n_recon_uav + fr.n_attack_uav
            mumt_ratio = total_uav / fr.n_fighter if fr.n_fighter > 0 else 0
            st.markdown(f"**MUM-T 비율**: 전투기 1 : UAV {mumt_ratio:.1f} "
                        f"{'✅ 교리 충족' if mumt_ratio >= 2.0 else '⚠️ 권장 비율(1:2) 미달'}")

    # 4. 임무 검증 (Validator)
    doctrine_policy = st.session_state.get("_doctrine_policy")
    if doctrine_policy and mission.formation and mission.formation.is_feasible:
        with tab_formation:
            st.divider()
            st.markdown("**교리 기반 자동 적용 정책**")
            for line in doctrine_policy.get("rationale", [])[:5]:
                st.markdown(f"- {line}")
            refs = doctrine_policy.get("refs", []) or []
            if refs:
                st.caption(
                    "참조 문서: " + ", ".join(
                        f"{r.get('source', '?')} p.{r.get('page', 0)}"
                        for r in refs[:4]
                    )
                )

    with tab_validator:
        st.subheader("✅ 규칙 기반 임무 검증")
        st.caption("근거: AFDP5-0 COA Analysis & Wargaming, JP3-30 ACO, FMI3-04.155, DAFMAN11-260")

        # 검증 실행 버튼
        col_vbtn, col_vinfo = st.columns([1, 2])
        run_validation = col_vbtn.button("🔍 임무 검증 실행", type="primary", use_container_width=True)
        col_vinfo.info("편대 구성 후 검증을 실행하면 교리 기반 7개 항목을 자동 검사합니다.")

        if run_validation:
            with st.spinner("📋 임무 계획 검증 중..."):
                validator = MissionValidator()
                threats_dict = [t.to_dict() for t in mission.threats]
                seq = st.session_state.get("mission_sequence", [])

                # formation_paths가 있으면 경로 포함 검증
                fp = st.session_state.get("_formation_paths", {})

                report = validator.validate(
                    formation_result=mission.formation,
                    formation_paths=fp,
                    threats=threats_dict,
                    mission_sequence=seq,
                    margin_km=mission.params.margin,
                    terrain_loader=terrain_fast
                )
                st.session_state["_validation_report"] = report

        # 검증 결과 표시
        report = st.session_state.get("_validation_report", None)
        if report:
            # 요약 배너
            if report.is_valid:
                st.success(f"🟢 {report.summary()} | 검증 시간: {report.validate_time_ms:.1f}ms")
            else:
                st.error(f"🔴 {report.summary()} | 검증 시간: {report.validate_time_ms:.1f}ms")

            st.divider()

            # 검증 항목별 결과
            if not report.issues:
                st.balloons()
                st.success("모든 검증 항목 통과! 임무 계획이 교리에 부합합니다.")
            else:
                # 심각도별로 분류
                errors   = [i for i in report.issues if i.severity == "ERROR"]
                warnings = [i for i in report.issues if i.severity == "WARNING"]
                infos    = [i for i in report.issues if i.severity == "INFO"]

                if errors:
                    st.markdown("### 🔴 오류 (ERROR) - 즉시 수정 필요")
                    for issue in errors:
                        with st.expander(f"{issue.icon} [{issue.rule_id}] {issue.message}", expanded=True):
                            col_a, col_b = st.columns(2)
                            col_a.markdown(f"**교리 근거:** {issue.doctrine_ref}")
                            if issue.asset_id:
                                col_b.markdown(f"**관련 자산:** `{issue.asset_id}`")
                            if issue.suggestion:
                                st.warning(f"💡 권고사항: {issue.suggestion}")

                if warnings:
                    st.markdown("### 🟡 경고 (WARNING) - 검토 권장")
                    for issue in warnings:
                        with st.expander(f"{issue.icon} [{issue.rule_id}] {issue.message}"):
                            col_a, col_b = st.columns(2)
                            col_a.markdown(f"**교리 근거:** {issue.doctrine_ref}")
                            if issue.asset_id:
                                col_b.markdown(f"**관련 자산:** `{issue.asset_id}`")
                            if issue.suggestion:
                                st.info(f"💡 권고사항: {issue.suggestion}")

                if infos:
                    st.markdown("### 🔵 참고 (INFO)")
                    for issue in infos:
                        st.info(f"{issue.icon} {issue.message}")

            st.divider()

            # 검증 규칙 목록
            with st.expander("📋 검사된 규칙 목록"):
                rules = {
                    "MISSION_SEQUENCE": "Rule 5 - 임무 순서 (JP3-30 MAAP)",
                    "MUMT_RATIO":       "Rule 7 - MUM-T 비율 (FMI3-04.155)",
                    "NFZ":              "Rule 1 - 비행금지구역 침범 (JP3-30 ACO)",
                    "THREAT":           "Rule 2 - 위협 반경 침범 (JP3-30 ROE)",
                    "ALT":              "Rule 3 - 최소 고도 (FMI3-04.155)",
                    "RANGE":            "Rule 6 - 항속거리 (DAFMAN11-260)",
                    "ASSET_COLLISION":  "Rule 4 - 자산 충돌 (FMI3-04.155)",
                }
                checked_summary = []
                for rule_id in report.checked_rules:
                    prefix = rule_id.split("_")[0]
                    label = rules.get(rule_id) or rules.get(prefix, f"Rule - {rule_id}")
                    checked_summary.append(label)

                # 중복 제거 후 표시
                for label in sorted(set(checked_summary)):
                    st.markdown(f"- ✓ {label}")

            # JSON 내보내기
            with st.expander("📄 검증 보고서 JSON"):
                st.json(report.to_dict())

        else:
            # 미실행 안내
            st.info("편대 구성 탭에서 최적화를 먼저 실행한 후 검증을 수행하세요.")

            # 검증 항목 미리보기
            st.markdown("### 📋 검증 항목 (7개 규칙)")
            rules_preview = [
                ("Rule 1", "🟥", "비행금지구역(NFZ) 침범 검사",   "JP3-30 ACO"),
                ("Rule 2", "🟧", "위협 반경(SAM/RADAR) 침범 검사", "JP3-30 ROE"),
                ("Rule 3", "🟨", "최소 비행고도 검사 (AGL 200m)",  "FMI3-04.155"),
                ("Rule 4", "🟩", "자산 간 충돌 위험 검사",         "FMI3-04.155"),
                ("Rule 5", "🟦", "임무 수행 순서 검사 (ISR→SEAD→STRIKE)", "JP3-30 MAAP"),
                ("Rule 6", "🟪", "항속거리 초과 검사",             "DAFMAN11-260"),
                ("Rule 7", "⬜", "MUM-T 비율 검사 (1:2 이상)",    "FMI3-04.155"),
            ]
            for rule_id, icon, desc, ref in rules_preview:
                st.markdown(f"{icon} **{rule_id}** {desc} _{ref}_")

    # 5. XAI & Debug
    with tab_xai:
        st.subheader("🤔 AI 판단 근거")
        if mission.chat_history:
            last = [m for m in mission.chat_history if m["role"] == "assistant"]
            if last and last[-1].get('reasoning'):
                reasoning = last[-1].get('reasoning', '')
                # Why / What / How 구조로 파싱해서 표시
                st.info(f"**📋 판단 근거:**\n\n{reasoning}")

        # 임무 순서 표시
        if st.session_state.get("mission_sequence"):
            st.divider()
            st.subheader("📌 임무 수행 순서")
            seq = st.session_state["mission_sequence"]
            cols = st.columns(len(seq))
            colors = {"ISR": "🔵", "SEAD": "🟡", "STRIKE": "🔴", "CAS": "🟢"}
            for i, (col, mission_type) in enumerate(zip(cols, seq)):
                with col:
                    icon = colors.get(mission_type, "⚪")
                    st.metric(f"Step {i+1}", f"{icon} {mission_type}")

        st.divider()
        if "_show_heatmap" not in st.session_state:
            st.session_state["_show_heatmap"] = True
        st.checkbox("위험도 히트맵 (음영 반영)", key="_show_heatmap")

    with tab_debug:
        st.subheader("발표/디버그 도구")
        st.json(mission.params.to_dict())

        st.divider()
        st.markdown("**LLM 캐시 제어**")
        st.checkbox("응답 캐시 사용", key="_llm_cache_enabled")
        LLMBrain.set_cache_enabled(st.session_state.get("_llm_cache_enabled", True))
        c_cache1, c_cache2 = st.columns([1, 1])
        c_cache1.metric("캐시 엔트리", f"{LLMBrain.cache_size()}개")
        if c_cache2.button("캐시 비우기"):
            LLMBrain.clear_cache()
            st.rerun()

        st.divider()
        st.markdown("**발표용 시나리오 프리셋**")
        p1, p2, p3, p4 = st.columns(4)
        if p1.button("기본 시나리오"):
            _apply_demo_preset("baseline")
            st.rerun()
        if p2.button("고위험 시나리오"):
            _apply_demo_preset("high_risk")
            st.rerun()
        if p3.button("우회 검증"):
            _apply_demo_preset("detour")
            st.rerun()
        if p4.button("완전 리셋"):
            new_mission = MissionState()
            st.session_state.mission = new_mission
            st.session_state.mission_sequence = []
            st.session_state.pop("_formation_paths", None)
            st.session_state.pop("final_in", None)
            st.session_state.pop("_validation_report", None)
            st.session_state.pop("_doctrine_policy", None)
            p_new = new_mission.params
            st.session_state["_pending_widget_updates"] = {
                "_mp_start": p_new.start,
                "_mp_target_lat": float(p_new.target_lat),
                "_mp_target_lon": float(p_new.target_lon),
                "_mp_rtb": bool(p_new.rtb),
                "_mp_algorithm": p_new.algorithm,
                "_mp_enable_3d": bool(p_new.enable_3d),
                "_mp_margin": float(p_new.margin),
                "_mp_stpt_gap": int(p_new.stpt_gap),
                "_mp_fuel_state": float(getattr(p_new, "fuel_state", 1.0)),
                "_mp_refuel_count": int(getattr(p_new, "refuel_count", 0)),
            }
            st.rerun()


# ===== 경로 계산 =====
with col_right:
    effective_algorithm = mission.params.algorithm
    st.subheader(f"🗺️ 전술 지도 ({effective_algorithm})")

    # 알고리즘 설정
    pathfinder = None
    if effective_algorithm == "A* 3D":
        pathfinder = AStarPathfinder3DOptimized(terrain_fast)
    elif effective_algorithm == "A*":
        pathfinder = AStarPathfinder()
    elif effective_algorithm == "RRT":
        pathfinder = RRTPathfinder(max_iterations=3000)
    elif effective_algorithm == "RRT*":
        pathfinder = RRTStarPathfinder(max_iterations=3000)

    # 좌표 설정
    start_coord = AIRPORTS[mission.params.start]["coords"]
    target_coord = [mission.params.target_lat, mission.params.target_lon]

    if mission.params.enable_3d:
        s_elev = terrain_fast.get_elevation(*start_coord)
        t_elev = terrain_fast.get_elevation(*target_coord)
        start_coord = [*start_coord, s_elev + 800]
        target_coord = [*target_coord, t_elev + 800]

    threats_dict = [t.to_dict() for t in mission.threats]
    fuel_state = float(getattr(mission.params, "fuel_state", 1.0))
    refuel_count = int(getattr(mission.params, "refuel_count", 0))

    # ── 자산별 경로 색상 팔레트 (고대비 6색 팔레트) ──
    # 각 자산이 지도 위에서 명확히 구분되도록 색상 최대 차별화
    # 색맹 친화적(Color-blind safe) + 흰 외곽선으로 배경 대비 보장
    # ── 자산별 경로 색상 팔레트 (완전 고대비 8색, 색맹 친화적) ──
    # 인접 자산끼리 절대 유사한 색이 나오지 않도록 최대 색조 간격 보장
    ASSET_PALETTE = [
        "#E53935",  # 1번: 선명한 빨강    ─ Eagle-1 (전투기)
        "#43A047",  # 2번: 선명한 초록    ─ Scout-1 (정찰UAV)
        "#FB8C00",  # 3번: 선명한 주황    ─ Scout-2 (정찰UAV)
        "#8E24AA",  # 4번: 선명한 보라    ─ Scout-3 (정찰UAV)
        "#F9A825",  # 5번: 황금노랑       ─ Scout-4 (정찰UAV)
        "#00897B",  # 6번: 짙은 틸        ─ Viper-1 (자폭UAV)
        "#D81B60",  # 7번: 진홍분홍       ─ Viper-2 (자폭UAV)
        "#1565C0",  # 8번: 짙은 파랑      ─ 추가 자산
    ]
    # 임무 유형 기본 색상 (편대 없을 때 단일 경로)
    MISSION_COLOR = {
        "ISR":    "#43A047",  # 초록 (정찰)
        "SEAD":   "#FB8C00",  # 주황 (전자전)
        "STRIKE": "#E53935",  # 빨강 (타격)
        "CAS":    "#F9A825",  # 황금 (근접지원)
    }
    # 자산 타입별 색상 (편대 없을 때 사용)
    ASSET_COLOR = {
        "fighter":    "#E53935",  # 빨강   ─ 전투기
        "recon_uav":  "#43A047",  # 초록   ─ 정찰UAV (파랑과 구분)
        "attack_uav": "#00897B",  # 틸     ─ 자폭UAV
    }

    # ── 경로 계산 ──
    start_time = time.time()
    final_in = []
    final_out = []

    # 편대 구성 결과가 있으면 자산별 경로 계산
    formation_paths = {}  # {asset_id: {"in": path, "out": path, "color": color}}

    if mission.formation and mission.formation.is_feasible and mission.formation.assets:
        for asset in mission.formation.assets:
            # 자산별 출발기지 좌표
            asset_base_coords = AIRPORTS.get(asset.base, AIRPORTS[mission.params.start])["coords"]
            a_start = list(asset_base_coords)
            a_target = list(target_coord[:2])

            if mission.params.enable_3d:
                a_elev = terrain_fast.get_elevation(*a_start)
                # 자산 타입별 비행고도 오프셋
                from modules.config import ASSET_PERFORMANCE
                alt_offset = ASSET_PERFORMANCE.get(asset.asset_type, {}).get("altitude_m", 800)
                a_start = [*a_start, a_elev + alt_offset * 0.3]
                t_elev2 = terrain_fast.get_elevation(*a_target)
                a_target = [*a_target, t_elev2 + alt_offset * 0.3]

            try:
                if effective_algorithm == "A* 3D":
                    raw = pathfinder.find_path_3d_fast(
                        a_start, a_target, threats_dict, mission.params.margin,
                        fuel_state=fuel_state, refuel_count=refuel_count
                    )
                elif effective_algorithm in ("RRT", "RRT*"):
                    raw = pathfinder.find_path(
                        a_start, a_target, threats_dict, mission.params.margin,
                        fuel_state=fuel_state, refuel_count=refuel_count
                    )
                elif effective_algorithm == "A*":
                    raw = pathfinder.find_path(
                        a_start[:2], a_target[:2], threats_dict, mission.params.margin,
                        fuel_state=fuel_state, refuel_count=refuel_count
                    )
                else:
                    raw = pathfinder.find_path(a_start[:2], a_target[:2], threats_dict, mission.params.margin)
                path_in = smooth_path_3d(raw) if (raw and len(raw[0]) == 3) else smooth_path(raw)
            except Exception as e:
                st.warning(f"⚠️ {asset.callsign} 경로 탐색 오류: {e}")
                path_in = []

            path_out = []
            if mission.params.rtb and path_in:
                try:
                    eg_start = path_in[-1]
                    eg_end   = a_start
                    if effective_algorithm == "A* 3D":
                        raw_o = pathfinder.find_path_3d_fast(
                            eg_start, eg_end, threats_dict, mission.params.margin,
                            fuel_state=fuel_state, refuel_count=refuel_count
                        )
                    elif effective_algorithm in ("RRT", "RRT*"):
                        raw_o = pathfinder.find_path(
                            eg_start, eg_end, threats_dict, mission.params.margin,
                            fuel_state=fuel_state, refuel_count=refuel_count
                        )
                    elif effective_algorithm == "A*":
                        raw_o = pathfinder.find_path(
                            eg_start[:2], eg_end[:2], threats_dict, mission.params.margin,
                            fuel_state=fuel_state, refuel_count=refuel_count
                        )
                    else:
                        raw_o = pathfinder.find_path(eg_start[:2], eg_end[:2], threats_dict, mission.params.margin)
                    path_out = smooth_path_3d(raw_o) if (raw_o and len(raw_o[0]) == 3) else smooth_path(raw_o)
                except Exception as e2:
                    st.warning(f"⚠️ {asset.callsign} 복귀 경로 오류: {e2}")
                    path_out = []

            # 자산 인덱스 기반 팔레트 색상 (자산마다 완전히 다른 색)
            asset_idx = list(mission.formation.assets).index(asset)
            color = ASSET_PALETTE[asset_idx % len(ASSET_PALETTE)]
            formation_paths[asset.asset_id] = {
                "in": path_in, "out": path_out,
                "color": color, "callsign": asset.callsign,
                "mission": asset.assigned_mission or "?",
                "type": asset.asset_type
            }
            # 대표 경로 (첫 번째 자산)
            if not final_in and path_in:
                final_in = path_in
                final_out = path_out

    # validator용 경로 데이터 저장 ({"asset_id": {"in": path, "out": path}})
    if formation_paths:
        st.session_state["_formation_paths"] = {
            aid: {"in": d["in"], "out": d["out"]}
            for aid, d in formation_paths.items()
        }

    else:
        # 편대 없으면 기존 단일 경로
        try:
            if effective_algorithm == "A* 3D":
                raw_in = pathfinder.find_path_3d_fast(
                    start_coord, target_coord, threats_dict, mission.params.margin,
                    fuel_state=fuel_state, refuel_count=refuel_count
                )
            elif effective_algorithm in ("RRT", "RRT*"):
                raw_in = pathfinder.find_path(
                    start_coord, target_coord, threats_dict, mission.params.margin,
                    fuel_state=fuel_state, refuel_count=refuel_count
                )
            elif effective_algorithm == "A*":
                raw_in = pathfinder.find_path(
                    start_coord[:2], target_coord[:2], threats_dict, mission.params.margin,
                    fuel_state=fuel_state, refuel_count=refuel_count
                )
            else:
                raw_in = pathfinder.find_path(start_coord[:2], target_coord[:2], threats_dict, mission.params.margin)
        except Exception as e:
            st.warning(f"⚠️ 단일 경로 탐색 오류: {e}")
            raw_in = []
        final_in = smooth_path_3d(raw_in) if (raw_in and len(raw_in[0]) == 3) else smooth_path(raw_in)

        if mission.params.rtb and final_in:
            eg_s = final_in[-1]
            eg_e = start_coord
            try:
                if effective_algorithm == "A* 3D":
                    raw_out = pathfinder.find_path_3d_fast(
                        eg_s, eg_e, threats_dict, mission.params.margin,
                        fuel_state=fuel_state, refuel_count=refuel_count
                    )
                elif effective_algorithm in ("RRT", "RRT*"):
                    raw_out = pathfinder.find_path(
                        eg_s, eg_e, threats_dict, mission.params.margin,
                        fuel_state=fuel_state, refuel_count=refuel_count
                    )
                elif effective_algorithm == "A*":
                    raw_out = pathfinder.find_path(
                        eg_s[:2], eg_e[:2], threats_dict, mission.params.margin,
                        fuel_state=fuel_state, refuel_count=refuel_count
                    )
                else:
                    raw_out = pathfinder.find_path(eg_s[:2], eg_e[:2], threats_dict, mission.params.margin)
            except Exception as e3:
                st.warning(f"⚠️ 복귀 경로 오류: {e3}")
                raw_out = []
            final_out = smooth_path_3d(raw_out) if (raw_out and len(raw_out[0]) == 3) else smooth_path(raw_out)

    calc_time = time.time() - start_time
    # 내보내기 버튼이 찾는 이름인 'final_in'으로 저장합니다.
    st.session_state['final_in'] = final_in  
    st.session_state.current_path = final_in # 기존 코드 호환을 위해 유지    st.caption(f"⏱️ 계산 시간: {calc_time:.3f}초")
    
    # [수정/추가 부분] ⏱️ 계산 시간 출력(st.caption) 바로 아래에 삽입

    # ── 요구사항 2: 실시간 경로 위험도 분석 리포트 표기 ──
    if final_in:
        # Ingress + Egress 전체 경로 분석 (항상 3D 거리 기반)
        if formation_paths:
            per_asset_reports = []
            weighted_avg_sum = 0.0
            weighted_count = 0
            total_length_km = 0.0
            total_high_risk = 0
            max_risk = 0.0

            for pdata in formation_paths.values():
                combined_path = (pdata.get("in", []) or []) + (pdata.get("out", []) or [])
                if not combined_path:
                    continue
                rr = XAIUtils.analyze_path_risk(
                    combined_path,
                    threats_dict,
                    mission.params.margin,
                    terrain_loader=terrain_fast
                )
                per_asset_reports.append(rr)
                w = len(combined_path)
                weighted_avg_sum += rr.get("avg_risk", 0.0) * w
                weighted_count += w
                total_length_km += rr.get("total_length_km", 0.0)
                total_high_risk += int(rr.get("high_risk_segments", 0))
                max_risk = max(max_risk, rr.get("max_risk", 0.0))

            if per_asset_reports:
                risk_report = {
                    "avg_risk": (weighted_avg_sum / weighted_count) if weighted_count > 0 else 0.0,
                    "max_risk": max_risk,
                    "high_risk_segments": total_high_risk,
                    "total_length_km": total_length_km,
                }
            else:
                risk_report = XAIUtils.analyze_path_risk(
                    final_in + final_out,
                    threats_dict,
                    mission.params.margin,
                    terrain_loader=terrain_fast
                )
        else:
            risk_report = XAIUtils.analyze_path_risk(
                final_in + final_out, 
                threats_dict, 
                mission.params.margin, 
                terrain_loader=terrain_fast
            )
        st.session_state["_last_path_analysis"] = {
            "max_risk": risk_report.get("max_risk", 0.0),
            "waypoint_count": len(final_in) + len(final_out),
            "total_distance_km": risk_report.get("total_length_km", 0.0),
        }
        
        st.divider()
        st.markdown("### 📊 실시간 경로 위험도 분석 (3D Dominant Risk)")
        m1, m2, m3, m4 = st.columns(4)
        
        # 요구사항 3: 지배적 위협 모델(Max) 기반 점수 표기
        m1.metric("지배적 위협 점수", f"{risk_report['max_risk']:.3f}", 
                  delta="🔴 고위험" if risk_report['max_risk'] > 0.7 else None, delta_color="inverse")
        m2.metric("평균 노출 위험", f"{risk_report['avg_risk']:.3f}")
        m3.metric("치명적 구간 수", f"{risk_report['high_risk_segments']}개")
        m4.metric("3D 실비행거리", f"{risk_report['total_length_km']:.1f}km")

        # 분석 결과에 따른 전술 권고
        if risk_report['max_risk'] >= 1.0:
            st.error("🚨 **작전 불가**: NFZ 침범 또는 치명적 위협이 감지되었습니다.")
        elif risk_report['max_risk'] > 0.7:
            st.error("🚨 **위험**: 피격 확률이 임계치(0.7)를 초과했습니다.")
        else:
            st.success("✅ **양호**: 계획된 경로의 위협 수준이 통제 범위 내에 있습니다.")
    else:
        st.session_state.pop("_last_path_analysis", None)
    # ── 여기까지 추가 ──

    # ===== 지도 시각화 v3.0 (이후 기존 코드 동일) =====

    # 경로 생성 실패 진단
    if formation_paths:
        failed = [aid for aid, d in formation_paths.items() if not d["in"]]
        ok     = [aid for aid, d in formation_paths.items() if d["in"]]
        if failed:
            st.warning(
                f"⚠️ 경로 탐색 부분 실패: {', '.join(failed)}\n\n"
                "**원인 및 해결책:**\n"
                "- 위협(RADAR 80km) 반경이 경로를 모두 차단할 수 있음\n"
                "- **안전 마진을 줄이거나(예: 2km)** A* 3D 알고리즘 선택 시 저고도 우회 자동 적용\n"
                "- 위협 반경을 줄이거나 위협을 삭제한 후 재시도"
            )
        if ok:
            st.success(f"✅ 경로 탐색 성공: {', '.join(ok)} ({len(ok)}/{len(formation_paths)} 자산)")
    elif not final_in and mission.threats:
        st.warning(
            "⚠️ 경로 탐색 실패\n\n"
            "위협 반경이 모든 경로를 차단 중입니다. "
            "안전 마진을 줄이거나(사이드바 슬라이더), "
            "위협을 일부 삭제한 후 재시도하세요.\n"
            "A* 3D 알고리즘 선택 시 저고도 우회를 자동 시도합니다."
        )

    # ===== 지도 시각화 v3.0 - 레이어 순서 완전 재설계 =====
    # 렌더링 순서 (아래→위): 히트맵 → 위협원(채움) → 위협원(테두리) → 경로선 → 마커
    # Folium은 나중에 add_to()한 요소가 위에 표시됨
    m = folium.Map(
        location=MAP_CENTER, zoom_start=MAP_ZOOM,
        tiles="CartoDB positron"  # 밝은 배경 → 경로 가시성 향상
    )

    # ── [Layer 1] 히트맵 (가장 아래, 경로를 절대 가리지 않도록) ──
    show_heatmap = st.session_state.get('_show_heatmap', True)
    if show_heatmap and mission.threats:
        h_data = XAIUtils.generate_heatmap_data(threats_dict, mission.params.margin, terrain_loader=terrain_fast)
        if h_data:
            HeatMap(h_data, radius=15, blur=25, min_opacity=0.1, max_opacity=0.35).add_to(m)

    # ── [Layer 2] 위협 영역 채움 (아주 연하게, 경로보다 먼저 그림) ──
    t_color_map = {"SAM": ("#D32F2F", "red"), "RADAR": ("#6A1B9A", "purple"), "NFZ": ("#E65100", "orange")}
    for t in mission.threats:
        hex_color, icon_color = t_color_map.get(t.type, ("#607D8B", "gray"))
        if t.type == "NFZ":
            folium.Rectangle(
                [[t.lat_min, t.lon_min], [t.lat_max, t.lon_max]],
                color=hex_color, weight=1.5,
                fill=True, fill_color=hex_color, fill_opacity=0.07
            ).add_to(m)
        elif t.lat and t.lon:
            folium.Circle(
                [t.lat, t.lon], radius=t.radius_km * 1000,
                color=hex_color, weight=1.5, opacity=0.5,
                fill=True, fill_color=hex_color, fill_opacity=0.06
            ).add_to(m)

    # ── [Layer 3] 경로선 (위협원보다 위에, 두껍게) ──
    def draw_path_with_outline(path_coords, color, weight=6, opacity=0.97, dash="", tooltip_text=""):
        """경로를 흰 외곽선 + 색상 선으로 그려 어떤 배경에서도 선명하게 표시"""
        if not path_coords:
            return
        latlon = [(p[0], p[1]) for p in path_coords]
        # Step 1: 검은 그림자 선 (가장 두껍게, 가장 아래)
        folium.PolyLine(
            latlon, color="#111111", weight=weight + 5,
            opacity=0.4, tooltip=tooltip_text
        ).add_to(m)
        # Step 2: 흰색 외곽선 (중간 두께)
        folium.PolyLine(
            latlon, color="white", weight=weight + 2,
            opacity=0.9, tooltip=tooltip_text
        ).add_to(m)
        # Step 3: 실제 색상 선 (가장 위)
        kwargs = dict(color=color, weight=weight, opacity=opacity, tooltip=tooltip_text)
        if dash:
            kwargs["dash_array"] = dash
        folium.PolyLine(latlon, **kwargs).add_to(m)

    type_icon_map = {"fighter": "✈", "recon_uav": "👁", "attack_uav": "💥"}

    if formation_paths:
        for asset_id, pdata in formation_paths.items():
            clr   = pdata["color"]
            label = f"{type_icon_map.get(pdata['type'],'?')} {pdata['callsign']} [{pdata['mission']}]"

            if pdata["in"]:
                draw_path_with_outline(
                    pdata["in"], clr, weight=6, opacity=0.97,
                    tooltip_text=f"{label} ▶ Ingress"
                )
            if pdata["out"]:
                draw_path_with_outline(
                    pdata["out"], clr, weight=4, opacity=0.80,
                    dash="10 6",
                    tooltip_text=f"{label} ◀ Egress"
                )
    else:
        if final_in:
            draw_path_with_outline(final_in, "#E53935", weight=6, opacity=0.97, tooltip_text="Ingress")
        if final_out:
            draw_path_with_outline(final_out, "#1E88E5", weight=5, opacity=0.85, dash="10 6", tooltip_text="Egress")

    # ── [Layer 4] 위협 테두리 + 아이콘 (경로 위에 그리되 얇게) ──
    for t in mission.threats:
        hex_color, icon_color = t_color_map.get(t.type, ("#607D8B", "gray"))
        if t.type != "NFZ" and t.lat and t.lon:
            folium.Circle(
                [t.lat, t.lon], radius=t.radius_km * 1000,
                color=hex_color, weight=2.5, opacity=0.8,
                fill=False, dash_array="10 5"
            ).add_to(m)
            icon_name = "rocket" if t.type == "SAM" else "wifi"
            alt_txt = ""
            if t.type == "SAM" and (getattr(t, "min_alt_m", None) is not None or getattr(t, "max_alt_m", None) is not None):
                alt_txt = f", 고도 {float(t.min_alt_m or 0):.0f}~{float(t.max_alt_m or 0):.0f}m"
            folium.Marker(
                [t.lat, t.lon],
                icon=folium.Icon(color=icon_color, icon=icon_name, prefix="fa"),
                tooltip=f"{t.type}: {t.name} (반경 {t.radius_km:.0f}km{alt_txt})"
            ).add_to(m)

    # ── [Layer 5] 경로 위에 자산 마커 (출발점 원) ──
    if formation_paths:
        for asset_id, pdata in formation_paths.items():
            clr = pdata["color"]
            label = f"{type_icon_map.get(pdata['type'],'?')} {pdata['callsign']} [{pdata['mission']}]"
            if pdata["in"]:
                # 출발 마커
                folium.CircleMarker(
                    pdata["in"][0][:2], radius=8,
                    color="white", weight=2.5,
                    fill=True, fill_color=clr, fill_opacity=1.0,
                    tooltip=label
                ).add_to(m)

    # ── [Layer 6] 출발·목표 마커 (최상위) ──
    folium.Marker(
        start_coord[:2],
        icon=folium.Icon(color="blue", icon="plane", prefix="fa"),
        tooltip=f"🛫 Base: {mission.params.start}"
    ).add_to(m)
    folium.Marker(
        target_coord[:2],
        icon=folium.Icon(color="red", icon="crosshairs", prefix="fa"),
        tooltip=f"🎯 Target: {mission.params.target_name}"
    ).add_to(m)

    # ── 범례 (편대 구성 시) ──
    if formation_paths:
        type_icon_map2 = {"fighter": "✈", "recon_uav": "🔍", "attack_uav": "💥"}
        legend_rows = ""
        for asset_id, pdata in formation_paths.items():
            icon_c = type_icon_map2.get(pdata["type"], "?")
            legend_rows += (
                f"<div style='display:flex;align-items:center;margin:4px 0;gap:8px;'>"
                f"<div style='width:32px;height:5px;background:{pdata['color']};"
                f"border:1px solid white;border-radius:3px;flex-shrink:0;'></div>"
                f"<span>{icon_c} <b>{pdata['callsign']}</b> "
                f"<span style='color:#ccc;font-size:11px;'>[{pdata['mission']}]</span></span>"
                f"</div>"
            )
        rtb_note = (
            "<div style='margin-top:8px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.2);"
            "color:#aaa;font-size:10px;'>실선 ─ Ingress &nbsp;│&nbsp; 점선 ╌ Egress</div>"
        ) if mission.params.rtb else ""
        legend_html = (
            f"<div style='background:rgba(10,10,20,0.90);color:white;"
            f"padding:12px 16px;border-radius:10px;font-size:12px;"
            f"border:1px solid rgba(255,255,255,0.15);min-width:190px;"
            f"box-shadow:0 4px 12px rgba(0,0,0,0.5);'>"
            f"<div style='font-size:13px;font-weight:bold;margin-bottom:6px;'>📍 자산 경로 범례</div>"
            f"{legend_rows}{rtb_note}</div>"
        )
        m.get_root().html.add_child(folium.Element(
            f"<div style='position:fixed;bottom:40px;left:40px;z-index:9999;'>{legend_html}</div>"
        ))

    st_folium(m, width="100%", height=720, returned_objects=[])

    # ===== [복구 완료] STPT 테이블 및 다운로드 =====
    if final_in:
        st.divider()
        st.subheader("📋 Steer Point List")
        
        gap = mission.params.stpt_gap
        data_in = []
        # 3D/2D 분기 처리
        for i, p in enumerate(final_in[::gap]):
            pt = {"Type": "Ingress", "Seq": i+1, "Lat": f"{p[0]:.4f}", "Lon": f"{p[1]:.4f}"}
            if len(p) == 3: pt["Alt(m)"] = f"{p[2]:.0f}"
            data_in.append(pt)

        data_out = []
        if final_out:
            for i, p in enumerate(final_out[::gap]):
                pt = {"Type": "Egress", "Seq": i+1, "Lat": f"{p[0]:.4f}", "Lon": f"{p[1]:.4f}"}
                if len(p) == 3: pt["Alt(m)"] = f"{p[2]:.0f}"
                data_out.append(pt)

        stpt_df = pd.DataFrame(data_in + data_out)
        st.dataframe(stpt_df, width="stretch", hide_index=True)

        csv = stpt_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 STPT CSV 다운로드", csv, "mission_stpt.csv", "text/csv")
        
        st.success(f"✅ 경로 생성 완료: 총 {len(final_in) + len(final_out)}개 웨이포인트")
        # =========================================================
        st.divider()
        st.subheader("📥 AirSim 전술 데이터 송출")

        if 'final_in' in st.session_state and st.session_state['final_in'] is not None:
            path_data = st.session_state['final_in']
            st.info(f"현재 추출 가능한 웨이포인트: {len(path_data)}개")

            # 버튼을 눌러야만 파일이 실제로 생성됩니다.
            if st.button("💾 mission_export.json 생성 (AirSim 연동용)"):
                try:
                    import json
                    import os
                    
                    # 현재 작업 디렉토리에 저장
                    file_path = os.path.join(os.getcwd(), "mission_export.json")
                    
                    with open(file_path, "w", encoding='utf-8') as f:
                        json.dump(path_data, f)
                    
                    st.success(f"✅ 파일 생성 성공! 위치: {file_path}")
                    st.balloons()  # 성공 축하 효과
                except Exception as e:
                    st.error(f"❌ 파일 생성 중 오류 발생: {e}")
        else:
            st.warning("경로 최적화를 먼저 수행하십시오. 데이터가 아직 준비되지 않았습니다.")
