"""
통합 임무계획 시스템 v10.5 (DB 연동 + LLM 인지능력 향상)
- UI: 위협 DB 기반 자동 선택 적용
- LLM: AI에 거리, 좌표 정확히 전달
"""
import streamlit as st
import folium
from streamlit_folium import st_folium
from folium.plugins import HeatMap
import pandas as pd
import time

from modules.config import AIRPORTS, MAP_CENTER, MAP_ZOOM, CHAT_CONTAINER_HEIGHT, AVAILABLE_ALGORITHMS
from modules.mission_state import MissionState, Threat, THREAT_DB
from modules.llm_brain import LLMBrain
from modules.pathfinder import AStarPathfinder, AStarPathfinder3D, smooth_path, smooth_path_3d
from modules.pathfinder_optimized import AStarPathfinder3DOptimized, TerrainCacheFast
from modules.pathfinder_rrt import RRTPathfinder, RRTStarPathfinder
from modules.terrain_loader import TerrainLoader
from modules.xai_utils import XAIUtils

# ===== 페이지 설정 =====
st.set_page_config(page_title="IMPS v10.5 (Tactical DB)", layout="wide", initial_sidebar_state="collapsed")
st.title("🚁 통합 임무계획 시스템 v10.5 (Tactical DB & AI Comm)")

# ===== 상태 초기화 =====
if "mission" not in st.session_state:
    st.session_state.mission = MissionState()

if "terrain" not in st.session_state:
    with st.spinner("🌍 지형 데이터 메모리 적재 중... (최초 1회)"):
        base_loader = TerrainLoader()
        st.session_state.terrain = TerrainCacheFast(base_loader)

mission = st.session_state.mission
terrain_fast = st.session_state.terrain 

# 호환성 매핑
if not hasattr(terrain_fast, 'get_elevation'):
    terrain_fast.get_elevation = terrain_fast.get

# ===== 레이아웃 =====
col_left, col_right = st.columns([1, 2])

with col_left:
    tab_ops, tab_intel, tab_xai, tab_debug = st.tabs(["💬 작전 통제", "⚠️ 위협 관리", "🤔 AI 판단 근거", "🔧 디버그"])

    # 1. 작전 통제
    with tab_ops:
        with st.expander("⚙️ 미션 프로파일 설정", expanded=True):
            with st.form("mission_form"):
                p = mission.params
                p.start = st.selectbox("출발 기지", list(AIRPORTS.keys()), index=list(AIRPORTS.keys()).index(p.start))
                
                c1, c2 = st.columns(2)
                p.target_lat = c1.number_input("Lat", 33.0, 43.0, p.target_lat, format="%.4f")
                p.target_lon = c2.number_input("Lon", 124.0, 132.0, p.target_lon, format="%.4f")

                c_rtb, c_algo = st.columns([1, 1])
                p.rtb = c_rtb.checkbox("Strike & RTB", value=p.rtb)
                p.algorithm = c_algo.selectbox("알고리즘", AVAILABLE_ALGORITHMS, index=AVAILABLE_ALGORITHMS.index(p.algorithm))

                p.enable_3d = st.checkbox("3D 모드 (지형 고려)", value=p.enable_3d)
                p.margin = st.slider("안전 마진(km)", 0.0, 50.0, p.margin)
                p.stpt_gap = st.slider("STPT 표시 간격", 1, 50, p.stpt_gap)

                if st.form_submit_button("🔄 설정 적용 및 경로 계산", type="primary"):
                    st.rerun()

        st.divider()
        chat_container = st.container(height=CHAT_CONTAINER_HEIGHT)
        for msg in mission.chat_history:
            with chat_container.chat_message(msg["role"]):
                st.write(msg["content"])

        if user_input := st.chat_input("명령 입력 (예: 현재 식별된 위협 보고해)"):
            mission.add_chat_message("user", user_input)
            with st.spinner("🧠 전술 참모 분석 중..."):
                brain = LLMBrain()
                
                # 💡 [핵심 수정 포인트] LLM에 넘겨줄 위협 리스트 요약 (거리, 좌표 포함)
                threat_info_for_ai = ", ".join([f"{t.name}(유형:{t.type}, 반경:{t.radius_km}km, 좌표: Lat {t.lat}, Lon {t.lon})" for t in mission.threats]) if mission.threats else "없음"
                
                # 경로 위험도 정밀 분석
                path_analysis = None
                current_path = st.session_state.get("current_path")
                if current_path:
                    threats_for_xai = [t.to_dict() for t in mission.threats]
                    path_analysis = XAIUtils.analyze_path_risk(current_path, threats_for_xai, mission.params.margin)
                
                # 강화된 상태 정보 전달
                enriched_state = mission.params.to_dict()
                enriched_state["active_threats"] = threat_info_for_ai
                
                result = brain.parse_tactical_command(user_input, enriched_state, path_analysis)
                
                if result["action"] == "UPDATE":
                    u = result["update_params"]
                    if u.get("safety_margin_km") is not None: mission.params.margin = u["safety_margin_km"]
                    if u.get("rtb") is not None: mission.params.rtb = u["rtb"]
                    if u.get("stpt_gap") is not None: mission.params.stpt_gap = u["stpt_gap"]
                    if u.get("waypoint_name"): mission.params.waypoint = u["waypoint_name"]
                    if u.get("algorithm"): mission.params.algorithm = u["algorithm"]
                    if u.get("enable_3d") is not None: mission.params.enable_3d = u["enable_3d"]

                ai_msg = result["response_text"]
                mission.add_chat_message("assistant", ai_msg, result.get("reasoning", ""))
                st.rerun()

