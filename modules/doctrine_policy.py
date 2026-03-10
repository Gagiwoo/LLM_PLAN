"""
Doctrine-to-policy bridge.

Builds structured planning constraints from doctrine retrieval so they can be
applied directly to optimizer constraints.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from modules.config import MISSION_ASSET_REQUIREMENTS, MUMT_RATIO
from modules.doctrine_rag import DoctrineRAG


DOCTRINE_ORDER = {"ISR": 0, "SEAD": 1, "STRIKE": 2, "CAS": 3}


@dataclass
class DoctrinePolicy:
    mission_sequence: List[str]
    min_fighter: int = 0
    min_recon_uav: int = 0
    min_attack_uav: int = 0
    mumt_ratio: float = MUMT_RATIO
    utilization_rate: float = 0.65
    max_recon_to_strike_ratio: Optional[float] = None
    recon_bias_allowance: int = 1
    safety_margin_floor_km: float = 0.0
    refs: List[Dict[str, object]] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)

    def to_optimizer_dict(self) -> Dict[str, object]:
        return {
            "mission_sequence": list(self.mission_sequence),
            "min_fighter": int(self.min_fighter),
            "min_recon_uav": int(self.min_recon_uav),
            "min_attack_uav": int(self.min_attack_uav),
            "mumt_ratio": float(self.mumt_ratio),
            "utilization_rate": float(self.utilization_rate),
            "max_recon_to_strike_ratio": (
                None
                if self.max_recon_to_strike_ratio is None
                else float(self.max_recon_to_strike_ratio)
            ),
            "recon_bias_allowance": int(self.recon_bias_allowance),
            "safety_margin_floor_km": float(self.safety_margin_floor_km),
            "refs": list(self.refs),
            "rationale": list(self.rationale),
        }


class DoctrinePolicyEngine:
    def __init__(self, doctrine_dir: str = "data/doctrine", fallback_doc: str = "doctrine_basis.md") -> None:
        self.rag = DoctrineRAG(
            doctrine_dir=doctrine_dir,
            fallback_doc=fallback_doc,
            max_pdf_pages=None,
        )

    def _normalize_mission_sequence(self, mission_types: List[str]) -> List[str]:
        deduped = []
        seen = set()
        for m in mission_types:
            if m not in seen:
                deduped.append(m)
                seen.add(m)
        seq = sorted(deduped, key=lambda x: DOCTRINE_ORDER.get(x, 99))
        if "STRIKE" in seq and "SEAD" not in seq:
            seq.insert(seq.index("STRIKE"), "SEAD")
        return seq

    def _extract_ratio_from_hits(self, hits: List[Dict[str, object]]) -> Optional[float]:
        # Accept "1:2", "1 : 2", "유인 1 무인 2", "1대당 2대" style.
        patterns = [
            r"1\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)",
            r"유인\s*1\s*[:：]?\s*무인\s*([0-9]+(?:\.[0-9]+)?)",
            r"1대당\s*([0-9]+(?:\.[0-9]+)?)\s*대",
        ]
        for h in hits:
            text = str(h.get("text", ""))
            for pat in patterns:
                m = re.search(pat, text, flags=re.IGNORECASE)
                if not m:
                    continue
                try:
                    ratio = float(m.group(1))
                    if 1.5 <= ratio <= 6.0:
                        return ratio
                except Exception:
                    continue
        return None

    def _extract_margin_floor_from_hits(self, hits: List[Dict[str, object]]) -> Optional[float]:
        patterns = [
            r"(?:안전\s*마진|안전거리|회피거리)\s*([0-9]+(?:\.[0-9]+)?)\s*km",
            r"([0-9]+(?:\.[0-9]+)?)\s*km\s*(?:이상|최소).{0,8}(?:간격|거리|마진)",
        ]
        for h in hits:
            text = str(h.get("text", ""))
            for pat in patterns:
                m = re.search(pat, text, flags=re.IGNORECASE)
                if not m:
                    continue
                try:
                    value = float(m.group(1))
                    if 0.0 <= value <= 50.0:
                        return value
                except Exception:
                    continue
        return None

    def _build_min_requirements(self, mission_sequence: List[str]) -> Dict[str, int]:
        req_f = req_r = req_k = 0
        for m in mission_sequence:
            reqs = MISSION_ASSET_REQUIREMENTS.get(m, {})
            req_f = max(req_f, int(reqs.get("fighter", 0)))
            req_r = max(req_r, int(reqs.get("recon_uav", 0)))
            req_k = max(req_k, int(reqs.get("attack_uav", 0)))
        return {
            "min_fighter": req_f,
            "min_recon_uav": req_r,
            "min_attack_uav": req_k,
        }

    def build_policy(
        self,
        mission_types: List[str],
        threats: Optional[List[Dict[str, object]]] = None,
        current_margin_km: float = 5.0,
    ) -> DoctrinePolicy:
        seq = self._normalize_mission_sequence(mission_types or [])
        reqs = self._build_min_requirements(seq)

        query = " ".join(seq) if seq else "ISR SEAD STRIKE CAS MUM-T Lead Wingman"
        hits = self.rag.search(query=query, top_k=8, min_score=0.01)
        refs = [
            {
                "source": h.get("source", ""),
                "page": int(h.get("page", 0) or 0),
                "score": float(h.get("score", 0.0) or 0.0),
            }
            for h in hits
        ]

        ratio = self._extract_ratio_from_hits(hits) or float(MUMT_RATIO)
        margin_floor = self._extract_margin_floor_from_hits(hits)
        if margin_floor is None:
            margin_floor = max(0.0, float(current_margin_km))

        threats = threats or []
        n_weapon_threat = sum(1 for t in threats if t.get("type") in ("SAM", "RADAR"))
        strike_pkg = ("SEAD" in seq) or ("STRIKE" in seq)

        # Keep utilization pressure, but reduce recon-heavy fill pattern.
        utilization_rate = 0.65 if strike_pkg else 0.55
        max_recon_to_strike_ratio: Optional[float] = 1.5 if strike_pkg else None

        # In denser threat environments, floor margin should not shrink.
        if n_weapon_threat >= 4:
            margin_floor = max(margin_floor, 8.0)
        elif n_weapon_threat >= 2:
            margin_floor = max(margin_floor, 5.0)

        rationale = []
        if seq:
            rationale.append(f"임무 순서 교리 정규화: {' -> '.join(seq)}")
        if "SEAD" in seq and "STRIKE" in seq:
            rationale.append("SEAD/STRIKE 패키지에서 정찰 편중 제한을 적용합니다.")
        rationale.append(f"MUM-T 비율 기준: 유인 1 : 무인 {ratio:.2f}")
        rationale.append(f"안전 마진 하한: {margin_floor:.1f}km")

        return DoctrinePolicy(
            mission_sequence=seq,
            min_fighter=reqs["min_fighter"],
            min_recon_uav=reqs["min_recon_uav"],
            min_attack_uav=reqs["min_attack_uav"],
            mumt_ratio=ratio,
            utilization_rate=utilization_rate,
            max_recon_to_strike_ratio=max_recon_to_strike_ratio,
            recon_bias_allowance=1,
            safety_margin_floor_km=margin_floor,
            refs=refs[:5],
            rationale=rationale,
        )
