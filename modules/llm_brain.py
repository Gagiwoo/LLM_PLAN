"""
LLM Brain 모듈 v2.0 - 군사 전문 참모 AI
- 모델: qwen3:14b (ollama)
- 자연어 전술 명령 → 문맥 이해 → 파라미터 자동 조정
- 교리 근거: JP3-30, AFDP3-03, AFDP5-0, FMI3-04.155
"""
import ollama
import json
import re
from pathlib import Path
from typing import Optional, Literal, List, Tuple
from pydantic import BaseModel, Field, ValidationError
from modules.doctrine_rag import DoctrineRAG
from modules.config import (
    LLM_MODEL, LLM_MODEL_FALLBACK, LLM_TEMPERATURE, LLM_TIMEOUT,
    AIRPORTS, MISSION_TYPES, MARGIN_LEVELS, THREAT_DEFAULT_RADIUS
)

try:
    from pypdf import PdfReader
    HAS_PDF_READER = True
except Exception:
    HAS_PDF_READER = False


# ================================================================
# Pydantic 스키마 - 확장된 구조
# ================================================================

class ThreatInfo(BaseModel):
    """LLM이 명령에서 추출한 위협 정보"""
    name: str = Field(..., description="위협 명칭 (예: Enemy-RADAR-01)")
    type: Literal["SAM", "RADAR", "NFZ"] = Field(..., description="위협 유형")
    lat: Optional[float] = Field(None, description="위협 위도")
    lon: Optional[float] = Field(None, description="위협 경도")
    radius_km: Optional[float] = Field(None, description="위협 반경(km)")


class MissionUpdateParams(BaseModel):
    """미션 파라미터 변경 내용"""
    safety_margin_km: Optional[float] = Field(None, ge=0.0, le=50.0, description="안전 마진(km)")
    rtb: Optional[bool] = Field(None, description="복귀(Return To Base) 여부")
    waypoint_name: Optional[str] = Field(None, description="경유할 공항 이름")
    stpt_gap: Optional[int] = Field(None, ge=1, le=50, description="STPT 표시 간격")
    algorithm: Optional[Literal["A*", "A* 3D", "RRT", "RRT*"]] = Field(None, description="알고리즘")
    enable_3d: Optional[bool] = Field(None, description="3D 지형 고려 여부")
    target_lat: Optional[float] = Field(None, ge=33.0, le=43.0, description="목표 위도")
    target_lon: Optional[float] = Field(None, ge=124.0, le=132.0, description="목표 경도")
    target_name: Optional[str] = Field(None, description="목표 명칭")
    start: Optional[str] = Field(None, description="출발 기지명")


class LLMResponse(BaseModel):
    """LLM 응답 전체 구조"""
    action: Literal["UPDATE", "THREAT_ADD", "MISSION_PLAN", "EXPLAIN", "CHAT"] = Field(
        ...,
        description=(
            "UPDATE: 파라미터만 변경 | "
            "THREAT_ADD: 위협 추가 + 파라미터 변경 | "
            "MISSION_PLAN: 임무 유형 분류 및 순서 결정 | "
            "EXPLAIN: 교리/전술 설명 | "
            "CHAT: 일반 대화"
        )
    )
    update_params: MissionUpdateParams = Field(
        default_factory=MissionUpdateParams,
        description="변경할 파라미터 (없으면 모두 null)"
    )
    threats_to_add: List[ThreatInfo] = Field(
        default_factory=list,
        description="추가할 위협 목록 (THREAT_ADD 액션 시 사용)"
    )
    mission_sequence: List[str] = Field(
        default_factory=list,
        description="임무 수행 순서 (예: ['ISR', 'SEAD', 'STRIKE'])"
    )
    response_text: str = Field(..., description="사용자에게 보여줄 한국어 응답")
    reasoning: str = Field(..., description="판단 근거 - Why(왜), What(무엇을), How(어떻게) 형식으로 Korean으로 작성")
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="판단 신뢰도 0~1")


# ================================================================
# 시스템 프롬프트 - 교리 기반 군사 전문 참모
# ================================================================

