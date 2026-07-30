"""DNA API routes — M16 §10.

  POST /internal/v1/dna/recompute   deterministic replay from history (backfill/repair)

Person-anchored (no tenant scoping, §9). Read-only: this reconstructs and
returns what each performance trait's EMA-replayed state would be from the
service's own processing log, for verification (FR-M16-08, AC-M16-05). It
does NOT automatically rewrite M04 — repairing a discrepancy is an operator
decision, not an automatic one.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cip_core import AuthenticatedPrincipal, require_authenticated
from cip_data import admin_session
from dna_service.deps import Deps, get_deps
from dna_service.domain import dna_runs_repo
from dna_service.domain.history import EvidencePoint
from dna_service.domain.replay import recompute_traits

internal_router = APIRouter(prefix="/internal/v1/dna", tags=["internal"])


class RecomputeRequest(BaseModel):
    person_id: uuid.UUID


class RecomputedTrait(BaseModel):
    trait_key: str
    new_value: float
    new_confidence: float


class RecomputeResponse(BaseModel):
    person_id: uuid.UUID
    traits: list[RecomputedTrait]


def _evidence_by_trait(runs: list[dict[str, Any]]) -> dict[str, list[EvidencePoint]]:
    """Reconstruct each trait's evidence sequence from the processing log,
    oldest first (the order dna_runs_repo.list_runs already returns)."""
    evidence: dict[str, list[EvidencePoint]] = {}
    for run in runs:
        traits_updated = run.get("traits_updated") or {}
        for trait_key, entry in traits_updated.items():
            if not isinstance(entry, dict) or "evidence_value" not in entry:
                continue  # not an EMA trait entry (e.g. weak.areas/trait.strengths)
            evidence.setdefault(trait_key, []).append(
                EvidencePoint(
                    value=entry["evidence_value"],
                    confidence=entry["evidence_confidence"],
                    source_ref=run["session_ref"],
                )
            )
    return evidence


@internal_router.post("/recompute", response_model=RecomputeResponse)
async def recompute(
    body: RecomputeRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RecomputeResponse:
    """Replay every EMA trait from the processing log; nothing is rewritten."""
    async with admin_session(deps.session_factory) as session:
        runs = await dna_runs_repo.list_runs(session, player_id=body.person_id)

    recomputed = recompute_traits(_evidence_by_trait(runs))
    traits = [
        RecomputedTrait(
            trait_key=key, new_value=result.new_value, new_confidence=result.new_confidence
        )
        for key, result in recomputed.items()
        if result is not None
    ]
    return RecomputeResponse(person_id=body.person_id, traits=traits)
