"""The anthropometric model — segment mass/length from M04 (M11 §6, Step 3).

Dynamics need per-segment mass and length; a phone knows neither directly. M11
applies a standard anthropometric model: Dempster (1955) segment mass fractions
of total body mass, segment lengths scaled from the player's stature, and
Dempster radii of gyration + centre-of-mass locations for the moments of inertia
the torque/energy estimates need.

The honesty rule of §6 lives here: **mass is uncertain, and that uncertainty
propagates.** When the player supplies a real body mass the estimate is firm;
when M11 has to infer mass from height (a fixed-BMI assumption) the uncertainty
is much larger, and :attr:`SegmentModel.mass_rel_uncertainty` carries it forward
so every dynamic quantity's confidence (Step 4) reflects it. Nothing here is
presented as measured — the whole model is the input to ESTIMATED quantities.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# --- Dempster segment mass as a fraction of total body mass -----------------
# Paired segments (arm/leg parts) are the fraction of ONE limb; the aggregate
# helpers double them. The full set sums to 1.0 of body mass.
SEGMENT_MASS_FRACTION: dict[str, float] = {
    "head_neck": 0.081,
    "trunk": 0.497,
    "upper_arm": 0.028,
    "forearm": 0.016,
    "hand": 0.006,
    "thigh": 0.100,
    "shank": 0.0465,
    "foot": 0.0145,
}

# --- segment length as a fraction of stature (Drillis-Contini / Winter) -----
SEGMENT_LENGTH_FRACTION: dict[str, float] = {
    "head_neck": 0.130,
    "trunk": 0.288,
    "upper_arm": 0.186,
    "forearm": 0.146,
    "hand": 0.108,
    "thigh": 0.245,
    "shank": 0.246,
    "foot": 0.152,
}

# --- Dempster radius of gyration about the segment CoM, as a fraction of
#     segment length (used for moment of inertia I = m*k^2) ------------------
RADIUS_GYRATION_FRACTION: dict[str, float] = {
    "head_neck": 0.495,
    "trunk": 0.372,
    "upper_arm": 0.322,
    "forearm": 0.303,
    "hand": 0.297,
    "thigh": 0.323,
    "shank": 0.302,
    "foot": 0.475,
}

# --- Dempster CoM location from the proximal end, as a fraction of length ----
SEGMENT_COM_FRACTION: dict[str, float] = {
    "head_neck": 0.500,
    "trunk": 0.500,
    "upper_arm": 0.436,
    "forearm": 0.430,
    "hand": 0.506,
    "thigh": 0.433,
    "shank": 0.433,
    "foot": 0.500,
}

PAIRED_SEGMENTS: frozenset[str] = frozenset(
    {"upper_arm", "forearm", "hand", "thigh", "shank", "foot"}
)

#: BMI assumed when the player supplies no body mass, so mass can be inferred
#: from stature (mass = BMI * height_m^2). A mid-range adult BMI.
DEFAULT_BMI = 22.5
#: Relative (1-sigma) uncertainty on the body mass used.
PROVIDED_MASS_REL_UNCERTAINTY = 0.03
ESTIMATED_MASS_REL_UNCERTAINTY = 0.18


@dataclass(frozen=True, slots=True)
class Anthropometrics:
    """Player body data from M04. ``body_mass_kg`` None -> inferred from height."""

    height_cm: float | None
    body_mass_kg: float | None = None
    handedness: str = "RHB"
    age_band: str | None = None


@dataclass(frozen=True, slots=True)
class Segment:
    """One body segment with the mechanical properties dynamics needs."""

    name: str
    mass_kg: float
    length_m: float
    #: Radius of gyration about the segment CoM (m).
    radius_of_gyration_m: float
    #: CoM distance from the proximal joint (m).
    com_distance_m: float

    @property
    def moment_of_inertia_cm(self) -> float:
        """I about the segment's own centre of mass (kg.m^2)."""
        return self.mass_kg * self.radius_of_gyration_m**2

    @property
    def moment_of_inertia_proximal(self) -> float:
        """I about the proximal joint, via the parallel-axis theorem."""
        return self.moment_of_inertia_cm + self.mass_kg * self.com_distance_m**2


@dataclass(frozen=True, slots=True)
class SegmentModel:
    """A player's body as segments, ready to feed the dynamics estimates."""

    total_mass_kg: float
    height_m: float
    #: True when body mass was inferred from height, not supplied by the player.
    mass_is_estimated: bool
    #: 1-sigma relative uncertainty on the body mass, which flows into every
    #: dynamic quantity's confidence (Step 4).
    mass_rel_uncertainty: float
    segments: Mapping[str, Segment]

    def segment(self, name: str) -> Segment | None:
        return self.segments.get(name)

    @property
    def mass_confidence(self) -> float:
        """A [0,1] factor for the estimate-confidence model: firm mass -> high."""
        return max(0.0, 1.0 - self.mass_rel_uncertainty)

    def _pair_mass(self, name: str) -> float:
        seg = self.segments.get(name)
        return 2.0 * seg.mass_kg if seg is not None else 0.0

    @property
    def arm_mass_kg(self) -> float:
        """Mass of one whole arm (upper arm + forearm + hand)."""
        return sum(
            self.segments[s].mass_kg for s in ("upper_arm", "forearm", "hand") if s in self.segments
        )

    @property
    def both_arms_mass_kg(self) -> float:
        return 2.0 * self.arm_mass_kg

    @property
    def hands_mass_kg(self) -> float:
        """Mass of both hands — the point mass the bat handle carries."""
        return self._pair_mass("hand")

    @property
    def leg_mass_kg(self) -> float:
        """Mass of one whole leg (thigh + shank + foot)."""
        return sum(
            self.segments[s].mass_kg for s in ("thigh", "shank", "foot") if s in self.segments
        )


def _resolve_mass(anthro: Anthropometrics, height_m: float) -> tuple[float, bool, float]:
    """(mass_kg, is_estimated, rel_uncertainty)."""
    if anthro.body_mass_kg is not None and anthro.body_mass_kg > 0:
        return anthro.body_mass_kg, False, PROVIDED_MASS_REL_UNCERTAINTY
    mass = DEFAULT_BMI * height_m * height_m
    return mass, True, ESTIMATED_MASS_REL_UNCERTAINTY


def build_segment_model(anthro: Anthropometrics) -> SegmentModel | None:
    """Build the Dempster segment model, or None when height is unavailable.

    Height is essential: it scales every segment length, and without lengths the
    moments of inertia (torque, rotational energy) cannot be formed. No height
    -> no model -> the dynamics that need it are honestly omitted downstream.
    """
    if anthro.height_cm is None or anthro.height_cm <= 0:
        return None
    height_m = anthro.height_cm / 100.0
    total_mass, is_estimated, rel_uncertainty = _resolve_mass(anthro, height_m)

    segments: dict[str, Segment] = {}
    for name, mass_fraction in SEGMENT_MASS_FRACTION.items():
        length = height_m * SEGMENT_LENGTH_FRACTION[name]
        segments[name] = Segment(
            name=name,
            mass_kg=total_mass * mass_fraction,
            length_m=length,
            radius_of_gyration_m=length * RADIUS_GYRATION_FRACTION[name],
            com_distance_m=length * SEGMENT_COM_FRACTION[name],
        )

    return SegmentModel(
        total_mass_kg=total_mass,
        height_m=height_m,
        mass_is_estimated=is_estimated,
        mass_rel_uncertainty=rel_uncertainty,
        segments=segments,
    )