SYSTEM_PROMPT_TEMPLATE = """
You are IMPS-AI, a military mission planning expert AI assistant for Korean Air Force operations.
You act as a tactical staff officer who understands military doctrine and translates commander's intent into mission parameters.

## DOCTRINE BASIS
- JP 3-30 Joint Air Operations: ROE, asset allocation, JPPA 7-step planning
- AFDP 3-03 Counterland: AI(Air Interdiction), CAS, SEAR mission types
- AFDP 5-0 Planning: COA development, constraints/restraints
- FMI 3-04.155 UAS Operations: ISR, surveillance, MUM-T teaming

## DOCTRINE EXCERPTS (loaded from local files)
{doctrine_context}

## MISSION TYPES (execute in this sequence when multiple apply)
1. ISR  - Intelligence/Surveillance/Reconnaissance (정보·감시·정찰) - ALWAYS FIRST
2. SEAD - Suppression of Enemy Air Defenses (적 방공망 제압) - BEFORE STRIKE
3. STRIKE - Air Interdiction Strike (공중 타격)
4. CAS - Close Air Support (근접항공지원)

## CURRENT MISSION STATE
{state_desc}

## AVAILABLE BASES (출발 가능 기지)
{airports}

## SAFETY MARGIN REFERENCE
- 최소(2km): 위험 감수, 속도 우선
- 표준(5km): 기본값
- 안전(15km): 안전 우선 (연료 여유 있을 때)
- 최대(30km): 최대 회피

## TACTICAL INTERPRETATION RULES
- "저고도" / "지형추종" / "레이더 회피" → enable_3d=true, algorithm="A* 3D"
- "안전하게" / "연료 여유" / "우회" → safety_margin_km 증가 (현재값 + 10~15)
- "빠르게" / "직선" → safety_margin_km 감소, algorithm="A*"
- "타격 후 복귀" / "RTB" → rtb=true
- 좌표 언급 시 → target_lat/target_lon 추출
- 위협 언급 시 (레이더, SAM, 방공망) → threats_to_add에 추가

## ACTION SELECTION RULES
- 위협 정보가 언급되면 → "THREAT_ADD"
- 파라미터만 바꾸면 되면 → "UPDATE"  
- 임무 유형/순서 질문이면 → "MISSION_PLAN"
- 교리/전술 설명 요청이면 → "EXPLAIN"
- 그 외 대화 → "CHAT"

## OUTPUT RULES
- response_text: ALWAYS in Korean, friendly and professional tone
- reasoning: ALWAYS in Korean, format "Why: ... / What: ... / How: ..."
- All coordinates must be within Korea bounds (lat 33~43, lon 124~132)
- Never invent coordinates that weren't mentioned
- If threat radius not mentioned, use defaults: SAM=30km, RADAR=80km

{path_info}
"""


# ================================================================
# LLMBrain 클래스
# ================================================================

