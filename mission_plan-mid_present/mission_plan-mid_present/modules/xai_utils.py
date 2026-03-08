"""
XAI (Explainable AI) 유틸리티 
- 레이더 음영 시각화 포함
- F-16 및 적성 방공망 현실화 파라미터 적용 (ZeroDivisionError 패치 완료)
"""

import numpy as np
import math
from typing import List, Dict, Tuple
from modules.config import HEATMAP_RESOLUTION, MAP_BOUNDS

# [중요] 레이더 음영 체크 함수 임포트
try:
    from modules.radar_shadow import check_line_of_sight
except ImportError:
    def check_line_of_sight(*args, **kwargs): return True

LAT_TO_KM = 110.57

class XAIUtils:
    """XAI 관련 기능"""
   
    @staticmethod
    def calculate_risk_score(lat: float, lon: float, threats: List[dict], margin: float, terrain_loader=None, target_alt: float = None) -> float:
        """
        특정 위치의 위험도 점수 계산 (음영 + SNR기반 Pd + Pk + 독립시행 누적 확률)
        """
        if not threats:
            return 0.0

        survival_prob = 1.0  # 생존 확률 (누적 연산용)

        # 타겟 고도 설정 (입력 없으면 지형 + 500m AGL 가정)
        if target_alt is None:
            target_alt = 500
            if terrain_loader:
                try:
                    target_alt = terrain_loader.get_elevation(lat, lon) + 500
                except:
                    pass

        for t in threats:
            risk = 0.0
            
            # (1) SAM 또는 RADAR
            if t["type"] in ["SAM", "RADAR"]:
                dist_km = math.sqrt(
                    ((lat - t["lat"]) * LAT_TO_KM) ** 2 +
                    ((lon - t["lon"]) * LAT_TO_KM * math.cos(math.radians(lat))) ** 2
                )
                threat_radius = float(t.get("radius_km", 0))

                # 거리상 완전 안전하면 패스
                if dist_km >= threat_radius + margin:
                    continue

                # 레이더 음영 체크(LOS)
                if terrain_loader:
                    threat_alt = float(t.get("alt", 0))
                    if threat_alt == 0:
                        try:
                            threat_alt = terrain_loader.get_elevation(t["lat"], t["lon"]) + 10
                        except:
                            threat_alt = 100

                    is_visible = check_line_of_sight(
                        radar_pos=(t["lat"], t["lon"], threat_alt),
                        aircraft_pos=(lat, lon, target_alt),
                        terrain_loader=terrain_loader,
                        samples=5
                    )
                    if not is_visible:
                        continue  # 지형에 가려지면 이 위협에 대해서는 위험도 0

                # ---------------------------------------------------------
                # [1] P_D: SNR 기반 탐지확률 (F-16 & 적성국 레이더 현실화)
                # ---------------------------------------------------------
                R_E = threat_radius
                R_D = R_E + margin
                
                # 시스템 손실(대기 감쇠, 기계적 손실 등)
                loss = float(t.get("loss", 8.0)) 
                # F-16 무장 장착 상태(Combat Configuration)의 평균 RCS
                rcs_m2 = float(t.get("rcs_m2", 2.5)) 
                # 탐지 곡선의 가파름(Steepness)
                pd_k = float(t.get("pd_k", 0.4)) 

                PD_AT_RD = 0.1
                logit_pd = math.log(PD_AT_RD / (1.0 - PD_AT_RD))
                pd_th_db = 0.0
                snr_req_db_at_rd = pd_th_db + (logit_pd / max(pd_k, 1e-9))
                snr_req_linear = 10.0 ** (snr_req_db_at_rd / 10.0)

                d_ref_m = max(1.0, R_D * 1000.0)
                snr0 = snr_req_linear * (d_ref_m ** 4) * (loss / max(rcs_m2, 1e-12))

                d_m = max(1.0, dist_km * 1000.0)
                snr = snr0 * (rcs_m2 / loss) / (d_m ** 4)
                snr_db = 10.0 * math.log10(max(snr, 1e-30))

                P_D = 1.0 / (1.0 + math.exp(-pd_k * (snr_db - pd_th_db)))
                P_D = max(0.0, min(1.0, P_D))

                # ---------------------------------------------------------
                # [2] P_K: 피격확률 (단발 격추 확률 SSKP & NEZ 반영)
                # ---------------------------------------------------------
                if dist_km >= R_E:
                    P_K = 0.0
                else:
                    # 단발 격추 확률(SSKP)
                    sskp = float(t.get("sskp", 0.75))
                    # No Escape Zone (가장 치명적인 거리)
                    d0 = float(t.get("pk_peak_km", 0.35 * R_E)) 
                    # 유효 교전 구역의 너비
                    sigma = float(t.get("pk_sigma_km", 0.2 * R_E)) 
                    
                    # 💡 [버그 수정] 레이더처럼 sigma나 sskp가 0인 경우 방어 로직
                    if sigma <= 0.0 or sskp <= 0.0:
                        P_K = 0.0
                    else:
                        P_K = sskp * math.exp(-((dist_km - d0) ** 2) / (2.0 * sigma ** 2))
                        
                    P_K = max(0.0, min(1.0, P_K))

                weight = float(t.get("weight", 1.0))
                risk = weight * (P_D * P_K)

            # (2) NFZ (비행금지구역)
            elif t["type"] == "NFZ":
                inside = (t["lat_min"] <= lat <= t["lat_max"] and t["lon_min"] <= lon <= t["lon_max"])
                if inside:
                    weight = float(t.get("weight", 1.0))
                    risk = weight * 1.0 
                else:
                    risk = 0.0

            # 누적 생존 확률 계산 (결합 법칙)
            risk = max(0.0, min(1.0, risk))
            survival_prob *= (1.0 - risk)

        # 전체 위험도 = 1 - 최종 생존 확률
        total_risk = 1.0 - survival_prob
        return total_risk
    
    @staticmethod
    def generate_heatmap_data(threats: List[dict], margin: float, terrain_loader=None) -> List[Tuple[float, float, float]]:
        min_lat, max_lat = MAP_BOUNDS["min_lat"], MAP_BOUNDS["max_lat"]
        min_lon, max_lon = MAP_BOUNDS["min_lon"], MAP_BOUNDS["max_lon"]
        
        heatmap_data = []
        step_lat = (max_lat - min_lat) / HEATMAP_RESOLUTION
        step_lon = (max_lon - min_lon) / HEATMAP_RESOLUTION
        
        for i in range(HEATMAP_RESOLUTION):
            for j in range(HEATMAP_RESOLUTION):
                lat = min_lat + i * step_lat
                lon = min_lon + j * step_lon
                
                risk = XAIUtils.calculate_risk_score(lat, lon, threats, margin, terrain_loader)
                
                if risk > 0.01:
                    heatmap_data.append([lat, lon, risk])
        
        return heatmap_data
    
    @staticmethod
    def analyze_path_risk(path: List[Tuple], threats: List[dict], margin: float, terrain_loader=None) -> Dict:
        if not path:
            return {"avg_risk": 0, "max_risk": 0, "high_risk_segments": 0, "total_length_km": 0}
        
        risks = []
        total_length = 0.0
        high_risk_count = 0
        
        for i, p in enumerate(path):
            lat, lon = p[0], p[1]
            target_alt = p[2] if len(p) == 3 else None 
            
            risk = XAIUtils.calculate_risk_score(lat, lon, threats, margin, terrain_loader, target_alt=target_alt) 
            risks.append(risk)
            
            if risk > 0.7: high_risk_count += 1
            if i > 0:
                dist = math.sqrt(((lat-path[i-1][0])*LAT_TO_KM)**2 + ((lon-path[i-1][1])*LAT_TO_KM*math.cos(math.radians(lat)))**2)
                total_length += dist
        
        return {
            "avg_risk": np.mean(risks) if risks else 0,
            "max_risk": max(risks) if risks else 0,
            "high_risk_segments": high_risk_count,
            "total_length_km": total_length
        }