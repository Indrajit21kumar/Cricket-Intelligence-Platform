"""ESTIMATED dynamics — PH-06..PH-11 (M11 §5, Step 4).

The dynamics half of the physics: momentum, torque, energy, ground reaction
force, ball-exit velocity, sweet-spot efficiency. A phone measures none of these
directly, so each is INFERRED through a model and labelled ESTIMATED, and every
value carries a confidence combining model + anthropometric-mass + input
uncertainty (:mod:`confidence`). No estimate is ever fabricated: when its inputs
are missing the quantity is omitted with a reason.

The models, deliberately simple and documented so the estimate is defensible
rather than a black box:

- **PH-06 momentum** p = m_strike . v_hand, where m_strike is the bat plus the
  hands (the mass the hand speed carries). Impulse ~ p (rest to contact).
- **PH-07 torque** tau = I_swing . alpha: the swing inertia (both arms + bat,
  about the shoulder) times the angular acceleration (measured angular velocity
  brought up from rest over the downswing).
- **PH-08 kinetic energy** KE = 1/2 . I_swing . omega^2, the rotational energy of
  the swing system.
- **PH-09 ground reaction force** F = m . g . k, with k a body-weight multiplier
  driven by the weight-transfer proxy — no force plate, hence a low base
  confidence (§13).
- **PH-10 ball-exit velocity** an impulse-momentum collision (coefficient of
  restitution) between the bat's effective mass at contact speed and the ball,
  scaled by sweet-spot efficiency. REQUIRES a usable bat + a tracked ball
  contact; absent, it is omitted, never guessed (FR-M11-07 / AC-M11-05).
- **PH-11 sweet-spot efficiency** modelled from bat-path linearity.
"""

from __future__ import annotations

import math

from physics_service.domain.anthropometry import SegmentModel
from physics_service.domain.biomech_input import (
    BM_BAT_PATH_LINEARITY,
    BM_HAND_SPEED,
    BM_WEIGHT_TRANSFER,
    FLAG_ABSOLUTE_TIMING,
    BiomechanicsInput,
)
from physics_service.domain.confidence import combine_confidence
from physics_service.domain.quantities import (
    CATALOGUE,
    PH_01,
    PH_02,
    PH_06,
    PH_07,
    PH_08,
    PH_09,
    PH_10,
    PH_11,
    PhysicsQuantity,
    omitted,
)

_DEG2RAD = math.pi / 180.0

# --- equipment + physical constants (ESTIMATED assumptions) -----------------
#: Standard senior cricket bat mass (kg).
BAT_MASS_KG = 1.2
#: Bat CoM distance below the hands (m) — for the swing moment of inertia.
BAT_COM_FROM_HANDLE_M = 0.35
#: Effective (recoil) mass of the bat at the impact point, as a fraction of bat
#: mass — a free bat presents less than its full mass at contact.
BAT_EFFECTIVE_FRACTION = 0.5
#: The contact point (sweet spot) moves faster than the hands.
BAT_SPEED_GAIN = 1.3
#: Cricket ball mass (kg) and the bat-ball coefficient of restitution.
BALL_MASS_KG = 0.16
COEFF_RESTITUTION = 0.5
#: Efficiency assumed for ball-exit when PH-11 could not be formed.
DEFAULT_EFFICIENCY = 0.7

GRAVITY = 9.81
#: Ground reaction force model: F = m.g.(1 + gain.weight_transfer).
GRF_TRANSFER_GAIN = 1.2
GRF_DEFAULT_MULTIPLIER = 1.5


def _estimated(
    quantity_id: str,
    value: float,
    confidence: float,
    *,
    provisional: bool = False,
    detail: dict[str, float] | None = None,
) -> PhysicsQuantity:
    """Build an ESTIMATED quantity; confidence is always a real float here."""
    definition = CATALOGUE[quantity_id]
    return PhysicsQuantity(
        quantity_id=quantity_id,
        value=round(value, 4),
        unit=definition.unit,
        provenance=definition.provenance,
        confidence=confidence,
        provisional=provisional,
        detail=detail or {},
    )


