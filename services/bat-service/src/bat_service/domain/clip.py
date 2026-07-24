"""Normalised-clip loader adapter + fake (M07 Step 7).

Same shape as M06's: ``video.normalized`` carries the clip reference, not its
frames, so the detector needs the clip's geometry to run over. The real loader
decodes the video from object storage; the fake returns deterministic geometry
so the pipeline is testable without any video.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ClipGeometry:
    frame_count: int
    width: int
    height: int


class ClipLoader(Protocol):
    """Loads a normalised clip's frame geometry from its storage reference."""

    async def load(self, normalized_ref: str) -> ClipGeometry:
        """Return the clip's frame geometry (a real loader decodes the video)."""
        ...


class FakeClipLoader:
    """Deterministic clip loader for dev + tests."""

    def __init__(self, *, frame_count: int = 30, width: int = 1920, height: int = 1080) -> None:
        self.geometry = ClipGeometry(frame_count=frame_count, width=width, height=height)

    def patch(
        self,
        *,
        frame_count: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        self.geometry = ClipGeometry(
            frame_count=frame_count if frame_count is not None else self.geometry.frame_count,
            width=width if width is not None else self.geometry.width,
            height=height if height is not None else self.geometry.height,
        )

    async def load(self, normalized_ref: str) -> ClipGeometry:
        _ = normalized_ref
        return self.geometry
