"""Report assembly — the structured coaching report (M14 §5, Step 2, FR-M14-01).

Assembles the report Section 5 defines from M13's ``analysis.reasoned`` (+
M10/M11 metrics + player history + M15 legend comparison): scores, findings,
metric panels, and the Legend view. Video annotation (Step 3) and the
grounded narrative (Step 5) are attached separately via :func:`attach_video`
and :func:`attach_narrative`, since both require an async call to their
respective adapter; the AI Coach (Step 6) reads this structure rather than
recomputing any of it, so every number in the report traces to exactly one
place.

Pure function of its inputs: the same ``analysis.reasoned`` + metrics + history
+ legend comparison always assembles the same report (NFR-M14-03, AC-M14-07).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from report_service.domain.legend import build_legend_view
from report_service.domain.narrative import Narrative
from report_service.domain.panels import MetricPanelEntry, build_metric_panels
from report_service.domain.scoring import Scores, compute_improvement, compute_scores
from report_service.domain.sources import PlayerHistory
from report_service.domain.video import AnnotatedVideo

SCHEMA_VERSION = "report.structure/1.0"


@dataclass(frozen=True, slots=True)
class ReportStructure:
    correlation_id: str
    person_id: str | None
    shot_type: str | None
    shot_confidence: float | None
    kg_version: str
    findings: list[dict[str, Any]]
    metric_panels: list[MetricPanelEntry]
    scores: Scores
    match_risk: dict[str, Any]
    provisional: bool
    #: Filled in by attach_video() after build_report(); None/empty until then.
    annotated_video_ref: str | None = None
    video_markers: tuple[dict[str, Any], ...] = ()
    video_overlays_applied: bool = False
    legend_view: dict[str, Any] | None = None
    #: Filled in by attach_narrative() after build_report(); None until then.
    narrative_text: str | None = None
    narrative_citations: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "person_id": self.person_id,
            "shot_type": self.shot_type,
            "shot_confidence": self.shot_confidence,
            "kg_version": self.kg_version,
            "findings": self.findings,
            "metric_panels": [p.to_dict() for p in self.metric_panels],
            "scores": self.scores.to_dict(),
            "match_risk": self.match_risk,
            "provisional": self.provisional,
            "annotated_video_ref": self.annotated_video_ref,
            "video_markers": list(self.video_markers),
            "video_overlays_applied": self.video_overlays_applied,
            "legend_view": self.legend_view,
            "narrative_text": self.narrative_text,
            "narrative_citations": list(self.narrative_citations),
            "schema_version": self.schema_version,
        }


def _facts_map(
    biomechanics: Mapping[str, Any], physics: Mapping[str, Any] | None
) -> dict[str, Any]:
    """A flat metric_id -> entry map, used by the confidence-score fallback."""
    facts: dict[str, Any] = {}
    metrics = biomechanics.get("metrics")
    if isinstance(metrics, Mapping):
        facts.update(metrics)
    if physics is not None:
        quantities = physics.get("quantities")
        if isinstance(quantities, Mapping):
            facts.update(quantities)
    return facts


def build_report(
    *,
    reasoned: Mapping[str, Any],
    biomechanics: Mapping[str, Any],
    physics: Mapping[str, Any] | None = None,
    history: Sequence[PlayerHistory] = (),
    legend_comparison: Mapping[str, Any] | None = None,
) -> ReportStructure:
    """Assemble the report structure from analysis.reasoned + metrics + history.

    ``legend_comparison`` is M15's ``benchmark.compared`` payload (via
    :class:`~report_service.domain.sources.LegendSource`), or None when M15
    has not produced one yet — the legend section is honestly omitted rather
    than faked.
    """
    findings = reasoned.get("findings", [])
    findings = findings if isinstance(findings, list) else []

    panels = build_metric_panels(biomechanics=biomechanics, physics=physics)
    panel_dicts = [p.to_dict() for p in panels]

    improvement = compute_improvement(panel_dicts, list(history))
    scores = compute_scores(findings, _facts_map(biomechanics, physics), improvement=improvement)

    match_risk = reasoned.get("match_risk", {})
    legend_view = build_legend_view(legend_comparison)

    return ReportStructure(
        correlation_id=str(reasoned.get("correlation_id", "")),
        person_id=reasoned.get("person_id"),
        shot_type=reasoned.get("shot_type"),
        shot_confidence=reasoned.get("shot_confidence"),
        kg_version=str(reasoned.get("kg_version", "")),
        findings=findings,
        metric_panels=panels,
        scores=scores,
        match_risk=match_risk if isinstance(match_risk, dict) else {},
        provisional=bool(reasoned.get("provisional", False)),
        legend_view=legend_view.to_dict() if legend_view is not None else None,
    )


def attach_video(report: ReportStructure, video: AnnotatedVideo) -> ReportStructure:
    """Fill in the report's annotated-video section (Step 3)."""
    return replace(
        report,
        annotated_video_ref=video.video_ref,
        video_markers=tuple(m.to_dict() for m in video.markers),
        video_overlays_applied=video.overlays_applied,
    )


def attach_narrative(report: ReportStructure, narrative: Narrative) -> ReportStructure:
    """Fill in the report's grounded narrative (Step 5)."""
    return replace(
        report,
        narrative_text=narrative.text,
        narrative_citations=narrative.citations,
    )
