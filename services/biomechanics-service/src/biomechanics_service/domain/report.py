"""The BiomechanicsReport + the pure compute pipeline (M10 §8, Step 7).

One pure function ties the module together, with no DB, event bus, or video:

    build stroke -> align phases -> compute BM-01..BM-17 -> quality + confidence
    -> range-check -> assemble report

Step 7's I/O layer wraps this and adds nothing to the numbers. The determinism
(NFR-M10-03) and the "M11 re-derives nothing" boundary (AC-M10-07) both rest on
the report being a complete, self-contained function of the stroke: everything a
downstream consumer needs is IN the report, so M11 never has to reach back to
pose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from biomechanics_service.domain.builder import RawStroke, build_normalised_stroke
from biomechanics_service.domain.catalogue import BM_IDS, CATALOGUE, SCHEMA_VERSION
from biomechanics_service.domain.metrics import compute_metrics
from biomechanics_service.domain.phase_align import align_phases
from biomechanics_service.domain.quality import (
    MetricValue,
    ReportQuality,
    assess_quality,
    finalise_metrics,
)
from biomechanics_service.domain.range_check import check_ranges


@dataclass(frozen=True, slots=True)
class BiomechanicsReport:
    correlation_id: str
    shot_type: str | None
    shot_confidence: float | None
    phase_boundaries: dict[str, int]
    phase_method: str
    metrics: dict[str, MetricValue]
    quality: ReportQuality
    out_of_expected_range: bool
    flagged_metrics: tuple[str, ...]
    provisional: bool
    schema_version: str = SCHEMA_VERSION

    def metrics_payload(self) -> dict[str, Any]:
        """The metrics object as stored/published: value + provenance + trust.

        Carries the catalogue's ``name`` and ``unit`` alongside each value.
        A consumer showing a number to a coach needs the unit to render it at
        all, and re-deriving it from the metric id downstream would duplicate
        the catalogue and let the two drift.
        """
        payload: dict[str, Any] = {}
        for metric_id, mv in self.metrics.items():
            definition = CATALOGUE[metric_id]
            entry: dict[str, Any] = {
                "value": mv.value,
                "name": definition.name,
                "unit": definition.unit,
                "provenance": mv.provenance,
                "confidence": mv.confidence,
            }
            if mv.provisional:
                entry["provisional"] = True
            if mv.disabled_reason is not None:
                entry["disabled_reason"] = mv.disabled_reason
            payload[metric_id] = entry
        return payload

    def quality_payload(self) -> dict[str, Any]:
        return {
            "mean_pose_confidence": round(self.quality.mean_pose_confidence, 3),
            "spatial_confidence": self.quality.spatial_confidence,
            "depth_estimated": self.quality.depth_estimated,
            "phase_segmentation_method": self.quality.phase_segmentation_method,
            "provisional": self.quality.provisional,
            # The capture rate that gives the frame-indexed phase_boundaries a
            # timescale — M11 reads this rather than the M05 calibration.
            "fps": round(self.quality.fps, 3),
            "flags": list(self.quality.flags),
            "out_of_expected_range_metrics": list(self.flagged_metrics),
        }


def compute_report(raw: RawStroke) -> BiomechanicsReport:
    """Compute a full BiomechanicsReport from a raw fan-in stroke."""
    stroke = build_normalised_stroke(raw)
    aligned = align_phases(stroke.phases, frame_count=stroke.frame_count)

    raw_metrics = compute_metrics(stroke, aligned)
    quality = assess_quality(stroke, aligned)
    metrics = finalise_metrics(stroke, raw_metrics, quality)
    ranges = check_ranges(metrics)

    return BiomechanicsReport(
        correlation_id=stroke.correlation_id,
        shot_type=stroke.shot_type,
        shot_confidence=stroke.shot_confidence,
        phase_boundaries={
            "stance": stroke.phases.stance,
            "backlift": stroke.phases.backlift,
            "downswing": stroke.phases.downswing,
            "impact": stroke.phases.impact,
            "follow_through": stroke.phases.follow_through,
        },
        phase_method=stroke.phases.method,
        metrics=metrics,
        quality=quality,
        out_of_expected_range=ranges.out_of_range,
        flagged_metrics=ranges.flagged,
        provisional=quality.provisional,
    )


# A report is "complete" for M11 if it carries every metric key. This is the
# structural guarantee behind AC-M10-07: M11 reads these, never pose.
def is_complete_for_physics(report: BiomechanicsReport) -> bool:
    return all(metric_id in report.metrics for metric_id in BM_IDS)