class LLMBrain:
    # 클래스 레벨 캐시: 동일 명령어 반복 시 재사용
    _response_cache: dict = {}
    _cache_enabled: bool = True
    _available_model: str = None  # 주모델 생존 여부 캐시
    _doctrine_context_cache: Optional[str] = None
    _doctrine_rag: Optional[DoctrineRAG] = None

    def __init__(self, model_name: str = LLM_MODEL):
        self.model = model_name
        self.temperature = LLM_TEMPERATURE

    @classmethod
    def set_cache_enabled(cls, enabled: bool) -> None:
        cls._cache_enabled = bool(enabled)

    @classmethod
    def clear_cache(cls) -> None:
        cls._response_cache.clear()

    @classmethod
    def cache_size(cls) -> int:
        return len(cls._response_cache)

    def _extract_pdf_text(self, pdf_path: Path, max_pages: int = 8, max_chars: int = 1800) -> str:
        if not HAS_PDF_READER:
            return ""
        try:
            reader = PdfReader(str(pdf_path))
            pages = reader.pages[:max_pages]
            text_parts = []
            for p in pages:
                txt = p.extract_text() or ""
                if txt:
                    text_parts.append(txt.strip())
                if sum(len(t) for t in text_parts) >= max_chars:
                    break
            text = "\n".join(text_parts)
            return re.sub(r"\s+", " ", text).strip()[:max_chars]
        except Exception:
            return ""

    def _extract_text_file(self, path: Path, max_chars: int = 1800) -> str:
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
            return re.sub(r"\s+", " ", raw).strip()[:max_chars]
        except Exception:
            return ""

    def _load_doctrine_context(self, max_files: int = 5, max_total_chars: int = 5000) -> str:
        if LLMBrain._doctrine_context_cache is not None:
            return LLMBrain._doctrine_context_cache

        doctrine_dir = Path("data/doctrine")
        files = []
        if doctrine_dir.exists():
            for ext in ("*.md", "*.txt", "*.pdf"):
                files.extend(doctrine_dir.glob(ext))

        # fallback to project doctrine summary
        fallback_doc = Path("doctrine_basis.md")
        if fallback_doc.exists():
            files.append(fallback_doc)

        if not files:
            LLMBrain._doctrine_context_cache = "No local doctrine files found."
            return LLMBrain._doctrine_context_cache

        def _priority(p: Path) -> int:
            name = p.name.lower()
            score = 0
            for kw in ("jp3", "joint", "3-03", "afdp5", "fmi3-04-155", "dafman11-260"):
                if kw in name:
                    score += 10
            if p.suffix.lower() == ".md":
                score += 2
            return -score

        files = sorted(set(files), key=lambda p: (_priority(p), p.name.lower()))

        chunks = []
        total = 0
        for path in files:
            if len(chunks) >= max_files or total >= max_total_chars:
                break
            suffix = path.suffix.lower()
            if suffix == ".pdf":
                text = self._extract_pdf_text(path)
            else:
                text = self._extract_text_file(path)
            if not text:
                continue

            remaining = max_total_chars - total
            snippet = text[:remaining]
            if not snippet:
                break
            chunks.append(f"[{path.name}] {snippet}")
            total += len(snippet)

        if not chunks:
            chunks = ["Doctrine files exist, but no text was extracted (PDF parser unavailable or empty text)."]

        LLMBrain._doctrine_context_cache = "\n\n".join(chunks)
        return LLMBrain._doctrine_context_cache

    def _get_doctrine_context(self, query: str, max_total_chars: int = 5000) -> str:
        ctx, _ = self._get_doctrine_context_bundle(
            query=query,
            max_total_chars=max_total_chars,
            top_k=5,
        )
        return ctx

    def _get_doctrine_context_bundle(
        self,
        query: str,
        max_total_chars: int = 5000,
        top_k: int = 5,
    ):
        refs = []
        # Primary path: query-aware RAG retrieval
        try:
            if LLMBrain._doctrine_rag is None:
                LLMBrain._doctrine_rag = DoctrineRAG(
                    doctrine_dir="data/doctrine",
                    fallback_doc="doctrine_basis.md",
                )
            hits = LLMBrain._doctrine_rag.search(query=query, top_k=top_k)
            if hits:
                refs = [
                    {
                        "source": h.get("source", ""),
                        "page": int(h.get("page", 0) or 0),
                        "score": float(h.get("score", 0.0) or 0.0),
                    }
                    for h in hits
                ]
            rag_ctx = LLMBrain._doctrine_rag.format_context(
                query=query,
                top_k=top_k,
                max_chars=max_total_chars,
            )
            if rag_ctx and "No retrieved doctrine chunks." not in rag_ctx:
                return rag_ctx, refs
        except Exception:
            pass

        # Fallback path: static context load
        return self._load_doctrine_context(max_total_chars=max_total_chars), refs

    def _build_state_desc(self, current_state: dict) -> str:
        """현재 상태를 LLM이 읽기 좋은 텍스트로 변환"""
        return (
            f"출발기지: {current_state.get('start', '?')} | "
            f"목표: lat={current_state.get('target_lat', '?')}, lon={current_state.get('target_lon', '?')} "
            f"({current_state.get('target_name', '?')}) | "
            f"안전마진: {current_state.get('margin', '?')}km | "
            f"RTB: {current_state.get('rtb', '?')} | "
            f"알고리즘: {current_state.get('algorithm', 'A*')} | "
            f"3D모드: {current_state.get('enable_3d', False)}"
        )

    def _build_airports_desc(self) -> str:
        """공항 목록 텍스트 생성"""
        return ", ".join(AIRPORTS.keys())

    def _build_recent_chat_messages(self, chat_history: Optional[List[dict]], current_user_msg: str, max_turns: int = 8) -> List[dict]:
        """
        Convert mission chat history into Ollama message format.
        Keeps only recent turns to limit token usage.
        """
        if not chat_history:
            return []

        recent = chat_history[-max_turns:]
        messages: List[dict] = []
        for msg in recent:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role not in ("user", "assistant") or not content:
                continue
            messages.append({"role": role, "content": content})

        # streamlit_app adds current user message to history before LLM call.
        # Avoid sending the exact same user turn twice.
        if messages and messages[-1]["role"] == "user" and messages[-1]["content"] == current_user_msg.strip():
            messages = messages[:-1]

        return messages

    def _try_parse_response(self, raw_content: str) -> dict:
        """
        qwen3의 <think>...</think> 태그 처리 후 JSON 파싱
        qwen3:14b는 thinking mode로 <think> 블록을 먼저 출력할 수 있음
        """
        # <think>...</think> 제거
        content = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()

        # JSON 블록 추출 (```json ... ``` 형식 대응)
        json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
        if json_match:
            content = json_match.group(1)

        # Pydantic 파싱
        validated = LLMResponse.model_validate_json(content)
        return validated.model_dump()

    def _extract_lat_lon_from_text(self, text: str) -> Tuple[Optional[float], Optional[float]]:
        """
        Extract coordinates from free-form Korean/English text.
        Supports patterns like:
        - "위도 41.0, 경도 125.7"
        - "lat=41.0, lon=125.7"
        - "41.0/125.7"
        """
        if not text:
            return None, None

        lat = lon = None
        t = text.lower()

        m_lat = re.search(r"(?:위도|lat)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", t)
        m_lon = re.search(r"(?:경도|lon|lng)\s*[:=]?\s*([0-9]+(?:\.[0-9]+)?)", t)
        if m_lat:
            lat = float(m_lat.group(1))
        if m_lon:
            lon = float(m_lon.group(1))

        if lat is None or lon is None:
            m_pair = re.search(r"\b([3-4][0-9](?:\.[0-9]+)?)\s*/\s*([12][0-9]{2}(?:\.[0-9]+)?)\b", t)
            if m_pair:
                lat = lat if lat is not None else float(m_pair.group(1))
                lon = lon if lon is not None else float(m_pair.group(2))

        if lat is not None and not (33.0 <= lat <= 43.0):
            lat = None
        if lon is not None and not (124.0 <= lon <= 132.0):
            lon = None

        return lat, lon

    def _extract_margin_km_from_text(self, text: str) -> Optional[float]:
        """
        Extract safety margin km from text.
        Examples:
        - "안전마진 15km"
        - "마진을 12.5 km로"
        - "safety margin 10km"
        """
        if not text:
            return None

        t = text.lower()

        # Prefer numbers near margin-related keywords.
        m = re.search(
            r"(?:안전\s*마진|안전마진|마진|safety\s*margin)[^0-9]{0,16}([0-9]+(?:\.[0-9]+)?)\s*km",
            t,
        )
        if not m:
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*km[^a-zA-Z0-9가-힣]{0,8}(?:안전\s*마진|안전마진|마진)", t)
        if not m:
            return None

        val = float(m.group(1))
        if 0.0 <= val <= 50.0:
            return val
        return None

    def _normalize_result(self, result: dict, user_msg: str, current_state: dict) -> dict:
        """
        Make model output safer and consistent with UI updates.
        - If text contains coordinates but update_params is empty, backfill target_lat/lon.
        - If user asked north/south shift but model omitted coordinates, apply small deterministic shift.
        - If any update field exists, coerce action to UPDATE unless THREAT_ADD/MISSION_PLAN.
        """
        update = result.get("update_params") or {}
        action = result.get("action", "CHAT")

        # 1) backfill coordinates from model response text
        t_lat, t_lon = self._extract_lat_lon_from_text(result.get("response_text", ""))
        if t_lat is not None and update.get("target_lat") is None:
            update["target_lat"] = t_lat
        if t_lon is not None and update.get("target_lon") is None:
            update["target_lon"] = t_lon

        # 2) deterministic directional fallback when user asks "north/up" etc.
        msg = (user_msg or "").lower()
        cur_lat = float(current_state.get("target_lat", 39.0))
        directional_requested = any(k in msg for k in ["북쪽", "위쪽", "올려", "상향", "north"])
        if directional_requested and update.get("target_lat") is None:
            update["target_lat"] = min(43.0, round(cur_lat + 1.0, 4))

        south_requested = any(k in msg for k in ["남쪽", "아래쪽", "내려", "하향", "south"])
        if south_requested and update.get("target_lat") is None:
            update["target_lat"] = max(33.0, round(cur_lat - 1.0, 4))

        # 3) if update fields exist, ensure action is UPDATE (unless stronger action already chosen)
        # margin normalization
        m_resp = self._extract_margin_km_from_text(result.get("response_text", ""))
        m_user = self._extract_margin_km_from_text(user_msg or "")
        if update.get("safety_margin_km") is None:
            if m_resp is not None:
                update["safety_margin_km"] = m_resp
            elif m_user is not None:
                update["safety_margin_km"] = m_user

        # directional request with no explicit value -> deterministic step
        if update.get("safety_margin_km") is None:
            if any(k in msg for k in ["안전", "우회", "회피", "위험"]):
                try:
                    cur_margin = float(current_state.get("margin", 5.0))
                except Exception:
                    cur_margin = 5.0
                update["safety_margin_km"] = min(50.0, round(cur_margin + 10.0, 2))

        # if update fields exist, ensure action is UPDATE (unless stronger action already chosen)
        has_update = any(v is not None for v in update.values())
        if has_update and action not in ("THREAT_ADD", "MISSION_PLAN"):
            result["action"] = "UPDATE"

        result["update_params"] = update
        return result

    def parse_tactical_command(
        self,
        user_msg: str,
        current_state: dict,
        path_analysis: dict = None,
        chat_history: Optional[List[dict]] = None,
        threat_signature: Optional[str] = None
    ) -> dict:
        """
        자연어 전술 명령 파싱 → 구조화된 응답 반환

        Returns:
            dict with keys:
                action, update_params, threats_to_add,
                mission_sequence, response_text, reasoning, confidence
        """
        import hashlib, json as _json

        # ── 간단 응답 캐시 (동일 명령+상태 조합은 LLM 재호출 스킵) ──
        history_sig = []
        if chat_history:
            for m in chat_history[-6:]:
                history_sig.append({
                    "role": m.get("role"),
                    "content": (m.get("content") or "")[:120],
                })

        _state_key = _json.dumps({
            'msg':   user_msg.strip().lower(),
            'state': {k: current_state.get(k) for k in
                      ('target_lat','target_lon','start','algorithm','margin','enable_3d','rtb')},
            'history': history_sig,
            'threat_sig': threat_signature or "",
        }, ensure_ascii=False, sort_keys=True)
        _cache_key = hashlib.md5(_state_key.encode()).hexdigest()
        if LLMBrain._cache_enabled and _cache_key in LLMBrain._response_cache:
            cached = LLMBrain._response_cache[_cache_key].copy()
            cached['response_text'] = '💾 ' + cached.get('response_text','')  # 캐시 표시
            cached['_model_used']   = 'cache'
            cached['_cache_hit'] = True
            return cached
        state_desc = self._build_state_desc(current_state)
        airports_desc = self._build_airports_desc()

        path_info = ""
        if path_analysis:
            path_info = (
                f"## CURRENT PATH ANALYSIS\n"
                f"Max Risk: {path_analysis.get('max_risk', 0):.2f} | "
                f"Waypoints: {path_analysis.get('waypoint_count', 0)} | "
                f"Distance: {path_analysis.get('total_distance_km', 0):.1f}km"
            )

        doctrine_context, doctrine_refs = self._get_doctrine_context_bundle(user_msg)

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            state_desc=state_desc,
            airports=airports_desc,
            path_info=path_info,
            doctrine_context=doctrine_context
        )

        history_messages = self._build_recent_chat_messages(chat_history, user_msg)

        # 모델 순서를 동적으로 결정 (ollamatags로 사용 가능한 모델 확인)
        def _get_model_list():
            """ollama에서 사용 가능한 모델 리스트 반환"""
            try:
                models_resp = ollama.list()
                return [m['name'] for m in models_resp.get('models', [])]
            except Exception:
                return []

        available_models = _get_model_list()
        # 우선순위: 설정된 주모델(qwen3) → 작은 빠른 모델(선택) → 폴백
        priority_models = [self.model]
        if available_models:
            fast_models = [m for m in available_models
                          if any(tag in m for tag in ['3b','1b','7b','8b','mistral','phi3','gemma2:2b'])]
            if fast_models:
                priority_models.extend(fast_models[:1])
        priority_models.append(LLM_MODEL_FALLBACK)
        # deduplicate while preserving order
        models_to_try = list(dict.fromkeys(priority_models))

        # 모델 순서대로 시도 (빠른 모델 우선 → qwen3:14b → fallback)
        for model in models_to_try:
            try:
                response = ollama.chat(
                    model=model,
                    messages=(
                        [{'role': 'system', 'content': system_prompt}]
                        + history_messages
                        + [{'role': 'user', 'content': user_msg}]
                    ),
                    format=LLMResponse.model_json_schema(),
                    options={
                        'temperature': self.temperature,
                        'num_predict': 512,   # 중요: 2048→2048대비 4배 빠름 (구조화 JSON만 필요하주어 512으로 충분)
                        'num_ctx':    2048,   # 컨텍스트 토큰 제한 (4096대비 2배 빠름)
                    }
                )

                raw_content = response['message']['content']
                result = self._try_parse_response(raw_content)
                result = self._normalize_result(result, user_msg, current_state)
                result["_doctrine_refs"] = doctrine_refs

                # 공항 유효성 검증
                wp = result['update_params'].get('waypoint_name')
                if wp and wp not in AIRPORTS:
                    result['update_params']['waypoint_name'] = None
                    result['response_text'] += f" (⚠️ '{wp}' 기지 없음)"

                start = result['update_params'].get('start')
                if start and start not in AIRPORTS:
                    result['update_params']['start'] = None
                    result['response_text'] += f" (⚠️ '{start}' 기지 없음)"

                # 위협 기본 반경 보정
                for threat in result.get('threats_to_add', []):
                    if threat.get('radius_km') is None:
                        threat['radius_km'] = THREAT_DEFAULT_RADIUS.get(
                            threat.get('type', 'SAM'), 30.0
                        )

                result['_model_used'] = model
                result['_cache_hit'] = False
                # 성공 응답 캐시 저장 (최대 50개, 오래된 것 제거)
                if LLMBrain._cache_enabled:
                    if len(LLMBrain._response_cache) >= 50:
                        oldest = next(iter(LLMBrain._response_cache))
                        del LLMBrain._response_cache[oldest]
                    LLMBrain._response_cache[_cache_key] = result.copy()
                return result

            except Exception as e:
                if model == LLM_MODEL_FALLBACK:
                    # 최종 폴백 응답
                    return self._fallback_response(str(e))
                continue

    def _fallback_response(self, error_msg: str) -> dict:
        """모든 모델 실패 시 안전한 기본 응답"""
        return {
            "action": "CHAT",
            "update_params": {},
            "threats_to_add": [],
            "mission_sequence": [],
            "response_text": "⚠️ AI 분석 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            "reasoning": f"시스템 오류: {error_msg}",
            "confidence": 0.0,
            "_model_used": "fallback",
            "_cache_hit": False,
            "_doctrine_refs": [],
        }
