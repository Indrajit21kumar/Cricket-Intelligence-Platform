"""Kinetic-chain energy transfer + loss-point detection (M11 §5, Step 5).

The headline coaching insight (FR-M11-05, AC-M11-04): the energy-transfer
sequence up the body — feet -> knee -> hip -> shoulder -> hands -> bat — and
where it leaks. A good swing is *summation of speed*: each link should be faster
than the one before it, the proximal segments handing momentum outward until the
bat is moving fastest. A leak is a link that fails to amplify — the classic one
is between hip and shoulder, where a batter who rotates the trunk as a block
(no X-factor stretch) loses the whip.

All ESTIMATED and labelled: the link speeds are modelled from measured angular
velocities and segment radii (the hands link is the one measured speed), and the
loss detection is a model of the sequence. Nothing is fabricated — a link whose
kinematics are missing simply has no speed, and the analysis works with what is
present.

The lower body (feet, knee) cannot be given a reliable speed from this data, so
its contribution is represented honestly as a foundation *engagement* score from
the weight-transfer proxy, rather than an invented foot speed. A weak foundation
is itself a loss point: the chain that does not start from the ground.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from physics_service.domain.anthropometry import SegmentModel
from physics_service.domain.biomech_input import (
    BM_HIP_ROTATION,
    BM_SHOULDER_ROTATION,
    BM_WEIGHT_TRANSFER,
    BiomechanicsInput,
)
from physics_service.domain.dynamics import BAT_SPEED_GAIN
from physics_service.domain.quantities import (
    PH_01,
    PH_02,
    PROVENANCE_ESTIMATED,
    PROVENANCE_MEASURED,
    PhysicsQuantity,
)

_DEG2RAD = math.pi / 180.0

# --- chain links, proximal -> distal ---
LINK_FEET = "feet"
LINK_KNEE = "knee"
LINK_PELVIS = "pelvis"
LINK_TRUNK = "trunk"
LINK_HANDS = "hands"
LINK_BAT = "bat"

#: Rotation radii as a fraction of stature — the lever the hip/shoulder rotation
#: acts through to produce a linear speed (nominal, hence ESTIMATED).
HIP_RADIUS_FRACTION = 0.10
SHOULDER_RADIUS_FRACTION = 0.11

#: The minimum speed gain expected across each adjacent link in a well-sequenced
#: swing. Below this is a leak; a distal link SLOWER than its proximal neighbour
#: (ratio < 1) is a major leak.
MIN_GAIN: dict[tuple[str, str], float] = {
    (LINK_PELVIS, LINK_TRUNK): 1.05,
    (LINK_TRUNK, LINK_HANDS): 1.30,
    (LINK_HANDS, LINK_BAT): 1.15,
}

#: Below this weight-transfer engagement, the chain did not start from the ground.
FOUNDATION_MIN = 0.40

SEVERITY_LEAK = "leak"
SEVERITY_MAJOR = "major_leak"

#: The kinetic chain is a modelled construct; a modest base confidence before
#: the input confidences pull it down.
KINETIC_CHAIN_MODEL_BASE = 0.6
PROVISIONAL_PENALTY = 0.6


@dataclass(frozen=True, slots=True)
class ChainLink:
    """One link in the chain: its speed and how that speed was obtained."""

    name: str
    speed_mps: float | None
    provenance: str
    confidence: float | None


@dataclass(frozen=True, slots=True)
class EnergyLoss:
    """A leak: a link that failed to amplify the speed handed to it."""

    from_link: str
    to_link: str
    transfer_ratio: float | None
    expected_min: float
    severity: str
    note: str


@dataclass(frozen=True, slots=True)
class KineticChain:
    links: tuple[ChainLink, ...]
    #: Feet/knee foundation, from the weight-transfer proxy (0..1), or None.
    lower_body_engagement: float | None
    loss_points: tuple[EnergyLoss, ...]
    #: True when the speed strictly amplifies down every present link and the
    #: foundation is engaged (i.e. no loss points).
    sequence_ok: bool
    provenance: str = PROVENANCE_ESTIMATED
    confidence: float | None = None
    #: The energy-loss flags, propagated (e.g. report provisional).
    flags: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provenance": self.provenance,
            "confidence": self.confidence,
            "sequence_ok": self.sequence_ok,
            "lower_body_engagement": self.lower_body_engagement,
            "links": [
                {
                    "name": link.name,
                    "speed_mps": link.speed_mps,
                    "provenance": link.provenance,
                    "confidence": link.confidence,
                }
                for link in self.links
            ],
            "loss_points": [
                {
                    "from": lp.from_link,
                    "to": lp.to_link,
                    "transfer_ratio": (
                        round(lp.transfer_ratio, 3) if lp.transfer_ratio is not None else None
                    ),
                    "expected_min": lp.expected_min,
                    "severity": lp.severity,
                    "note": lp.note,
                }
                for lp in self.loss_points
            ],
        }


def _link_speeds(
    bio: BiomechanicsInput, measured: dict[str, PhysicsQuantity], sm: SegmentModel | None
) -> list[ChainLink]:
    """Build the ordered speed-carrying links (pelvis..bat)."""
    angular = measured.get(PH_02)
    hip_deg = angular.detail.get("hip_deg_per_s") if angular is not None else None
    shoulder_deg = angular.detail.get("shoulder_deg_per_s") if angular is not None else None

    links: list[ChainLink] = []

    # Pelvis + trunk: rotation speed * a stature-scaled radius (needs height).
    if sm is not None and hip_deg is not None:
        v_hip = hip_deg * _DEG2RAD * (HIP_RADIUS_FRACTION * sm.height_m)
        links.append(
            ChainLink(
                LINK_PELVIS, round(v_hip, 4), PROVENANCE_ESTIMATED, bio.confidence(BM_HIP_ROTATION)
            )
        )
    else:
        links.append(ChainLink(LINK_PELVIS, None, PROVENANCE_ESTIMATED, None))

    if sm is not None and shoulder_deg is not None:
        v_shoulder = shoulder_deg * _DEG2RAD * (SHOULDER_RADIUS_FRACTION * sm.height_m)
        links.append(
            ChainLink(
                LINK_TRUNK,
                round(v_shoulder, 4),
                PROVENANCE_ESTIMATED,
                bio.confidence(BM_SHOULDER_ROTATION),
            )
        )
    else:
        links.append(ChainLink(LINK_TRUNK, None, PROVENANCE_ESTIMATED, None))

    # Hands: the one MEASURED speed in the chain.
    speed = measured.get(PH_01)
    if speed is not None and speed.value is not None:
        links.append(ChainLink(LINK_HANDS, speed.value, PROVENANCE_MEASURED, speed.confidence))
        # Bat: the contact point runs faster than the hands (estimated).
        v_bat = round(speed.value * BAT_SPEED_GAIN, 4)
        conf = None if speed.confidence is None else round(speed.confidence * 0.9, 3)
        links.append(ChainLink(LINK_BAT, v_bat, PROVENANCE_ESTIMATED, conf))
    else:
        links.append(ChainLink(LINK_HANDS, None, PROVENANCE_MEASURED, None))
        links.append(ChainLink(LINK_BAT, None, PROVENANCE_ESTIMATED, None))

    return links


def _detect_losses(speeds: dict[str, float], engagement: float | None) -> list[EnergyLoss]:
    losses: list[EnergyLoss] = []

    # Foundation: a chain that does not start from the ground.
    if engagement is not None and engagement < FOUNDATION_MIN:
        losses.append(
            EnergyLoss(
                from_link=LINK_FEET,
                to_link=LINK_PELVIS,
                transfer_ratio=None,
                expected_min=FOUNDATION_MIN,
                severity=SEVERITY_MAJOR,
                note="weak lower-body engagement: the chain barely started from the ground",
            )
        )

    for (proximal, distal), expected in MIN_GAIN.items():
        if proximal not in speeds or distal not in speeds:
            continue
        p_speed = speeds[proximal]
        if p_speed <= 0:
            continue
        ratio = speeds[distal] / p_speed
        if ratio < 1.0:
            losses.append(
                EnergyLoss(
                    from_link=proximal,
                    to_link=distal,
                    transfer_ratio=ratio,
                    expected_min=expected,
                    severity=SEVERITY_MAJOR,
                    note=f"{distal} is slower than {proximal}: energy leaked, not transferred",
                )
            )
        elif ratio < expected:
            losses.append(
                EnergyLoss(
                    from_link=proximal,
                    to_link=distal,
                    transfer_ratio=ratio,
                    expected_min=expected,
                    severity=SEVERITY_LEAK,
                    note=f"weak transfer from {proximal} to {distal}",
                )
            )
    return losses


def build_kinetic_chain(
    bio: BiomechanicsInput,
    measured: dict[str, PhysicsQuantity],
    segment_model: SegmentModel | None,
) -> KineticChain:
    """Build the energy-transfer sequence + loss points (all ESTIMATED)."""
    links = _link_speeds(bio, measured, segment_model)
    speeds = {link.name: link.speed_mps for link in links if link.speed_mps is not None}
    engagement = bio.value(BM_WEIGHT_TRANSFER)

    loss_points = _detect_losses(speeds, engagement)

    present_confs = [link.confidence for link in links if link.confidence is not None]
    if present_confs:
        confidence = min(present_confs) * KINETIC_CHAIN_MODEL_BASE
        if bio.provisional:
            confidence *= PROVISIONAL_PENALTY
        chain_confidence: float | None = round(max(0.0, min(1.0, confidence)), 3)
    else:
        chain_confidence = None

    return KineticChain(
        links=tuple(links),
        lower_body_engagement=engagement,
        loss_points=tuple(loss_points),
        sequence_ok=not loss_points,
        confidence=chain_confidence,
        flags=("PROVISIONAL",) if bio.provisional else (),
    )