def _omega_rad(measured: dict[str, PhysicsQuantity]) -> float | None:
    """Peak segment angular velocity (PH-02) in rad/s, or None."""
    q = measured.get(PH_02)
    if q is None or q.value is None:
        return None
    return q.value * _DEG2RAD


def _swing_inertia(sm: SegmentModel) -> float | None:
    """Moment of inertia of the swing system (both arms + bat) about the shoulder."""
    arm_inertia = sm.arm_chain_inertia_about_shoulder()
    arm_length = sm.arm_length_m()
    if arm_inertia is None or arm_length is None:
        return None
    bat_com_distance = arm_length + BAT_COM_FROM_HANDLE_M
    bat_inertia = BAT_MASS_KG * bat_com_distance**2
    return 2.0 * arm_inertia + bat_inertia


def _momentum(
    bio: BiomechanicsInput, measured: dict[str, PhysicsQuantity], sm: SegmentModel | None
) -> PhysicsQuantity:
    speed = measured[PH_01]
    if speed.value is None:
        return omitted(PH_06, "no_bat_speed")
    if sm is None:
        return omitted(PH_06, "no_anthropometrics")
    striking_mass = BAT_MASS_KG + sm.hands_mass_kg
    momentum = striking_mass * speed.value
    provisional = bio.provisional or speed.provisional
    confidence = combine_confidence(
        PH_06, input_confidence=speed.confidence, mass_model=sm, provisional=provisional
    )
    return _estimated(
        PH_06,
        momentum,
        confidence,
        provisional=provisional,
        detail={"striking_mass_kg": striking_mass, "impulse_ns": momentum},
    )


def _torque(
    bio: BiomechanicsInput, measured: dict[str, PhysicsQuantity], sm: SegmentModel | None
) -> PhysicsQuantity:
    omega = _omega_rad(measured)
    duration = bio.downswing_duration_s()
    if omega is None or duration is None:
        return omitted(PH_07, "no_angular_kinematics")
    if sm is None:
        return omitted(PH_07, "no_anthropometrics")
    inertia = _swing_inertia(sm)
    if inertia is None:
        return omitted(PH_07, "no_swing_inertia")
    alpha = omega / duration  # rest -> omega over the downswing
    torque = inertia * alpha
    angular = measured[PH_02]
    provisional = bio.provisional or angular.provisional
    confidence = combine_confidence(
        PH_07, input_confidence=angular.confidence, mass_model=sm, provisional=provisional
    )
    return _estimated(
        PH_07,
        torque,
        confidence,
        provisional=provisional,
        detail={"swing_inertia_kg_m2": inertia, "angular_accel_rad_s2": alpha},
    )


def _kinetic_energy(
    bio: BiomechanicsInput, measured: dict[str, PhysicsQuantity], sm: SegmentModel | None
) -> PhysicsQuantity:
    omega = _omega_rad(measured)
    if omega is None:
        return omitted(PH_08, "no_angular_velocity")
    if sm is None:
        return omitted(PH_08, "no_anthropometrics")
    inertia = _swing_inertia(sm)
    if inertia is None:
        return omitted(PH_08, "no_swing_inertia")
    energy = 0.5 * inertia * omega**2
    angular = measured[PH_02]
    provisional = bio.provisional or angular.provisional
    confidence = combine_confidence(
        PH_08, input_confidence=angular.confidence, mass_model=sm, provisional=provisional
    )
    return _estimated(
        PH_08,
        energy,
        confidence,
        provisional=provisional,
        detail={"swing_inertia_kg_m2": inertia, "angular_velocity_rad_s": omega},
    )