# 2. 위협 관리
    with tab_intel:
        st.subheader("위협 추가")
        
        # 💡 [핵심 수정] 라디오 버튼을 st.form 바깥으로 이동! (클릭 즉시 반응하도록)
        add_type = st.radio('위협 입력 방식', ["군사 DB (SAM/RADAR)", "수동 설정 (SAM/RADAR)", "수동 설정 (NFZ)"], horizontal=True)
        
        with st.form("threat_form"):
            if add_type == "군사 DB (SAM/RADAR)":
                selected_db = st.selectbox("적성 체계 식별명", list(THREAT_DB.keys()))
                t_name = st.text_input("전술 지도 표시 명칭", value=f"{selected_db.split()[0]}-{len(mission.threats)+1:02d}")
            elif add_type == "수동 설정 (SAM/RADAR)":
                manual_type = st.radio("위협 유형", ["SAM", "RADAR"], horizontal=True)
                t_name = st.text_input("전술 지도 표시 명칭", value=f"Threat-{len(mission.threats)+1:02d}")
            else:
                t_name = st.text_input("비행금지구역 명칭", value=f"NFZ-{len(mission.threats)+1:02d}")

            c1, c2 = st.columns(2)
            t_lat = c1.number_input("Lat (위도)", 33.0, 43.0, 38.0000, format="%.4f", key="t_lat")
            t_lon = c2.number_input("Lon (경도)", 124.0, 132.0, 127.0000, format="%.4f", key="t_lon")
            
            if add_type == "수동 설정 (SAM/RADAR)":
                t_rad = st.slider("반경(km)", 5, 200, 30, key="t_rad")

            if add_type == "수동 설정 (NFZ)":
                l_min = c1.number_input("Min Lat", 33.0, 43.0, 37.5000, format="%.4f")
                l_max = c2.number_input("Max Lat", 33.0, 43.0, 37.8000, format="%.4f")
                ln_min = c1.number_input("Min Lon", 124.0, 132.0, 127.5000, format="%.4f")
                ln_max = c2.number_input("Max Lon", 124.0, 132.0, 127.8000, format="%.4f")

            if st.form_submit_button("➕ 위협 추가"):
                if add_type == "수동 설정 (NFZ)":
                    mission.add_threat(Threat(name=t_name, type="NFZ", lat_min=l_min, lat_max=l_max, lon_min=ln_min, lon_max=ln_max))
                
                elif add_type == "군사 DB (SAM/RADAR)":
                    db_info = THREAT_DB[selected_db]
                    ground_elev = terrain_fast.get_elevation(t_lat, t_lon)
                    r_km = db_info["radius_km"]

                    mission.add_threat(Threat(
                        name=t_name,
                        type=db_info["type"],
                        lat=t_lat,
                        lon=t_lon,
                        radius_km=r_km,
                        alt=ground_elev + 10.0,
                        loss=db_info["loss"],
                        rcs_m2=db_info["rcs_m2"],
                        pd_k=db_info["pd_k"],
                        sskp=db_info["sskp"],
                        pk_peak_km=r_km * db_info["peak_ratio"],
                        pk_sigma_km=r_km * db_info["sigma_ratio"]
                    ))
                
                elif add_type == "수동 설정 (SAM/RADAR)":
                    ground_elev = terrain_fast.get_elevation(t_lat, t_lon)
                    
                    if manual_type == "RADAR":
                        peak, sigma, sskp = 0.0, 0.0, 0.0
                    else:
                        peak = t_rad * 0.35
                        sigma = t_rad * 0.20
                        sskp = 0.75
                        
                    mission.add_threat(Threat(
                        name=t_name,
                        type=manual_type,
                        lat=t_lat,
                        lon=t_lon,
                        radius_km=t_rad,
                        alt=ground_elev + 10.0,
                        loss=8.0,
                        rcs_m2=2.5,
                        pd_k=0.4,      
                        sskp=sskp,
                        pk_peak_km=peak,
                        pk_sigma_km=sigma
                    ))
                st.rerun()

        st.divider()
        if mission.threats:
            threat_df = pd.DataFrame([t.to_dict() for t in mission.threats])
            cols = [c for c in ['name', 'type', 'radius_km', 'lat', 'lon', 'sskp'] if c in threat_df.columns]
            st.dataframe(threat_df[cols], hide_index=True, use_container_width=True)
            
            c_del, c_btn = st.columns([3, 1])
            del_name = c_del.selectbox("삭제할 위협", [t.name for t in mission.threats])
            if c_btn.button("🗑️ 삭제"):
                mission.remove_threat(del_name)
                st.rerun()

    # 3. XAI & Debug
    with tab_xai:
        st.subheader("🤔 AI 판단 근거")
        if mission.chat_history:
            last = [m for m in mission.chat_history if m["role"] == "assistant"]
            if last: st.info(f"**Reasoning:**\n\n{last[-1].get('reasoning', '')}")
        st.divider()
        show_heatmap = st.checkbox("위험도 히트맵 (음영 반영)", value=True)

    with tab_debug:
        st.json(mission.params.to_dict())


