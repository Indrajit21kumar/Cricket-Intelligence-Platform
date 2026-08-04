"""Real (OpenCV) clip loader — decodes the normalised clip into frames.

Opt-in: skipped unless the ``real`` extra is installed. ``FakeClipLoader``
returns fixed geometry and no frames; these tests prove the real loader
actually reads the file it is pointed at.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from pose_service.domain.clip import RealClipLoader  # noqa: E402

pytestmark = pytest.mark.real_model

WIDTH, HEIGHT, FPS, FRAMES = 320, 240, 30.0, 12
REF = "tenant/t/player/p/normalized/clip"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A storage root holding one normalised clip at a real (extension-less) key.

    OpenCV's writer needs an extension to pick a container, so the clip is
    encoded to a temp ``.mp4`` first and then moved onto the object key —
    which is how M05 actually stores it.
    """
    path = tmp_path / REF
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = path.with_name(path.name + ".src.mp4")
    writer = cv2.VideoWriter(str(encoded), cv2.VideoWriter.fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    for _ in range(FRAMES):
        writer.write(np.full((HEIGHT, WIDTH, 3), 90, dtype=np.uint8))
    writer.release()
    shutil.move(encoded, path)
    return tmp_path


class TestRealClipLoader:
    async def test_decodes_real_geometry_and_frames(self, root: Path) -> None:
        geo = await RealClipLoader(root=root).load(REF)
        assert (geo.frame_count, geo.width, geo.height) == (FRAMES, WIDTH, HEIGHT)
        assert geo.frames is not None
        assert len(geo.frames) == FRAMES
        assert geo.frames[0].shape == (HEIGHT, WIDTH, 3)

    async def test_frame_content_matches_what_was_written(self, root: Path) -> None:
        geo = await RealClipLoader(root=root).load(REF)
        assert geo.frames is not None
        # Written as a flat mid-grey; lossy encoding shifts it slightly.
        assert float(geo.frames[0].mean()) == pytest.approx(90.0, abs=5.0)

    async def test_missing_clip_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            await RealClipLoader(root=tmp_path).load("tenant/t/player/p/normalized/absent")
