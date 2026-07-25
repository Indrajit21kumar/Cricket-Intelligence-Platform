"""Range validation + review-queue routing (M10 Step 6, FR-M10-08, AC-M10-04).

A metric outside its physiologically plausible band is worth a human's eyes —
it might be a genuine outlier (a freak stroke), or a bad calibration, or a
formula edge case. What it is NOT is a reason to throw the report away. So this
step FLAGS out-of-range values and routes the report to the review queue, and
the value is emitted exactly as computed. Silently dropping it would hide both
the outlier and the possible bug.

The distinction that matters: these are *plausibility* ranges (catalogue
``expected_range``), not the mocap *accuracy* tolerances of Step 8. A value can
be perfectly accurate and still out of the usual range — an unusually side-on
stride, say — and that is precisely the case a coach should see rather than have
suppressed.

A disabled metric (Step 5 turned off an X-axis metric on a bad angle) is not
range-checked: there is no value to judge.
"""

from __future__ import annotations

from dataclasses import dataclass

from biomechanics_service.domain.catalogue import CATALOGUE
from biomechanics_service.domain.quality import MetricValue


@dataclass(frozen=True, slots=True)
class RangeResult:
    #: True when at least one metric fell outside its plausible band.
    out_of_range: bool
    #: The metric IDs that were out of range, for the review record.
    flagged: tuple[str, ...]


def check_ranges(metrics: dict[str, MetricValue]) -> RangeResult:
    """Flag out-of-range metrics for review. Never mutates or drops a value."""
    flagged: list[str] = []
    for metric_id, mv in metrics.items():
        if mv.value is None or mv.disabled_reason is not None:
            continue
        definition = CATALOGUE.get(metric_id)
        if definition is None or definition.expected_range is None:
            continue
        lo, hi = definition.expected_range
        if mv.value < lo or mv.value > hi:
            flagged.append(metric_id)
    return RangeResult(out_of_range=bool(flagged), flagged=tuple(flagged))
