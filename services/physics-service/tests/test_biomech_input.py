"""The purity seam — parsing an M10 report into BiomechanicsInput (M11 Step 2).

The parser is the only reader of the report's wire shape. These tests prove it
faithfully lifts the payload M10 publishes (metrics, quality incl. fps, phases,
flags) and that the typed view answers the questions the compute asks — usable
values, propagated confidence, the downswing duration that gives frame-indexed
phases a timescale.
"""

from __future__ import annotations

from typing import Any

from physics_service.domain.biomech_input import (
    BM_FOOT_ALIGNMENT,
    BM_HAND_SPEED,
    BM_SHOULDER_ROTATION,
    MetricInput,
    from_report_payload,
)


class TestParser:
    def test_round_trips_the_published_payload(self, make_payload: Any) -> None:
        bio = from_report_payload(make_payload())
        assert bio.correlation_id == "stroke-1"
        assert bio.fps == 60.0
        assert bio.spatial_confidence == "high"
        assert bio.schema_version == "biomechanics.metrics/1.1"
        assert bio.value(BM_HAND_SPEED) == 20.0
        assert bio.value(BM_SHOULDER_ROTATION) == 90.0
        assert bio.phase("downswing") == 8 and bio.phase("impact") == 14

    def test_flags_and_provisional_are_lifted(self, make_payload: Any) -> None:
        bio = from_report_payload(make_payload(provisional=True, flags=["ABSOLUTE_TIMING"]))
        assert bio.provisional is True
        assert bio.has_flag("ABSOLUTE_TIMING") is True

    def test_missing_fps_defaults_to_zero(self, make_payload: Any) -> None:
        payload = make_payload()
        del payload["quality"]["fps"]
        bio = from_report_payload(payload)
        assert bio.fps == 0.0

    def test_a_garbage_metric_entry_is_absent_not_a_crash(self, make_payload: Any) -> None:
        payload = make_payload()
        payload["metrics"]["BM-12"] = "not-a-dict"
        bio = from_report_payload(payload)
        assert bio.value(BM_HAND_SPEED) is None


class TestTypedView:
    def test_a_disabled_metric_is_not_usable(self, make_bio: Any) -> None:
        bio = make_bio(disabled={BM_FOOT_ALIGNMENT: "crease_axis_unresolved"})
        mi = bio.metric(BM_FOOT_ALIGNMENT)
        assert mi is not None and mi.usable is False
        assert bio.value(BM_FOOT_ALIGNMENT) is None

    def test_an_absent_metric_reads_as_none(self, make_bio: Any) -> None:
        bio = make_bio(drop=(BM_HAND_SPEED,))
        assert bio.value(BM_HAND_SPEED) is None
        assert bio.confidence(BM_HAND_SPEED) == 0.0

    def test_downswing_duration_from_frames_and_fps(self, make_bio: Any) -> None:
        # (impact 14 - downswing 8) / 60 fps = 0.1 s.
        bio = make_bio()
        assert bio.downswing_duration_s() == 0.1

    def test_no_fps_means_no_duration(self, make_bio: Any) -> None:
        assert make_bio(fps=0.0).downswing_duration_s() is None

    def test_collapsed_window_means_no_duration(self, make_bio: Any) -> None:
        bio = make_bio(phases={"downswing": 12, "impact": 12})
        assert bio.downswing_duration_s() is None

    def test_metric_input_usable_requires_value_and_no_disable(self) -> None:
        assert MetricInput(4.0, "measured", 0.9).usable is True
        assert MetricInput(None, "measured", 0.0).usable is False
        assert MetricInput(4.0, "measured", 0.9, disabled_reason="x").usable is False
