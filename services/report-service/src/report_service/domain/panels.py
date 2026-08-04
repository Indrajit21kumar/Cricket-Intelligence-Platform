"""Metric panels — BM/PH values with provenance + confidence (M14 §5, Step 2, FR-M14-03).

Every number the player sees carries its provenance label and confidence, and
an estimated/modelled value is visibly distinct from a measured one (Book 0
§8, AC-M14-02). This module is a thin, honest passthrough of the M10/M11
payloads into the report's metric-panel shape — it adds no numbers, only
labels the ones already there.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: Why a metric could not be produced, in words a coach can act on. The keys
#: are M10's ``disabled_reason`` slugs; anything unmapped falls back to the raw
#: slug rather than being hidden, so a new reason cannot silently vanish.
WITHHELD_EXPLANATIONS: dict[str, str] = {
    "depth_unresolved": (
        "Rotation about the body's vertical axis needs two camera angles. "
        "A single camera cannot see it, so no value is reported."
    ),
    "scale_unresolved": (
        "No real-world scale was established for this clip, so distances and "
        "speeds cannot be given in centimetres or metres per second."
    ),
    "crease_axis_unresolved": (
        "The camera angle could not be resolved, so across-the-crease "
        "measurements are not reliable. Film side-on for these."
    ),
    "no_input_data": ("This measurement needs bat tracking, which is not available yet."),
}


@dataclass(frozen=True, slots=True)
class MetricPanelEntry:
    metric_id: str
    value: float | None
    unit: str | None
    provenance: str
    confidence: float | None
    provisional: bool = False
    disabled_reason: str | None = None
    #: Human-readable metric name from the M10 catalogue (e.g. "pelvic_tilt").
    name: str | None = None

    @property
    def delivered(self) -> bool:
        """True when this panel carries a number a coach can actually read."""
        return self.value is not None

    @property
    def withheld_explanation(self) -> str | None:
        """Plain-English reason this metric is absent, for the report."""
        if self.delivered:
            return None
        reason = self.disabled_reason or "no_input_data"
        return WITHHELD_EXPLANATIONS.get(reason, reason)

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "metric_id": self.metric_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "provisional": self.provisional,
            "disabled_reason": self.disabled_reason,
        }
        explanation = self.withheld_explanation
        if explanation is not None:
            entry["withheld_explanation"] = explanation
        return entry


def _panel_from_entries(raw: Any, *, unit_key: str = "unit") -> list[MetricPanelEntry]:
    panels: list[MetricPanelEntry] = []
    if not isinstance(raw, Mapping):
        return panels
    for metric_id, entry in raw.items():
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("value")
        panels.append(
            MetricPanelEntry(
                metric_id=str(metric_id),
                value=float(value) if isinstance(value, int | float) else None,
                unit=entry.get(unit_key),
                provenance=str(entry.get("provenance", "measured")),
                confidence=entry.get("confidence"),
                provisional=bool(entry.get("provisional", False)),
                disabled_reason=entry.get("disabled_reason") or entry.get("omitted_reason"),
                name=entry.get("name"),
            )
        )
    # Stable, readable order: BM ids then PH ids, numerically.
    panels.sort(key=lambda p: p.metric_id)
    return panels


def build_metric_panels(
    *, biomechanics: Mapping[str, Any], physics: Mapping[str, Any] | None = None
) -> list[MetricPanelEntry]:
    """Assemble the report's metric panels from the M10 + M11 payloads."""
    panels = _panel_from_entries(biomechanics.get("metrics"))
    if physics is not None:
        panels.extend(_panel_from_entries(physics.get("quantities")))
    return panels
