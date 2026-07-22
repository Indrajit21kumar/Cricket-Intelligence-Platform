"""Proration math for mid-cycle plan changes (M03 Step 5, FR-M03-06).

When a subject changes plan partway through a billing period we settle the
*unused* remainder fairly:

- credit back the unused fraction of what they already paid for the OLD plan;
- charge the same unused fraction of the NEW plan for the rest of the period.

``net = charge - credit``. A net > 0 is owed by the customer (an upgrade
usually); a net < 0 is a credit back to them (a downgrade usually).

The maths is deliberately pure + integer-only so it is trivially unit-testable
against typical / boundary / degenerate fixtures (Book 3 Ch. 6) and never
introduces floating-point drift into money:

- fraction = clamp(remaining_seconds / period_seconds, 0..1)
- amounts use floor division on minor units (paise) — deterministic, and
  rounding *down* never over-charges or over-credits by more than a paisa.

CIP never moves money here (§11): this computes the intent only. Step 6 turns
a proration into an invoice the payment provider settles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Proration:
    """The settlement for a mid-cycle change, in minor currency units."""

    fraction_remaining: float  # 0.0 (period over) .. 1.0 (whole period left)
    credit_minor: int  # unused remainder of the OLD plan, credited back
    charge_minor: int  # remaining portion of the NEW plan, charged now
    net_minor: int  # charge - credit; >0 customer owes, <0 credit to customer


def compute_proration(
    *,
    old_price_minor: int,
    new_price_minor: int,
    period_start: datetime,
    period_end: datetime,
    at: datetime,
) -> Proration:
    """Prorate a plan change happening at ``at`` within ``[start, end)``.

    Boundaries:
    - ``at`` at/after ``period_end`` (or a zero/negative-length period) leaves
      no remainder -> fraction 0.0, credit 0, charge 0, net 0.
    - ``at`` at/before ``period_start`` leaves the whole period -> fraction
      1.0, credit = old price, charge = new price.
    """
    span_seconds = int((period_end - period_start).total_seconds())
    if span_seconds <= 0:
        return Proration(fraction_remaining=0.0, credit_minor=0, charge_minor=0, net_minor=0)

    remaining_seconds = int((period_end - at).total_seconds())
    remaining_seconds = max(0, min(span_seconds, remaining_seconds))

    credit = old_price_minor * remaining_seconds // span_seconds
    charge = new_price_minor * remaining_seconds // span_seconds
    return Proration(
        fraction_remaining=remaining_seconds / span_seconds,
        credit_minor=credit,
        charge_minor=charge,
        net_minor=charge - credit,
    )
