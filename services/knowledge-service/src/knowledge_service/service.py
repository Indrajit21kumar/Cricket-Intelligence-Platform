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
from knowledge_service.domain import rules_repo, versions_repo
from knowledge_service.domain.lifecycle import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    STATUS_RELEASED,
    STATUS_SUPERSEDED,
    can_transition,
)
from knowledge_service.domain.matcher import MatchFacts, select_matches
from knowledge_service.domain.rag import RagQuery, ground
from knowledge_service.domain.rule_schema import RuleValidationError, validate_rule


def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
    """The frozen, citable content of a rule row (no mutable governance fields)."""
    return {
        "rule_id": row["rule_id"],
        "version": row["version"],
        "conditions": row["conditions"],
        "fault": row["fault"],
        "cause": row["cause"],
        "risk": row["risk"],
        "drill": row["drill"],
        "confidence": row["confidence"],
    }


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


async def release_rule(
    session_factory: async_sessionmaker[Any], *, row_id: Any, actor: str
) -> dict[str, Any]:
    """Pin an approved rule into the served graph (§12).

    Freezes the rule's content as an immutable ``rule_versions`` snapshot and
    flips its ``released`` pin. Any previously-released version of the same
    rule_id is superseded ATOMICALLY (its status -> superseded, its snapshot pin
    cleared) so the served graph never has two live versions of one rule — no
    mid-analysis drift (NFR-M12-02). The old snapshot stays for reproduction.
    """
    async with admin_session(session_factory) as session:
        current = await rules_repo.get_by_id(session, row_id)
        if current is None:
            raise NotFound("rule not found")
        if not can_transition(current["status"], STATUS_RELEASED):
            raise Conflict(f"only an approved rule can be released (status is {current['status']})")

        # Supersede the outgoing released version of this rule_id, if any.
        previous = await rules_repo.get_released(session, current["rule_id"])
        if previous is not None and previous["id"] != current["id"]:
            await rules_repo.set_status(session, previous["id"], STATUS_SUPERSEDED)
            await versions_repo.mark_unreleased(
                session, rule_id=previous["rule_id"], version=previous["version"]
            )

        await versions_repo.freeze_snapshot(
            session,
            rule_id=current["rule_id"],
            version=current["version"],
            snapshot=_snapshot(current),
            released=True,
        )
        row = await rules_repo.set_status(session, row_id, STATUS_RELEASED)
        await audit_record(
            session,
            action="kg.rule.released",
            entity=f"rule:{current['rule_id']}:v{current['version']}",
            actor=actor,
            meta={
                "row_id": str(row_id),
                "superseded": str(previous["id"]) if previous else None,
            },
        )
    return row


async def match_facts(
    session_factory: async_sessionmaker[Any], *, facts_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the RELEASED rules whose conditions the stroke's facts satisfy (M13)."""
    facts = MatchFacts.from_payload(facts_payload)
    async with admin_session(session_factory) as session:
        released = await versions_repo.list_released(session)
    return [m.to_dict() for m in select_matches(released, facts)]


async def query_knowledge(
    session_factory: async_sessionmaker[Any], *, query_payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return released knowledge for M14's RAG grounding, each with a citation."""
    query = RagQuery.from_payload(query_payload)
    async with admin_session(session_factory) as session:
        released = await versions_repo.list_released(session)
    return [item.to_dict() for item in ground(released, query)]


async def get_rule_versions(
    session_factory: async_sessionmaker[Any], *, rule_id: str
) -> list[dict[str, Any]]:
    async with admin_session(session_factory) as session:
        return await rules_repo.list_versions(session, rule_id)
