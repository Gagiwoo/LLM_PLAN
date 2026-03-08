"""
SRTM 지형 데이터 로더 (자동 감지 + 가상 지형 Fallback)
"""
import os
import math
import numpy as np
from modules.config import SRTM_DATA_DIR, MAP_BOUNDS

try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False
    print("⚠️ rasterio 미설치. 가상 지형 모드로 동작합니다.")

class TerrainLoader:
    def __init__(self, dem_dir: str = SRTM_DATA_DIR):
        self.dem_dir = dem_dir
        self.datasets = []
        self.cache = {}
        self.use_fallback = False

        # 1. 라이브러리가 있고 폴더가 존재하면 파일 스캔 시도
        if HAS_RASTERIO and os.path.exists(self.dem_dir):
            self._scan_srtm_files()
        else:
            print(f"⚠️ 경로({self.dem_dir}) 확인 불가 또는 라이브러리 부재. 가상 지형 사용.")
            self.use_fallback = True

    def _scan_srtm_files(self):
        """폴더 내의 모든 tif, hgt 파일 자동 스캔"""
        try:
            files = [f for f in os.listdir(self.dem_dir) if f.lower().endswith(('.tif', '.hgt', '.tiff'))]
        except Exception:
            files = []

        if not files:
            print("⚠️ 지형 파일 없음. 가상 지형 모드 전환.")
            self.use_fallback = True
            return

        print(f"🌍 지형 파일 {len(files)}개 로딩 중...")
        for f in files:
            filepath = os.path.join(self.dem_dir, f)
            try:
                ds = rasterio.open(filepath)
                # 데이터셋 객체와 경계정보 저장
                self.datasets.append((ds.bounds, ds))
                print(f"  - 로드 성공: {f}")
            except Exception as e:
                print(f"  ❌ 파일 로드 실패 {f}: {e}")
        
        if not self.datasets:
            self.use_fallback = True

    def get_elevation(self, lat: float, lon: float) -> float:
        """위경도에 대한 고도 반환 (캐싱 적용)"""
        cache_key = (round(lat, 4), round(lon, 4))
        if cache_key in self.cache:
            return self.cache[cache_key]

        elev = 0.0

        if not self.use_fallback:
            found = False
            for bounds, ds in self.datasets:
                # bounds: left, bottom, right, top
                if bounds.left <= lon <= bounds.right and bounds.bottom <= lat <= bounds.top:
                    try:
                        # rasterio index: (lon, lat) -> (row, col)
                        rows, cols = ds.index(lon, lat)
                        
                        if 0 <= rows < ds.height and 0 <= cols < ds.width:
                            val = ds.read(1)[rows, cols]
                            elev = float(val)
                            
                            # NoData 값(-32768 등) 처리
                            if elev < -100: 
                                elev = 0.0
                            found = True
                            break
                    except Exception:
                        continue
            
            # 파일 범위 밖이면 가상 지형 사용
            if not found:
                elev = self._generate_synthetic_terrain(lat, lon)
        else:
            # Fallback 모드면 무조건 가상 지형
            elev = self._generate_synthetic_terrain(lat, lon)

        self.cache[cache_key] = elev
        return elev

    def _generate_synthetic_terrain(self, lat: float, lon: float) -> float:
        """
        가상 산악 지형 생성 (테스트용)
        태백산맥을 흉내내어 동쪽이 높고 서쪽이 낮은 지형 생성
        """
        base = 100
        # 큰 산맥
        mountain = math.sin(lon * 2.5) * math.cos(lat * 1.5) * 600 
        # 작은 언덕
        hills = math.sin(lat * 10) * math.cos(lon * 10) * 150
        # 동고서저 바이어스
        bias = (lon - 126) * 100 if lon > 126 else 0
        
        total = base + abs(mountain) + hills + bias
        return max(0.0, total)