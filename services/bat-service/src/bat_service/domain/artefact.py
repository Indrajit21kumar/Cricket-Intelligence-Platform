"""Bat-track artefact store + serialisation (M07 Step 7, FR-M07-09).

The per-frame bat track is large, so it goes to object storage referenced by
tenant/correlation, while ``bat_runs`` keeps the summary — the same split M05
uses for video and M06 for keypoints.

The serialised form carries provenance per point and the derived quantities
alongside the detected ones, so a consumer reading the artefact alone (without
the event) still cannot mistake a modelled sweet spot for an observed one.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

from bat_service.domain.bat import BatFrame
from bat_service.domain.geometry import BatAngle, SwingPlane


def artefact_key(*, tenant_id: uuid.UUID, correlation_id: str) -> str:
    """Tenant/correlation-namespaced object key for the bat-track artefact."""
    return f"tenant/{tenant_id}/bat/{correlation_id}/track.json"


def serialise_track(
    frames: tuple[BatFrame, ...],
    *,
    angles: tuple[BatAngle, ...],
    plane: SwingPlane | None,
) -> str:
    """Serialise the bat track, its per-frame angles and the swing plane."""
    angle_by_frame = {a.frame_index: a for a in angles}
    payload: dict[str, Any] = {
        "schema": "bat.track/1.0",
        "frames": [
            {
                "frame_index": f.frame_index,
                "detected": f.detected,
                "confidence": f.confidence,
                "parts": [
                    {
                        "part": p.part,
                        "x": p.x,
                        "y": p.y,
                        "confidence": p.confidence,
                        "provenance": p.provenance,
                    }
                    for p in f.parts
                ],
                **(
                    {
                        "bat_angle": {
                            "degrees": angle_by_frame[f.frame_index].degrees,
                            "confidence": angle_by_frame[f.frame_index].confidence,
                            "provenance": angle_by_frame[f.frame_index].provenance,
                        }
                    }
                    if f.frame_index in angle_by_frame
                    else {}
                ),
            }
            for f in frames
        ],
        "swing_plane": (
            {
                "x": plane.x,
                "y": plane.y,
                "inclination_degrees": plane.inclination_degrees,
                "linearity": plane.linearity,
                "confidence": plane.confidence,
                "provenance": plane.provenance,
            }
            if plane is not None
            else None
        ),
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
