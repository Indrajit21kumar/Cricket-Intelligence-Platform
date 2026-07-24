"""Capture-condition gate (M08 Step 2, FR-M08-05).

The gate decides BEFORE tracking what the clip can support, and caps
confidence accordingly.
"""

from __future__ import annotations

import pytest

from ball_service.domain.conditions import (
    CEILING_MARGINAL,
    CEILING_SUPPORTED,
    CEILING_UNSUPPORTED,
    FPS_HARD_FLOOR,
    FPS_PREFERRED,
    PROFILE_MARGINAL,
    PROFILE_SUPPORTED,
    PROFILE_UNSUPPORTED,
    assess_conditions,
)


def _flags(*codes: str) -> list[dict[str, str]]:
    return [{"code": c, "severity": "flag", "message": c} for c in codes]


def _good(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "fps": 60.0,
        "quality_flags": [],
        "pixel_to_meter": 0.0042,
        "spatial_confidence": "high",
    }
    base.update(overrides)
    return base


class TestSupported:
    def test_good_capture_is_supported_and_uncapped(self) -> None:
        result = assess_conditions(**_good())  # type: ignore[arg-type]
        assert result.profile == PROFILE_SUPPORTED
        assert result.confidence_ceiling == CEILING_SUPPORTED
        assert result.limits == ()
        assert result.met is True


class TestFrameRate:
    def test_below_the_floor_is_unsupported(self) -> None:
        """At 24fps a fast ball moves metres between frames."""
        result = assess_conditions(**_good(fps=20.0))  # type: ignore[arg-type]
        assert result.profile == PROFILE_UNSUPPORTED
        assert result.confidence_ceiling == CEILING_UNSUPPORTED
        assert "fps_below_floor" in result.limits
        assert result.met is False

    def test_at_the_floor_is_marginal_not_unsupported(self) -> None:
        result = assess_conditions(**_good(fps=FPS_HARD_FLOOR))  # type: ignore[arg-type]
        assert result.profile == PROFILE_MARGINAL
        assert "fps_marginal" in result.limits

    def test_between_floor_and_preferred_is_marginal(self) -> None:
        result = assess_conditions(**_good(fps=30.0))  # type: ignore[arg-type]
        assert result.profile == PROFILE_MARGINAL
        assert result.confidence_ceiling == CEILING_MARGINAL

    def test_at_preferred_is_supported(self) -> None:
        result = assess_conditions(**_good(fps=FPS_PREFERRED))  # type: ignore[arg-type]
        assert result.profile == PROFILE_SUPPORTED

    def test_unknown_fps_is_unsupported_not_assumed_good(self) -> None:
        """Guessing a frame rate would fabricate the basis of every speed."""
        result = assess_conditions(**_good(fps=None))  # type: ignore[arg-type]
        assert result.profile == PROFILE_UNSUPPORTED
        assert result.limits == ("fps_unknown",)

    def test_m05_frame_rate_flag_is_honoured(self) -> None:
        """A clip M05 flagged is marginal here even if the number looks fine."""
        result = assess_conditions(
            **_good(fps=60.0, quality_flags=_flags("frame_rate_marginal"))  # type: ignore[arg-type]
        )
        assert result.profile == PROFILE_MARGINAL


class TestBlurAndLight:
    def test_excessive_blur_is_unsupported(self) -> None:
        result = assess_conditions(**_good(quality_flags=_flags("excessive_blur")))  # type: ignore[arg-type]
        assert result.profile == PROFILE_UNSUPPORTED
        assert "excessive_blur" in result.limits

    def test_some_blur_is_marginal(self) -> None:
        result = assess_conditions(**_good(quality_flags=_flags("some_blur")))  # type: ignore[arg-type]
        assert result.profile == PROFILE_MARGINAL

    def test_poor_lighting_is_unsupported(self) -> None:
        result = assess_conditions(**_good(quality_flags=_flags("too_dark")))  # type: ignore[arg-type]
        assert result.profile == PROFILE_UNSUPPORTED

    def test_unknown_flag_codes_are_ignored(self) -> None:
        """M05 may add flags M08 has no opinion on; they must not gate silently."""
        result = assess_conditions(**_good(quality_flags=_flags("batter_partially_framed")))  # type: ignore[arg-type]
        assert result.profile == PROFILE_SUPPORTED


class TestCalibration:
    def test_missing_calibration_is_marginal_not_fatal(self) -> None:
        """Events are still findable without metric scale; speed is not."""
        result = assess_conditions(**_good(pixel_to_meter=None))  # type: ignore[arg-type]
        assert result.profile == PROFILE_MARGINAL
        assert "no_calibration" in result.limits
        assert result.met is True

    def test_low_spatial_confidence_is_marginal(self) -> None:
        result = assess_conditions(**_good(spatial_confidence="low"))  # type: ignore[arg-type]
        assert result.profile == PROFILE_MARGINAL
        assert "weak_calibration" in result.limits


class TestAccumulation:
    def test_every_limit_is_named_not_just_the_first(self) -> None:
        """Ops needs to know all of what was wrong, not the first thing found."""
        result = assess_conditions(
            **_good(  # type: ignore[arg-type]
                fps=30.0,
                quality_flags=_flags("some_blur", "low_light"),
                spatial_confidence="low",
            )
        )
        assert set(result.limits) == {
            "fps_marginal",
            "some_blur",
            "marginal_lighting",
            "weak_calibration",
        }

    def test_one_fatal_condition_outranks_several_marginal_ones(self) -> None:
        result = assess_conditions(
            **_good(fps=30.0, quality_flags=_flags("some_blur", "excessive_blur"))  # type: ignore[arg-type]
        )
        assert result.profile == PROFILE_UNSUPPORTED
        assert result.confidence_ceiling == pytest.approx(CEILING_UNSUPPORTED)
