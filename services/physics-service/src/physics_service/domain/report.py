"""The PhysicsReport + the pure compute pipeline (M11 §7, Step 6/7).

One pure function ties the module together, with no DB, event bus, video, or
pose:

    measure kinematics (PH-01..05) -> apply anthropometric model ->
    estimate dynamics (PH-06..11) -> kinetic chain + loss points ->
    propagate M10 provisional/quality -> range-check -> enforce trust -> report

Because it is a pure function of (BiomechanicsReport, anthropometrics), the whole
report is testable on fixture reports with no vision stack (the purity boundary,
AC-M11-02), and it is deterministic (AC-M11-08). Step 7's I/O layer wraps this
and adds nothing to the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from physics_service.domain.anthropometry import (
    Anthropometrics,
    SegmentModel,
    build_segment_model,
)
from physics_service.domain.biomech_input import BiomechanicsInput
from physics_service.domain.dynamics import estimate_dynamics
from physics_service.domain.kinematics import measure_kinematics
from physics_service.domain.kinetic_chain import KineticChain, build_kinetic_chain
from physics_service.domain.models import ACTIVE_MODEL_VERSION
from physics_service.domain.quantities import PH_IDS, SCHEMA_VERSION, PhysicsQuantity
from physics_service.domain.ranges import check_ranges
from physics_service.domain.trust import enforce_trust

#: The estimation-model version stamped on every report — the single source of
#: truth is the model registry, which also gates production readiness
#: (NFR-M11-04). Changing it is a deliberate, reviewable registry change.
DEFAULT_MODEL_VERSION = ACTIVE_MODEL_VERSION

# --- M11 quality flags (in addition to the M10 flags propagated through) ---
FLAG_MASS_ESTIMATED = "MASS_ESTIMATED"
FLAG_OUT_OF_RANGE = "OUT_OF_EXPECTED_RANGE"
FLAG_NO_ANTHROPOMETRICS = "NO_ANTHROPOMETRICS"


@dataclass(frozen=True, slots=True)
class ReportQuality:
    """Quality propagated from the M10 report + the mass uncertainty M11 adds."""

    spatial_confidence: str
    depth_estimated: bool
    mean_pose_confidence: float
    provisional: bool
    #: None when no anthropometric model could be built (no height).
    mass_is_estimated: bool | None
    mass_rel_uncertainty: float | None
    flags: tuple[str, ...]
    out_of_expected_range_quantities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PhysicsReport:
    correlation_id: str
    person_id: str | None
    shot_type: str | None
    shot_confidence: float | None
    quantities: dict[str, PhysicsQuantity]
    kinetic_chain: KineticChain
    quality: ReportQuality
    out_of_expected_range: bool
    provisional: bool
    model_version: str
    schema_version: str = SCHEMA_VERSION

    def quantities_payload(self) -> dict[str, Any]:
        return {qid: q.to_payload() for qid, q in self.quantities.items()}

    def kinetic_chain_payload(self) -> dict[str, Any]:
        return self.kinetic_chain.to_payload()

    def quality_payload(self) -> dict[str, Any]:
        q = self.quality
        return {
            "spatial_confidence": q.spatial_confidence,
            "depth_estimated": q.depth_estimated,
            "mean_pose_confidence": round(q.mean_pose_confidence, 3),
            "provisional": q.provisional,
            "mass_is_estimated": q.mass_is_estimated,
            "mass_rel_uncertainty": q.mass_rel_uncertainty,
            "flags": list(q.flags),
            "out_of_expected_range_quantities": list(q.out_of_expected_range_quantities),
        }


def _mark_provisional(
    quantities: dict[str, PhysicsQuantity], provisional: bool
) -> dict[str, PhysicsQuantity]:
    """Propagate the report-level provisional onto every value-bearing quantity."""
    if not provisional:
        return quantities
    return {
        qid: (replace(q, provisional=True) if q.value is not None else q)
        for qid, q in quantities.items()
    }


def _build_quality(
    bio: BiomechanicsInput,
    segment_model: SegmentModel | None,
    flagged: tuple[str, ...],
) -> ReportQuality:
    # Propagate the M10 flags, then add M11's own.
    flags = list(bio.flags)
    if segment_model is None:
        flags.append(FLAG_NO_ANTHROPOMETRICS)
        mass_is_estimated: bool | None = None
        mass_rel_uncertainty: float | None = None
    else:
        mass_is_estimated = segment_model.mass_is_estimated
        mass_rel_uncertainty = segment_model.mass_rel_uncertainty
        if segment_model.mass_is_estimated:
            flags.append(FLAG_MASS_ESTIMATED)
    if flagged:
        flags.append(FLAG_OUT_OF_RANGE)

    return ReportQuality(
        spatial_confidence=bio.spatial_confidence,
        depth_estimated=bio.depth_estimated,
        mean_pose_confidence=bio.mean_pose_confidence,
        provisional=bio.provisional,
        mass_is_estimated=mass_is_estimated,
        mass_rel_uncertainty=mass_rel_uncertainty,
        flags=tuple(flags),
        out_of_expected_range_quantities=flagged,
    )


def compute_report(
    bio: BiomechanicsInput,
    anthropometrics: Anthropometrics | None,
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
) -> PhysicsReport:
    """Compute a full PhysicsReport from an M10 report + M04 anthropometrics."""
    segment_model = build_segment_model(anthropometrics) if anthropometrics is not None else None

    measured = measure_kinematics(bio)
    dynamics = estimate_dynamics(bio, measured, segment_model)
    kinetic_chain = build_kinetic_chain(bio, measured, segment_model)

    quantities: dict[str, PhysicsQuantity] = {**measured, **dynamics}
    quantities = _mark_provisional(quantities, bio.provisional)

    # Trust doctrine: verify no estimate reads as measured and every estimate
    # with a value carries a confidence (raises on violation — a code bug).
    enforce_trust(quantities)

    flagged = check_ranges(quantities)
    quality = _build_quality(bio, segment_model, flagged)

    return PhysicsReport(
        correlation_id=bio.correlation_id,
        person_id=bio.person_id,
        shot_type=bio.shot_type,
        shot_confidence=bio.shot_confidence,
        quantities=quantities,
        kinetic_chain=kinetic_chain,
        quality=quality,
        out_of_expected_range=bool(flagged),
        provisional=bio.provisional,
        model_version=model_version,
    )


def is_complete(report: PhysicsReport) -> bool:
    """True when the report carries every PH quantity key (present or omitted)."""
    return all(qid in report.quantities for qid in PH_IDS)
