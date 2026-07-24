"""Ball-tracker validation gate (M08 Step 8, AC-M08-07, ENG-007).

The decisive test is `test_a_tracker_that_stops_reporting_is_blocked`: M08 is
allowed to report nothing when unsure, so a tracker that became uniformly
unsure would emit no wrong events and score perfectly on accuracy alone. The
gate must not let the fail-safe become a way to pass.
"""

from __future__ import annotations

import math
from dataclasses import replace

from ball_service.domain.tracker import MODEL_VERSION, FakeBallTracker
from ball_service.domain.validation import (
    DEFAULT_MIN_RECALL,
    build_golden_from_reference,
    run_validation,
)

SPECS = [
    ("golden-60fps-a", 24, 1920, 1080, 60.0),
    ("golden-60fps-b", 30, 1280, 720, 60.0),
]


class TestGate:
    def test_the_reference_tracker_passes_its_own_golden(self) -> None:
        tracker = FakeBallTracker()
        golden = build_golden_from_reference(tracker, SPECS)
        report = run_validation(tracker, golden)
        assert report.passed is True
        assert report.event_recall == 1.0
        assert report.event_accuracy == 1.0
        assert report.reason is None

    def test_a_tracker_that_stops_reporting_is_blocked(self) -> None:
        """The failure mode M08's own fail-safe would otherwise reward."""
        golden = build_golden_from_reference(FakeBallTracker(), SPECS)
        silent = FakeBallTracker(no_ball=True)

        report = run_validation(silent, golden)

        assert report.passed is False
        assert "event_recall" in (report.reason or "")
        assert report.event_recall == 0.0
        # The point: it reported nothing wrong, because it reported nothing.
        assert report.event_accuracy == 0.0

    def test_a_tracker_that_loses_the_early_flight_is_blocked(self) -> None:
        """Losing release costs M10 its timing anchor — a real regression."""
        golden = build_golden_from_reference(FakeBallTracker(), SPECS)
        late = FakeBallTracker(fail_frames=frozenset(range(0, 14)))

        report = run_validation(late, golden)

        assert report.passed is False
        assert report.event_recall < DEFAULT_MIN_RECALL

    def test_an_empty_golden_set_is_not_a_pass(self) -> None:
        """No evidence must never read as evidence of no regression."""
        report = run_validation(FakeBallTracker(), [])
        assert report.passed is False
        assert report.reason == "empty_golden_set"
        assert report.speed_error == math.inf

    def test_speed_regression_is_blocked(self) -> None:
        """Same events, wrong speed: caught by the third axis alone."""
        golden = build_golden_from_reference(FakeBallTracker(), SPECS)
        # Doubling the truth makes the tracker read 50% slow — well past the
        # 15% tolerance — while leaving every event frame untouched, so only
        # the speed axis can catch it.
        slowed = [
            replace(sample, true_speed_mps=sample.true_speed_mps * 2)
            for sample in golden
            if sample.true_speed_mps is not None
        ]
        assert slowed, "expected the reference snapshot to carry speeds"
        report = run_validation(FakeBallTracker(), slowed)
        assert report.passed is False
        assert "speed_error" in (report.reason or "")

    def test_report_names_each_delivery(self) -> None:
        """A failing gate must say which clips regressed, not just that it did."""
        tracker = FakeBallTracker()
        golden = build_golden_from_reference(tracker, SPECS)
        report = run_validation(tracker, golden)
        assert set(report.per_delivery) == {name for name, *_ in SPECS}

    def test_model_version_is_pinned(self) -> None:
        """The gate keys off a pinned version; a retrain must bump it."""
        assert FakeBallTracker().version == MODEL_VERSION


class TestGoldenConstruction:
    def test_the_reference_snapshot_captures_events_and_speed(self) -> None:
        golden = build_golden_from_reference(FakeBallTracker(), SPECS)
        assert golden[0].true_release is not None
        assert golden[0].true_bounce is not None
        assert golden[0].true_speed_mps is not None
        assert golden[0].true_speed_mps > 0
