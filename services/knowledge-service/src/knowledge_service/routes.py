"""Knowledge-graph authoring API — M12 §11 (Step 3).

  POST  /v1/kg/rules            create a draft rule           (author role)
  PATCH /v1/kg/rules/{id}       edit a draft / submit review  (author role)
  POST  /v1/kg/rules/{id}/review  approve / request / reject  (reviewer role)
  GET   /v1/kg/rules/{ruleId}   read a rule + version history (any authed)

The knowledge graph is global (not tenant-scoped), so these routes take NO
tenant header; access is governed purely by RBAC (deny-by-default) + audit.
Authoring/serving separation and the serving APIs (match/query/release) arrive
in later steps.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from cip_core import (
    AuthenticatedPrincipal,
    BadRequest,
    NotFound,
    require_authenticated,
    require_role,
    roles,
)
from knowledge_service import service
from knowledge_service.deps import Deps, get_deps

kg_router = APIRouter(prefix="/v1/kg", tags=["knowledge"])
internal_router = APIRouter(prefix="/internal/kg", tags=["internal"])

_EDITABLE = ("conditions", "fault", "cause", "risk", "drill", "confidence")


class ReviewRequest(BaseModel):
    decision: str = Field(..., description="approve | request_changes | reject")
    note: str | None = None


class ReleaseRequest(BaseModel):
    row_id: uuid.UUID = Field(..., description="the approved rule version to pin into the graph")


class ConfidenceRequest(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str | None = None


class ConflictRequest(BaseModel):
    rule_a: str
    rule_b: str
    precedence: str | None = Field(None, description="rule_id that wins; None = still open")
    note: str | None = None


class ResolveConflictRequest(BaseModel):
    precedence: str = Field(..., description="the rule_id that takes precedence")
    note: str | None = None


class SourceRequest(BaseModel):
    type: str = Field("paper", description="paper | manual | expert")
    title: str
    authors: str | None = None
    year: int | None = None
    authority: str | None = None
    url_or_ref: str | None = None
    license_note: str | None = None


class VetRequest(BaseModel):
    reviewer: str
    credential: str


class AttachSourceRequest(BaseModel):
    source_id: uuid.UUID
    relation: str = Field(..., description="supported_by | contradicted_by")
    locator: str | None = None


class EvidenceRequest(BaseModel):
    evidence_tier: int | None = Field(None, ge=1, le=3)
    contradicts_tradition: bool = False
    contradiction_note: str | None = None
    validated_by: dict[str, Any] | None = None


class RuleResponse(BaseModel):
    id: uuid.UUID
    rule_id: str
    version: int
    conditions: list[dict[str, Any]]
    fault: str | None
    cause: str | None
    risk: dict[str, Any]
    drill: dict[str, Any]
    confidence: float | None
    status: str
    author: str | None
    reviewer: str | None
    created_at: datetime
    updated_at: datetime


def _to_response(row: dict[str, Any]) -> RuleResponse:
    return RuleResponse(
        id=row["id"],
        rule_id=row["rule_id"],
        version=row["version"],
        conditions=row["conditions"],
        fault=row["fault"],
        cause=row["cause"],
        risk=row["risk"],
        drill=row["drill"],
        confidence=row["confidence"],
        status=row["status"],
        author=row["author"],
        reviewer=row["reviewer"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@kg_router.post("/rules", response_model=RuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: dict[str, Any],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_AUTHORING_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleResponse:
    """Create a draft rule. Malformed rules and duplicate versions are rejected."""
    row = await service.create_draft(
        deps.session_factory, payload=body, author=str(principal.person_id)
    )
    return _to_response(row)


@kg_router.patch("/rules/{row_id}", response_model=RuleResponse)
async def edit_rule(
    row_id: uuid.UUID,
    body: dict[str, Any],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_AUTHORING_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleResponse:
    """Edit a draft and/or submit it for review."""
    submit = bool(body.pop("submit", False))
    actor = str(principal.person_id)
    has_edits = any(key in body for key in _EDITABLE)

    row: dict[str, Any] | None = None
    if has_edits:
        row = await service.edit_draft(deps.session_factory, row_id=row_id, patch=body, actor=actor)
    if submit:
        row = await service.submit_for_review(deps.session_factory, row_id=row_id, actor=actor)
    if row is None:
        raise BadRequest("nothing to do: provide edits and/or submit=true")
    return _to_response(row)


@kg_router.post("/rules/{row_id}/review", response_model=RuleResponse)
async def review_rule(
    row_id: uuid.UUID,
    body: ReviewRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleResponse:
    """Approve / request-changes / reject a rule in review (expert reviewer)."""
    row = await service.review(
        deps.session_factory,
        row_id=row_id,
        decision=body.decision,
        reviewer=str(principal.person_id),
        note=body.note,
    )
    return _to_response(row)


@kg_router.post("/release", response_model=RuleResponse)
async def release_rule(
    body: ReleaseRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleResponse:
    """Pin an approved rule into the served graph (immutable release)."""
    row = await service.release_rule(
        deps.session_factory, row_id=body.row_id, actor=str(principal.person_id)
    )
    return _to_response(row)


@kg_router.post("/rules/{row_id}/confidence", response_model=RuleResponse)
async def adjust_confidence(
    row_id: uuid.UUID,
    body: ConfidenceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleResponse:
    """Evidence-driven confidence adjustment (audited)."""
    row = await service.adjust_confidence(
        deps.session_factory,
        row_id=row_id,
        confidence=body.confidence,
        actor=str(principal.person_id),
        reason=body.reason,
    )
    return _to_response(row)


@kg_router.post("/conflicts", response_model=dict[str, Any])
async def record_conflict(
    body: ConflictRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    """Record a conflict between two rules, optionally with a resolving precedence."""
    return await service.record_conflict(
        deps.session_factory,
        rule_a=body.rule_a,
        rule_b=body.rule_b,
        precedence=body.precedence,
        note=body.note,
        actor=str(principal.person_id),
    )


@kg_router.get("/conflicts", response_model=list[dict[str, Any]])
async def list_conflicts(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
    unresolved: Annotated[bool, Query()] = False,
) -> list[dict[str, Any]]:
    """Surface conflicts to reviewers (optionally only the unresolved ones)."""
    return await service.list_conflicts(deps.session_factory, unresolved_only=unresolved)


@kg_router.post("/conflicts/{conflict_id}/resolve", response_model=dict[str, Any])
async def resolve_conflict(
    conflict_id: uuid.UUID,
    body: ResolveConflictRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    """Resolve a conflict by recording which rule takes precedence."""
    return await service.resolve_conflict(
        deps.session_factory,
        conflict_id=conflict_id,
        precedence=body.precedence,
        note=body.note,
        actor=str(principal.person_id),
    )


@kg_router.get("/export", response_model=list[dict[str, Any]])
async def export_graph(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[dict[str, Any]]:
    """Export the released graph for backup / offline review (FR-M12-10)."""
    return await service.export_released(deps.session_factory)


# --- evidence layer (Book 10) ---------------------------------------------------
@kg_router.post("/sources", response_model=dict[str, Any], status_code=status.HTTP_201_CREATED)
async def create_source(
    body: SourceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_AUTHORING_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    """Register a cited source (unvetted until SAB sign-off)."""
    return await service.create_source(
        deps.session_factory, payload=body.model_dump(), actor=str(principal.person_id)
    )


@kg_router.post("/sources/{source_id}/vet", response_model=dict[str, Any])
async def vet_source(
    source_id: uuid.UUID,
    body: VetRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    """SAB sign-off on a source (reviewer + credential)."""
    return await service.vet_source(
        deps.session_factory,
        source_id=source_id,
        vetted_by=body.model_dump(),
        actor=str(principal.person_id),
    )


@kg_router.post("/rules/{row_id}/sources", response_model=dict[str, Any])
async def attach_source(
    row_id: uuid.UUID,
    body: AttachSourceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_AUTHORING_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    """Link a source to a rule (supported_by / contradicted_by)."""
    return await service.attach_source(
        deps.session_factory,
        row_id=row_id,
        source_id=body.source_id,
        relation=body.relation,
        locator=body.locator,
        actor=str(principal.person_id),
    )


@kg_router.post("/rules/{row_id}/evidence", response_model=RuleResponse)
async def set_evidence(
    row_id: uuid.UUID,
    body: EvidenceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*roles.KG_REVIEW_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleResponse:
    """Set a rule's evidence tier + SAB sign-off (Book 10)."""
    row = await service.set_rule_evidence(
        deps.session_factory,
        row_id=row_id,
        evidence_tier=body.evidence_tier,
        contradicts_tradition=body.contradicts_tradition,
        contradiction_note=body.contradiction_note,
        validated_by=body.validated_by,
        actor=str(principal.person_id),
    )
    return _to_response(row)


