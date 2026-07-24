"""M07 bat reader — blade positions for contact detection (M08 Step 4/7).

Contact requires knowing where the bat was (§11), which M07 already computed
and published on ``bat.tracked``. Reading its artefact is cheaper and more
honest than M08 re-detecting the bat itself.

The units question matters here and is easy to get silently wrong: M07's track
is in CIP units when M06 supplied a stance origin (``frame_basis = "cip"``) and
only clip-relative otherwise. M08's own track is in frame-height units with the
raw pixel origin. Mixing the two would put the bat metres away from the ball
without anything erroring, so this reader **refuses a clip_relative bat track**
rather than comparing incompatible coordinates — the same reason M07 published
``frame_basis`` in the first place.

Missing bat data is expected, not exceptional: M07 rejects clips it cannot
track. Contact is simply not claimed then (Step 4 already handles ``None``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

#: M07's part names. The blade tip is the striking surface, so it is the part
#: whose proximity to the ball indicates contact.
BLADE_TIP = "blade_tip"
SWEET_SPOT = "sweet_spot"

#: Only a bat track sharing M06's stance origin is comparable with anything.
FRAME_BASIS_CIP = "cip"


@dataclass(frozen=True, slots=True)
class BatTrack:
    """Per-frame bat positions usable for contact detection."""

    #: frame_index -> (x, y) of the striking surface, in CIP units.
    positions: dict[int, tuple[float, float]]
    frame_basis: str

    @property
    def usable(self) -> bool:
        return bool(self.positions) and self.frame_basis == FRAME_BASIS_CIP


def parse_bat_artefact(payload: str, *, frame_basis: str) -> BatTrack:
    """Read blade positions out of an M07 bat-track artefact.

    Prefers the sweet spot, falling back to the blade tip: the sweet spot is
    the middle of the striking surface, which is where a well-struck ball
    actually meets the bat.
    """
    data = json.loads(payload)
    positions: dict[int, tuple[float, float]] = {}
    for frame in data.get("frames", []):
        if not frame.get("detected"):
            continue
        parts = {p.get("part"): p for p in frame.get("parts", [])}
        chosen = parts.get(SWEET_SPOT) or parts.get(BLADE_TIP)
        if chosen is None:
            continue
        positions[int(frame["frame_index"])] = (float(chosen["x"]), float(chosen["y"]))
    return BatTrack(positions=positions, frame_basis=frame_basis)


class BatClient(Protocol):
    """Fetches the M07 bat track for a clip, keyed on correlation_id."""

    async def load(self, correlation_id: str) -> BatTrack | None:
        """Return the bat track, or None when M07 has no usable run for it."""
        ...


class FakeBatClient:
    """In-process bat client for dev + tests.

    ``set_payload`` takes a real M07 artefact string so tests exercise the
    published format rather than a parallel structure that could drift from it.
    """

    def __init__(self) -> None:
        self.payloads: dict[str, tuple[str, str]] = {}
        #: When True, behaves as if M07 produced nothing for any clip.
        self.missing = False

    def set_payload(
        self, correlation_id: str, payload: str, *, frame_basis: str = FRAME_BASIS_CIP
    ) -> None:
        self.payloads[correlation_id] = (payload, frame_basis)

    async def load(self, correlation_id: str) -> BatTrack | None:
        if self.missing:
            return None
        entry = self.payloads.get(correlation_id)
        if entry is None:
            return None
        payload, frame_basis = entry
        return parse_bat_artefact(payload, frame_basis=frame_basis)
