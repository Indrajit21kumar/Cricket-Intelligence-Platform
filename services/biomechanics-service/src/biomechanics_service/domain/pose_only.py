"""Assemble a RawStroke from pose alone (Pose-First MVP).

M10's normal fan-in wants six upstream inputs. Three of them — bat (M07), ball
(M08) and shot (M09) — are still stubs returning invented values, so a report
built through the usual path carries fabricated numbers dressed as
measurements. This module builds the same RawStroke from the ONLY genuinely
measured inputs available today: M06 pose keypoints, plus M05 calibration and
M04 anthropometrics.

What that costs, stated rather than hidden:

- ``bat`` is an EMPTY tuple, not fabricated geometry. The bat-dependent
  formulas (BM-09 backlift, BM-10 bat path, BM-11 bat lag, BM-12 hand speed,
  BM-13 follow-through) therefore find no bat and return None, which
  ``finalise_metrics`` turns into a null value at zero confidence. They are
  omitted, never guessed.
- ``ball`` carries no release and no contact. Impact comes from wrist motion
  (:mod:`pose_phases`), so the report's ``phase_method`` says
  ``pose_wrist_heuristic`` and nothing claims ball evidence.
- ``shot_type`` is None. No classifier ran, so the report names no stroke.

What survives is the body: shoulder and hip rotation, their separation
(X-Factor), pelvic tilt and front-knee flexion. Those are angles between
keypoints, so they need neither a bat nor a metric scale — which is why they
are deliverable now while the rest waits on training data.
"""

from __future__ import annotations

from collections.abc import Sequence

from biomechanics_service.domain.builder import RawPoseFrame, RawStroke
from biomechanics_service.domain.pose_phases import (
    DEFAULT_THRESHOLDS,
    PhaseThresholds,
    Sample,
    segment_phases_from_pose,
)
from biomechanics_service.domain.stroke import (
    LEFT_WRIST,
    RIGHT_WRIST,
    Anthropometrics,
    BallContext,
    Calibration,
)

#: Timing is anchored to the clip, not to a ball release M08 never found.
TIMING_ABSOLUTE = "absolute"


def _wrist_samples(pose: Sequence[RawPoseFrame]) -> list[Sample]:
    """Wrist-midpoint per frame in image space, None where either is missing.

    Phase detection runs on image-space wrists deliberately: it needs only the
    SHAPE of the motion over time, and the CIP transform is a per-axis affine
    map that leaves the turning points where they are. Running it before
    normalisation keeps the segmenter independent of calibration, which the
    pose-only path frequently lacks.
    """
    if not pose:
        return []
    last_frame = max(f.frame_index for f in pose)
    by_index = {f.frame_index: f for f in pose}
    samples: list[Sample] = []
    for i in range(last_frame + 1):
        frame = by_index.get(i)
        if frame is None:
            samples.append(None)
            continue
        left = frame.joints.get(LEFT_WRIST)
        right = frame.joints.get(RIGHT_WRIST)
        if left is None or right is None:
            samples.append(None)
            continue
        samples.append(((left[0] + right[0]) / 2.0, (left[1] + right[1]) / 2.0))
    return samples


def build_pose_only_stroke(
    *,
    correlation_id: str,
    pose: Sequence[RawPoseFrame],
    calibration: Calibration,
    anthropometrics: Anthropometrics,
    thresholds: PhaseThresholds = DEFAULT_THRESHOLDS,
) -> RawStroke:
    """Assemble the fan-in from pose only — no bat, no ball, no shot label."""
    frame_count = (max(f.frame_index for f in pose) + 1) if pose else 0
    phases = segment_phases_from_pose(
        _wrist_samples(pose),
        fps=calibration.fps,
        frame_count=frame_count,
        thresholds=thresholds,
    )
    return RawStroke(
        correlation_id=correlation_id,
        pose=tuple(pose),
        # Empty, not fabricated: the bat formulas will find nothing and report
        # None rather than a plausible-looking number.
        bat=(),
        phases=phases,
        ball=BallContext(
            release_frame=None,
            contact_frame=None,
            timing_reference=TIMING_ABSOLUTE,
        ),
        anthropometrics=anthropometrics,
        calibration=calibration,
        shot_type=None,
        shot_confidence=None,
        # None, not 0.0: there was no bat detector to lose the bat. Passing a
        # ratio here would trip the FR-M10-06 bat-loss flag and imply M07 ran.
        bat_downswing_failure_ratio=None,
    )
