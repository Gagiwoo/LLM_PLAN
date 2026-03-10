"""
Fuel-aware planning helpers.

The model intentionally stays simple and transparent for demo/research use:
- F-16 baseline is used as the reference scale.
- Fuel state and air-refuel events are converted into an "endurance factor".
- Endurance factor biases threat-avoidance strength in A* cost design.
"""

from modules.config import FUEL_POLICY


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def fuel_endurance_factor(fuel_state: float, refuel_count: int) -> float:
    """
    Convert mission fuel settings into a normalized endurance factor.

    fuel_state: 0.2~1.0 (UI slider; 1.0 means full planned fuel at takeoff)
    refuel_count: number of AR events (0..N)
    """
    fs = _clamp(fuel_state, 0.05, 1.2)
    max_refuel = int(FUEL_POLICY.get("max_refuel_events", 2))
    rc = max(0, min(int(refuel_count), max_refuel))
    gain = float(FUEL_POLICY.get("refuel_gain_per_event", 0.45))
    return _clamp(fs * (1.0 + rc * gain), 0.10, 2.50)


def fuel_risk_modifiers(fuel_state: float, refuel_count: int) -> tuple[float, float]:
    """
    Return (risk_penalty_scale, threshold_bias).

    - risk_penalty_scale multiplies continuous threat penalty.
      low fuel -> smaller penalty -> planner accepts shorter/riskier path.
      high fuel -> larger penalty -> planner prefers safer detour.
    - threshold_bias shifts the hard risk block threshold.
      low fuel -> positive bias (less strict).
      high fuel -> negative bias (more strict).
    """
    endu = fuel_endurance_factor(fuel_state, refuel_count)
    norm = _clamp((endu - 0.20) / 1.00, 0.0, 1.0)

    # 0.02~1.32 (low fuel strongly prioritizes short path)
    risk_penalty_scale = 0.02 + 1.30 * norm

    # Aggressive bias for visible behavior:
    # low fuel -> much less strict blocking, high fuel -> stricter blocking.
    threshold_bias = 0.45 * (1.0 - norm) - 0.12 * max(0.0, endu - 1.0)
    threshold_bias = _clamp(threshold_bias, -0.14, 0.48)
    return risk_penalty_scale, threshold_bias


def estimate_effective_range_km(base_range_km: float, fuel_state: float, refuel_count: int) -> float:
    return float(base_range_km) * fuel_endurance_factor(fuel_state, refuel_count)
