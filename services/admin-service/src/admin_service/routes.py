"""Admin console routes (M20 Step 2 onward, FR-M20-01, NFR-M20-01).

Every route here is gated by ``require_admin`` — deny-by-default, only
``platform_admin`` reaches anything under ``/v1/admin``. Step 2 establishes
this dependency once so every later step's route just depends on it; it
also ships the console's first real endpoint (``whoami``), which the
console UI uses to bootstrap the logged-in admin's identity.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from cip_core import AuthenticatedPrincipal, require_role, roles

admin_router = APIRouter(prefix="/v1/admin", tags=["admin"])

#: The single RBAC gate every admin route depends on (deny-by-default).
require_admin = require_role(roles.PLATFORM_ADMIN)


class WhoAmIResponse(BaseModel):
    person_id: str
    roles: list[str]


@admin_router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
) -> WhoAmIResponse:
    """The caller's own identity — a harmless read, so not itself audited."""
    return WhoAmIResponse(person_id=str(principal.person_id), roles=list(principal.roles))
