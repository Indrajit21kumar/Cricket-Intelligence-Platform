"""Speed estimation (M08 Step 5, AC-M08-03).

Two things must hold: the arithmetic is right against a known displacement, and
the ESTIMATED label plus its caveats can never be lost.
"""

from __future__ import annotations

import pytest

from ball_service.domain.ball import EVENT_BOUNCE, PROVENANCE_ESTIMATED, BallEvent, BallPosition
from ball_service.domain.detection import BallTrack
from ball_service.domain.speed import (
    FPS_TRUSTWORTHY,
    estimate_speed,
)

HEIGHT = 1000
# 1 metre per 100 pixels.
PIXEL_TO_METER = 0.01


def _straight_track(
    *, steps: int = 5, step_units: float = 0.10, confidence: float = 0.9
) -> BallTrack:
    """A ball moving a fixed distance per frame, purely horizontally."""
    return BallTrack(
        positions=tuple(
            BallPosition(frame_index=i, x=step_units * i, y=0.5, confidence=confidence)
            for i in range(steps)
        )
    )


class TestArithmetic:
    def test_known_displacement_gives_known_speed(self) -> None:
        """0.10 frame-heights = 100px = 1m per frame at 60fps -> 60 m/s."""
        speed = estimate_speed(
            _straight_track(),
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert speed.metres_per_second == pytest.approx(60.0)

    def test_speed_scales_with_frame_rate(self) -> None:
        """Same displacement per frame, twice the fps, twice the speed."""
        slow = estimate_speed(
            _straight_track(),
            bounce=None,
            fps=30.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        fast = estimate_speed(
            _straight_track(),
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert slow is not None and fast is not None
        assert fast.metres_per_second == pytest.approx(2 * slow.metres_per_second)

    def test_kph_conversion(self) -> None:
        speed = estimate_speed(
            _straight_track(step_units=0.05),
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert speed.kph == pytest.approx(speed.metres_per_second * 3.6)

    def test_a_frame_gap_is_accounted_for(self) -> None:
        """Two frames' displacement over two frames' time is the same speed."""
        gappy = BallTrack(
            positions=(
                BallPosition(frame_index=0, x=0.0, y=0.5, confidence=0.9),
                BallPosition(frame_index=2, x=0.2, y=0.5, confidence=0.9),
                BallPosition(frame_index=4, x=0.4, y=0.5, confidence=0.9),
            )
        )
        speed = estimate_speed(
            gappy,
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert speed.metres_per_second == pytest.approx(60.0)


class TestProvenance:
    def test_speed_is_always_estimated(self) -> None:
        """AC-M08-03: never presented as measured."""
        speed = estimate_speed(
            _straight_track(),
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert speed.provenance == PROVENANCE_ESTIMATED

    def test_monocular_depth_is_always_a_named_limit(self) -> None:
        """A phone cannot see motion along its own axis — every estimate says so."""
        speed = estimate_speed(
            _straight_track(),
            bounce=None,
            fps=120.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert "monocular_depth" in speed.limited_by
        assert speed.confidence < 1.0


class TestRefusals:
    def test_no_calibration_means_no_speed(self) -> None:
        """Pixels per second is not a speed anyone can coach from."""
        assert (
            estimate_speed(
                _straight_track(),
                bounce=None,
                fps=60.0,
                pixel_to_meter=None,
                frame_height=HEIGHT,
            )
            is None
        )

    def test_no_fps_means_no_speed(self) -> None:
        assert (
            estimate_speed(
                _straight_track(),
                bounce=None,
                fps=None,
                pixel_to_meter=PIXEL_TO_METER,
                frame_height=HEIGHT,
            )
            is None
        )

    def test_a_single_position_means_no_speed(self) -> None:
        single = BallTrack(positions=(BallPosition(frame_index=0, x=0.0, y=0.5, confidence=0.9),))
        assert (
            estimate_speed(
                single,
                bounce=None,
                fps=60.0,
                pixel_to_meter=PIXEL_TO_METER,
                frame_height=HEIGHT,
            )
            is None
        )

    def test_an_empty_track_means_no_speed(self) -> None:
        assert (
            estimate_speed(
                BallTrack(positions=()),
                bounce=None,
                fps=60.0,
                pixel_to_meter=PIXEL_TO_METER,
                frame_height=HEIGHT,
            )
            is None
        )


class TestConfidenceDegradation:
    def _speed_at(self, fps: float, **kwargs: object):  # type: ignore[no-untyped-def]
        return estimate_speed(
            _straight_track(),
            bounce=None,
            fps=fps,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_low_fps_lowers_confidence_and_is_named(self) -> None:
        good = self._speed_at(60.0, spatial_confidence="high")
        poor = self._speed_at(30.0, spatial_confidence="high")
        assert good is not None and poor is not None
        assert poor.confidence < good.confidence
        assert "low_fps" in poor.limited_by
        assert "low_fps" not in good.limited_by

    def test_the_fps_threshold_boundary(self) -> None:
        at_threshold = self._speed_at(FPS_TRUSTWORTHY, spatial_confidence="high")
        assert at_threshold is not None
        assert "low_fps" not in at_threshold.limited_by

    def test_weak_calibration_lowers_confidence(self) -> None:
        strong = self._speed_at(60.0, spatial_confidence="high")
        weak = self._speed_at(60.0, spatial_confidence="low")
        assert strong is not None and weak is not None
        assert weak.confidence < strong.confidence
        assert "weak_calibration" in weak.limited_by

    def test_a_two_point_track_is_penalised_as_short(self) -> None:
        short = BallTrack(
            positions=(
                BallPosition(frame_index=0, x=0.0, y=0.5, confidence=0.9),
                BallPosition(frame_index=1, x=0.1, y=0.5, confidence=0.9),
            )
        )
        speed = estimate_speed(
            short,
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert "short_track" in speed.limited_by

    def test_disagreeing_intervals_lower_confidence(self) -> None:
        """The estimate's own error signal — no golden data needed to see it."""
        erratic = BallTrack(
            positions=(
                BallPosition(frame_index=0, x=0.00, y=0.5, confidence=0.9),
                BallPosition(frame_index=1, x=0.02, y=0.5, confidence=0.9),
                BallPosition(frame_index=2, x=0.30, y=0.5, confidence=0.9),
                BallPosition(frame_index=3, x=0.33, y=0.5, confidence=0.9),
            )
        )
        steady = _straight_track()
        noisy_speed = estimate_speed(
            erratic,
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        steady_speed = estimate_speed(
            steady,
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert noisy_speed is not None and steady_speed is not None
        assert "inconsistent_intervals" in noisy_speed.limited_by
        assert noisy_speed.confidence < steady_speed.confidence


class TestBounceExclusion:
    def test_speed_is_measured_before_the_bounce(self) -> None:
        """The ball slows on the pitch; averaging across the bounce reports neither."""
        track = BallTrack(
            positions=(
                BallPosition(frame_index=0, x=0.0, y=0.30, confidence=0.9),
                BallPosition(frame_index=1, x=0.2, y=0.60, confidence=0.9),
                BallPosition(frame_index=2, x=0.4, y=0.90, confidence=0.9),  # bounce
                BallPosition(frame_index=3, x=0.44, y=0.80, confidence=0.9),  # much slower
                BallPosition(frame_index=4, x=0.48, y=0.70, confidence=0.9),
            )
        )
        bounce = BallEvent(kind=EVENT_BOUNCE, frame_index=2, confidence=0.9)
        with_bounce = estimate_speed(
            track,
            bounce=bounce,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        ignoring_bounce = estimate_speed(
            track,
            bounce=None,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert with_bounce is not None and ignoring_bounce is not None
        # Excluding the slow post-bounce segment gives the faster, correct figure.
        assert with_bounce.metres_per_second > ignoring_bounce.metres_per_second

    def test_a_bounce_on_the_first_frame_does_not_empty_the_segment(self) -> None:
        track = _straight_track()
        bounce = BallEvent(kind=EVENT_BOUNCE, frame_index=0, confidence=0.9)
        speed = estimate_speed(
            track,
            bounce=bounce,
            fps=60.0,
            pixel_to_meter=PIXEL_TO_METER,
            frame_height=HEIGHT,
            spatial_confidence="high",
        )
        assert speed is not None
        assert "bounce_not_excluded" in speed.limited_by
