"""Notification API routes — M19 §10 (M19 Step 6).

  GET  /v1/notifications                    the caller's own in-app inbox
  POST /v1/notifications/{id}/read          mark one read, self-only
  PATCH /v1/preferences                     update one (channel, topic) preference
  POST /v1/webhooks/provider-status         channel-provider delivery-status callback

The first three are self-scoped (a principal only ever reads/writes their
own inbox/preferences — no separate role needed, same posture as M04's
"self" access branch). The webhook has no bearer auth at all; the HMAC
signature (§10/§11, "signed provider webhooks") IS its authentication —
matching billing-service's own payment webhook exactly.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field

from cip_core import AuthenticatedPrincipal, NotFound, require_authenticated
from notification_service import service
from notification_service.deps import Deps, get_deps
from notification_service.domain.webhooks import SIGNATURE_HEADER, verify_webhook_signature

notifications_router = APIRouter(prefix="/v1/notifications", tags=["notifications"])
preferences_router = APIRouter(prefix="/v1/preferences", tags=["preferences"])
webhooks_router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])


@notifications_router.get("")
async def get_inbox(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[dict[str, Any]]:
    return await service.get_inbox(
        session_factory=deps.session_factory,
        recipient_ref=principal.person_id,
        limit=limit,
        offset=offset,
    )


@notifications_router.post("/{notification_id}/read")
async def post_mark_read(
    notification_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, bool]:
    marked = await service.mark_notification_read(
        session_factory=deps.session_factory,
        notification_id=notification_id,
        recipient_ref=principal.person_id,
    )
    if not marked:
        raise NotFound("no such notification")
    return {"read": True}


class PreferenceRequest(BaseModel):
    channel: str = Field(..., min_length=1)
    topic: str = Field(..., min_length=1)
    enabled: bool
    quiet_hours: dict[str, Any] | None = None


@preferences_router.patch("")
async def patch_preference(
    body: PreferenceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    return await service.update_preference(
        session_factory=deps.session_factory,
        person_ref=principal.person_id,
        channel=body.channel,
        topic=body.topic,
        enabled=body.enabled,
        quiet_hours=body.quiet_hours,
    )


class ProviderStatusPayload(BaseModel):
    provider_ref: str = Field(..., min_length=1)
    delivered: bool


@webhooks_router.post("/provider-status")
async def post_provider_status(
    request: Request,
    deps: Annotated[Deps, Depends(get_deps)],
    x_signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
) -> dict[str, Any]:
    body = await request.body()
    verify_webhook_signature(
        secret=deps.settings.provider_webhook_secret, body=body, header_value=x_signature
    )
    payload = ProviderStatusPayload.model_validate_json(body)
    notification = await service.handle_provider_status(
        session_factory=deps.session_factory,
        provider_ref=payload.provider_ref,
        delivered=payload.delivered,
    )
    if notification is None:
        raise NotFound("no notification for this provider_ref")
    return notification
