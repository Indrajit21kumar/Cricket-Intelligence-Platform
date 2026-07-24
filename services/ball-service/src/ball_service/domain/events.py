"""Event detection: release, bounce, contact + line and length (M08 Step 4).

Each event is inferred from a different signal, and each can independently be
absent. That independence is the design: a clip may show a clear bounce but
start after release, or catch release and lose the ball before contact. Nothing
here infers one event from another's presence.

- **Release** (FR-M08-02) — the start of the tracked flight, but only when the
  track actually begins near the bowler's end. If the first sighting is already
  well down the pitch, release happened off-camera or unseen, and claiming it
  would hand M10 a false timing anchor. That refusal drives
  ``timing_reference = absolute`` in Step 6.
- **Bounce** — the frame where vertical travel reverses. A direction change in
  the data, not a fitted curve, so it survives short or partly-blurred tracks.
- **Contact** — proximity to the bat (from M07's ``bat.tracked``) AND a change
  in ball direction (§11). Both are required: proximity alone happens whenever
  the ball passes a stationary bat, and a direction change alone is the bounce.
  Without M07 data, contact is not claimed.

**Line and length depend on which axis the camera can actually resolve** — the
part that would be easy to fake and wrong to. Length is a DOWN-pitch
measurement and line is an ACROSS-pitch one, and a single camera resolves one
well and the other as depth:

- side-on: the pitch runs across the image, so length is measurable and line
  is depth — unmeasurable.
- front-on (down the pitch): the reverse — line is measurable, length is depth.

So each classifier refuses on the angle that cannot support it, rather than
converting a pixel offset into a confident cricket term. This is FR-M08-03's
"where detected" taken literally.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ball_service.domain.ball import (
    EVENT_BOUNCE,
    EVENT_CONTACT,
    EVENT_RELEASE,
    LENGTH_FULL,
    LENGTH_GOOD,
    LENGTH_SHORT,
    LENGTH_SHORT_OF_GOOD,
    LENGTH_YORKER,
    LINE_DOWN_LEG,
    LINE_LEG_STUMP,
    LINE_MIDDLE,
    LINE_OFF_STUMP,
    LINE_OUTSIDE_OFF,
    BallEvent,
    BallPosition,
)
from ball_service.domain.detection import BallTrack

#: Release must be seen within this fraction of the frame width, measured from
#: whichever edge the ball is travelling AWAY from.
RELEASE_START_LIMIT = 0.35

#: Minimum vertical travel (frame-height units) either side of the turning
#: point for it to be a bounce rather than tracking jitter.
MIN_BOUNCE_TRAVEL = 0.04

#: How close the ball must come to the bat, in frame-height units, for contact.
CONTACT_DISTANCE = 0.08
#: Minimum direction change at contact, in degrees. A ball that passes the bat
#: unchanged was not struck.
MIN_CONTACT_TURN = 25.0

#: Camera angles whose strong axis is DOWN the pitch, so length is measurable.
LENGTH_CAPABLE_ANGLES = frozenset({"side_on"})
#: Camera angles whose strong axis is ACROSS the pitch, so line is measurable.
LINE_CAPABLE_ANGLES = frozenset({"front_on"})


@dataclass(frozen=True, slots=True)
class StumpReference:
    """The pitch landmarks line/length are measured against.

    Positions are on the image X axis in frame-height units — the same axis the
    track uses — because whichever cricket axis the camera resolves, it resolves
    it horizontally. Supplied by the caller from M05 calibration; without it,
    line and length are not classified at all.
    """

    #: Stump position on the image X axis.
    stump_x: float
    #: Roughly a stump-width, used to band the line.
    half_width: float = 0.02
    #: The batter's crease on the image X axis (length only).
    crease_x: float | None = None
    #: Pitch length in the same units, for banding length off the bounce.
    pitch_span: float | None = None


def _turn_degrees(a: BallPosition, b: BallPosition, c: BallPosition) -> float:
    ax, ay = b.x - a.x, b.y - a.y
    bx, by = c.x - b.x, c.y - b.y
    if (ax == 0 and ay == 0) or (bx == 0 and by == 0):
        return 0.0
    dot = ax * bx + ay * by
    cross = ax * by - ay * bx
    return abs(math.degrees(math.atan2(cross, dot)))


def _at(track: BallTrack, frame_index: int) -> BallPosition | None:
    return next((p for p in track.positions if p.frame_index == frame_index), None)


def detect_release(track: BallTrack, *, frame_width: float) -> BallEvent | None:
    """The first tracked frame, IF the track began near the bowler's end.

    ``frame_width`` is the frame's width in frame-height units (width/height),
    so "near the edge" means the same thing at any aspect ratio. Direction of
    travel decides which edge counts, so footage shot from the other side is
    handled without a mirroring flag.

    Refusing here rather than always returning the first frame is the point: a
    false release anchor would silently corrupt every release-relative timing
    M10 computes (BM-17).
    """
    if track.frames_detected < 2:
        return None
    first, last = track.positions[0], track.positions[-1]
    travelling_right = last.x >= first.x
    from_start_edge = first.x if travelling_right else max(frame_width - first.x, 0.0)
    if from_start_edge > RELEASE_START_LIMIT * frame_width:
        # First sighting is already well down the pitch — release was not seen.
        return None
    return BallEvent(kind=EVENT_RELEASE, frame_index=first.frame_index, confidence=first.confidence)


def detect_bounce(track: BallTrack) -> BallEvent | None:
    """The frame where vertical travel reverses — a turning point, not a fit.

    Pixel Y grows downward, so the ball's lowest point is its MAXIMUM y.
    """
    positions = track.positions
    if len(positions) < 3:
        return None

    lowest = max(range(len(positions)), key=lambda i: positions[i].y)
    if lowest in (0, len(positions) - 1):
        # The turning point sits at an end, so no reversal was observed.
        return None

    descent = positions[lowest].y - positions[0].y
    ascent = positions[lowest].y - positions[-1].y
    if descent < MIN_BOUNCE_TRAVEL or ascent < MIN_BOUNCE_TRAVEL:
        # Too little travel either side to tell a bounce from jitter.
        return None

    point = positions[lowest]
    # Bounded by the frames the reversal was actually seen in.
    neighbours = (
        positions[lowest - 1].confidence,
        point.confidence,
        positions[lowest + 1].confidence,
    )
    return BallEvent(kind=EVENT_BOUNCE, frame_index=point.frame_index, confidence=min(neighbours))


def detect_contact(
    track: BallTrack,
    *,
    bat_positions: dict[int, tuple[float, float]] | None,
) -> BallEvent | None:
    """Bat proximity AND a direction change (§11). Both, or no claim.

    ``bat_positions`` maps frame_index to the bat's blade position in the same
    units as the track (from M07). Without it contact is not claimed: proximity
    cannot be established, and a direction change on its own is the bounce.
    """
    if not bat_positions or track.frames_detected < 3:
        return None

    positions = track.positions
    best: tuple[float, BallEvent] | None = None
    for i in range(1, len(positions) - 1):
        point = positions[i]
        bat = bat_positions.get(point.frame_index)
        if bat is None:
            continue
        distance = math.hypot(point.x - bat[0], point.y - bat[1])
        if distance > CONTACT_DISTANCE:
            continue
        if _turn_degrees(positions[i - 1], point, positions[i + 1]) < MIN_CONTACT_TURN:
            # The ball passed the bat without being struck.
            continue
        # Closer is better evidence; confidence reflects both proximity and
        # how well the ball itself was located.
        proximity = 1.0 - (distance / CONTACT_DISTANCE)
        event = BallEvent(
            kind=EVENT_CONTACT,
            frame_index=point.frame_index,
            confidence=min(point.confidence, proximity),
        )
        if best is None or distance < best[0]:
            best = (distance, event)
    return best[1] if best is not None else None


def classify_line(
    bounce: BallEvent | None,
    track: BallTrack,
    *,
    stumps: StumpReference | None,
    camera_angle: str | None,
) -> tuple[str | None, float]:
    """Line relative to the stumps at the bounce point, where measurable.

    Returns ``(None, 0.0)`` without a bounce, without stumps, or from a camera
    angle that sees the across-pitch axis as depth. A line is a claim about
    where the ball pitched relative to the wicket; a side-on pixel offset
    cannot support it.
    """
    if bounce is None or stumps is None:
        return None, 0.0
    if camera_angle not in LINE_CAPABLE_ANGLES:
        return None, 0.0
    point = _at(track, bounce.frame_index)
    if point is None:
        return None, 0.0

    offset = point.x - stumps.stump_x
    band = stumps.half_width
    if offset < -3 * band:
        line = LINE_OUTSIDE_OFF
    elif offset < -band:
        line = LINE_OFF_STUMP
    elif offset <= band:
        line = LINE_MIDDLE
    elif offset <= 3 * band:
        line = LINE_LEG_STUMP
    else:
        line = LINE_DOWN_LEG
    return line, bounce.confidence


def classify_length(
    bounce: BallEvent | None,
    track: BallTrack,
    *,
    stumps: StumpReference | None,
    camera_angle: str | None,
) -> tuple[str | None, float]:
    """Length from where the ball pitched relative to the batter's crease.

    Needs the crease position and the pitch span as well as a bounce; without
    them the distance means nothing in cricket terms, so nothing is claimed.
    Refuses on angles that see the down-pitch axis as depth.
    """
    if bounce is None or stumps is None:
        return None, 0.0
    if camera_angle not in LENGTH_CAPABLE_ANGLES:
        return None, 0.0
    if stumps.crease_x is None or not stumps.pitch_span:
        return None, 0.0
    point = _at(track, bounce.frame_index)
    if point is None:
        return None, 0.0

    # Fraction of the pitch between the bounce and the batter: 0 = at the
    # batter's feet, 1 = at the bowler's end.
    from_batter = abs(point.x - stumps.crease_x) / stumps.pitch_span
    if from_batter <= 0.02:
        length = LENGTH_YORKER
    elif from_batter <= 0.08:
        length = LENGTH_FULL
    elif from_batter <= 0.20:
        length = LENGTH_GOOD
    elif from_batter <= 0.35:
        length = LENGTH_SHORT_OF_GOOD
    else:
        length = LENGTH_SHORT
    return length, bounce.confidence
