"""Object-storage adapter + fake provider (M05 Step 2, FR-M05-01, NFR-M05-04).

M05 ingests via signed, time-limited upload URLs to object storage. Raw +
normalised video is namespaced per tenant/player so lifecycle tiering,
encryption, and consent-governed retention apply cleanly (NFR-M05-04).

The :class:`StorageProvider` protocol is the seam a real S3/MinIO client
plugs into later; Step 2 ships a :class:`FakeStorageProvider` (deterministic,
in-process) so upload + validation are testable without any object store.
The dev stack has no MinIO — this is the same "adapter + fake, defer real"
decision M03 made for the payment provider.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

#: Presigned URL lifetime (seconds).
DEFAULT_URL_TTL = 900


@dataclass(frozen=True, slots=True)
class SignedUpload:
    raw_ref: str  # object-storage key (namespaced by tenant/player)
    upload_url: str  # presigned PUT URL the client uploads to
    expires_in: int  # seconds


def object_key(*, tenant_id: uuid.UUID, person_id: uuid.UUID, ingestion_id: uuid.UUID) -> str:
    """The tenant/player-namespaced storage key for a raw clip (NFR-M05-04)."""
    return f"tenant/{tenant_id}/player/{person_id}/raw/{ingestion_id}"


class StorageProvider(Protocol):
    """Adapter every object-storage backend (S3, MinIO, fake) satisfies."""

    def create_upload_url(
        self,
        *,
        tenant_id: uuid.UUID,
        person_id: uuid.UUID,
        ingestion_id: uuid.UUID,
        content_type: str,
    ) -> SignedUpload:
        """Return a namespaced key + a presigned upload URL for the raw clip."""
        ...

    async def object_exists(self, raw_ref: str) -> bool:
        """True if the object has been uploaded (HEAD in a real backend)."""
        ...


class FakeStorageProvider:
    """In-process storage used for dev + tests.

    ``create_upload_url`` registers the key as "present" — the fake assumes
    the client's PUT to the (fake) URL succeeds, so ``object_exists`` returns
    True for any key it minted. Deterministic + observable via ``objects``.
    """

    def __init__(self) -> None:
        self.objects: set[str] = set()

    def create_upload_url(
        self,
        *,
        tenant_id: uuid.UUID,
        person_id: uuid.UUID,
        ingestion_id: uuid.UUID,
        content_type: str,
    ) -> SignedUpload:
        _ = content_type  # a real backend encodes content-type into the sig
        key = object_key(tenant_id=tenant_id, person_id=person_id, ingestion_id=ingestion_id)
        self.objects.add(key)
        return SignedUpload(
            raw_ref=key,
            upload_url=f"https://fake-storage.local/upload/{key}?sig={uuid.uuid4().hex}",
            expires_in=DEFAULT_URL_TTL,
        )

    async def object_exists(self, raw_ref: str) -> bool:
        return raw_ref in self.objects
