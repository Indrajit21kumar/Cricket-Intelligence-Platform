"""Trust Doctrine enforcement (M11 §13, Step 6, FR-M11-04, AC-M11-03).

The hard rule of the whole module: no ESTIMATED quantity is ever labelled or
rendered as MEASURED, and every estimate that has a value carries a confidence.
Presenting an estimate as a measurement would destroy trust faster than any
inaccuracy (§2), so it must be impossible, not merely avoided.

By construction it already is: every quantity is built through a helper that
reads its provenance from the catalogue (so provenance cannot drift per call
site) and every estimate is given a confidence by the confidence model. This
module is the belt-and-braces check that verifies the invariant on the assembled
report and raises if it was ever violated — a code bug, never a data condition,
hence an internal error rather than a soft flag.
"""

from __future__ import annotations

from collections.abc import Mapping

from physics_service.domain.quantities import CATALOGUE, PhysicsQuantity


class TrustDoctrineError(Exception):
    """A quantity broke the provenance/confidence invariant — a code bug."""


def enforce_trust(quantities: Mapping[str, PhysicsQuantity]) -> None:
    """Assert every quantity honours the trust doctrine, or raise.

    - a quantity's provenance MUST equal its catalogue provenance (no estimate
      mislabelled measured, and no measured quantity mislabelled estimated);
    - every ESTIMATED quantity that HAS a value MUST carry a confidence.
    """
    for quantity_id, quantity in quantities.items():
        definition = CATALOGUE.get(quantity_id)
        if definition is None:
            raise TrustDoctrineError(f"unknown quantity {quantity_id!r}")
        if quantity.provenance != definition.provenance:
            raise TrustDoctrineError(
                f"{quantity_id} is labelled {quantity.provenance!r} but the catalogue "
                f"says {definition.provenance!r} — an estimate must never read as measured"
            )
        if quantity.is_estimated and quantity.value is not None and quantity.confidence is None:
            raise TrustDoctrineError(f"{quantity_id} is an estimate with a value but no confidence")
