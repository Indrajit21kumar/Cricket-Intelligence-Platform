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

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import Conflict, Forbidden, NotFound, Unprocessable, audit_record
from cip_data import admin_session
from knowledge_service.domain import (
    conflicts_repo,
    rules_repo,
    sources_repo,
    versions_repo,
)
from knowledge_service.domain.lifecycle import (
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    STATUS_RELEASED,
    STATUS_SUPERSEDED,
    can_transition,
)
from knowledge_service.domain.matcher import MatchFacts, select_matches
from knowledge_service.domain.ontology import REL_CONTRADICTED_BY, REL_SUPPORTED_BY
from knowledge_service.domain.rag import RagQuery, ground
from knowledge_service.domain.rule_schema import RuleValidationError, validate_rule


def _evidence_block(row: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    """The Book 10 evidence served alongside a rule — tier + who signed it off +
    the cited sources. Tier and validated_by are surfaced as-is so downstream
    (M14) renders them honestly and never presents Tier 2/3 as validated."""
    return {
        "tier": row.get("evidence_tier"),
        "validated_by": row.get("validated_by"),
        "contradicts_tradition": bool(row.get("contradicts_tradition", False)),
        "contradiction_note": row.get("contradiction_note"),
        "sources": [
            {
                "source_id": str(s["source_id"]),
                "relation": s["relation"],
                "locator": s.get("locator"),
                "title": s.get("title"),
                "authors": s.get("authors"),
                "year": s.get("year"),
                "authority": s.get("authority"),
                "url_or_ref": s.get("url_or_ref"),
                "vetted_by": s.get("vetted_by"),
            }
            for s in sources
        ],
    }


def _snapshot(row: dict[str, Any], sources: list[dict[str, Any]]) -> dict[str, Any]:
    """The frozen, citable content of a rule row + its evidence (Book 10)."""
    return {
        "rule_id": row["rule_id"],
        "version": row["version"],
        "conditions": row["conditions"],
        "fault": row["fault"],
        "cause": row["cause"],
        "risk": row["risk"],
        "drill": row["drill"],
        "confidence": row["confidence"],
        "evidence": _evidence_block(row, sources),
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

        # Book 10 vetting gate: a rule carrying evidence may only be released once
        # its sources are SAB-vetted and its tier is signed off, and a tradition-
        # contradicting rule must cite the contradicting source (never dropped).
        sources = await sources_repo.sources_for_rule(session, current["rule_id"])
        _check_evidence_gate(current, sources)

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
            snapshot=_snapshot(current, sources),
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


def _check_evidence_gate(rule: dict[str, Any], sources: list[dict[str, Any]]) -> None:
    """Block release of a rule whose evidence is not fully vetted (FR-M12-12/14)."""
    has_evidence = rule.get("evidence_tier") is not None or bool(sources)
    if has_evidence:
        if any(not s.get("vetted_by") for s in sources):
            raise Conflict("cannot release: a linked source is not SAB-vetted")
        if rule.get("validated_by") is None:
            raise Conflict("cannot release: the evidence tier is not signed off (validated_by)")
    if rule.get("contradicts_tradition") and not any(
        s["relation"] == REL_CONTRADICTED_BY for s in sources
    ):
        raise Conflict(
            "a tradition-contradicting rule must cite the contradicting source, not drop it"
        )


async def create_source(
    session_factory: async_sessionmaker[Any], *, payload: dict[str, Any], actor: str
) -> dict[str, Any]:
    """Register a cited source (unvetted until SAB sign-off)."""
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        raise Unprocessable("source.title is required")
    async with admin_session(session_factory) as session:
        row = await sources_repo.insert_source(
            session,
            type_=str(payload.get("type", "paper")),
            title=title,
            authors=payload.get("authors"),
            year=payload.get("year"),
            authority=payload.get("authority"),
            url_or_ref=payload.get("url_or_ref"),
            license_note=payload.get("license_note"),
        )
        await audit_record(
            session,
            action="kg.source.created",
            entity=f"source:{row['id']}",
            actor=actor,
            meta={"title": title},
        )
    return row


async def vet_source(
    session_factory: async_sessionmaker[Any],
    *,
    source_id: uuid.UUID,
    vetted_by: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """SAB sign-off on a source (records the reviewer + credential)."""
    async with admin_session(session_factory) as session:
        row = await sources_repo.vet_source(session, source_id, vetted_by=vetted_by)
        if row is None:
            raise NotFound("source not found")
        await audit_record(
            session,
            action="kg.source.vetted",
            entity=f"source:{source_id}",
            actor=actor,
            meta={"vetted_by": vetted_by},
        )
    return row


async def attach_source(
    session_factory: async_sessionmaker[Any],
    *,
    row_id: uuid.UUID,
    source_id: uuid.UUID,
    relation: str,
    locator: str | None,
    actor: str,
) -> dict[str, Any]:
    """Link a source to a rule (supported_by / contradicted_by)."""
    if relation not in (REL_SUPPORTED_BY, REL_CONTRADICTED_BY):
        raise Unprocessable(f"relation must be {REL_SUPPORTED_BY} or {REL_CONTRADICTED_BY}")
    async with admin_session(session_factory) as session:
        rule = await rules_repo.get_by_id(session, row_id)
        if rule is None:
            raise NotFound("rule not found")
        if rule["status"] == STATUS_RELEASED:
            raise Conflict("cannot change the evidence of a released rule; supersede it instead")
        if await sources_repo.get_source(session, source_id) is None:
            raise NotFound("source not found")
        link = await sources_repo.link_source(
            session,
            rule_id=rule["rule_id"],
            source_id=source_id,
            relation=relation,
            locator=locator,
        )
        await audit_record(
            session,
            action="kg.rule.source_linked",
            entity=f"rule:{rule['rule_id']}:v{rule['version']}",
            actor=actor,
            meta={"source_id": str(source_id), "relation": relation},
        )
    return link


async def set_rule_evidence(
    session_factory: async_sessionmaker[Any],
    *,
    row_id: uuid.UUID,
    evidence_tier: int | None,
    contradicts_tradition: bool,
    contradiction_note: str | None,
    validated_by: dict[str, Any] | None,
    actor: str,
) -> dict[str, Any]:
    """Set a rule's evidence tier + SAB sign-off (Book 10)."""
    if evidence_tier is not None and evidence_tier not in (1, 2, 3):
        raise Unprocessable("evidence_tier must be 1 (validated), 2 (consensus), or 3 (folklore)")
    async with admin_session(session_factory) as session:
        rule = await rules_repo.get_by_id(session, row_id)
        if rule is None:
            raise NotFound("rule not found")
        if rule["status"] == STATUS_RELEASED:
            raise Conflict("cannot change the evidence of a released rule; supersede it instead")
        row = await rules_repo.set_evidence(
            session,
            row_id,
            evidence_tier=evidence_tier,
            contradicts_tradition=contradicts_tradition,
            contradiction_note=contradiction_note,
            validated_by=json.dumps(validated_by) if validated_by is not None else None,
        )
        await audit_record(
            session,
            action="kg.rule.evidence_set",
            entity=f"rule:{rule['rule_id']}:v{rule['version']}",
            actor=actor,
            meta={"tier": evidence_tier, "validated_by": validated_by},
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


async def adjust_confidence(
    session_factory: async_sessionmaker[Any],
    *,
    row_id: uuid.UUID,
    confidence: float,
    actor: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Evidence-driven confidence adjustment (FR-M12-08), fully audited.

    Confidence is the one quantity §6 lets drift within a pinned version, so a
    released rule's served snapshot confidence is updated too — the version's
    logic (conditions/fault/cause/risk/drill) is untouched, preserving
    reproduction.
    """
    if not 0.0 <= confidence <= 1.0:
        raise Unprocessable("confidence must be in [0, 1]")
    async with admin_session(session_factory) as session:
        current = await rules_repo.get_by_id(session, row_id)
        if current is None:
            raise NotFound("rule not found")
        old = current["confidence"]
        row = await rules_repo.set_confidence(session, row_id, confidence)
        if current["status"] == STATUS_RELEASED:
            await versions_repo.update_confidence(
                session,
                rule_id=current["rule_id"],
                version=current["version"],
                confidence=confidence,
            )
        await audit_record(
            session,
            action="kg.rule.confidence_adjusted",
            entity=f"rule:{current['rule_id']}:v{current['version']}",
            actor=actor,
            meta={"row_id": str(row_id), "old": old, "new": confidence, "reason": reason},
        )
    return row


async def record_conflict(
    session_factory: async_sessionmaker[Any],
    *,
    rule_a: str,
    rule_b: str,
    precedence: str | None,
    note: str | None,
    actor: str,
) -> dict[str, Any]:
    """Record a conflict between two rules (with optional resolving precedence)."""
    async with admin_session(session_factory) as session:
        row = await conflicts_repo.upsert_conflict(
            session, rule_a=rule_a, rule_b=rule_b, precedence=precedence, note=note
        )
        await audit_record(
            session,
            action="kg.conflict.recorded",
            entity=f"conflict:{rule_a}|{rule_b}",
            actor=actor,
            meta={"precedence": precedence, "resolved": row["resolved"]},
        )
    return row


async def resolve_conflict(
    session_factory: async_sessionmaker[Any],
    *,
    conflict_id: uuid.UUID,
    precedence: str,
    note: str | None,
    actor: str,
) -> dict[str, Any]:
    async with admin_session(session_factory) as session:
        row = await conflicts_repo.resolve_conflict(
            session, conflict_id, precedence=precedence, note=note
        )
        if row is None:
            raise NotFound("conflict not found")
        await audit_record(
            session,
            action="kg.conflict.resolved",
            entity=f"conflict:{conflict_id}",
            actor=actor,
            meta={"precedence": precedence},
        )
    return row


async def list_conflicts(
    session_factory: async_sessionmaker[Any], *, unresolved_only: bool = False
) -> list[dict[str, Any]]:
    async with admin_session(session_factory) as session:
        return await conflicts_repo.list_conflicts(session, unresolved_only=unresolved_only)


async def export_released(session_factory: async_sessionmaker[Any]) -> list[dict[str, Any]]:
    """Export the released graph (backup / offline review, FR-M12-10)."""
    async with admin_session(session_factory) as session:
        return await versions_repo.list_released(session)


async def get_rule_versions(
    session_factory: async_sessionmaker[Any], *, rule_id: str
) -> list[dict[str, Any]]:
    async with admin_session(session_factory) as session:
        return await rules_repo.list_versions(session, rule_id)
