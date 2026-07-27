"""Canonical CIP role names — the six roles Book 2 §5.2 defines.

Roles are scoped to a tenant (except ``PLATFORM_ADMIN``). Every service
that RBAC-guards an endpoint imports these constants; string literals
elsewhere are drift and should be caught in code review.
"""

from __future__ import annotations

from typing import Final

PLAYER: Final[str] = "player"
PARENT: Final[str] = "parent"
COACH: Final[str] = "coach"
ACADEMY_ADMIN: Final[str] = "academy_admin"
ORG_ADMIN: Final[str] = "org_admin"
PLATFORM_ADMIN: Final[str] = "platform_admin"

ALL_ROLES: Final[tuple[str, ...]] = (
    PLAYER,
    PARENT,
    COACH,
    ACADEMY_ADMIN,
    ORG_ADMIN,
    PLATFORM_ADMIN,
)

#: Roles that can manage tenant membership (add/remove members, assign roles).
TENANT_ADMIN_ROLES: Final[tuple[str, ...]] = (
    ACADEMY_ADMIN,
    ORG_ADMIN,
    PLATFORM_ADMIN,
)

#: Roles that can see analytical data for players.
COACHING_ROLES: Final[tuple[str, ...]] = (COACH, ACADEMY_ADMIN, ORG_ADMIN)

# --- knowledge-graph governance roles (M12) -----------------------------------
# The knowledge graph is platform-global coaching IP, so authoring is governed
# by dedicated platform-level roles, not the tenant coaching roles. Separation
# of duties: an author drafts, a (distinct) reviewer approves.
RULE_AUTHOR: Final[str] = "rule_author"
RULE_REVIEWER: Final[str] = "rule_reviewer"

#: May create/edit drafts and submit them for review.
KG_AUTHORING_ROLES: Final[tuple[str, ...]] = (RULE_AUTHOR, RULE_REVIEWER, PLATFORM_ADMIN)
#: May approve/reject a rule under review (the expert reviewer).
KG_REVIEW_ROLES: Final[tuple[str, ...]] = (RULE_REVIEWER, PLATFORM_ADMIN)
