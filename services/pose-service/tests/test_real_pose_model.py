"""Real (YOLOv8-pose) model adapter.

Opt-in: skipped unless the ``real`` extra is installed. Downloads model
weights on first run, so this never belongs in the default gate.

The load-bearing assertion is that the model's output actually depends on the
image — two different photographs must not yield the same detections.
Synthetic noise would detect nobody for ANY input and so would "pass" without
proving anything, hence real sample imagery (ultralytics ships its own, so no
fixture binaries are committed here).
"""

from __future__ import annotations

import pytest

cv2 = pytest.importorskip("cv2")
ultralytics = pytest.importorskip("ultralytics")

from pose_service.domain.keypoints import CANONICAL_JOINTS  # noqa: E402
from pose_service.domain.model import MODEL_VERSION, RealPoseModel  # noqa: E402

pytestmark = pytest.mark.real_model


@pytest.fixture(scope="module")
def model() -> RealPoseModel:
    return RealPoseModel()


def _image(name: str):  # type: ignore[no-untyped-def]
    from ultralytics.utils import ASSETS

    return cv2.imread(str(ASSETS / name))


class TestRealInference:
    def test_version_is_not_the_fake(self, model: RealPoseModel) -> None:
        assert model.version != MODEL_VERSION
        assert model.version.startswith("real-pose-yolov8-")

    def test_frames_are_required(self, model: RealPoseModel) -> None:
        with pytest.raises(ValueError):
            model.infer(frame_count=1, width=640, height=480)

    def test_detects_people_with_the_canonical_joint_set(self, model: RealPoseModel) -> None:
        frame = _image("zidane.jpg")  # real photo containing people
        detections = model.infer(
            frame_count=1, width=frame.shape[1], height=frame.shape[0], frames=[frame]
        )
        assert len(detections) == 1
        persons = detections[0].persons
        assert len(persons) >= 1
        person = persons[0]
        assert tuple(k.joint for k in person.keypoints) == CANONICAL_JOINTS
        assert person.area > 0
        # Real inference: coordinates vary per joint and land inside the frame.
        xs = {round(k.x, 3) for k in person.keypoints}
        assert len(xs) > 1
        assert all(0 <= k.x <= frame.shape[1] for k in person.keypoints)
        assert any(k.confidence > 0.5 for k in person.keypoints)

    def test_output_depends_on_the_image(self, model: RealPoseModel) -> None:
        """Two different photos must not produce identical detections.

        Both sample images happen to contain people, so this compares the
        detections themselves rather than merely "found somebody vs not" —
        a stricter check, and the one that would actually catch a model
        ignoring its input.
        """
        first, second = _image("zidane.jpg"), _image("bus.jpg")
        a = model.infer(frame_count=1, width=first.shape[1], height=first.shape[0], frames=[first])
        b = model.infer(
            frame_count=1, width=second.shape[1], height=second.shape[0], frames=[second]
        )
        assert a[0].persons != b[0].persons
