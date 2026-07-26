"""Expected-range check (M11 §8, Step 6, FR-M11-09).

A quantity outside its plausible range is FLAGGED for review, never rejected —
consistent with M10's policy. An out-of-range physics value is more often a
degraded input than a wrong batter, and silently dropping it would hide exactly
the strokes a coach or reviewer should see. So the check only returns which
quantities to flag; the value is always kept.
"""

from __future__ import annotations

from collections.abc import Mapping

from physics_service.domain.quantities import CATALOGUE, PhysicsQuantity


def check_ranges(quantities: Mapping[str, PhysicsQuantity]) -> tuple[str, ...]:
    """Return the ids of quantities whose value falls outside their range."""
    flagged: list[str] = []
    for quantity_id, quantity in quantities.items():
        if quantity.value is None:
            continue
        expected = CATALOGUE[quantity_id].expected_range
        if expected is None:
            continue
        low, high = expected
        if quantity.value < low or quantity.value > high:
            flagged.append(quantity_id)
    return tuple(flagged)
