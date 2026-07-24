"""Bat tracking + hand-bat association (M07 Step 4, AC-M07-02).

The decisive test is `test_decoy_bat_is_rejected_in_favour_of_the_held_one`:
with two bats in frame, M07 must follow the one at the batter's hands, not the
more confident or more central one.
"""

from __future__ import annotations

import json

import pytest

from bat_service.domain.bat import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    HANDLE_TOP,
    BatDetection,
    BatPart,
    FrameDetections,
)
from bat_service.domain.pose_client import CipFrame, PoseTrack, WristPair, parse_pose_artefact
from bat_service.domain.tracking import (
    ASSOCIATION_CONTINUITY,
    ASSOCIATION_HANDS,
    ASSOCIATION_NONE,
    ASSOCIATION_SOLE,
    track_bat,
)

# A realistic 1080p transform. The detector works in PIXELS (Y down); M06's
# wrists are in CIP units (Y up). Keeping both spaces real in the fixtures is
# the point — an "identity" frame would hide the Y flip that the transform
# exists to perform.
FRAME = CipFrame(origin_x=960.0, origin_y=1000.0, scale=1080.0)


def _px(cip_x: float, cip_y: float) -> tuple[float, float]:
    """Inverse of CipFrame.to_cip: the pixels a detector would have emitted."""
    return (cip_x * FRAME.scale + FRAME.origin_x, FRAME.origin_y - cip_y * FRAME.scale)


def _bat(handle_cip: tuple[float, float], *, confidence: float = 0.9) -> BatDetection:
    """A bat whose handle sits at the given CIP point, expressed in pixels."""
    hx, hy = _px(*handle_cip)
    return BatDetection(
        parts=(
            # Handle top is ABOVE the handle bottom, i.e. smaller pixel y.
            BatPart(part=HANDLE_TOP, x=hx, y=hy - 0.05 * FRAME.scale, confidence=confidence),
            BatPart(part=HANDLE_BOTTOM, x=hx, y=hy, confidence=confidence),
            BatPart(part=BLADE_TIP, x=hx, y=hy + 0.30 * FRAME.scale, confidence=confidence),
        ),
        score=confidence,
    )


def _pose(*wrists: WristPair) -> PoseTrack:
    return PoseTrack(frame=FRAME, wrists=tuple(wrists))


def _hands_at(frame_index: int, x: float, y: float) -> WristPair:
    return WristPair(
        frame_index=frame_index,
        left=(x - 0.01, y),
        right=(x + 0.01, y),
        confidence=0.9,
    )


class TestHandAssociation:
    def test_single_bat_at_the_hands_is_tracked(self) -> None:
        detections = [FrameDetections(frame_index=0, bats=(_bat((0.0, 0.5)),))]
        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)
        assert result.frames[0].detected is True
        assert result.associations[0] == ASSOCIATION_HANDS

    def test_decoy_bat_is_rejected_in_favour_of_the_held_one(self) -> None:
        """AC-M07-02: the batter's bat wins even when the decoy scores higher."""
        held = _bat((0.0, 0.5), confidence=0.7)
        decoy = _bat((0.6, 0.5), confidence=0.99)  # more confident, wrong hands
        detections = [FrameDetections(frame_index=0, bats=(decoy, held))]

        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)

        handle = result.frames[0].part(HANDLE_BOTTOM)
        assert handle is not None
        assert handle.x == pytest.approx(0.0)  # the held bat, not the decoy
        assert result.associations[0] == ASSOCIATION_HANDS

    def test_bat_too_far_from_the_hands_is_not_tracked(self) -> None:
        """A bat nobody is holding is not this batter's bat."""
        detections = [FrameDetections(frame_index=0, bats=(_bat((0.9, 0.5)),))]
        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)
        assert result.frames[0].detected is False
        assert result.associations[0] == ASSOCIATION_NONE

    def test_one_visible_wrist_still_anchors_the_choice(self) -> None:
        wrists = WristPair(frame_index=0, left=(0.0, 0.5), right=None, confidence=0.8)
        detections = [FrameDetections(frame_index=0, bats=(_bat((0.02, 0.5)),))]
        result = track_bat(detections, pose=_pose(wrists), cip_frame=FRAME)
        assert result.associations[0] == ASSOCIATION_HANDS


class TestContinuity:
    def test_missing_wrists_fall_back_to_continuity(self) -> None:
        """Occlusion loses the hands for a frame; the bat has not teleported."""
        detections = [
            FrameDetections(frame_index=0, bats=(_bat((0.0, 0.5)),)),
            FrameDetections(frame_index=1, bats=(_bat((0.05, 0.45)),)),
        ]
        # Pose only covers frame 0.
        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)
        assert result.associations == (ASSOCIATION_HANDS, ASSOCIATION_CONTINUITY)
        assert result.frames_detected == 2

    def test_continuity_survives_a_gap_frame(self) -> None:
        detections = [
            FrameDetections(frame_index=0, bats=(_bat((0.0, 0.5)),)),
            FrameDetections(frame_index=1),  # detector found nothing
            FrameDetections(frame_index=2, bats=(_bat((0.06, 0.44)),)),
        ]
        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)
        assert result.associations == (
            ASSOCIATION_HANDS,
            ASSOCIATION_NONE,
            ASSOCIATION_CONTINUITY,
        )

    def test_a_teleporting_candidate_is_refused(self) -> None:
        """Beyond the continuity radius it is a different object, not the bat."""
        detections = [
            FrameDetections(frame_index=0, bats=(_bat((0.0, 0.5)),)),
            FrameDetections(frame_index=1, bats=(_bat((0.9, 0.5)),)),
        ]
        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)
        assert result.frames[1].detected is False


