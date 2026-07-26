"""Fan-in source adapter (M10 Step 7, §4).

M10 needs six upstream inputs together — pose, bat, ball, shot+phases,
calibration, anthropometrics — to compute one report, so the seam is a single
``StrokeSource`` that assembles them into a RawStroke, not six separate fetches
the compute would have to re-join. The real implementation reads the M06 pose
artefact, the M07 bat artefact, the M08 ball events, the M09 shot event, M05
calibration and M04 anthropometrics and assembles the RawStroke; the fake holds
one a test provides, so the whole pipeline runs without any upstream service.

A None return means the inputs are not (yet) assembleable — M06 rejected the
clip, or a required upstream has not landed — so M10 produces no report, which
is correct: there is nothing to measure without a body.
"""

from __future__ import annotations

from typing import Protocol

from biomechanics_service.domain.builder import RawStroke


class StrokeSource(Protocol):
    async def load(self, correlation_id: str) -> RawStroke | None:
        """Assemble the fan-in for a stroke, or None when it cannot be built."""
        ...


class FakeStrokeSource:
    """In-process source holding pre-assembled RawStrokes for dev + tests."""

    def __init__(self) -> None:
        self.strokes: dict[str, RawStroke] = {}
        self.missing = False

    def set_stroke(self, correlation_id: str, stroke: RawStroke) -> None:
        self.strokes[correlation_id] = stroke

    async def load(self, correlation_id: str) -> RawStroke | None:
        if self.missing:
            return None
        return self.strokes.get(correlation_id)