class RuleHistoryResponse(BaseModel):
    rule_id: str
    versions: list[RuleResponse]


class MatchResponse(BaseModel):
    matched: list[dict[str, Any]]
    count: int


@internal_router.post("/match", response_model=MatchResponse)
async def match_rules(
    facts: dict[str, Any],
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> MatchResponse:
    """Facts (metrics/phases/shot/context) -> applicable RELEASED rules, for M13.

    Only rules in the pinned released graph are considered, so a draft or
    approved-but-unreleased rule never reaches reasoning (AC-M12-02).
    """
    matched = await service.match_facts(deps.session_factory, facts_payload=facts)
    return MatchResponse(matched=matched, count=len(matched))


class QueryResponse(BaseModel):
    results: list[dict[str, Any]]
    count: int


@internal_router.post("/query", response_model=QueryResponse)
async def query_knowledge(
    query: dict[str, Any],
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> QueryResponse:
    """RAG grounding for M14: released knowledge + rule_id/version citations.

    Draws only from the released graph, so the AI coach can never cite a draft
    (AC-M12-05, ENG-005).
    """
    results = await service.query_knowledge(deps.session_factory, query_payload=query)
    return QueryResponse(results=results, count=len(results))


@kg_router.get("/rules/{rule_id}", response_model=RuleHistoryResponse)
async def read_rule(
    rule_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RuleHistoryResponse:
    """Read a rule and its full version history."""
    rows = await service.get_rule_versions(deps.session_factory, rule_id=rule_id)
    if not rows:
        raise NotFound("rule not found")
    return RuleHistoryResponse(rule_id=rule_id, versions=[_to_response(r) for r in rows])