def _ground_reaction_force(bio: BiomechanicsInput, sm: SegmentModel | None) -> PhysicsQuantity:
    if sm is None:
        return omitted(PH_09, "no_anthropometrics")
    weight_transfer = bio.value(BM_WEIGHT_TRANSFER)
    if weight_transfer is not None:
        multiplier = 1.0 + GRF_TRANSFER_GAIN * weight_transfer
        input_confidence = bio.confidence(BM_WEIGHT_TRANSFER)
    else:
        multiplier = GRF_DEFAULT_MULTIPLIER
        input_confidence = 0.5
    force = sm.total_mass_kg * GRAVITY * multiplier
    confidence = combine_confidence(
        PH_09, input_confidence=input_confidence, mass_model=sm, provisional=bio.provisional
    )
    return _estimated(
        PH_09,
        force,
        confidence,
        provisional=bio.provisional,
        detail={"body_weight_multiplier": multiplier},
    )


def _sweet_spot_efficiency(bio: BiomechanicsInput) -> PhysicsQuantity:
    linearity = bio.value(BM_BAT_PATH_LINEARITY)
    if linearity is None:
        return omitted(PH_11, "no_bat_path")
    efficiency = max(0.0, min(1.0, 0.4 + 0.6 * linearity))
    provisional = bio.provisional or bio.is_provisional(BM_BAT_PATH_LINEARITY)
    confidence = combine_confidence(
        PH_11,
        input_confidence=bio.confidence(BM_BAT_PATH_LINEARITY),
        mass_dependent=False,
        provisional=provisional,
    )
    return _estimated(
        PH_11,
        efficiency,
        confidence,
        provisional=provisional,
        detail={"bat_path_linearity": linearity},
    )


def _ball_exit_velocity(
    bio: BiomechanicsInput,
    measured: dict[str, PhysicsQuantity],
    efficiency: PhysicsQuantity,
) -> PhysicsQuantity:
    # PH-10 requires a usable bat AND a tracked ball contact. Absolute timing
    # means no ball was anchored; a provisional/absent hand speed means the bat
    # was not tracked through impact. Either way, omit — never fabricate.
    if bio.has_flag(FLAG_ABSOLUTE_TIMING):
        return omitted(PH_10, "no_tracked_ball_contact")
    speed = measured[PH_01]
    if speed.value is None or bio.is_provisional(BM_HAND_SPEED):
        return omitted(PH_10, "no_usable_bat_at_contact")

    contact_speed = speed.value * BAT_SPEED_GAIN
    m_bat_eff = BAT_MASS_KG * BAT_EFFECTIVE_FRACTION
    exit_speed = contact_speed * (1.0 + COEFF_RESTITUTION) * m_bat_eff / (m_bat_eff + BALL_MASS_KG)
    applied_efficiency = efficiency.value if efficiency.value is not None else DEFAULT_EFFICIENCY
    exit_speed *= applied_efficiency

    confidence = combine_confidence(
        PH_10,
        input_confidence=speed.confidence,
        mass_dependent=False,
        provisional=bio.provisional,
    )
    return _estimated(
        PH_10,
        exit_speed,
        confidence,
        provisional=bio.provisional,
        detail={
            "contact_speed_mps": contact_speed,
            "restitution": COEFF_RESTITUTION,
            "efficiency_applied": applied_efficiency,
        },
    )


def estimate_dynamics(
    bio: BiomechanicsInput,
    measured: dict[str, PhysicsQuantity],
    segment_model: SegmentModel | None,
) -> dict[str, PhysicsQuantity]:
    """Compute the ESTIMATED dynamics PH-06..PH-11 from the report + anthropometrics."""
    efficiency = _sweet_spot_efficiency(bio)
    return {
        PH_06: _momentum(bio, measured, segment_model),
        PH_07: _torque(bio, measured, segment_model),
        PH_08: _kinetic_energy(bio, measured, segment_model),
        PH_09: _ground_reaction_force(bio, segment_model),
        PH_10: _ball_exit_velocity(bio, measured, efficiency),
        PH_11: efficiency,
    }
