"""Unit tests for camera-angle classification (M05 Step 4, FR-M05-04)."""

from __future__ import annotations

import pytest

from video_service.domain.angle import classify_angle


class TestClassifyAngle:
    @pytest.mark.parametrize("angle", ["side_on", "front_on"])
    def test_supported_high_confidence(self, angle: str) -> None:
        r = classify_angle(angle_hint=angle, angle_confidence=0.9)
        assert r.camera_angle == angle
        assert r.supported is True
        assert r.recommendation is None

    def test_square_is_unsupported_with_recommendation(self) -> None:
        r = classify_angle(angle_hint="square", angle_confidence=0.9)
        assert r.camera_angle == "square"
        assert r.supported is False
        assert r.recommendation is not None
        assert "side-on" in r.recommendation

    def test_unknown_hint_normalises_to_other(self) -> None:
        r = classify_angle(angle_hint="upside_down", angle_confidence=0.9)
        assert r.camera_angle == "other"
        assert r.supported is False
        assert r.recommendation is not None

    def test_low_confidence_supported_angle_is_unsupported(self) -> None:
        """A side-on hint below the confidence floor is not trusted."""
        r = classify_angle(angle_hint="side_on", angle_confidence=0.3)
        assert r.camera_angle == "side_on"
        assert r.supported is False
        assert "unclear" in (r.recommendation or "")

    def test_confidence_boundary(self) -> None:
        # Exactly at the floor (0.5) is trusted; just below is not.
        assert classify_angle(angle_hint="side_on", angle_confidence=0.5).supported is True
        assert classify_angle(angle_hint="side_on", angle_confidence=0.49).supported is False
