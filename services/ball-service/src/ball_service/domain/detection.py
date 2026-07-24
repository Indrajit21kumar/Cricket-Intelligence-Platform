"""Ball detection under blur: appearance + motion cues (M08 Step 3, §11).

The spec's instruction is that detection "combines appearance with motion cues
(frame differencing / trajectory continuity) rather than relying on a crisp
circular blob". The appearance half belongs to the trained detector behind the
:class:`BallTracker` protocol. This module is the motion half, and it is the
half that does the real work of separating a ball from everything else that
looks vaguely like one.

The governing idea: **a cricket ball is defined by how it moves, not by how it
looks.** A round white object that stays put across ten frames is a helmet, a
sightscreen, or a ball in someone's hand — never a delivery. So the track is
built by testing candidates against motion, not appearance score:

- **Displacement floor.** A candidate that barely moves between frames cannot
  be the delivery (:data:`MIN_STEP`). This is what rejects the static clutter
  that a pure appearance detector confidently reports every frame.
- **Displacement ceiling.** Nothing physical crosses the frame in one step
  (:data:`MAX_STEP`), so a distant jump is a different object, not the ball.
- **Direction continuity.** A ball's heading changes smoothly except at the
  bounce, so a candidate that reverses sharply is rejected — with the bounce
  deliberately survivable, since the vertical flip there is the very signal
  Step 4 needs.

Seeding matters as much as stepping. The first frame has no motion history, so
instead of trusting the best-scoring candidate, the track starts from the
candidate that turns out to have a plausible SUCCESSOR — the earliest pair of
frames that look like a ball in flight. That way a confident static object
never becomes the seed.

All distances are in fractions of frame height, so thresholds hold at any
resolution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ball_service.domain.ball import BallPosition, FrameCandidates

#: Minimum inter-frame movement for a candidate to be the delivery. Below this
#: it is a static object that merely looks like a ball.
MIN_STEP = 0.010
#: Maximum plausible inter-frame movement. Beyond it, a different object.
MAX_STEP = 0.400
#: Sharpest heading change tolerated between consecutive steps, in degrees.
#: Generous, because the bounce genuinely reverses the vertical component.
MAX_TURN_DEGREES = 110.0
#: A track shorter than this is not evidence of a delivery.
MIN_TRACK_LENGTH = 3


@dataclass(frozen=True, slots=True)
class BallTrack:
    """The delivery's positions, in the frame they were detected in."""

    positions: tuple[BallPosition, ...]

    @property
    def frames_detected(self) -> int:
        return len(self.positions)

    @property
    def mean_confidence(self) -> float:
        if not self.positions:
            return 0.0
        return sum(p.confidence for p in self.positions) / len(self.positions)

    @property
    def streak_ratio(self) -> float:
        """Fraction of the track recovered from motion smear rather than blobs."""
        if not self.positions:
            return 0.0
        return sum(1 for p in self.positions if p.streak) / len(self.positions)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _turn_degrees(
    previous: tuple[float, float], current: tuple[float, float], nxt: tuple[float, float]
) -> float:
    """Heading change in degrees across three consecutive points."""
    ax, ay = current[0] - previous[0], current[1] - previous[1]
    bx, by = nxt[0] - current[0], nxt[1] - current[1]
    if (ax == 0 and ay == 0) or (bx == 0 and by == 0):
        return 0.0
    dot = ax * bx + ay * by
    cross = ax * by - ay * bx
    return abs(math.degrees(math.atan2(cross, dot)))


def _scaled(
    frames: list[FrameCandidates], *, height: int
) -> dict[int, list[tuple[float, float, float, bool]]]:
    """Candidates as (x, y, score, streak) in frame-height units."""
    scale = float(height) if height else 1.0
    return {
        f.frame_index: [(c.x / scale, c.y / scale, c.score, c.streak) for c in f.candidates]
        for f in frames
    }


def build_track(frames: list[FrameCandidates], *, height: int) -> BallTrack:
    """Recover the delivery's path from per-frame candidates using motion.

    Returns an empty track when no sequence of candidates moves like a ball —
    which is the honest answer for a clip with no delivery in it, and the one
    the fail-safe path (Step 6) depends on.
    """
    by_frame = _scaled(frames, height=height)
    order = sorted(by_frame)
    if len(order) < 2:
        return BallTrack(positions=())

    best: list[BallPosition] = []
    # Seed on a PAIR, not a single frame: a lone candidate has no motion to
    # judge, and the best-scoring one is exactly how static clutter wins.
    for seed_pos, seed_frame in enumerate(order[:-1]):
        for candidate in by_frame.get(seed_frame, []):
            track = _extend(
                by_frame,
                order,
                start_at=seed_pos,
                seed=candidate,
                seed_frame=seed_frame,
            )
            if len(track) > len(best):
                best = track

    if len(best) < MIN_TRACK_LENGTH:
        return BallTrack(positions=())
    return BallTrack(positions=tuple(best))


def _extend(
    by_frame: dict[int, list[tuple[float, float, float, bool]]],
    order: list[int],
    *,
    start_at: int,
    seed: tuple[float, float, float, bool],
    seed_frame: int,
) -> list[BallPosition]:
    """Greedily follow the most motion-plausible successor from a seed."""
    sx, sy, sscore, sstreak = seed
    track = [BallPosition(frame_index=seed_frame, x=sx, y=sy, confidence=sscore, streak=sstreak)]
    previous_point: tuple[float, float] | None = None
    current = (sx, sy)

    for frame_index in order[start_at + 1 :]:
        candidates = by_frame.get(frame_index, [])
        chosen: tuple[float, float, float, bool] | None = None
        chosen_step = 0.0
        for cx, cy, score, streak in candidates:
            step = _distance(current, (cx, cy))
            if step < MIN_STEP or step > MAX_STEP:
                continue
            if previous_point is not None:
                turn = _turn_degrees(previous_point, current, (cx, cy))
                if turn > MAX_TURN_DEGREES:
                    continue
            # Prefer the smoothest continuation, not the highest score: the
            # ball is whatever keeps moving like a ball.
            if chosen is None or step < chosen_step:
                chosen, chosen_step = (cx, cy, score, streak), step

        if chosen is None:
            # A gap is not the end of the delivery — the ball may be blurred
            # out for a frame or two and reappear on the same trajectory.
            continue

        cx, cy, score, streak = chosen
        track.append(
            BallPosition(frame_index=frame_index, x=cx, y=cy, confidence=score, streak=streak)
        )
        previous_point, current = current, (cx, cy)

    return track
