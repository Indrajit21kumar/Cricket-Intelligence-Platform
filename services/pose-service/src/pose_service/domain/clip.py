"""Normalised-clip loader adapter + fake (M06 Step 2).

M05's ``video.normalized`` event carries the normalised-clip *reference*, not
its frames. M06 loads the clip to run the model over its frames — a real
loader reads the video from object storage and decodes it; the fake returns
deterministic geometry so the pipeline is testable without any video.

Same adapter-+-fake pattern as everything else in the vision stack. Geometry
(frame_count / width / height) is all the fake pose model needs as a stand-in
for real decoded frames; :class:`RealClipLoader` additionally carries the
decoded frames themselves, which a real pose model cannot work without.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pose_service.domain.keypoints import FrameImage


@dataclass(frozen=True, slots=True)
class ClipGeometry:
    frame_count: int
    width: int
    height: int
    #: Decoded frames, when the loader actually read the video. ``None`` on
    #: the fake path — a model that needs pixels must say so rather than
    #: silently inventing them.
    frames: tuple[FrameImage, ...] | None = None


class ClipLoader(Protocol):
    """Loads a normalised clip's frame geometry from its storage reference."""

    async def load(self, normalized_ref: str) -> ClipGeometry:
        """Return the clip's frame geometry (a real loader decodes the video)."""
        ...


class FakeClipLoader:
    """Deterministic clip loader for dev + tests.

    Returns a fixed default geometry; ``patch`` lets a test set the geometry
    for a specific run (e.g. to exercise short/edge clips).
    """

    def __init__(self, *, frame_count: int = 30, width: int = 1920, height: int = 1080) -> None:
        self.geometry = ClipGeometry(frame_count=frame_count, width=width, height=height)

    def patch(
        self, *, frame_count: int | None = None, width: int | None = None, height: int | None = None
    ) -> None:
        self.geometry = ClipGeometry(
            frame_count=frame_count if frame_count is not None else self.geometry.frame_count,
            width=width if width is not None else self.geometry.width,
            height=height if height is not None else self.geometry.height,
        )

    async def load(self, normalized_ref: str) -> ClipGeometry:
        _ = normalized_ref
        return self.geometry


class RealClipLoader:
    """Decodes the normalised clip from the shared local storage root.

    M05's ``LocalFilesystemStorageProvider`` writes the normalised clip under
    the same root, so ``normalized_ref`` resolves directly to a real file.
    """

    def __init__(self, *, root: Path) -> None:
        self._root = root

    async def load(self, normalized_ref: str) -> ClipGeometry:
        return await asyncio.to_thread(self._decode, self._root / normalized_ref)

    def _decode(self, path: Path) -> ClipGeometry:
        import cv2  # lazy: only the real path needs OpenCV installed

        cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise ValueError(f"Could not open normalised clip for decoding: {path.name}")
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            frames: list[FrameImage] = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(frame)
        finally:
            cap.release()
        return ClipGeometry(
            frame_count=len(frames), width=width, height=height, frames=tuple(frames)
        )
