"""Report + AI Coach API routes — M14 §12.

  GET  /v1/reports/{correlation_id}   fetch a report (auth + consent scoped)
  POST /v1/coach/messages             ask the AI Coach a question (grounded)
  GET  /v1/coach/{session_id}         retrieve a coach conversation

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header. A coach question that
isn't entitled (AI Coach is a Pro feature, Step 7) is rejected with 403
before any LLM call — the same pattern M05 uses for its analysis quota.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cip_core import (
    AuthenticatedPrincipal,
    Forbidden,
    NotFound,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session
from report_service.deps import Deps, get_deps
from report_service.domain import reports_repo
from report_service.domain.evidence import build_evidence
from report_service.service import ask_coach

reports_router = APIRouter(prefix="/v1/reports", tags=["reports"])
coach_router = APIRouter(prefix="/v1/coach", tags=["coach"])


class ReportResponse(BaseModel):
    correlation_id: str
    person_id: uuid.UUID | None
    kg_version: str
    structure: dict[str, Any]
    scores: dict[str, Any]
    annotated_video_ref: str | None
    schema_version: str
    provisional: bool
    created_at: datetime
    updated_at: datetime


def _to_report_response(row: dict[str, Any]) -> ReportResponse:
    return ReportResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        kg_version=row["kg_version"],
        structure=row["structure"],
        scores=row["scores"],
        annotated_video_ref=row["annotated_video_ref"],
        schema_version=row["schema_version"],
        provisional=row["provisional"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@reports_router.get("/{correlation_id}", response_model=ReportResponse)
async def read_report(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ReportResponse:
    """Retrieve a report. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await reports_repo.get_report(session, correlation_id)
    if row is None:
        raise NotFound("report not found")
    return _to_report_response(row)


class CoachMessageRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=64)
    person_id: uuid.UUID
    question: str = Field(..., min_length=1, max_length=2000)
    coach_session_id: uuid.UUID | None = None


class CoachMessageResponse(BaseModel):
    coach_session_id: uuid.UUID
    text: str
    citations: list[str]
    deferred: bool


@coach_router.post("/messages", response_model=CoachMessageResponse)
async def post_coach_message(
    body: CoachMessageRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> CoachMessageResponse:
    """Ask the AI Coach; 403 (no LLM call) when AI Coach isn't entitled."""
    tenant_id = require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        report_row = await reports_repo.get_report(session, body.correlation_id)
    if report_row is None:
        raise NotFound("report not found for this correlation_id")

    structure = report_row["structure"]
    evidence = build_evidence(
        findings=structure.get("findings", []), legend_view=structure.get("legend_view")
    )

    coach_session_id, result = await ask_coach(
        session_factory=deps.session_factory,
        entitlement=deps.entitlement,
        llm=deps.coach_llm,
        tenant_id=tenant_id,
        person_id=body.person_id,
        coach_session_id=body.coach_session_id,
        question=body.question,
        evidence=evidence,
    )
    if not result.allowed:
        raise Forbidden("The AI Coach is a Pro feature", details={"reason": result.denial_reason})

    answer = result.answer
    if answer is None:
        # Invariant of ask_gated: allowed=True always carries an answer.
        raise RuntimeError("ask_gated returned allowed=True with no answer")
    return CoachMessageResponse(
        coach_session_id=coach_session_id,
        text=answer.text,
        citations=list(answer.citations),
        deferred=answer.deferred,
    )


class CoachMessageItem(BaseModel):
    role: str
    content: str
    citations: list[str]
    deferred: bool
    created_at: datetime


class CoachConversationResponse(BaseModel):
    coach_session_id: uuid.UUID
    messages: list[CoachMessageItem]


@coach_router.get("/{session_id}", response_model=CoachConversationResponse)
async def read_coach_conversation(
    session_id: uuid.UUID,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> CoachConversationResponse:
    """Retrieve a coach conversation. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        coach_session = await reports_repo.get_coach_session(session, session_id)
        if coach_session is None:
            raise NotFound("coach session not found")
        messages = await reports_repo.list_coach_messages(session, session_id)

    return CoachConversationResponse(
        coach_session_id=session_id,
        messages=[
            CoachMessageItem(
                role=row["role"],
                content=row["content"],
                citations=row["citations"],
                deferred=row["deferred"],
                created_at=row["created_at"],
            )
            for row in messages
        ],
    )
