"""Feature builder + upstream parsers (M09 Step 2, FR-M09-04, AC-M09-05).

The parsers are fed the ACTUAL published shapes (pose.keypoints/1.1,
bat.tracked, ball.events) so drift upstream breaks a test here. The builder
tests centre on graceful degradation: pose-only must work, and absent signals
must be recorded as absent, never zero-filled.
"""

from __future__ import annotations

import json
import math

import pytest

from shot_service.domain.feature_builder import build_features
from shot_service.domain.shot import SIGNAL_BALL, SIGNAL_BAT, SIGNAL_POSE
from shot_service.domain.sources import (
    BallSummary,
    BatSummary,
    parse_pose_artefact,
)


def _pose_artefact(frames: int = 20) -> str:
    """A synthetic M06 artefact: a front-foot stroke, hands sweeping up-and-across."""
    frame_list = []
    for i in range(frames):
        t = i / (frames - 1)
        hand_x = -0.1 + 0.4 * t  # travels across the body
        hand_y = 0.6 + 0.5 * math.sin(math.pi * t)  # rises then falls
        frame_list.append(
            [
                {"joint": "left_wrist", "x": hand_x - 0.02, "y": hand_y, "confidence": 0.9},
                {"joint": "right_wrist", "x": hand_x + 0.02, "y": hand_y, "confidence": 0.9},
                {"joint": "left_shoulder", "x": -0.1, "y": 1.3, "confidence": 0.9},
                {"joint": "right_shoulder", "x": 0.1 + 0.1 * t, "y": 1.3, "confidence": 0.9},
                {"joint": "left_hip", "x": 0.08 * t, "y": 0.9, "confidence": 0.9},
                {"joint": "right_hip", "x": 0.08 * t, "y": 0.9, "confidence": 0.9},
                {"joint": "left_ankle", "x": 0.0, "y": 0.0, "confidence": 0.9},
                {"joint": "right_ankle", "x": 0.0, "y": 0.0, "confidence": 0.9},
            ]
        )
    return json.dumps(
        {
            "schema": "pose.keypoints/1.1",
            "frame": {"origin_x": 960.0, "origin_y": 600.0, "scale": 1080.0, "y_up": True},
            "frames": frame_list,
        }
    )


def _bat_event(inclination: float = 20.0) -> dict:
    return {
        "swing_plane": {
            "inclination_degrees": inclination,
            "linearity": 0.9,
            "confidence": 0.7,
            "provenance": "derived",
        },
        "frames_detected": 18,
        "provisional": False,
    }


def _ball_event(*, contact_frame: int | None = 12, timing: str = "release_relative") -> dict:
    events: dict = {"timing_reference": timing}
    if contact_frame is not None:
        events["contact"] = {"frame_index": contact_frame, "confidence": 0.7}
    events["line"] = {"value": "outside_off", "confidence": 0.6}
    events["length"] = {"value": "good", "confidence": 0.6}
    return {"events": events, "conditions_met": True}


class TestPoseParser:
    def test_parses_the_published_keypoint_shape(self) -> None:
        seq = parse_pose_artefact(_pose_artefact(frames=10))
        assert seq.frame_count == 10
        first = seq.frames[0]
        assert first.point("left_wrist") is not None
        hands = first.midpoint("left_wrist", "right_wrist")
        assert hands is not None

    def test_missing_joints_are_absent_not_zero(self) -> None:
        payload = json.dumps(
            {"schema": "pose.keypoints/1.1", "frames": [[{"joint": "nose", "x": 0.0, "y": 1.5}]]}
        )
        seq = parse_pose_artefact(payload)
        assert seq.frames[0].point("left_wrist") is None


class TestFullFusion:
    def test_all_three_signals_populate_the_vector(self) -> None:
        features = build_features(
            parse_pose_artefact(_pose_artefact()),
            bat=BatSummary.from_event(_bat_event(inclination=18.0)),
            ball=BallSummary.from_event(_ball_event()),
        )
        assert set(features.signals) == {SIGNAL_POSE, SIGNAL_BAT, SIGNAL_BALL}
        assert features.swing_plane_inclination == pytest.approx(18.0)
        assert features.ball_line == "outside_off"
        assert features.ball_length == "good"
        assert features.has_bat and features.has_ball

    def test_pose_features_are_computed_from_geometry(self) -> None:
        features = build_features(parse_pose_artefact(_pose_artefact()))
        # Hands travelled across the body (-0.1 -> +0.3) and rose to ~1.1.
        assert features.wrist_lateral_travel == pytest.approx(0.4, abs=0.05)
        assert features.wrist_peak_height > 1.0
        # Hips move ahead of the ankles -> front-foot (positive) commitment.
        assert features.footedness > 0.0


class TestGracefulDegradation:
    def test_pose_only_still_produces_a_vector(self) -> None:
        """AC-M09-05: classification degrades to pose-only."""
        features = build_features(parse_pose_artefact(_pose_artefact()))
        assert features.signals == (SIGNAL_POSE,)
        assert features.has_bat is False
        assert features.has_ball is False

    def test_absent_bat_is_none_not_zero(self) -> None:
        """A missing swing plane must never read as a bat that did not move."""
        features = build_features(
            parse_pose_artefact(_pose_artefact()),
            ball=BallSummary.from_event(_ball_event()),
        )
        assert features.swing_plane_inclination is None
        assert SIGNAL_BAT not in features.signals
        assert SIGNAL_BALL in features.signals

    def test_absent_ball_is_none_not_empty_string(self) -> None:
        features = build_features(
            parse_pose_artefact(_pose_artefact()),
            bat=BatSummary.from_event(_bat_event()),
        )
        assert features.ball_line is None
        assert features.ball_length is None
        assert SIGNAL_BAT in features.signals
        assert SIGNAL_BALL not in features.signals


class TestBallUsability:
    def test_a_release_relative_contact_is_usable(self) -> None:
        ball = BallSummary.from_event(_ball_event(contact_frame=12, timing="release_relative"))
        assert ball.usable_contact is True

    def test_absolute_timing_makes_contact_unusable(self) -> None:
        """M08 fell back to absolute timing, so its contact frame is not trusted."""
        ball = BallSummary.from_event(_ball_event(contact_frame=12, timing="absolute"))
        assert ball.usable_contact is False

    def test_no_contact_event_is_not_usable(self) -> None:
        ball = BallSummary.from_event(_ball_event(contact_frame=None))
        assert ball.usable_contact is False
