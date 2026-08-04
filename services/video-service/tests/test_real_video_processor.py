"""Real (OpenCV) preprocessing adapter.

Opt-in: skipped unless the ``real`` extra is installed. The point of these
tests is to prove the real processor genuinely DEPENDS on the clip's content —
the fake returns an identical envelope for any input, so "it produced numbers"
is not evidence of anything on its own.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from video_service.domain.angle import ANGLE_UNKNOWN  # noqa: E402
from video_service.domain.processor import RealVideoProcessor  # noqa: E402
from video_service.domain.storage import object_key  # noqa: E402

pytestmark = pytest.mark.real_model

WIDTH, HEIGHT, FPS, FRAMES = 320, 240, 30.0, 15


def _write_clip(path: Path, *, noise: bool) -> None:
    """Write a tiny clip: uniform grey (no detail) or random noise (high detail).

    OpenCV's writer picks its container from the file extension and refuses an
    extension-less path, so the clip is encoded to a temp ``.mp4`` and then
    copied to the real (extension-less) object key — exactly the shape a
    client's upload lands in.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = path.with_name(path.name + ".src.mp4")
    writer = cv2.VideoWriter(str(encoded), cv2.VideoWriter.fourcc(*"mp4v"), FPS, (WIDTH, HEIGHT))
    rng = np.random.default_rng(7)
    for _ in range(FRAMES):
        if noise:
            frame = rng.integers(0, 256, (HEIGHT, WIDTH, 3), dtype=np.uint8)
        else:
            frame = np.full((HEIGHT, WIDTH, 3), 128, dtype=np.uint8)
        writer.write(frame)
    writer.release()
    shutil.move(encoded, path)


@pytest.fixture
def clips(tmp_path: Path) -> tuple[Path, str, str]:
    """A storage root holding two raw clips under real object keys."""
    import uuid

    tid, pid = uuid.uuid4(), uuid.uuid4()
    flat_ref = object_key(tenant_id=tid, person_id=pid, ingestion_id=uuid.uuid4())
    noisy_ref = object_key(tenant_id=tid, person_id=pid, ingestion_id=uuid.uuid4())
    _write_clip(tmp_path / flat_ref, noise=False)
    _write_clip(tmp_path / noisy_ref, noise=True)
    return tmp_path, flat_ref, noisy_ref


class TestRealMeasurement:
    async def test_geometry_matches_the_actual_file(self, clips: tuple[Path, str, str]) -> None:
        root, flat_ref, _ = clips
        result = await RealVideoProcessor(root=root).preprocess(raw_ref=flat_ref)
        m = result.measurements
        assert (m.width, m.height) == (WIDTH, HEIGHT)
        assert m.fps == pytest.approx(FPS)
        assert m.frame_count == FRAMES
        assert m.duration_s == pytest.approx(FRAMES / FPS)

    async def test_normalised_clip_is_written(self, clips: tuple[Path, str, str]) -> None:
        root, flat_ref, _ = clips
        result = await RealVideoProcessor(root=root).preprocess(raw_ref=flat_ref)
        assert (root / result.normalized_ref).is_file()

    async def test_different_content_gives_different_blur(
        self, clips: tuple[Path, str, str]
    ) -> None:
        """The measurement is real: detail-free vs high-detail footage differ."""
        root, flat_ref, noisy_ref = clips
        processor = RealVideoProcessor(root=root)
        flat = (await processor.preprocess(raw_ref=flat_ref)).measurements
        noisy = (await processor.preprocess(raw_ref=noisy_ref)).measurements
        assert flat.blur_score > noisy.blur_score

    async def test_missing_file_is_an_error_not_a_canned_result(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            await RealVideoProcessor(root=tmp_path).preprocess(raw_ref="tenant/x/player/y/raw/z")


class TestHonestPlaceholders:
    async def test_unmeasured_signals_are_reported_unknown(
        self, clips: tuple[Path, str, str]
    ) -> None:
        """M05 has no stump/person detector — these must not be invented."""
        root, flat_ref, _ = clips
        m = (await RealVideoProcessor(root=root).preprocess(raw_ref=flat_ref)).measurements
        assert m.stump_visible is False
        assert m.stump_pixel_height is None
        assert m.player_pixel_height is None
        # "unknown" (not "other") so the gate can distinguish "no classifier
        # ran" from "a classifier ran and saw an odd angle".
        assert m.angle_hint == ANGLE_UNKNOWN
        assert m.angle_confidence == 0.0
