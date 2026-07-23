"""Unit tests for calibration math (M05 Step 5, Book 4 §2.3, NFR-M05-03)."""

from __future__ import annotations

import pytest

from video_service.domain.calibration import STUMP_HEIGHT_CM, compute_calibration


class TestStumpMethod:
    def test_stump_gives_high_confidence(self) -> None:
        r = compute_calibration(
            stump_visible=True,
            stump_pixel_height=220.0,
            player_height_cm=175.0,
            player_pixel_height=430.0,
            angle_supported=True,
        )
        assert r.method == "stump"
        assert r.spatial_confidence == "high"
        assert r.depth_estimated is True
        # 0.711 m / 220 px.
        assert r.pixel_to_meter == pytest.approx((STUMP_HEIGHT_CM / 100.0) / 220.0)

    def test_unsupported_angle_caps_stump_to_low(self) -> None:
        r = compute_calibration(
            stump_visible=True,
            stump_pixel_height=220.0,
            player_height_cm=175.0,
            player_pixel_height=430.0,
            angle_supported=False,
        )
        assert r.method == "stump"
        assert r.spatial_confidence == "low"  # angle caps it
        assert r.pixel_to_meter is not None  # scale still derived


class TestHeightFallback:
    def test_height_used_when_no_stump(self) -> None:
        r = compute_calibration(
            stump_visible=False,
            stump_pixel_height=None,
            player_height_cm=180.0,
            player_pixel_height=450.0,
            angle_supported=True,
        )
        assert r.method == "height"
        assert r.spatial_confidence == "medium"
        assert r.pixel_to_meter == pytest.approx((180.0 / 100.0) / 450.0)

    def test_unsupported_angle_caps_height_to_low(self) -> None:
        r = compute_calibration(
            stump_visible=False,
            stump_pixel_height=None,
            player_height_cm=180.0,
            player_pixel_height=450.0,
            angle_supported=False,
        )
        assert r.spatial_confidence == "low"


class TestNoReference:
    def test_neither_reference_is_uncalibrated_low(self) -> None:
        r = compute_calibration(
            stump_visible=False,
            stump_pixel_height=None,
            player_height_cm=None,
            player_pixel_height=None,
            angle_supported=True,
        )
        assert r.method == "none"
        assert r.spatial_confidence == "low"
        assert r.pixel_to_meter is None
        assert r.depth_estimated is True

    def test_stump_flag_but_no_pixel_height_falls_back(self) -> None:
        """stump_visible True but no measured pixel height -> height fallback."""
        r = compute_calibration(
            stump_visible=True,
            stump_pixel_height=None,
            player_height_cm=175.0,
            player_pixel_height=430.0,
            angle_supported=True,
        )
        assert r.method == "height"
