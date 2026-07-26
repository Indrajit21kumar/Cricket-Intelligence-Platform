"""Confidence, provenance, precondition + degradation (M10 Step 5, §14).

Step 4 produces raw numbers. This turns them into an honest report: every value
labelled MEASURED (or ESTIMATED for BM-15), every value carrying a confidence
that reflects the capture, and the whole report marked ``provisional`` when a
precondition or a degradation says the inputs cannot fully be trusted.

The rules, each from the flagship chapter:

- **Precondition (REQ-BIO-003).** If fewer than 80% of the stroke's frames have
  mean keypoint confidence >= 0.5, the pose was too poor to trust: emit
  ``LOW_CONFIDENCE_INPUT`` and mark the report provisional. This is a floor on
  the whole run, not a per-metric adjustment.
- **Bat loss (FR-M10-06).** When M07 lost the bat on more than 30% of downswing
  frames, the bat-dependent metrics (BM-09..BM-13) are marked provisional and
  their confidence cut — the body metrics are unaffected.
- **Camera angle (§14).** A non-side-on / low-spatial-confidence capture cannot
  resolve the crease axis, so the X-axis-dependent metrics (BM-07 foot
  alignment, BM-08 stride) are DISABLED rather than reported wrong, and the
  clip is flagged for re-film.
- **Depth (§5).** A value that leans on the estimated horizontal axis carries a
  reduced confidence — the ``depth_estimated`` flag from the coordinate
  transform, surfaced as a number.

Confidence is a property OF each value, so nothing downstream can read a
low-confidence or estimated figure as a measured certainty.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from biomechanics_service.domain.catalogue import (
    BAT_DEPENDENT_IDS,
    CATALOGUE,
    CLASS_LINEAR,
    CLASS_VELOCITY,
    FLAG_ABSOLUTE_TIMING,
    FLAG_BAT_LOSS,
    FLAG_LOW_CONFIDENCE_INPUT,
    FLAG_NON_STANDARD_ANGLE,
    PROVENANCE_ESTIMATED,
    X_AXIS_DEPENDENT_IDS,
)
from biomechanics_service.domain.phase_align import AlignedPhases
from biomechanics_service.domain.stroke import (
    ANGLE_SIDE_ON,
    SPATIAL_HIGH,
    SPATIAL_LOW,
    SPATIAL_MEDIUM,
    NormalisedStroke,
)

#: Fraction of frames that must clear the per-frame confidence floor.
MIN_GOOD_FRAME_RATIO = 0.80
#: Per-frame mean keypoint confidence floor.
FRAME_CONFIDENCE_FLOOR = 0.5
#: Bat-loss fraction beyond which bat-dependent metrics go provisional.
MAX_BAT_LOSS_RATIO = 0.30

_SPATIAL_BASE = {SPATIAL_HIGH: 0.9, SPATIAL_MEDIUM: 0.7, SPATIAL_LOW: 0.4}
#: Confidence multipliers for the softening conditions.
_DEPTH_FACTOR = 0.85
_ESTIMATED_PROXY_FACTOR = 0.7
_BAT_LOSS_FACTOR = 0.6
#: Ceiling applied to every metric once the run is provisional overall.
_PROVISIONAL_CEILING = 0.5


@dataclass(frozen=True, slots=True)
class MetricValue:
    """One finalised metric: its value, how it was obtained, how much to trust it."""

    value: float | None
    provenance: str
    confidence: float
    #: Per-metric provisional flag. Distinct from the report-level flag: bat
    #: loss marks only the bat-dependent metrics provisional (FR-M10-06), while
    #: the body metrics of the same report stay trustworthy.
    provisional: bool = False
    #: Set when the metric was DISABLED (e.g. X-axis metric on a bad angle).
    disabled_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ReportQuality:
    mean_pose_confidence: float
    spatial_confidence: str
    depth_estimated: bool
    phase_segmentation_method: str
    provisional: bool
    #: The capture frame rate. Carried in the report because phase boundaries
    #: are frame indices; without fps a downstream physics consumer (M11) cannot
    #: turn a phase window into a duration, and M11 must not reach back to the
    #: M05 calibration (its purity boundary). So the report is self-contained
    #: only if it also carries the rate that gives its frame indices a timescale.
    fps: float = 0.0
    flags: tuple[str, ...] = field(default_factory=tuple)


def _good_frame_ratio(stroke: NormalisedStroke) -> tuple[float, float]:
    """(mean pose confidence, fraction of frames clearing the floor)."""
    if not stroke.pose_frames:
        return 0.0, 0.0
    confs = [f.mean_confidence for f in stroke.pose_frames]
    mean = sum(confs) / len(confs)
    good = sum(1 for c in confs if c >= FRAME_CONFIDENCE_FLOOR)
    return mean, good / len(confs)


def assess_quality(stroke: NormalisedStroke, phases: AlignedPhases) -> ReportQuality:
    """Decide the run-level quality block: precondition, angle, timing flags."""
    mean_conf, good_ratio = _good_frame_ratio(stroke)
    cal = stroke.calibration
    flags: list[str] = []
    provisional = False

    if good_ratio < MIN_GOOD_FRAME_RATIO:
        flags.append(FLAG_LOW_CONFIDENCE_INPUT)
        provisional = True

    if cal.camera_angle != ANGLE_SIDE_ON or cal.spatial_confidence == SPATIAL_LOW:
        flags.append(FLAG_NON_STANDARD_ANGLE)

    # Bat loss degrades the bat-dependent metrics (handled per-metric in
    # finalise_metrics), NOT the whole report — the body metrics are still
    # sound. So it flags but does not set the report-level provisional.
    bat_loss = stroke.bat_downswing_failure_ratio
    if bat_loss is not None and bat_loss > MAX_BAT_LOSS_RATIO:
        flags.append(FLAG_BAT_LOSS)

    if stroke.ball.timing_reference == "absolute":
        flags.append(FLAG_ABSOLUTE_TIMING)

    return ReportQuality(
        mean_pose_confidence=mean_conf,
        spatial_confidence=cal.spatial_confidence,
        depth_estimated=cal.depth_estimated,
        phase_segmentation_method=phases.method,
        provisional=provisional,
        fps=cal.fps,
        flags=tuple(flags),
    )


def finalise_metrics(
    stroke: NormalisedStroke,
    raw: dict[str, float | None],
    quality: ReportQuality,
) -> dict[str, MetricValue]:
    """Attach provenance + confidence to every metric; disable the impossible ones."""
    cal = stroke.calibration
    spatial_low = cal.spatial_confidence == SPATIAL_LOW or cal.camera_angle != ANGLE_SIDE_ON
    bat_loss = stroke.bat_downswing_failure_ratio
    bat_lost = bat_loss is not None and bat_loss > MAX_BAT_LOSS_RATIO

    out: dict[str, MetricValue] = {}
    for metric_id, definition in CATALOGUE.items():
        value = raw.get(metric_id)

        # Disable X-axis-dependent metrics when the crease axis is unresolved.
        if metric_id in X_AXIS_DEPENDENT_IDS and spatial_low:
            out[metric_id] = MetricValue(
                value=None,
                provenance=definition.provenance,
                confidence=0.0,
                disabled_reason="crease_axis_unresolved",
            )
            continue

        confidence = _SPATIAL_BASE.get(cal.spatial_confidence, 0.5)
        if cal.depth_estimated and definition.metric_class in (CLASS_LINEAR, CLASS_VELOCITY):
            confidence *= _DEPTH_FACTOR
        if definition.provenance == PROVENANCE_ESTIMATED:
            confidence *= _ESTIMATED_PROXY_FACTOR

        metric_provisional = quality.provisional
        if bat_lost and metric_id in BAT_DEPENDENT_IDS:
            confidence *= _BAT_LOSS_FACTOR
            metric_provisional = True

        if quality.provisional:
            confidence = min(confidence, _PROVISIONAL_CEILING)
        if value is None:
            confidence = 0.0

        out[metric_id] = MetricValue(
            value=value,
            provenance=definition.provenance,
            confidence=round(confidence, 3),
            provisional=metric_provisional,
        )
    return out
