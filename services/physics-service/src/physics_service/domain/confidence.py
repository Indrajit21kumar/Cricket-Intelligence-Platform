"""Confidence combination for the ESTIMATED dynamics (M11 §13, Step 4).

Every estimate MUST carry a confidence (the trust doctrine's hard rule), and the
confidence must be honest about *why* an estimate is soft. §13 names three
sources of uncertainty, and this module combines them multiplicatively — each a
factor in [0, 1], so any one weak link pulls the whole estimate down:

1. **Model uncertainty** — how far the model reaches from what the camera saw.
   A per-quantity base: momentum (mass x measured velocity) is firm; ground
   reaction force and ball-exit velocity are the furthest reaches and the
   lowest base, per §13's "highest-uncertainty estimates".
2. **Anthropometric-mass uncertainty** — a dynamic quantity built on an inferred
   body mass is softer than one built on a supplied mass (Step 3).
3. **Input quality** — the confidence of the measured kinematics the estimate is
   built on (which already carries M10's spatial/depth softening), plus a
   penalty when the report is provisional.

The result is a property OF the estimate, so nothing downstream can read a
low-confidence figure as a firm one.
"""

from __future__ import annotations

from physics_service.domain.anthropometry import SegmentModel
from physics_service.domain.quantities import PH_06, PH_07, PH_08, PH_09, PH_10, PH_11

#: Per-quantity model base confidence — how well the model is grounded. GRF and
#: ball-exit are the highest-uncertainty estimates (§13), so the lowest base.
MODEL_BASE: dict[str, float] = {
    PH_06: 0.85,  # momentum — mass x measured velocity, most direct
    PH_07: 0.72,  # torque — modelled segment dynamics
    PH_08: 0.72,  # kinetic energy — modelled kinetic chain
    PH_09: 0.45,  # ground reaction force — no force plate (§13)
    PH_10: 0.40,  # ball-exit velocity — the furthest reach (§13)
    PH_11: 0.55,  # sweet-spot efficiency — modelled contact quality
}

#: Multiplier applied when the source report/measurement is provisional.
PROVISIONAL_PENALTY = 0.6


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def combine_confidence(
    quantity_id: str,
    *,
    input_confidence: float | None,
    mass_model: SegmentModel | None = None,
    mass_dependent: bool = True,
    provisional: bool = False,
) -> float:
    """Combine model, mass, and input uncertainty into one [0,1] confidence."""
    factor = MODEL_BASE[quantity_id] * _clamp01(input_confidence or 0.0)
    if mass_dependent and mass_model is not None:
        factor *= mass_model.mass_confidence
    if provisional:
        factor *= PROVISIONAL_PENALTY
    return round(_clamp01(factor), 3)
