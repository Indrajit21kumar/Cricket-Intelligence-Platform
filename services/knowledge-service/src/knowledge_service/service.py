"""Authoring service — the draft -> review -> approve workflow (M12 §6, §12, Step 3).

The governance heart of M12. Rules are authored as drafts, submitted for review,
and approved by a (distinct) expert reviewer before they can ever be released.
This module enforces the invariants that keep the knowledge trustworthy:

- every lifecycle move is a legal transition (:mod:`lifecycle`);
- a rule is always well-formed (:func:`validate_rule`) — a malformed edit is
  rejected, never half-stored;
- **separation of duties**: a reviewer may not approve a rule they authored;
- every authoring/review action is audited (FR-M12-09, AC-M12-07).

The store is global, so all writes run under ``admin_session``; RBAC is enforced
at the route layer.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import Conflict, Forbidden, NotFound, Unprocessable, audit_record
from cip_data import admin_session
from knowledge_service.domain import rules_repo
from knowledge_service.domain.lifecycle import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    can_transition,
)
from knowledge_service.domain.rule_schema import RuleValidationError, validate_rule

DECISION_APPROVE = "approve"
DECISION_REQUEST_CHANGES = "request_changes"
DECISION_REJECT = "reject"
DECISIONS = frozenset({DECISION_APPROVE, DECISION_REQUEST_CHANGES, DECISION_REJECT})

# Content fields an edit may replace (never status / version / rule_id / author).
_EDITABLE = ("conditions", "fault", "cause", "risk", "drill", "confidence")


def _validate(payload: dict[str, Any]) -> Any:
    try:
        return validate_rule(payload)
    except RuleValidationError as exc:
        raise Unprocessable(f"invalid rule: {exc}") from exc


async def create_draft(
    session_factory: async_sessionmaker[Any], *, payload: dict[str, Any], author: str
) -> dict[str, Any]:
    """Create a new rule draft. Rejects a malformed rule or a duplicate version."""
    rule = _validate({**payload, "status": STATUS_DRAFT})
    async with admin_session(session_factory) as session:
        if await rules_repo.get_version(session, rule.rule_id, rule.version) is not None:
            raise Conflict(f"rule {rule.rule_id} v{rule.version} already exists")
        row = await rules_repo.insert_rule(session, rule, author=author)
        await audit_record(
            session,
            action="kg.rule.drafted",
            entity=f"rule:{rule.rule_id}:v{rule.version}",
            actor=author,
            meta={"row_id": str(row["id"])},
        )
    return row


def _merge_for_edit(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "rule_id": current["rule_id"],
        "version": current["version"],
        "conditions": current["conditions"],
        "fault": current["fault"],
        "cause": current["cause"],
        "risk": current["risk"],
        "drill": current["drill"],
        "confidence": current["confidence"],
        "status": STATUS_DRAFT,
    }
    for key in _EDITABLE:
        if key in patch:
            merged[key] = patch[key]
    return merged


async def edit_draft(
    session_factory: async_sessionmaker[Any], *, row_id: Any, patch: dict[str, Any], actor: str
) -> dict[str, Any]:
    """Replace a draft's content. Only a draft may be edited."""
    async with admin_session(session_factory) as session:
        current = await rules_repo.get_by_id(session, row_id)
        if current is None:
            raise NotFound("rule not found")
        if current["status"] != STATUS_DRAFT:
            raise Conflict(f"only a draft can be edited (status is {current['status']})")
        rule = _validate(_merge_for_edit(current, patch))
        row = await rules_repo.update_content(session, row_id, rule)
        await audit_record(
            session,
            action="kg.rule.edited",
            entity=f"rule:{current['rule_id']}:v{current['version']}",
            actor=actor,
            meta={"row_id": str(row_id)},
        )
    return row


async def submit_for_review(
    session_factory: async_sessionmaker[Any], *, row_id: Any, actor: str
) -> dict[str, Any]:
    """Move a draft into review."""
    async with admin_session(session_factory) as session:
        current = await rules_repo.get_by_id(session, row_id)
        if current is None:
            raise NotFound("rule not found")
        if not can_transition(current["status"], STATUS_IN_REVIEW):
            raise Conflict(f"cannot submit a rule in status {current['status']}")
        row = await rules_repo.set_status(session, row_id, STATUS_IN_REVIEW)
        await audit_record(
            session,
            action="kg.rule.submitted",
            entity=f"rule:{current['rule_id']}:v{current['version']}",
            actor=actor,
            meta={"row_id": str(row_id)},
        )
    return row


async def review(
    session_factory: async_sessionmaker[Any],
    *,
    row_id: Any,
    decision: str,
    reviewer: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Approve / request-changes / reject a rule in review."""
    if decision not in DECISIONS:
        raise Unprocessable(f"decision must be one of {sorted(DECISIONS)}")
    async with admin_session(session_factory) as session:
        current = await rules_repo.get_by_id(session, row_id)
        if current is None:
            raise NotFound("rule not found")
        if current["status"] != STATUS_IN_REVIEW:
            raise Conflict(f"only a rule in review can be reviewed (status is {current['status']})")

        if decision == DECISION_APPROVE:
            # Separation of duties: a reviewer cannot approve their own authored rule.
            if current["author"] and current["author"] == reviewer:
                raise Forbidden("a reviewer may not approve a rule they authored")
            target = STATUS_APPROVED
        else:
            target = STATUS_DRAFT  # request_changes / reject bounce back to draft

        row = await rules_repo.set_status(session, row_id, target, reviewer=reviewer)
        await audit_record(
            session,
            action="kg.rule.reviewed",
            entity=f"rule:{current['rule_id']}:v{current['version']}",
            actor=reviewer,
            meta={"row_id": str(row_id), "decision": decision, "note": note, "result": target},
        )
    return row


async def get_rule_versions(
    session_factory: async_sessionmaker[Any], *, rule_id: str
) -> list[dict[str, Any]]:
    async with admin_session(session_factory) as session:
        return await rules_repo.list_versions(session, rule_id)
