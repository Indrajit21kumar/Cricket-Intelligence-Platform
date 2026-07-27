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

from fastapi import APIRouter, Depends, status
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
