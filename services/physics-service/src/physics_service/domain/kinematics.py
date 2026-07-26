"""MEASURED kinematics — PH-01..PH-05 (M11 §5, Step 2).

The measured half of the physics: quantities derivable from what the camera saw,
because each is a function of already-measured M10 kinematics. They are labelled
MEASURED and the trust doctrine lets them be presented as measurements.

Each is a pure function of the :class:`BiomechanicsInput` — the report, nothing
else (the purity boundary). Confidence is PROPAGATED from the source
measurement(s): a bat/hand speed built on a low-confidence BM-12 is itself
low-confidence, so a soft input can never masquerade as a firm physics number.

- **PH-01 bat/hand speed** — BM-12 hand speed (already m/s), passed through.
- **PH-02 angular velocity** — segment rotation over the downswing duration. The
  angle (BM-02/BM-03) is measured and the interval (phase frames / fps) is
  measured, so their ratio is measured. It is the MEAN angular velocity across
  the downswing, not an instantaneous peak: M11 has no time series (purity), so
  it does not claim to see the peak.
- **PH-03 bat lag / separation** — BM-04 hip-shoulder separation is the headline,
  BM-11 bat lag carried alongside.
- **PH-04 centre of mass & balance** — BM-16 CoM path, with BM-01 head stability
  as the balance companion.
- **PH-05 reaction / timing** — BM-17 ground-contact timing, with BM-14 balance
  recovery alongside.
"""

from __future__ import annotations

from physics_service.domain.biomech_input import (
    BM_BALANCE_RECOVERY,
    BM_BAT_LAG,
    BM_COM_PATH,
    BM_GROUND_CONTACT_TIMING,
    BM_HAND_SPEED,
    BM_HEAD_STABILITY,
    BM_HIP_ROTATION,
    BM_SHOULDER_ROTATION,
    BM_X_FACTOR,
    FLAG_ABSOLUTE_TIMING,
    BiomechanicsInput,
)
from physics_service.domain.quantities import (
    CATALOGUE,
    PH_01,
    PH_02,
    PH_03,
    PH_04,
    PH_05,
    PhysicsQuantity,
    omitted,
)


def _measured(
    quantity_id: str,
    value: float,
    confidence: float,
    *,
    provisional: bool = False,
    detail: dict[str, float] | None = None,
) -> PhysicsQuantity:
    """Build a MEASURED quantity, reading unit/provenance from the catalogue."""
    definition = CATALOGUE[quantity_id]
    return PhysicsQuantity(
        quantity_id=quantity_id,
        value=round(value, 4),
        unit=definition.unit,
        provenance=definition.provenance,
        confidence=round(confidence, 3),
        provisional=provisional,
        detail=detail or {},
    )


def _omitted_with_detail(
    quantity_id: str, reason: str, detail: dict[str, float]
) -> PhysicsQuantity:
    """An omitted quantity that still surfaces whatever companion data exists."""
    definition = CATALOGUE[quantity_id]
    return PhysicsQuantity(
        quantity_id=quantity_id,
        value=None,
        unit=definition.unit,
        provenance=definition.provenance,
        confidence=None,
        omitted_reason=reason,
        detail=detail,
    )


def _bat_hand_speed(bio: BiomechanicsInput) -> PhysicsQuantity:
    speed = bio.value(BM_HAND_SPEED)
    if speed is None:
        return omitted(PH_01, "no_hand_speed")
    return _measured(
        PH_01,
        speed,
        bio.confidence(BM_HAND_SPEED),
        provisional=bio.is_provisional(BM_HAND_SPEED),
    )


def _angular_velocity(bio: BiomechanicsInput) -> PhysicsQuantity:
    duration = bio.downswing_duration_s()
    if duration is None:
        return omitted(PH_02, "no_downswing_duration")

    detail: dict[str, float] = {}
    contributions: list[tuple[float, float]] = []  # (omega deg/s, confidence)

    shoulder = bio.value(BM_SHOULDER_ROTATION)
    if shoulder is not None:
        s_omega = abs(shoulder) / duration
        detail["shoulder_deg_per_s"] = s_omega
        contributions.append((s_omega, bio.confidence(BM_SHOULDER_ROTATION)))

    hip = bio.value(BM_HIP_ROTATION)
    if hip is not None:
        h_omega = abs(hip) / duration
        detail["hip_deg_per_s"] = h_omega
        contributions.append((h_omega, bio.confidence(BM_HIP_ROTATION)))

    if not contributions:
        return omitted(PH_02, "no_segment_rotation")

    # Headline = the faster-rotating segment's mean angular velocity; confidence
    # is the weakest contributing measurement (an unknown segment drags trust).
    peak_omega = max(omega for omega, _ in contributions)
    confidence = min(conf for _, conf in contributions)
    provisional = bio.is_provisional(BM_SHOULDER_ROTATION) or bio.is_provisional(BM_HIP_ROTATION)
    return _measured(PH_02, peak_omega, confidence, provisional=provisional, detail=detail)


def _bat_lag_separation(bio: BiomechanicsInput) -> PhysicsQuantity:
    separation = bio.value(BM_X_FACTOR)
    bat_lag = bio.value(BM_BAT_LAG)
    detail: dict[str, float] = {}
    if bat_lag is not None:
        detail["bat_lag_deg"] = bat_lag
    if separation is None:
        return _omitted_with_detail(PH_03, "no_separation", detail)
    provisional = bio.is_provisional(BM_X_FACTOR) or bio.is_provisional(BM_BAT_LAG)
    return _measured(
        PH_03, separation, bio.confidence(BM_X_FACTOR), provisional=provisional, detail=detail
    )


def _centre_of_mass(bio: BiomechanicsInput) -> PhysicsQuantity:
    com = bio.value(BM_COM_PATH)
    head = bio.value(BM_HEAD_STABILITY)
    detail: dict[str, float] = {}
    if head is not None:
        detail["head_stability_cm"] = head
    if com is None:
        return _omitted_with_detail(PH_04, "no_com_path", detail)
    return _measured(
        PH_04,
        com,
        bio.confidence(BM_COM_PATH),
        provisional=bio.is_provisional(BM_COM_PATH),
        detail=detail,
    )


def _reaction_timing(bio: BiomechanicsInput) -> PhysicsQuantity:
    gct = bio.value(BM_GROUND_CONTACT_TIMING)
    recovery = bio.value(BM_BALANCE_RECOVERY)
    detail: dict[str, float] = {}
    if recovery is not None:
        detail["balance_recovery_ms"] = recovery
    if gct is None:
        return _omitted_with_detail(PH_05, "no_ground_contact_timing", detail)
    # Absolute timing (no ball-release anchor) makes the reaction number softer;
    # mark provisional so it is never read as a firm reaction measurement.
    provisional = bio.is_provisional(BM_GROUND_CONTACT_TIMING) or bio.has_flag(FLAG_ABSOLUTE_TIMING)
    return _measured(
        PH_05, gct, bio.confidence(BM_GROUND_CONTACT_TIMING), provisional=provisional, detail=detail
    )


def measure_kinematics(bio: BiomechanicsInput) -> dict[str, PhysicsQuantity]:
    """Compute the MEASURED kinematics PH-01..PH-05 from the report."""
    return {
        PH_01: _bat_hand_speed(bio),
        PH_02: _angular_velocity(bio),
        PH_03: _bat_lag_separation(bio),
        PH_04: _centre_of_mass(bio),
        PH_05: _reaction_timing(bio),
    }
