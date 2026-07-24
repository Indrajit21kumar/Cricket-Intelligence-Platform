"""Ball-track artefact store + serialisation (M08 Step 7, FR-M08-10).

The per-frame track goes to object storage referenced by tenant/correlation;
``ball_runs`` keeps the summary — the same split M05/M06/M07 use.

The serialised form keeps ``timing_reference`` and every provenance label
alongside the numbers, so a consumer reading the artefact alone cannot take an
ESTIMATED speed for a measured one, or assume release-relative timing that was
never established.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

from ball_service.domain.ball import BallEvent, BallEvents
from ball_service.domain.detection import BallTrack


def artefact_key(*, tenant_id: uuid.UUID, correlation_id: str) -> str:
    """Tenant/correlation-namespaced object key for the ball-track artefact."""
    return f"tenant/{tenant_id}/ball/{correlation_id}/track.json"


def _event_dict(event: BallEvent | None) -> dict[str, Any] | None:
    if event is None:
        return None
    return {
        "frame_index": event.frame_index,
        "confidence": event.confidence,
        "provenance": event.provenance,
    }


def events_payload(events: BallEvents) -> dict[str, Any]:
    """The events object stored in ``ball_runs.events`` and published.

    Absent events are absent KEYS, never null-valued frame numbers: a consumer
    doing ``payload.get("release")`` gets nothing, which is the truth, rather
    than a zero it might treat as frame 0.
    """
    payload: dict[str, Any] = {"timing_reference": events.timing_reference}
    for kind, event in (
        ("release", events.release),
        ("bounce", events.bounce),
        ("contact", events.contact),
    ):
        as_dict = _event_dict(event)
        if as_dict is not None:
            payload[kind] = as_dict
    if events.line is not None:
        payload["line"] = {"value": events.line, "confidence": events.line_confidence}
    if events.length is not None:
        payload["length"] = {"value": events.length, "confidence": events.length_confidence}
    if events.speed is not None:
        payload["speed"] = {
            "metres_per_second": events.speed.metres_per_second,
            "kph": events.speed.kph,
            "confidence": events.speed.confidence,
            # Never droppable: Book 4 Ch. 4 requires speed to read as ESTIMATED
            # wherever it surfaces.
            "provenance": events.speed.provenance,
            "limited_by": list(events.speed.limited_by),
        }
    return payload


def serialise_track(track: BallTrack, *, events: BallEvents) -> str:
    """Serialise the ball track and its derived events."""
    payload = {
        "schema": "ball.track/1.0",
        "positions": [
            {
                "frame_index": p.frame_index,
                "x": p.x,
                "y": p.y,
                "confidence": p.confidence,
                "streak": p.streak,
                "provenance": p.provenance,
            }
            for p in track.positions
        ],
        "events": events_payload(events),
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
