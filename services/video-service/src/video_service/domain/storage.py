"""Object-storage adapter + fake provider (M05 Step 2, FR-M05-01, NFR-M05-04).

M05 ingests via signed, time-limited upload URLs to object storage. Raw +
normalised video is namespaced per tenant/player so lifecycle tiering,
encryption, and consent-governed retention apply cleanly (NFR-M05-04).

The :class:`StorageProvider` protocol is the seam a real S3/MinIO client
plugs into later; Step 2 ships a :class:`FakeStorageProvider` (deterministic,
in-process) so upload + validation are testable without any object store.
The dev stack has no MinIO — this is the same "adapter + fake, defer real"
decision M03 made for the payment provider.

:class:`LocalFilesystemStorageProvider` is the real-for-local-dev backend
added for the "real pose model" slice: since a real S3/MinIO client isn't
available in this environment, ``upload_url`` points back at this service's
own ``PUT /v1/videos/{id}/raw`` route instead of an external bucket, and
bytes land on a shared local directory both video-service and pose-service
read from.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
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

    async def receive_upload(self, raw_ref: str, body: AsyncIterator[bytes]) -> int:
        """Persist the uploaded bytes under ``raw_ref``; returns bytes written.

        A real cloud backend never has this called — the client PUTs straight
        to the cloud-issued signed URL. It exists on the Protocol so a local
        backend's own upload-receiving route can stay Protocol-typed.
        """
        ...


class FakeStorageProvider:
    """In-process storage used for dev + tests.

    ``create_upload_url`` registers the key as "present" — the fake assumes
    the client's PUT to the (fake) URL succeeds, so ``object_exists`` returns
    True for any key it minted. Deterministic + observable via ``objects``.
    """

    def __init__(self) -> None:
        self.objects: set[str] = set()
        #: raw_ref -> bytes received via receive_upload (dev/test observability).
        self.received: dict[str, int] = {}

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

    async def receive_upload(self, raw_ref: str, body: AsyncIterator[bytes]) -> int:
        total = 0
        async for chunk in body:
            total += len(chunk)
        self.received[raw_ref] = total
        self.objects.add(raw_ref)
        return total


class LocalFilesystemStorageProvider:
    """Real, local-disk-backed storage for the "real pose model" dev slice.

    ``upload_url`` points back at this service's own upload route (there is
    no external bucket to PUT to), so the client's PUT is a real HTTP call
    this same process serves. Writes go to a ``.part`` temp file and are
    atomically renamed into place, so ``object_exists`` never observes a
    half-written upload. ``raw_ref`` always comes from server-generated
    :func:`object_key` — never client-supplied path text — so there is no
    path-traversal surface here.
    """

    def __init__(self, *, root: Path, public_base_url: str) -> None:
        self._root = root
        self._base = public_base_url.rstrip("/")

    def create_upload_url(
        self,
        *,
        tenant_id: uuid.UUID,
        person_id: uuid.UUID,
        ingestion_id: uuid.UUID,
        content_type: str,
    ) -> SignedUpload:
        _ = content_type
        key = object_key(tenant_id=tenant_id, person_id=person_id, ingestion_id=ingestion_id)
        return SignedUpload(
            raw_ref=key,
            upload_url=f"{self._base}/v1/videos/{ingestion_id}/raw",
            expires_in=DEFAULT_URL_TTL,
        )

    async def object_exists(self, raw_ref: str) -> bool:
        return (self._root / raw_ref).is_file()

    async def receive_upload(self, raw_ref: str, body: AsyncIterator[bytes]) -> int:
        dest = self._root / raw_ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        total = 0
        with tmp.open("wb") as f:
            async for chunk in body:
                f.write(chunk)
                total += len(chunk)
        tmp.replace(dest)  # atomic on the same filesystem — no half-written reads
        return total