# ===== 경로 계산 =====
with col_right:
    st.subheader(f"🗺️ 전술 지도 ({mission.params.algorithm})")

    pathfinder = None
    if mission.params.algorithm == "A* 3D":
        pathfinder = AStarPathfinder3DOptimized(terrain_fast)
    elif mission.params.algorithm == "A*":
        pathfinder = AStarPathfinder()
    elif mission.params.algorithm == "RRT":
        pathfinder = RRTPathfinder(max_iterations=2000)
    elif mission.params.algorithm == "RRT*":
        pathfinder = RRTStarPathfinder(max_iterations=2000)

    start_coord = AIRPORTS[mission.params.start]["coords"]
    target_coord = [mission.params.target_lat, mission.params.target_lon]
    
    if mission.params.enable_3d:
        s_elev = terrain_fast.get_elevation(*start_coord)
        t_elev = terrain_fast.get_elevation(*target_coord)
        start_coord = [*start_coord, s_elev + 800]
        target_coord = [*target_coord, t_elev + 800]

    threats_dict = [t.to_dict() for t in mission.threats]
    
    start_time = time.time()
    final_in = []
    final_out = []
    
    if mission.params.algorithm == "A* 3D":
        raw_in = pathfinder.find_path_3d_fast(start_coord, target_coord, threats_dict, mission.params.margin)
    elif hasattr(pathfinder, 'find_path_3d') and mission.params.enable_3d:
        raw_in = pathfinder.find_path_3d(start_coord, target_coord, threats_dict, mission.params.margin)
    else:
        raw_in = pathfinder.find_path(start_coord[:2], target_coord[:2], threats_dict, mission.params.margin)
        
    final_in = smooth_path_3d(raw_in) if (raw_in and len(raw_in[0])==3) else smooth_path(raw_in)

    if mission.params.rtb and final_in:
        egress_start = final_in[-1]
        egress_end = start_coord
        if mission.params.algorithm == "A* 3D":
            raw_out = pathfinder.find_path_3d_fast(egress_start, egress_end, threats_dict, mission.params.margin)
        elif hasattr(pathfinder, 'find_path_3d') and mission.params.enable_3d:
            raw_out = pathfinder.find_path_3d(egress_start, egress_end, threats_dict, mission.params.margin)
        else:
            raw_out = pathfinder.find_path(egress_start[:2], egress_end[:2], threats_dict, mission.params.margin) 
        final_out = smooth_path_3d(raw_out) if (raw_out and len(raw_out[0])==3) else smooth_path(raw_out)

    calc_time = time.time() - start_time
    st.session_state.current_path = final_in
    st.caption(f"⏱️ 계산 시간: {calc_time:.3f}초")

    m = folium.Map(location=MAP_CENTER, zoom_start=MAP_ZOOM)
    folium.Marker(start_coord[:2], icon=folium.Icon(color="blue", icon="plane"), tooltip="Start").add_to(m)
    folium.Marker(target_coord[:2], icon=folium.Icon(color="red", icon="crosshairs", prefix="fa"), tooltip="Target").add_to(m)

    for t in mission.threats:
        color = "crimson" if t.type == "SAM" else ("purple" if t.type == "RADAR" else "orange")
        if t.type == "NFZ":
            folium.Rectangle([[t.lat_min, t.lon_min], [t.lat_max, t.lon_max]], color=color, fill=True).add_to(m)
        else:
            folium.Circle([t.lat, t.lon], radius=t.radius_km*1000, color=color, fill=True, fill_opacity=0.2).add_to(m)
            icon_name = "rocket" if t.type == "SAM" else "wifi"
            folium.Marker([t.lat, t.lon], icon=folium.Icon(color=color, icon=icon_name, prefix="fa"), tooltip=f"{t.type}: {t.name}").add_to(m)

    if final_in:
        folium.PolyLine([(p[0], p[1]) for p in final_in], color="blue", weight=4, opacity=0.8).add_to(m)
    if final_out:
        folium.PolyLine([(p[0], p[1]) for p in final_out], color="orange", weight=4, dash_array="5, 5").add_to(m)

    if 'show_heatmap' in locals() and show_heatmap and mission.threats:
        h_data = XAIUtils.generate_heatmap_data(threats_dict, mission.params.margin, terrain_loader=terrain_fast)
        if h_data: HeatMap(h_data, radius=15, blur=20, min_opacity=0.2).add_to(m)

    st_folium(m, width="100%", height=700, returned_objects=[])

    if final_in:
        st.divider()
        st.subheader("📋 Steer Point List")
        gap = mission.params.stpt_gap
        data_in = []
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
        st.dataframe(stpt_df, use_container_width=True, hide_index=True)
        csv = stpt_df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 STPT CSV 다운로드", csv, "mission_stpt.csv", "text/csv")
        st.success(f"✅ 경로 생성 완료: 총 {len(final_in) + len(final_out)}개 웨이포인트")