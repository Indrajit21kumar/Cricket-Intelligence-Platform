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


def serialise_frames(
    frames: tuple[tuple[Keypoint, ...], ...],
    *,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
    scale: float = 1.0,
) -> str:
    """Serialise the per-frame keypoint sequence to a compact JSON payload.

    The ``frame`` block records the CIP-frame transform these coordinates are
    expressed in (pixel origin, divisor, Y-up). Consumers that need to place
    something else — M07's bat, M08's ball — into the same frame cannot do so
    without it, so it ships with the keypoints rather than being re-derived.
    """
    payload = {
        "schema": "pose.keypoints/1.1",
        "frame": {
            "origin_x": origin_x,
            "origin_y": origin_y,
            "scale": scale,
            "y_up": True,
        },
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
