"""Annotated-video rendering (M14 §5, Step 3, FR-M14-04).

The report's annotated clip overlays the player's pose/bat skeleton and marks
where each finding occurred, so a coach can see exactly which frame the report
is talking about. Rendering pixels is out of scope for this build (no
self-hosted CV pipeline) — this module defines the CONTRACT: given the source
clip + the M06/M07 artefact refs + the findings' phase timecodes, produce a
marker list and an opaque ``annotated_video_ref``.

Adapter + fake, the same pattern as every other external-rendering seam in this
build (M05's VideoProcessor, M07/M08's detector adapters): the real renderer is
deferred; :class:`FakeVideoAnnotator` is deterministic so Step 3's marker logic
is fully testable now, and the real worker swaps in without touching the report
assembly.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class VideoMarker:
    """One annotation on the timeline: a finding's location in the clip."""

    finding_id: str
    frame_index: int | None
    label: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"finding_id": self.finding_id, "frame_index": self.frame_index, "label": self.label}


@dataclass(frozen=True, slots=True)
class AnnotatedVideo:
    video_ref: str
    markers: tuple[VideoMarker, ...]
    #: True when overlays could not be produced (e.g. no pose/bat artefact) —
    #: the clip is still returned unannotated rather than withheld.
    overlays_applied: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_ref": self.video_ref,
            "markers": [m.to_dict() for m in self.markers],
            "overlays_applied": self.overlays_applied,
        }


def _finding_marker(finding: Mapping[str, Any], phases: Mapping[str, int]) -> VideoMarker:
    """Anchor a finding's marker to the impact frame when phases are known."""
    frame_index = phases.get("impact")
    return VideoMarker(
        finding_id=str(finding.get("finding_id", "")),
        frame_index=frame_index,
        label=finding.get("what"),
    )


def build_markers(
    findings: Sequence[Mapping[str, Any]], *, phases: Mapping[str, int]
) -> list[VideoMarker]:
    """One marker per finding, anchored to the stroke's phase boundaries."""
    return [_finding_marker(f, phases) for f in findings]


class VideoAnnotator(Protocol):
    async def annotate(
        self,
        *,
        clip_ref: str,
        pose_artefact_ref: str | None,
        bat_artefact_ref: str | None,
        markers: Sequence[VideoMarker],
    ) -> AnnotatedVideo:
        """Render the overlaid clip; return its ref + the markers actually drawn."""
        ...


class FakeVideoAnnotator:
    """Deterministic in-process annotator for dev + tests.

    Overlays "apply" only when a pose artefact is present (there is nothing to
    draw a skeleton from otherwise) — the clip is still returned, honestly
    marked ``overlays_applied=False``, never withheld or silently faked.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def annotate(
        self,
        *,
        clip_ref: str,
        pose_artefact_ref: str | None,
        bat_artefact_ref: str | None,
        markers: Sequence[VideoMarker],
    ) -> AnnotatedVideo:
        self.calls.append(clip_ref)
        overlays_applied = pose_artefact_ref is not None
        suffix = "annotated" if overlays_applied else "unannotated"
        return AnnotatedVideo(
            video_ref=f"{clip_ref}::{suffix}",
            markers=tuple(markers),
            overlays_applied=overlays_applied,
        )
