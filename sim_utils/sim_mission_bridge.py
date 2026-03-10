import airsim
import time
import math

class SimBridge:
    def __init__(self):
        self.client = airsim.MultirotorClient()
        self.client.confirmConnection()
        self.client.enableApiControl(True)
        self.client.armDisarm(True)

    def run_takeoff(self):
        """활주로 이륙 시퀀스"""
        print("🛫 이륙 시퀀스 개시: Full Throttle...")
        # 스로틀 100%, 기수 수평 유지하며 가속
        self.client.moveByRollPitchYawThrottleAsync(0, 0, 0, 1.0, 10).join()
        
        # 속도가 붙으면 기수를 10도 들어올림 (Rotation)
        print("🚀 Rotation: 기수 인상")
        self.client.moveByRollPitchYawThrottleAsync(0, -0.17, 0, 1.0, 5).join()

    def cruise_mach_08(self, ned_path):
        """마하 0.8(272m/s) 속도로 경로 추종"""
        print(f"⚡ 마하 0.8 돌입 (속도: 272m/s)")
        # F-16의 특성에 맞춰 고속 경로 비행
        self.client.moveOnPathAsync(
            ned_path, 
            velocity=272, # Mach 0.8
            drivetrain=airsim.DrivetrainType.ForwardOnly,
            yaw_mode=airsim.YawMode(False, 0)
        ).join()

    def run_landing(self, runway_pos_ned):
        """착륙 및 감속 시퀀스"""
        print("🛬 착륙 접근 시작: 속도 감속 중...")
        # 1. 속도를 착륙 속도(약 70m/s)로 급감속
        # 스로틀을 낮추고 기수를 살짝 들어 공기 저항을 이용합니다.
        self.client.moveToPositionAsync(
            runway_pos_ned.x_val, 
            runway_pos_ned.y_val, 
            runway_pos_ned.z_val, 
            velocity=75
        ).join()
        
        # 2. 최종 접지 (Touchdown)
        print("🎯 Touchdown!")
        self.client.moveByRollPitchYawThrottleAsync(0, 0, 0, 0, 5).join()
        self.client.armDisarm(False)