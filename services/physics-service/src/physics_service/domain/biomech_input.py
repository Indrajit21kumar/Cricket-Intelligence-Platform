"""The BiomechanicsReport as M11 sees it — the purity seam (M11 §4, FR-M11-02).

M11 consumes the M10 report and MUST NOT re-derive kinematics from raw pose or
video. This module is the ONE place that reads the report's wire shape; the
compute reads :class:`BiomechanicsInput` and nothing else. So the purity
boundary is enforced structurally: there is no pose, no video, no M05
calibration reachable from here — only the report M10 published.

M11 depends on the *contract* (the ``BM-01``..``BM-17`` string keys and the
quality block M10 emits), not on the biomechanics-service package. The BM ids
below are those wire keys, named by what they mean, so the physics code reads
in physical terms rather than opaque ids.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# --- the M10 metric wire keys M11 reads (BM-01..BM-17), named by meaning ---
BM_HEAD_STABILITY = "BM-01"
BM_SHOULDER_ROTATION = "BM-02"
BM_HIP_ROTATION = "BM-03"
BM_X_FACTOR = "BM-04"  # hip-shoulder separation
BM_PELVIC_TILT = "BM-05"
BM_FRONT_KNEE_FLEXION = "BM-06"
BM_FOOT_ALIGNMENT = "BM-07"
BM_STRIDE_LENGTH = "BM-08"
BM_BACKLIFT = "BM-09"
BM_BAT_PATH_LINEARITY = "BM-10"
BM_BAT_LAG = "BM-11"
BM_HAND_SPEED = "BM-12"
BM_FOLLOW_THROUGH = "BM-13"
BM_BALANCE_RECOVERY = "BM-14"
BM_WEIGHT_TRANSFER = "BM-15"
BM_COM_PATH = "BM-16"
BM_GROUND_CONTACT_TIMING = "BM-17"

# --- phase-boundary keys ---
PHASE_STANCE = "stance"
PHASE_BACKLIFT = "backlift"
PHASE_DOWNSWING = "downswing"
PHASE_IMPACT = "impact"
PHASE_FOLLOW_THROUGH = "follow_through"

# --- M10 quality flags M11 propagates ---
FLAG_ABSOLUTE_TIMING = "ABSOLUTE_TIMING"
FLAG_BAT_LOSS = "BAT_DETECTION_LOSS"


@dataclass(frozen=True, slots=True)
class MetricInput:
    """One BM metric as it arrived in the report: value + provenance + trust."""

    value: float | None
    provenance: str
    confidence: float
    provisional: bool = False
    disabled_reason: str | None = None

    @property
    def usable(self) -> bool:
        """A value M11 can build on: present and not a disabled placeholder."""
        return self.value is not None and self.disabled_reason is None


@dataclass(frozen=True, slots=True)
class BiomechanicsInput:
    """The whole M10 report, typed — the only input the physics compute reads."""

    correlation_id: str
    person_id: str | None
    shot_type: str | None
    shot_confidence: float | None
    phase_boundaries: Mapping[str, int]
    phase_method: str
    metrics: Mapping[str, MetricInput]
    #: Capture rate (report quality block, schema 1.1) — gives the frame-indexed
    #: phase boundaries a timescale. M11 reads this rather than the calibration.
    fps: float
    spatial_confidence: str
    depth_estimated: bool
    mean_pose_confidence: float
    provisional: bool
    flags: tuple[str, ...]
    out_of_expected_range: bool
    schema_version: str

    def metric(self, metric_id: str) -> MetricInput | None:
        return self.metrics.get(metric_id)

    def value(self, metric_id: str) -> float | None:
        """The usable value of a metric, or None if absent/disabled."""
        mi = self.metrics.get(metric_id)
        return mi.value if mi is not None and mi.usable else None

    def confidence(self, metric_id: str) -> float:
        mi = self.metrics.get(metric_id)
        return mi.confidence if mi is not None else 0.0

    def is_provisional(self, metric_id: str) -> bool:
        mi = self.metrics.get(metric_id)
        return mi.provisional if mi is not None else False

    def has_flag(self, flag: str) -> bool:
        return flag in self.flags

    def phase(self, name: str) -> int | None:
        return self.phase_boundaries.get(name)

    def downswing_duration_s(self) -> float | None:
        """Seconds from downswing start to impact — the interval the trunk
        rotates and the hands accelerate through. None when it cannot be
        resolved (no fps, or a collapsed/degenerate window)."""
        start = self.phase(PHASE_DOWNSWING)
        end = self.phase(PHASE_IMPACT)
        if start is None or end is None or self.fps <= 0 or end <= start:
            return None
        return (end - start) / self.fps


def _metric_input(raw: Any) -> MetricInput:
    """Parse one metric entry from the report payload."""
    if not isinstance(raw, Mapping):
        return MetricInput(value=None, provenance="measured", confidence=0.0)
    value = raw.get("value")
    return MetricInput(
        value=float(value) if isinstance(value, int | float) else None,
        provenance=str(raw.get("provenance", "measured")),
        confidence=float(raw.get("confidence", 0.0) or 0.0),
        provisional=bool(raw.get("provisional", False)),
        disabled_reason=raw.get("disabled_reason"),
    )


def _int_map(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, int] = {}
    for key, val in raw.items():
        if isinstance(val, int):
            out[str(key)] = val
    return out


def from_report_payload(payload: Mapping[str, Any]) -> BiomechanicsInput:
    """Build the typed input from an M10 ``biomechanics.metrics`` payload.

    This is the sole reader of the report's wire shape. Everything downstream
    reads :class:`BiomechanicsInput`, so the compute never depends on the
    payload layout — or, structurally, on anything upstream of the report.
    """
    metrics_raw = payload.get("metrics", {})
    metrics = {
        str(mid): _metric_input(entry)
        for mid, entry in (metrics_raw.items() if isinstance(metrics_raw, Mapping) else [])
    }
    quality = payload.get("quality", {})
    quality = quality if isinstance(quality, Mapping) else {}
    flags_raw = quality.get("flags", [])
    flags = tuple(str(f) for f in flags_raw) if isinstance(flags_raw, list | tuple) else ()

    return BiomechanicsInput(
        correlation_id=str(payload.get("correlation_id", "")),
        person_id=(str(payload["person_id"]) if payload.get("person_id") else None),
        shot_type=payload.get("shot_type"),
        shot_confidence=payload.get("shot_confidence"),
        phase_boundaries=_int_map(payload.get("phase_boundaries")),
        phase_method=str(payload.get("phase_method", "")),
        metrics=metrics,
        fps=float(quality.get("fps", 0.0) or 0.0),
        spatial_confidence=str(quality.get("spatial_confidence", "low")),
        depth_estimated=bool(quality.get("depth_estimated", True)),
        mean_pose_confidence=float(quality.get("mean_pose_confidence", 0.0) or 0.0),
        provisional=bool(payload.get("provisional", False)),
        flags=flags,
        out_of_expected_range=bool(payload.get("out_of_expected_range", False)),
        schema_version=str(payload.get("schema_version", "")),
    )
