"""The physics quantity catalogue - the vocabulary M11 speaks (M11 §5, Book 4 Ch. 4).

Eleven canonical physics quantities (PH-01..PH-11), each with a stable ID, a
unit, a *provenance class* (MEASURED or ESTIMATED), and a *quantity class* that
groups it for the accuracy gate (Step 8). The provenance split is the whole
point of the module and is a property of the quantity ID, so it cannot drift per
call site:

- **PH-01..PH-05 are MEASURED.** They are derivable from what the camera saw
  (they are functions of already-measured M10 kinematics), so the trust doctrine
  lets them be presented as measurements.
- **PH-06..PH-11 are ESTIMATED.** A phone cannot measure force, energy, or
  ball-exit velocity; these are inferred through models, so every one MUST carry
  a confidence and MUST NOT be rendered as a measurement (§13, AC-M11-03).

``PH-10`` (impact / ball-exit) additionally ``needs_bat_ball``: it can only be
estimated when the report carries a usable bat/contact, otherwise it is omitted
or very-low-confidence, never fabricated (FR-M11-07 / AC-M11-05).

:class:`PhysicsQuantity` is the runtime value: the number plus how it was
obtained and how much to trust it. A quantity can be omitted (value ``None`` +
an ``omitted_reason``) — an honest silence, never a guess.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# --- provenance (Book 0 §8 trust doctrine) ---
PROVENANCE_MEASURED = "measured"
PROVENANCE_ESTIMATED = "estimated"

# --- quantity classes (group a quantity for the Step 8 accuracy bands) ---
CLASS_LINEAR_VELOCITY = "linear_velocity"  # m/s
CLASS_ANGULAR_VELOCITY = "angular_velocity"  # deg/s
CLASS_ANGLE = "angle"  # deg
CLASS_DISTANCE = "distance"  # cm
CLASS_TIMING = "timing"  # ms
CLASS_MOMENTUM = "momentum"  # kg.m/s
CLASS_TORQUE = "torque"  # N.m
CLASS_ENERGY = "energy"  # J
CLASS_FORCE = "force"  # N
CLASS_RATIO = "ratio"  # unitless

# --- units ---
UNIT_MPS = "m_per_s"
UNIT_DEG_PER_S = "deg_per_s"
UNIT_DEG = "deg"
UNIT_CM = "cm"
UNIT_MS = "ms"
UNIT_KG_MPS = "kg_m_per_s"
UNIT_NM = "N_m"
UNIT_JOULE = "J"
UNIT_NEWTON = "N"
UNIT_RATIO = "ratio"


@dataclass(frozen=True, slots=True)
class PhysicsQuantityDef:
    """Static definition of one PH quantity."""

    id: str
    name: str
    unit: str
    provenance: str
    quantity_class: str
    #: Plausible range [lo, hi]; values outside are FLAGGED for review, never
    #: rejected (Step 6). None where a hard range is ill-defined.
    expected_range: tuple[float, float] | None = None
    #: True when the quantity needs a usable bat/contact from the report to be
    #: estimated at all (PH-10). Absent -> omit or very-low-confidence.
    needs_bat_ball: bool = False

    @property
    def is_estimated(self) -> bool:
        return self.provenance == PROVENANCE_ESTIMATED


PH_01 = "PH-01"
PH_02 = "PH-02"
PH_03 = "PH-03"
PH_04 = "PH-04"
PH_05 = "PH-05"
PH_06 = "PH-06"
PH_07 = "PH-07"
PH_08 = "PH-08"
PH_09 = "PH-09"
PH_10 = "PH-10"
PH_11 = "PH-11"

CATALOGUE: dict[str, PhysicsQuantityDef] = {
    # --- MEASURED kinematics (PH-01..PH-05) ---
    PH_01: PhysicsQuantityDef(
        PH_01,
        "bat_hand_speed",
        UNIT_MPS,
        PROVENANCE_MEASURED,
        CLASS_LINEAR_VELOCITY,
        expected_range=(0.0, 45.0),
    ),
    PH_02: PhysicsQuantityDef(
        PH_02,
        "angular_velocity",
        UNIT_DEG_PER_S,
        PROVENANCE_MEASURED,
        CLASS_ANGULAR_VELOCITY,
        expected_range=(0.0, 4000.0),
    ),
    PH_03: PhysicsQuantityDef(
        PH_03,
        "bat_lag_separation",
        UNIT_DEG,
        PROVENANCE_MEASURED,
        CLASS_ANGLE,
        expected_range=(-20.0, 90.0),
    ),
    PH_04: PhysicsQuantityDef(
        PH_04,
        "centre_of_mass",
        UNIT_CM,
        PROVENANCE_MEASURED,
        CLASS_DISTANCE,
        expected_range=(0.0, 100.0),
    ),
    PH_05: PhysicsQuantityDef(
        PH_05,
        "reaction_timing",
        UNIT_MS,
        PROVENANCE_MEASURED,
        CLASS_TIMING,
        expected_range=(-500.0, 1000.0),
    ),
    # --- ESTIMATED dynamics (PH-06..PH-11) — every value carries a confidence ---
    PH_06: PhysicsQuantityDef(
        PH_06,
        "momentum",
        UNIT_KG_MPS,
        PROVENANCE_ESTIMATED,
        CLASS_MOMENTUM,
        expected_range=(0.0, 100.0),
    ),
    PH_07: PhysicsQuantityDef(
        PH_07,
        "torque",
        UNIT_NM,
        PROVENANCE_ESTIMATED,
        CLASS_TORQUE,
        expected_range=(0.0, 600.0),
    ),
    PH_08: PhysicsQuantityDef(
        PH_08,
        "kinetic_energy",
        UNIT_JOULE,
        PROVENANCE_ESTIMATED,
        CLASS_ENERGY,
        expected_range=(0.0, 700.0),
    ),
    PH_09: PhysicsQuantityDef(
        PH_09,
        "ground_reaction_force",
        UNIT_NEWTON,
        PROVENANCE_ESTIMATED,
        CLASS_FORCE,
        expected_range=(0.0, 5000.0),
    ),
    PH_10: PhysicsQuantityDef(
        PH_10,
        "ball_exit_velocity",
        UNIT_MPS,
        PROVENANCE_ESTIMATED,
        CLASS_LINEAR_VELOCITY,
        expected_range=(0.0, 55.0),
        needs_bat_ball=True,
    ),
    PH_11: PhysicsQuantityDef(
        PH_11,
        "sweet_spot_efficiency",
        UNIT_RATIO,
        PROVENANCE_ESTIMATED,
        CLASS_RATIO,
        expected_range=(0.0, 1.0),
    ),
}

PH_IDS: tuple[str, ...] = tuple(CATALOGUE.keys())
MEASURED_IDS: tuple[str, ...] = tuple(q.id for q in CATALOGUE.values() if not q.is_estimated)
ESTIMATED_IDS: tuple[str, ...] = tuple(q.id for q in CATALOGUE.values() if q.is_estimated)

SCHEMA_VERSION = "physics.metrics/1.0"


@dataclass(frozen=True, slots=True)
class PhysicsQuantity:
    """One computed PH quantity: its value, how it was obtained, how much to trust it.

    ``confidence`` is a float for every ESTIMATED quantity that has a value (the
    trust doctrine's hard rule) and for the MEASURED quantities it is propagated
    from the source measurement's confidence. It is ``None`` only when the
    quantity was omitted (``value is None``): there is no estimate to attach a
    confidence to.
    """

    quantity_id: str
    value: float | None
    unit: str
    provenance: str
    confidence: float | None
    #: Degraded-but-computed: a quality/degradation flag from the M10 report
    #: propagated onto this quantity (e.g. the report was provisional).
    provisional: bool = False
    #: Why the quantity carries no value (missing input, no bat/ball, ...).
    #: An honest omission, never a fabricated fill-in.
    omitted_reason: str | None = None
    #: Sub-components of a composite quantity (e.g. per-segment angular velocity),
    #: for the report + the kinetic-chain analysis.
    detail: Mapping[str, float] = field(default_factory=dict)

    @property
    def is_estimated(self) -> bool:
        return self.provenance == PROVENANCE_ESTIMATED

    def to_payload(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "value": self.value,
            "unit": self.unit,
            "provenance": self.provenance,
            "confidence": self.confidence,
        }
        if self.provisional:
            entry["provisional"] = True
        if self.omitted_reason is not None:
            entry["omitted_reason"] = self.omitted_reason
        if self.detail:
            entry["detail"] = {k: round(v, 4) for k, v in self.detail.items()}
        return entry


def omitted(quantity_id: str, reason: str) -> PhysicsQuantity:
    """A quantity that could not be computed — value None, an explicit reason."""
    definition = CATALOGUE[quantity_id]
    return PhysicsQuantity(
        quantity_id=quantity_id,
        value=None,
        unit=definition.unit,
        provenance=definition.provenance,
        confidence=None,
        omitted_reason=reason,
    )