class TestWithoutPose:
    def test_no_pose_at_all_still_produces_a_track(self) -> None:
        """M06 rejecting a clip must not take M07 down with it."""
        detections = [
            FrameDetections(frame_index=0, bats=(_bat((0.0, 0.5)),)),
            FrameDetections(frame_index=1, bats=(_bat((0.03, 0.47)),)),
        ]
        # No pose means no stance origin, but the clip's height still gives a
        # scale — without it, CIP-unit thresholds would be compared against
        # raw pixels. compute_bat_run supplies this fallback in production.
        result = track_bat(detections, pose=None, cip_frame=FRAME)
        # One bat, nothing to confuse it with: followed on the weakest basis,
        # and the basis is visible to the caller.
        assert result.associations[0] == ASSOCIATION_SOLE
        assert result.frames[0].detected is True
        assert result.frames_detected == 2

    def test_no_pose_with_two_bats_never_guesses(self) -> None:
        """AC-M07-02 still binds: competing candidates are never picked blind."""
        detections = [
            FrameDetections(frame_index=0, bats=(_bat((0.0, 0.5)), _bat((0.6, 0.5)))),
        ]
        result = track_bat(detections, pose=None, cip_frame=FRAME)
        assert result.frames_detected == 0
        assert result.associations[0] == ASSOCIATION_NONE

    def test_sole_candidate_never_overrides_a_hand_mismatch(self) -> None:
        """With wrists present, a far-away lone bat is still refused."""
        detections = [FrameDetections(frame_index=0, bats=(_bat((0.9, 0.5)),))]
        result = track_bat(detections, pose=_pose(_hands_at(0, 0.0, 0.5)), cip_frame=FRAME)
        assert result.frames[0].detected is False
        assert result.associations[0] == ASSOCIATION_NONE


class TestCoordinateFrame:
    def test_pixels_are_mapped_into_the_cip_frame(self) -> None:
        """Bat and body must end up in one frame, or no metric means anything."""
        # Built in raw pixels, not via the _bat helper, so the transform itself
        # is under test: 108px ABOVE the origin (smaller pixel y, Y-down) must
        # become +0.1 in CIP units (Y-up).
        detection = BatDetection(
            parts=(
                BatPart(part=HANDLE_TOP, x=960.0, y=838.0, confidence=0.9),
                BatPart(part=HANDLE_BOTTOM, x=960.0, y=892.0, confidence=0.9),
                BatPart(part=BLADE_TIP, x=960.0, y=1216.0, confidence=0.9),
            ),
            score=0.9,
        )
        detections = [FrameDetections(frame_index=0, bats=(detection,))]
        pose = PoseTrack(frame=FRAME, wrists=(_hands_at(0, 0.0, 0.1),))

        result = track_bat(detections, pose=pose)

        handle = result.frames[0].part(HANDLE_BOTTOM)
        assert handle is not None
        assert handle.x == pytest.approx(0.0)
        assert handle.y == pytest.approx(0.1)
        # The blade tip is BELOW the origin, so its CIP y is negative.
        tip = result.frames[0].part(BLADE_TIP)
        assert tip is not None
        assert tip.y == pytest.approx(-0.2)


class TestRealM06Artefact:
    def test_parses_the_published_pose_format(self) -> None:
        """Read the actual M06 artefact shape, so drift breaks a test here."""
        payload = json.dumps(
            {
                "schema": "pose.keypoints/1.1",
                "frame": {
                    "origin_x": 960.0,
                    "origin_y": 1000.0,
                    "scale": 1080.0,
                    "y_up": True,
                },
                "frames": [
                    [
                        {"joint": "left_wrist", "x": -0.05, "y": 0.30, "confidence": 0.88},
                        {"joint": "right_wrist", "x": 0.05, "y": 0.30, "confidence": 0.86},
                        {"joint": "nose", "x": 0.0, "y": 0.75, "confidence": 0.9},
                    ]
                ],
            }
        )
        track = parse_pose_artefact(payload)
        assert track.frame.scale == 1080.0
        assert track.wrists[0].midpoint == pytest.approx((0.0, 0.30))
        # Confidence is the weaker wrist, not an average.
        assert track.wrists[0].confidence == pytest.approx(0.86)

    def test_artefact_without_a_frame_block_degrades_to_identity(self) -> None:
        payload = json.dumps({"schema": "pose.keypoints/1.0", "frames": []})
        track = parse_pose_artefact(payload)
        assert track.frame == CipFrame(origin_x=0.0, origin_y=0.0, scale=1.0)
