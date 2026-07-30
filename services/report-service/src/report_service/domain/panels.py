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


@dataclass(frozen=True, slots=True)
class MetricPanelEntry:
    metric_id: str
    value: float | None
    unit: str | None
    provenance: str
    confidence: float | None
    provisional: bool = False
    disabled_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "value": self.value,
            "unit": self.unit,
            "provenance": self.provenance,
            "confidence": self.confidence,
            "provisional": self.provisional,
            "disabled_reason": self.disabled_reason,
        }


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
