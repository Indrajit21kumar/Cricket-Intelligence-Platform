"""Rule lifecycle states + legal transitions (M12 §12).

    draft -> in_review -> approved -> released -> superseded

Only ``released`` rules in the pinned graph version are served to M13/M14
(NFR-M12-05). The transition map is the single source of truth for what an
authoring action may do; Step 3's workflow enforces it, and keeping it here
(not scattered across handlers) means an illegal transition is one check.
"""

from __future__ import annotations

from typing import Final

STATUS_DRAFT: Final[str] = "draft"
STATUS_IN_REVIEW: Final[str] = "in_review"
STATUS_APPROVED: Final[str] = "approved"
STATUS_RELEASED: Final[str] = "released"
STATUS_SUPERSEDED: Final[str] = "superseded"

STATUSES: Final[frozenset[str]] = frozenset(
    {STATUS_DRAFT, STATUS_IN_REVIEW, STATUS_APPROVED, STATUS_RELEASED, STATUS_SUPERSEDED}
)

#: The only status a served rule may have.
SERVABLE_STATUS: Final[str] = STATUS_RELEASED

#: Legal transitions: current status -> the statuses it may move to.
TRANSITIONS: Final[dict[str, frozenset[str]]] = {
    STATUS_DRAFT: frozenset({STATUS_IN_REVIEW}),
    # Review can approve, bounce back to draft (request changes), or reject.
    STATUS_IN_REVIEW: frozenset({STATUS_APPROVED, STATUS_DRAFT}),
    STATUS_APPROVED: frozenset({STATUS_RELEASED, STATUS_DRAFT}),
    STATUS_RELEASED: frozenset({STATUS_SUPERSEDED}),
    STATUS_SUPERSEDED: frozenset(),
}


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current, frozenset())
