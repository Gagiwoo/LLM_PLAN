"""
Rule-based mission validator.

References:
- AFDP5-0 COA Analysis & Wargaming
- JP3-30 ACO / MAAP / ROE
- FMI3-04.155
- DAFMAN11-260
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from modules.config import (
    ASSET_PERFORMANCE,
    MIN_ALTITUDE_AGL,
    MISSION_ASSET_REQUIREMENTS,
    MUMT_RATIO,
)
from modules.xai_utils import XAIUtils


@dataclass
class ValidationIssue:
    rule_id: str
    severity: str  # ERROR / WARNING / INFO
    asset_id: Optional[str]
    message: str
    doctrine_ref: str
    suggestion: str = ""

    @property
    def icon(self) -> str:
        return {"ERROR": "E", "WARNING": "W", "INFO": "I"}.get(self.severity, "I")


@dataclass
class ValidationReport:
    is_valid: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    checked_rules: List[str] = field(default_factory=list)
    validate_time_ms: float = 0.0

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARNING")

    def summary(self) -> str:
        if self.is_valid:
            return f"validation passed | warnings {self.warning_count}"
        return f"validation failed | errors {self.error_count} | warnings {self.warning_count}"

    def to_dict(self) -> dict:
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "issues": [
                {
                    "rule_id": i.rule_id,
                    "severity": i.severity,
                    "asset_id": i.asset_id,
                    "message": i.message,
                    "doctrine_ref": i.doctrine_ref,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
            "checked_rules": self.checked_rules,
            "validate_time_ms": self.validate_time_ms,
        }


def _dist_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = lat1 - lat2
    dlon = lon1 - lon2
    return math.sqrt(dlat ** 2 + dlon ** 2) * 111.0


def _path_length_km(path: List) -> float:
    total = 0.0
    for i in range(1, len(path)):
        total += _dist_km(path[i - 1][0], path[i - 1][1], path[i][0], path[i][1])
    return total


def check_nfz_violation(asset_id: str, path: List, threats: List[Dict]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    nfz_list = [t for t in threats if t.get("type") == "NFZ"]
    if not nfz_list or not path:
        return issues

    for point in path[::5]:
        lat, lon = point[0], point[1]
        for nfz in nfz_list:
            if (
                nfz.get("lat_min", 99.0) <= lat <= nfz.get("lat_max", -99.0)
                and nfz.get("lon_min", 999.0) <= lon <= nfz.get("lon_max", -999.0)
            ):
                issues.append(
                    ValidationIssue(
                        rule_id="NFZ_VIOLATION",
                        severity="ERROR",
                        asset_id=asset_id,
                        message=f"[{asset_id}] NFZ violation: {nfz.get('name', 'NFZ')}",
                        doctrine_ref="JP3-30 ACO",
                        suggestion="Replan route to avoid NFZ.",
                    )
                )
                return issues
    return issues


def check_threat_penetration(
    asset_id: str,
    asset_type: str,
    path: List,
    threats: List[Dict],
    margin_km: float,
    terrain_loader=None,
) -> List[ValidationIssue]:
    """
    Validator is aligned with planner:
    - planner blocks nodes with risk >= 0.5
    - validator flags same threshold as penetration
    """
    issues: List[ValidationIssue] = []
    active_threats = [t for t in threats if t.get("type") in ("SAM", "RADAR") and t.get("lat") is not None]
    if not active_threats or not path:
        return issues

    for point in path[::5]:
        lat, lon = point[0], point[1]
        if len(point) >= 3:
            alt_msl = float(point[2])
        elif terrain_loader:
            try:
                alt_msl = float(terrain_loader.get_elevation(lat, lon)) + 500.0
            except Exception:
                alt_msl = 500.0
        else:
            alt_msl = 500.0

        risk = XAIUtils.calculate_risk_score(
            lat=lat,
            lon=lon,
            threats=active_threats,
            margin=margin_km,
            terrain_loader=terrain_loader,
            target_alt=alt_msl,
        )
        if risk >= 0.5:
            sev = "ERROR" if risk >= 0.7 else "WARNING"
            issues.append(
                ValidationIssue(
                    rule_id="THREAT_PENETRATION",
                    severity=sev,
                    asset_id=asset_id,
                    message=f"[{asset_id}] threat-dominant segment (risk={risk:.2f}, threshold=0.50)",
                    doctrine_ref="JP3-30 ROE / FMI3-04.155",
                    suggestion=f"Increase safety margin above {margin_km + 5:.0f}km or reroute with terrain masking.",
                )
            )
            return issues
    return issues


def check_min_altitude(asset_id: str, path: List, min_agl: float = MIN_ALTITUDE_AGL) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not path or len(path[0]) < 3:
        return issues

    violations = [p for p in path if p[2] < min_agl]
    if violations:
        min_alt = min(p[2] for p in violations)
        issues.append(
            ValidationIssue(
                rule_id="MIN_ALTITUDE",
                severity="WARNING",
                asset_id=asset_id,
                message=f"[{asset_id}] minimum altitude violation (min={min_alt:.0f}m, criterion={min_agl:.0f}m)",
                doctrine_ref="FMI3-04.155",
                suggestion="Tune 3D min-altitude settings.",
            )
        )
    return issues


def check_asset_collision(
    formation_paths: Dict[str, List],
    min_sep_km: float = 2.0,
    min_vertical_sep_m: float = 300.0,
) -> List[ValidationIssue]:
    """
    Time-aligned separation check to reduce false positives.
    - compares aligned samples instead of all-pairs nearest points
    - considers vertical separation for 3D paths
    """
    issues: List[ValidationIssue] = []
    asset_ids = list(formation_paths.keys())

    def _sample(path: List, n: int = 30) -> List:
        if not path:
            return []
        if len(path) <= n:
            return path
        if n <= 1:
            return [path[0]]
        idxs = [int(round(i * (len(path) - 1) / (n - 1))) for i in range(n)]
        return [path[i] for i in idxs]

    for i in range(len(asset_ids)):
        for j in range(i + 1, len(asset_ids)):
            id_a = asset_ids[i]
            id_b = asset_ids[j]
            path_a = formation_paths[id_a]
            path_b = formation_paths[id_b]
            if not path_a or not path_b:
                continue

            a = _sample(path_a, 30)
            b = _sample(path_b, 30)
            n = min(len(a), len(b))
            if n < 3:
                continue

            min_dist = float("inf")
            for k in range(1, n - 1):  # ignore endpoints near common departure/arrival
                pa = a[k]
                pb = b[k]
                d2d = _dist_km(pa[0], pa[1], pb[0], pb[1])
                if len(pa) >= 3 and len(pb) >= 3:
                    if abs(float(pa[2]) - float(pb[2])) >= min_vertical_sep_m:
                        continue
                min_dist = min(min_dist, d2d)

            if min_dist < min_sep_km:
                issues.append(
                    ValidationIssue(
                        rule_id="ASSET_COLLISION",
                        severity="WARNING",
                        asset_id=f"{id_a}/{id_b}",
                        message=(
                            f"[{id_a}] <-> [{id_b}] closest distance {min_dist:.1f}km "
                            f"(criterion {min_sep_km:.1f}km, vertical {min_vertical_sep_m:.0f}m)"
                        ),
                        doctrine_ref="FMI3-04.155",
                        suggestion="Adjust timing or altitude deliction between assets.",
                    )
                )
    return issues


def check_mission_sequence(mission_sequence: List[str]) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if not mission_sequence:
        return issues

    doctrine_order = {"ISR": 0, "SEAD": 1, "STRIKE": 2, "CAS": 3}
    for i in range(len(mission_sequence) - 1):
        curr = mission_sequence[i]
        nxt = mission_sequence[i + 1]
        if doctrine_order.get(curr, 99) > doctrine_order.get(nxt, 99):
            issues.append(
                ValidationIssue(
                    rule_id="MISSION_SEQUENCE",
                    severity="WARNING",
                    asset_id=None,
                    message=f"mission sequence out of doctrine order: {curr} -> {nxt}",
                    doctrine_ref="JP3-30 MAAP",
                    suggestion=f"recommended order: {' -> '.join(sorted(mission_sequence, key=lambda x: doctrine_order.get(x, 99)))}",
                )
            )

    if "STRIKE" in mission_sequence and "SEAD" not in mission_sequence:
        issues.append(
            ValidationIssue(
                rule_id="SEAD_REQUIRED",
                severity="WARNING",
                asset_id=None,
                message="STRIKE requested without SEAD support",
                doctrine_ref="JP3-30 MAAP",
                suggestion="add SEAD or justify low-threat window.",
            )
        )
    return issues


def check_range_limit(asset_id: str, asset_type: str, path_in: List, path_out: List) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    max_range = ASSET_PERFORMANCE.get(asset_type, {}).get("range_km", 999.0)
    total_dist = _path_length_km(path_in) + _path_length_km(path_out)
    if total_dist > max_range * 0.9:
        sev = "ERROR" if total_dist > max_range else "WARNING"
        issues.append(
            ValidationIssue(
                rule_id="RANGE_EXCEEDED",
                severity=sev,
                asset_id=asset_id,
                message=f"[{asset_id}] route distance {total_dist:.0f}km / max {max_range:.0f}km",
                doctrine_ref="DAFMAN11-260",
                suggestion="insert waypoint/air-refuel or use longer-range asset.",
            )
        )
    return issues


def check_mumt_ratio(n_fighter: int, n_uav_total: int) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    if n_fighter <= 0:
        return issues
    ratio = n_uav_total / n_fighter
    if ratio < MUMT_RATIO:
        issues.append(
            ValidationIssue(
                rule_id="MUMT_RATIO",
                severity="WARNING",
                asset_id=None,
                message=f"MUM-T ratio low: fighter {n_fighter}, uav {n_uav_total}, current 1:{ratio:.1f}",
                doctrine_ref="FMI3-04.155",
                suggestion=f"add at least {max(0, int(n_fighter * MUMT_RATIO - n_uav_total))} UAV.",
            )
        )
    return issues


class MissionValidator:
    def validate(
        self,
        formation_result=None,
        formation_paths: Dict = None,
        threats: List[Dict] = None,
        mission_sequence: List[str] = None,
        margin_km: float = 5.0,
        terrain_loader=None,
    ) -> ValidationReport:
        import time as _time

        start_t = _time.time()
        report = ValidationReport()
        threats = threats or []
        formation_paths = formation_paths or {}
        mission_sequence = mission_sequence or []

        report.checked_rules.append("MISSION_SEQUENCE")
        report.issues.extend(check_mission_sequence(mission_sequence))

        if formation_result:
            report.checked_rules.append("MUMT_RATIO")
            n_uav = formation_result.n_recon_uav + formation_result.n_attack_uav
            report.issues.extend(check_mumt_ratio(formation_result.n_fighter, n_uav))

        if formation_result and formation_paths:
            for asset in (formation_result.assets or []):
                path_in = formation_paths.get(asset.asset_id, {}).get("in", [])
                path_out = formation_paths.get(asset.asset_id, {}).get("out", [])
                full_path = path_in + path_out

                report.checked_rules.append(f"NFZ_{asset.asset_id}")
                report.issues.extend(check_nfz_violation(asset.asset_id, full_path, threats))

                report.checked_rules.append(f"THREAT_{asset.asset_id}")
                report.issues.extend(
                    check_threat_penetration(
                        asset.asset_id,
                        asset.asset_type,
                        full_path,
                        threats,
                        margin_km,
                        terrain_loader,
                    )
                )

                report.checked_rules.append(f"ALT_{asset.asset_id}")
                report.issues.extend(check_min_altitude(asset.asset_id, full_path))

                report.checked_rules.append(f"RANGE_{asset.asset_id}")
                report.issues.extend(check_range_limit(asset.asset_id, asset.asset_type, path_in, path_out))

        if len(formation_paths) > 1:
            report.checked_rules.append("ASSET_COLLISION")
            merged_paths = {
                aid: (v.get("in", []) + v.get("out", []))
                for aid, v in formation_paths.items()
            }
            report.issues.extend(check_asset_collision(merged_paths))

        report.is_valid = report.error_count == 0
        report.validate_time_ms = round((_time.time() - start_t) * 1000, 2)
        return report
