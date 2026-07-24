"""Bat-detector adapter + fake detector + pinned registry version (M07 §11, FR-M07-07).

M07's honest constraint, from the spec itself: unlike pose, bat detection is
NOT solved off the shelf — it needs a custom model trained on CIP's own
labelled cricket data, which does not exist yet. So the detector sits behind
this protocol and ships with a deterministic fake, exactly as M05 did for CV
and M06 for pose. A trained YOLO-family/keypoint model drops in behind the
same interface once the dataset in §9 exists; everything downstream of the
protocol — tracking, association, angle derivation, degradation — is real.

``MODEL_VERSION`` and ``DATASET_VERSION`` are the registry anchors: a detector
is only meaningful alongside the corpus it learned from, so runs record both
(§9), and the validation gate (Step 8) keys off the pair.
"""

from __future__ import annotations

import math
from typing import Protocol

from bat_service.domain.bat import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    HANDLE_TOP,
    BatDetection,
    BatPart,
    FrameDetections,
)

#: Pinned detector version. A retrain bumps this and must clear the gate.
MODEL_VERSION = "fake-bat-v1"
#: The labelled corpus the pinned detector was trained on. None until a real
#: dataset exists — recorded per run so a result is always traceable.
DATASET_VERSION: str | None = None


class BatDetector(Protocol):
    """Adapter every bat detector (trained model or fake) satisfies."""

    @property
    def version(self) -> str:
        """Registry version pinned to this detector."""
        ...

    @property
    def dataset_version(self) -> str | None:
        """Labelled dataset this detector was trained on, if known."""
        ...

    def detect(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
        """Run detection over the clip's frames, returning raw per-frame candidates."""
        ...


class FakeBatDetector:
    """Deterministic in-process bat detector for dev + tests.

    Simulates a straight bat swung through an arc: the handle stays near the
    hands while the blade tip sweeps from high (backlift) to low (impact) and
    up again (follow-through). Configurable via :meth:`patch` — the seam the
    association (Step 4), degradation (Step 6) and gate (Step 8) tests use.

    ``fail_frames`` marks frames where detection "fails" (blur/occlusion), so
    the >30%-downswing rule can be exercised without a real hard-case corpus.
    ``decoy`` adds a second bat-like object away from the batter's hands — a
    net partner's bat — which hand-bat association must reject.
    """

    def __init__(
        self,
        *,
        base_confidence: float = 0.85,
        fail_frames: frozenset[int] = frozenset(),
        decoy: bool = False,
    ) -> None:
        self._version = MODEL_VERSION
        self._dataset_version = DATASET_VERSION
        self.base_confidence = base_confidence
        self.fail_frames = fail_frames
        self.decoy = decoy

    @property
    def version(self) -> str:
        return self._version

    @property
    def dataset_version(self) -> str | None:
        return self._dataset_version

    def patch(
        self,
        *,
        base_confidence: float | None = None,
        fail_frames: frozenset[int] | None = None,
        decoy: bool | None = None,
    ) -> None:
        """One-shot test override for the next detect()."""
        if base_confidence is not None:
            self.base_confidence = base_confidence
        if fail_frames is not None:
            self.fail_frames = fail_frames
        if decoy is not None:
            self.decoy = decoy

    def detect(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
        frames: list[FrameDetections] = []
        for f in range(frame_count):
            if f in self.fail_frames:
                frames.append(FrameDetections(frame_index=f))
                continue
            bats = [self._bat(f, frame_count, width, height, decoy=False)]
            if self.decoy:
                bats.append(self._bat(f, frame_count, width, height, decoy=True))
            frames.append(FrameDetections(frame_index=f, bats=tuple(bats)))
        return frames

    def _bat(
        self, f: int, frame_count: int, width: int, height: int, *, decoy: bool
    ) -> BatDetection:
        # Swing phase: 0 at the top of the backlift, pi at the end of the
        # follow-through, with the blade lowest around impact (phase ~ pi/2).
        phase = (f / max(frame_count - 1, 1)) * math.pi
        # The batter's hands sit centre-frame; the decoy stands off to the side.
        hand_x = width * (0.5 if not decoy else 0.18)
        hand_y = height * 0.55
        blade_len = 0.30 * height

        # Bat rotates from roughly vertical (backlift) through horizontal.
        angle = -math.pi / 2 + phase  # radians from vertical, screen space
        tip_x = hand_x + blade_len * math.sin(angle)
        tip_y = hand_y + blade_len * math.cos(angle)

        conf = self.base_confidence * (1.0 if not decoy else 0.95)
        parts = (
            BatPart(part=HANDLE_TOP, x=hand_x, y=hand_y - 0.08 * height, confidence=conf),
            BatPart(part=HANDLE_BOTTOM, x=hand_x, y=hand_y, confidence=conf),
            BatPart(part=BLADE_TIP, x=tip_x, y=tip_y, confidence=conf * 0.98),
        )
        return BatDetection(parts=parts, score=conf)
