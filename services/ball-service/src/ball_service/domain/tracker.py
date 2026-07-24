"""Ball-tracker adapter + fake + pinned registry version (M08 §11, FR-M08-08).

The feasibility study rates ball tracking the hardest perception task in the
platform, and for a physical reason: at 30-60 fps a fast delivery is a
motion-blurred streak spanning several pixels, not a crisp circle. A real
tracker is a custom-trained detector plus a temporal tracker, trained on a
labelled ball corpus under supported conditions — which, like M07's bat
corpus, does not exist yet. So the tracker sits behind this protocol with a
deterministic fake, and everything downstream of it is real.

The fake models the delivery the way the physics does, because the event
detector (Step 4) has to find real structure in it: the ball travels down the
pitch, bounces once, and continues to the batter. Its knobs are the failure
modes the spec names — blur, dropped frames, and no ball at all — so the
fail-safe path (Step 6) can be exercised without a corpus of bad clips.
"""

from __future__ import annotations

from typing import Protocol

from ball_service.domain.ball import BallCandidate, FrameCandidates

#: Pinned tracker version. A retrain bumps this and must clear the gate.
MODEL_VERSION = "fake-ball-v1"
#: The labelled corpus this tracker was trained on. None until one exists —
#: recorded per run so a result is always traceable to its training data.
DATASET_VERSION: str | None = None


class BallTracker(Protocol):
    """Adapter every ball tracker (trained model or fake) satisfies."""

    @property
    def version(self) -> str:
        """Registry version pinned to this tracker."""
        ...

    @property
    def dataset_version(self) -> str | None:
        """Labelled dataset this tracker was trained on, if known."""
        ...

    def detect(self, *, frame_count: int, width: int, height: int) -> list[FrameCandidates]:
        """Run detection over the clip's frames, returning per-frame candidates."""
        ...


class FakeBallTracker:
    """Deterministic in-process ball tracker for dev + tests.

    Generates a plausible delivery in PIXEL space (Y down, as a detector would
    emit): the ball starts high at the bowler's end, descends to a bounce
    roughly two-thirds of the way through, then rises slightly toward the
    batter. Vertical motion is piecewise-linear rather than a true parabola —
    the event detector must find the bounce from the direction change, which
    is the signal that actually exists in real data.

    Knobs, each matching a failure mode in §11:
      ``blur_from``      frames at or after this index come back as streaks
      ``fail_frames``    frames where detection finds nothing
      ``no_ball``        the ball is never detected at all (fail-safe path)
      ``clutter``        a second ball-like object (a net, a distant ball)
    """

    def __init__(
        self,
        *,
        base_confidence: float = 0.75,
        blur_from: int | None = None,
        fail_frames: frozenset[int] = frozenset(),
        no_ball: bool = False,
        clutter: bool = False,
    ) -> None:
        self._version = MODEL_VERSION
        self._dataset_version = DATASET_VERSION
        self.base_confidence = base_confidence
        self.blur_from = blur_from
        self.fail_frames = fail_frames
        self.no_ball = no_ball
        self.clutter = clutter

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
        blur_from: int | None = None,
        fail_frames: frozenset[int] | None = None,
        no_ball: bool | None = None,
        clutter: bool | None = None,
    ) -> None:
        """Test override for the next detect()."""
        if base_confidence is not None:
            self.base_confidence = base_confidence
        if blur_from is not None:
            self.blur_from = blur_from
        if fail_frames is not None:
            self.fail_frames = fail_frames
        if no_ball is not None:
            self.no_ball = no_ball
        if clutter is not None:
            self.clutter = clutter

    def detect(self, *, frame_count: int, width: int, height: int) -> list[FrameCandidates]:
        frames: list[FrameCandidates] = []
        if self.no_ball:
            return [FrameCandidates(frame_index=f) for f in range(frame_count)]

        bounce_at = max(int(frame_count * 0.65), 1)
        for f in range(frame_count):
            if f in self.fail_frames:
                frames.append(FrameCandidates(frame_index=f))
                continue

            progress = f / max(frame_count - 1, 1)
            # Down the pitch: left to right across the frame.
            x = width * (0.10 + 0.75 * progress)
            if f <= bounce_at:
                # Descending from release height to the pitch.
                fall = f / bounce_at
                y = height * (0.35 + 0.55 * fall)
            else:
                # Rising off the pitch toward the batter, more slowly.
                rise = (f - bounce_at) / max(frame_count - 1 - bounce_at, 1)
                y = height * (0.90 - 0.25 * rise)

            streak = self.blur_from is not None and f >= self.blur_from
            # A streak is a worse localisation, and says so in its confidence.
            confidence = self.base_confidence * (0.7 if streak else 1.0)
            candidates = [BallCandidate(x=x, y=y, score=confidence, streak=streak)]
            if self.clutter:
                # A stationary ball-like object off to the side — never moves,
                # so trajectory continuity should reject it.
                candidates.append(
                    BallCandidate(x=width * 0.5, y=height * 0.15, score=0.9, streak=False)
                )
            frames.append(FrameCandidates(frame_index=f, candidates=tuple(candidates)))
        return frames
