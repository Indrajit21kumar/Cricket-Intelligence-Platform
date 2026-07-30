"""Benchmark API routes — M15 §10.

  GET  /v1/benchmarks/profiles          list available (released) profiles
  POST /internal/v1/benchmark/compare   sync compare (tests/reprocessing)
  GET  /v1/benchmarks/{correlation_id}  retrieve a comparison (auth + consent scoped)

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header for comparisons;
``benchmark_profiles`` is platform-global (read via ``admin_session``).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from benchmark_service.deps import Deps, get_deps
from benchmark_service.domain import comparisons_repo, profiles_repo
from benchmark_service.service import compare_stroke
from cip_core import (
    AuthenticatedPrincipal,
    NotFound,
    Unprocessable,
    require_authenticated,
    require_tenant_id,
)
from cip_data import admin_session, tenant_session

benchmarks_router = APIRouter(prefix="/v1/benchmarks", tags=["benchmarks"])
internal_router = APIRouter(prefix="/internal/v1/benchmark", tags=["internal"])


class ProfileSummary(BaseModel):
    benchmark_id: str
    type: str
    scope: dict[str, Any]
    version: int


@benchmarks_router.get("/profiles", response_model=list[ProfileSummary])
async def list_profiles(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[ProfileSummary]:
    """List every RELEASED benchmark profile (NFR-M15-05)."""
    async with admin_session(deps.session_factory) as session:
        profiles = await profiles_repo.list_released_profiles(session)
    return [
        ProfileSummary(
            benchmark_id=p.benchmark_id, type=p.type, scope=dict(p.scope), version=p.version
        )
        for p in profiles
    ]


class CompareRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=64)
    person_id: uuid.UUID | None = None


class ComparisonResponse(BaseModel):
    correlation_id: str
    person_id: uuid.UUID | None
    per_metric: list[dict[str, Any]]
    legend_similarity: dict[str, Any] | None
    benchmark_version: str
    confidence: float | None
    schema_version: str
    provisional: bool
    computed_at: datetime


def _to_response(row: dict[str, Any]) -> ComparisonResponse:
    return ComparisonResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        per_metric=row["per_metric"],
        legend_similarity=row["legend_similarity"] or None,
        benchmark_version=row["benchmark_version"],
        confidence=row["confidence"],
        schema_version=row["schema_version"],
        provisional=row["provisional"],
        computed_at=row["computed_at"],
    )


@internal_router.post("/compare", response_model=ComparisonResponse)
async def run_compare(
    body: CompareRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ComparisonResponse:
    """Run comparison synchronously; 422 when nothing is comparable."""
    tenant_id = require_tenant_id()
    row = await compare_stroke(
        session_factory=deps.session_factory,
        facts_source=deps.facts_source,
        player_context_source=deps.player_context_source,
        personal_baseline_source=deps.personal_baseline_source,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
    )
    if row is None:
        raise Unprocessable("no assembleable facts or shot context for this stroke")
    return _to_response(row)


@benchmarks_router.get("/{correlation_id}", response_model=ComparisonResponse)
async def read_comparison(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ComparisonResponse:
    """Retrieve a comparison. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await comparisons_repo.get_comparison(session, correlation_id)
    if row is None:
        raise NotFound("comparison not found")
    return _to_response(row)
