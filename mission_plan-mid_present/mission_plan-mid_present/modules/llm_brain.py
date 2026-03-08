"""
LLM Brain 모듈 - Pydantic 기반 구조화된 출력 (전술 참모 모드 적용)
"""
import ollama
from typing import Optional, Literal
from pydantic import BaseModel, Field, ValidationError
from modules.config import LLM_MODEL, LLM_TEMPERATURE, AIRPORTS

# --- Pydantic 스키마 정의 ---
class MissionUpdateParams(BaseModel):
    safety_margin_km: Optional[float] = Field(None, ge=0.0, le=50.0, description="안전 마진(km)")
    rtb: Optional[bool] = Field(None, description="복귀(Return To Base) 여부")
    waypoint_name: Optional[str] = Field(None, description="경유할 공항 이름")
    stpt_gap: Optional[int] = Field(None, ge=1, le=50, description="STPT 표시 간격")
    algorithm: Optional[Literal["A*", "A* 3D", "RRT", "RRT*"]] = Field(None, description="알고리즘")
    enable_3d: Optional[bool] = Field(None, description="3D 지형 고려 여부")

class LLMResponse(BaseModel):
    action: Literal["UPDATE", "CHAT"]
    update_params: MissionUpdateParams
    response_text: str
    reasoning: str = Field(..., description="AI의 판단 근거 (Why, What, How)")

class LLMBrain:
    def __init__(self, model_name: str = LLM_MODEL):
        self.model = model_name
        self.temperature = LLM_TEMPERATURE
        
    def parse_tactical_command(self, user_msg: str, current_state: dict, path_analysis: dict = None) -> dict:
        
        # [추가된 부분] 전달받은 위협 리스트 꺼내기 (streamlit_app.py에서 가공된 문자열 수신)
        active_threats = current_state.get('active_threats', '없음')
        
        # 💡 [업그레이드] AI가 더 잘 이해하도록 상태 설명(State Desc)을 명확하게 구조화
        state_desc = (
            f"- 설정된 안전 마진: {current_state.get('margin', 5.0)}km\n"
            f"- RTB(복귀) 여부: {current_state.get('rtb', True)}\n"
            f"- 탐색 알고리즘: {current_state.get('algorithm', 'A*')}\n"
            f"- 3D 지형 고려: {current_state.get('enable_3d', False)}\n"
            f"- 식별된 적대 위협 목록: {active_threats}"  
        )
        
        path_info = ""
        if path_analysis:
            path_info = f"- 현재 경로 최대 위험도(Risk): {path_analysis.get('max_risk', 0):.2f}"

        # 💡 [업그레이드] 군사 용어 적용 및 명확한 행동 지침(Prompt) 하달
        system_prompt = f"""당신은 대한민국 공군의 전술 임무 계획(Mission Planning)을 보좌하는 AI 전술 참모입니다.
사용자(작전관)의 질문에 대해 반드시 군사 용어('~입니다', '~알려드립니다', '보고드립니다' 등 다나까 체)를 사용하여 브리핑하십시오.

[현재 전술 상황]
{state_desc}
{path_info}

[행동 지침]
1. 상황 브리핑: 작전관이 위협 정보나 현재 상태를 물어보면, [현재 전술 상황]의 데이터를 바탕으로 '정확한 수치(위협 명칭, 종류, 반경, 좌표 등)'를 100% 반영하여 구체적으로 보고하십시오. 임의의 수치를 절대 지어내지 마십시오.
2. 명령 수행: 경로, 마진, 고도 등 작전 파라미터 변경 지시가 확인되면 action을 "UPDATE"로 설정하십시오.
3. 일반 응답: 단순 현황 보고나 질문에 대한 답변은 action을 "CHAT"으로 설정하십시오.

[출력 형식]
반드시 제공된 JSON 스키마를 엄격히 준수해야 합니다.
- response_text: 작전관에게 구두로 보고할 내용 (군사 용어, 한국어)
- reasoning: AI 참모로서 이 보고를 구성한 전술적 판단 근거 (한국어)
- Available Airports: {list(AIRPORTS.keys())}
"""
        
        try:
            response = ollama.chat(
                model=self.model,
                messages=[
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_msg}
                ],
                format=LLMResponse.model_json_schema(), # 구조 강제
                options={'temperature': self.temperature}
            )
            
            # Pydantic 파싱
            validated = LLMResponse.model_validate_json(response['message']['content'])
            result = validated.model_dump()
            
            # 공항 유효성 2차 검증
            wp = result['update_params'].get('waypoint_name')
            if wp and wp not in AIRPORTS:
                result['update_params']['waypoint_name'] = None
                result['response_text'] += f" (⚠️ '{wp}' 공항 없음)"
                
            return result
            
        except Exception as e:
            return {
                "action": "CHAT",
                "response_text": "작전관님, 명령 처리 중 시스템 오류가 발생했습니다. 통신 상태를 확인해 주십시오.",
                "reasoning": f"시스템 오류: {str(e)}",
                "update_params": {}
            }