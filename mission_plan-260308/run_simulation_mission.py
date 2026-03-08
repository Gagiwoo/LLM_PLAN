import json
from sim_utils.sim_mission_bridge import SimBridge

def start_tactical_flight():
    try:
        with open("mission_export.json", "r") as f:
            path_data = json.load(f)
        print(f"📂 {len(path_data)}개의 웨이포인트를 로드했습니다.")
    except FileNotFoundError:
        print("❌ mission_export.json 파일이 없습니다.")
        return

    home_lat, home_lon, home_alt = path_data[0]
    bridge = SimBridge()
    bridge.fly_imps_path(path_data, home_lat, home_lon, home_alt)

if __name__ == "__main__":
    print("⚡ F-16 Viper 전술 기동 시스템 가동...")
    start_tactical_flight()