"""Annotated-video markers + rendering (M14 Step 3, FR-M14-04)."""

from __future__ import annotations

import asyncio

from report_service.domain.video import FakeVideoAnnotator, build_markers


def _findings() -> list[dict]:
    return [
        {"finding_id": "F::KG-A:v1", "what": "head falling outside off"},
        {"finding_id": "F::KG-B:v1", "what": "front elbow collapse"},
    ]


class TestBuildMarkers:
    def test_one_marker_per_finding_anchored_to_impact(self) -> None:
        markers = build_markers(_findings(), phases={"downswing": 8, "impact": 14})
        assert len(markers) == 2
        assert all(m.frame_index == 14 for m in markers)
        assert markers[0].label == "head falling outside off"

    def test_no_impact_phase_leaves_frame_index_none(self) -> None:
        markers = build_markers(_findings(), phases={})
        assert all(m.frame_index is None for m in markers)

    def test_no_findings_no_markers(self) -> None:
        assert build_markers([], phases={"impact": 14}) == []


class TestFakeVideoAnnotator:
    def test_overlays_applied_when_pose_artefact_present(self) -> None:
        annotator = FakeVideoAnnotator()
        markers = build_markers(_findings(), phases={"impact": 14})
        video = asyncio.run(
            annotator.annotate(
                clip_ref="clip://abc",
                pose_artefact_ref="pose://abc",
                bat_artefact_ref="bat://abc",
                markers=markers,
            )
        )
        assert video.overlays_applied is True
        assert video.video_ref == "clip://abc::annotated"
        assert len(video.markers) == 2

    def test_overlays_not_applied_without_pose_artefact_but_clip_still_returned(self) -> None:
        annotator = FakeVideoAnnotator()
        video = asyncio.run(
            annotator.annotate(
                clip_ref="clip://abc", pose_artefact_ref=None, bat_artefact_ref=None, markers=[]
            )
        )
        assert video.overlays_applied is False
        assert video.video_ref == "clip://abc::unannotated"

    def test_records_calls(self) -> None:
        annotator = FakeVideoAnnotator()
        asyncio.run(
            annotator.annotate(
                clip_ref="c1", pose_artefact_ref=None, bat_artefact_ref=None, markers=[]
            )
        )
        assert annotator.calls == ["c1"]
