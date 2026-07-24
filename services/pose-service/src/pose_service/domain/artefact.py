"""Keypoint-artefact store + serialisation (M06 Step 6, FR-M06-09).

Keypoint sequences are large, so the full per-frame payload is written to
object storage as an ARTEFACT (referenced by tenant/correlation), while the DB
keeps only a compact summary — the same split M05 uses for video. The
``ArtefactStore`` protocol takes a real S3/MinIO client later; the fake keeps
artefacts in-process for tests.
"""

from __future__ import annotations

import json
import uuid
from typing import Protocol

from pose_service.domain.keypoints import Keypoint


def artefact_key(*, tenant_id: uuid.UUID, correlation_id: str) -> str:
    """Tenant/correlation-namespaced object key for the keypoint artefact."""
    return f"tenant/{tenant_id}/pose/{correlation_id}/keypoints.json"


def serialise_frames(frames: tuple[tuple[Keypoint, ...], ...]) -> str:
    """Serialise the per-frame keypoint sequence to a compact JSON payload."""
    payload = {
        "schema": "pose.keypoints/1.0",
        "frames": [
            [
                {
                    "joint": k.joint,
                    "x": k.x,
                    "y": k.y,
                    "confidence": k.confidence,
                    **({"z": k.z} if k.z is not None else {}),
                    **({"depth_estimated": True} if k.depth_estimated else {}),
                }
                for k in frame
            ]
            for frame in frames
        ],
    }
    return json.dumps(payload)


class ArtefactStore(Protocol):
    async def save(self, key: str, payload: str) -> str:
        """Persist ``payload`` under ``key``; return the stored ref."""
        ...

    async def load(self, key: str) -> str | None: ...


class FakeArtefactStore:
    """In-process artefact store for dev + tests."""

    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    async def save(self, key: str, payload: str) -> str:
        self.objects[key] = payload
        return key

    async def load(self, key: str) -> str | None:
        return self.objects.get(key)
