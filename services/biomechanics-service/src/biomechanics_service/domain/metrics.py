"""The 17 CIP-STD biomechanical formulas (M10 Step 4, §7, Book 4 Ch. 3).

Pure, deterministic functions of the NormalisedStroke + AlignedPhases. Each
returns a float, or None when the keypoints a metric needs are absent - a
missing metric is honestly absent, never a fabricated zero. compute_metrics()
runs them all and returns ``{BM-id: value | None}``.

Two honest limitations are documented where they bite. COCO-17 has no foot/toe
keypoint, so BM-07 (foot alignment) approximates the foot axis from the shank;
and BM-16 (centre of mass) uses coarse Dempster-style fractions over the
available joints rather than a full segment model. Both are flagged by their
metric class and the depth/spatial-confidence machinery in Step 5.
"""

from __future__ import annotations

import itertools
import math

from biomechanics_service.domain.catalogue import (
    BM_01,
    BM_02,
    BM_03,
    BM_04,
    BM_05,
    BM_06,
    BM_07,
    BM_08,
    BM_09,
    BM_10,
    BM_11,
    BM_12,
    BM_13,
    BM_14,
    BM_15,
    BM_16,
    BM_17,
)
from biomechanics_service.domain.filters import savgol_smooth, smoothed_speed
from biomechanics_service.domain.geometry import (
    Point3D,
    Vector3D,
    angle_between,
    midpoint,
    planar_angle,
    signed_angle_from_vertical,
)
from biomechanics_service.domain.phase_align import AlignedPhases
from biomechanics_service.domain.stroke import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_ELBOW,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    NormalisedStroke,
)

# Dempster-style segment mass fractions over the joints COCO gives us. These do
# not sum to 1 across a full body (COCO has no hands/feet detail); they are
# renormalised at use, so what matters is their RELATIVE weighting - trunk-heavy,
# as a real CoM is.
_COM_WEIGHTS: dict[str, float] = {
    NOSE: 0.081,
    LEFT_SHOULDER: 0.16,
    RIGHT_SHOULDER: 0.16,
    LEFT_HIP: 0.16,
    RIGHT_HIP: 0.16,
    LEFT_KNEE: 0.05,
    RIGHT_KNEE: 0.05,
    LEFT_ANKLE: 0.0145,
    RIGHT_ANKLE: 0.0145,
    LEFT_WRIST: 0.016,
    RIGHT_WRIST: 0.016,
}


def _pt(stroke: NormalisedStroke, frame: int, joint: str) -> Point3D | None:
    f = stroke.pose_at(frame)
    return f.get(joint) if f is not None else None


def _bat_pt(stroke: NormalisedStroke, frame: int, part: str) -> Point3D | None:
    f = stroke.bat_at(frame)
    return f.get(part) if f is not None else None


def _line_angle_topdown(left: Point3D, right: Point3D) -> float:
    """Angle of a body line (left->right keypoints) viewed from above."""
    return planar_angle(right.z - left.z, right.x - left.x)


def _front_foot_is_left(stroke: NormalisedStroke, impact: int) -> bool:
    """The front foot is the one further down the pitch (larger Z) at impact."""
    la = _pt(stroke, impact, LEFT_ANKLE)
    ra = _pt(stroke, impact, RIGHT_ANKLE)
    if la is None or ra is None:
        return True
    return la.z >= ra.z


# --- BM-01: head stability -----------------------------------------------------
def head_stability(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    head_stance = _pt(stroke, phases.stance.start, NOSE)
    head_impact = _pt(stroke, phases.impact_frame, NOSE)
    if head_stance is None or head_impact is None:
        return None
    dx = head_impact.x - head_stance.x
    dz = head_impact.z - head_stance.z
    return math.hypot(dx, dz) * 100.0  # metres -> cm


# --- BM-02 / BM-03: shoulder / hip rotation ------------------------------------
def _segment_rotation(
    stroke: NormalisedStroke, phases: AlignedPhases, left: str, right: str
) -> float | None:
    sl = _pt(stroke, phases.stance.start, left)
    sr = _pt(stroke, phases.stance.start, right)
    il = _pt(stroke, phases.impact_frame, left)
    ir = _pt(stroke, phases.impact_frame, right)
    if None in (sl, sr, il, ir):
        return None
    assert sl and sr and il and ir  # nosec B101  # narrowed by the None check
    return _line_angle_topdown(il, ir) - _line_angle_topdown(sl, sr)


def shoulder_rotation(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    return _segment_rotation(stroke, phases, LEFT_SHOULDER, RIGHT_SHOULDER)


def hip_rotation(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    return _segment_rotation(stroke, phases, LEFT_HIP, RIGHT_HIP)


# --- BM-04: X-Factor (shoulder-hip separation change to downswing start) -------
def x_factor(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    ds = phases.downswing.start
    ssl = _pt(stroke, phases.stance.start, LEFT_SHOULDER)
    ssr = _pt(stroke, phases.stance.start, RIGHT_SHOULDER)
    hsl = _pt(stroke, phases.stance.start, LEFT_HIP)
    hsr = _pt(stroke, phases.stance.start, RIGHT_HIP)
    sdl = _pt(stroke, ds, LEFT_SHOULDER)
    sdr = _pt(stroke, ds, RIGHT_SHOULDER)
    hdl = _pt(stroke, ds, LEFT_HIP)
    hdr = _pt(stroke, ds, RIGHT_HIP)
    if None in (ssl, ssr, hsl, hsr, sdl, sdr, hdl, hdr):
        return None
    assert ssl and ssr and hsl and hsr and sdl and sdr and hdl and hdr  # nosec B101
    shoulder_rot = _line_angle_topdown(sdl, sdr) - _line_angle_topdown(ssl, ssr)
    hip_rot = _line_angle_topdown(hdl, hdr) - _line_angle_topdown(hsl, hsr)
    return shoulder_rot - hip_rot


# --- BM-05: pelvic tilt (hip-line elevation from horizontal at impact) ---------
def pelvic_tilt(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    hl = _pt(stroke, phases.impact_frame, LEFT_HIP)
    hr = _pt(stroke, phases.impact_frame, RIGHT_HIP)
    if hl is None or hr is None:
        return None
    horizontal = math.hypot(hr.x - hl.x, hr.z - hl.z)
    return math.degrees(math.atan2(hr.y - hl.y, horizontal))


# --- BM-06: front knee flexion -------------------------------------------------
def front_knee_flexion(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    impact = phases.impact_frame
    left = _front_foot_is_left(stroke, impact)
    hip = _pt(stroke, impact, LEFT_HIP if left else RIGHT_HIP)
    knee = _pt(stroke, impact, LEFT_KNEE if left else RIGHT_KNEE)
    ankle = _pt(stroke, impact, LEFT_ANKLE if left else RIGHT_ANKLE)
    if hip is None or knee is None or ankle is None:
        return None
    v1 = Vector3D(hip.x - knee.x, hip.y - knee.y, hip.z - knee.z)
    v2 = Vector3D(ankle.x - knee.x, ankle.y - knee.y, ankle.z - knee.z)
    return angle_between(v1, v2)


# --- BM-07: foot alignment (front-shank horizontal axis vs crease) -------------
def foot_alignment(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    """Approximate: COCO-17 has no toe, so the foot axis is taken from the
    shank's horizontal projection. Angle vs the crease line (the X axis)."""
    impact = phases.impact_frame
    left = _front_foot_is_left(stroke, impact)
    knee = _pt(stroke, impact, LEFT_KNEE if left else RIGHT_KNEE)
    ankle = _pt(stroke, impact, LEFT_ANKLE if left else RIGHT_ANKLE)
    if knee is None or ankle is None:
        return None
    dx = ankle.x - knee.x
    dz = ankle.z - knee.z
    if dx == 0.0 and dz == 0.0:
        return None
    # Angle of the horizontal shank direction relative to the crease (X axis).
    return math.degrees(math.atan2(dz, dx))


# --- BM-08: stride length (% of height) ----------------------------------------
def stride_length(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    height_cm = stroke.anthropometrics.height_cm
    if not height_cm:
        return None
    la = _pt(stroke, phases.impact_frame, LEFT_ANKLE)
    ra = _pt(stroke, phases.impact_frame, RIGHT_ANKLE)
    if la is None or ra is None:
        return None
    stride_m = math.hypot(ra.x - la.x, ra.z - la.z)
    stride_cm = stride_m * 100.0
    return stride_cm / height_cm * 100.0


# --- bat angle helper ----------------------------------------------------------
def _bat_angle(stroke: NormalisedStroke, frame: int) -> float | None:
    handle = _bat_pt(stroke, frame, HANDLE_BOTTOM)
    tip = _bat_pt(stroke, frame, BLADE_TIP)
    if handle is None or tip is None:
        return None
    dx = tip.x - handle.x
    dy = tip.y - handle.y
    if dx == 0.0 and dy == 0.0:
        return None
    return signed_angle_from_vertical(dx, dy)


# --- BM-09: backlift (peak bat angle vs vertical in backlift) -------------------
def backlift(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    window = phases.backlift
    if window.is_empty:
        return None
    peak: float | None = None
    for frame in range(window.start, window.end + 1):
        angle = _bat_angle(stroke, frame)
        if angle is None:
            continue
        if peak is None or abs(angle) > abs(peak):
            peak = angle
    return peak


# --- BM-10: bat path linearity (R^2 of sweet-spot path in downswing) -----------
def bat_path_linearity(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    window = phases.downswing
    if window.is_empty:
        return None
    pts: list[tuple[float, float]] = []
    for frame in range(window.start, window.end + 1):
        sp = _bat_pt(stroke, frame, "sweet_spot") or _bat_pt(stroke, frame, BLADE_TIP)
        if sp is not None:
            pts.append((sp.z, sp.y))  # path in the vertical/down-pitch plane
    if len(pts) < 3:
        return None
    return _r_squared(pts)


def _r_squared(pts: list[tuple[float, float]]) -> float:
    """R^2 of the best-fit line y = a*x + b through (x, y) points."""
    n = len(pts)
    mean_x = sum(p[0] for p in pts) / n
    mean_y = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mean_x) ** 2 for p in pts)
    syy = sum((p[1] - mean_y) ** 2 for p in pts)
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in pts)
    if sxx == 0.0 or syy == 0.0:
        # A vertical or horizontal path is perfectly linear.
        return 1.0
    return (sxy * sxy) / (sxx * syy)


# --- forearm angle helper ------------------------------------------------------
def _forearm_angle(stroke: NormalisedStroke, frame: int) -> float | None:
    wrist = _pt(stroke, frame, LEFT_WRIST) or _pt(stroke, frame, RIGHT_WRIST)
    elbow = _pt(stroke, frame, LEFT_ELBOW) or _pt(stroke, frame, RIGHT_ELBOW)
    if wrist is None or elbow is None:
        return None
    dx = wrist.x - elbow.x
    dy = wrist.y - elbow.y
    if dx == 0.0 and dy == 0.0:
        return None
    return signed_angle_from_vertical(dx, dy)


# --- BM-11: bat lag (bat angle - forearm angle at 40% downswing) ---------------
def bat_lag(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    window = phases.downswing
    if window.is_empty:
        return None
    span = window.end - window.start
    frame = window.start + round(0.4 * span)
    bat = _bat_angle(stroke, frame)
    forearm = _forearm_angle(stroke, frame)
    if bat is None or forearm is None:
        return None
    return bat - forearm


# --- BM-12: hand speed (SG-smoothed wrist-midpoint peak, m/s) -------------------
def _wrist_midpoints(stroke: NormalisedStroke) -> list[tuple[int, tuple[float, float, float]]]:
    series: list[tuple[int, tuple[float, float, float]]] = []
    for f in stroke.pose_frames:
        lw, rw = f.get(LEFT_WRIST), f.get(RIGHT_WRIST)
        hands = None
        if lw is not None and rw is not None:
            hands = midpoint(lw, rw)
        elif lw is not None or rw is not None:
            hands = lw or rw
        if hands is not None:
            series.append((f.frame_index, (hands.x, hands.y, hands.z)))
    return series


def hand_speed(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    series = _wrist_midpoints(stroke)
    if len(series) < 2:
        return None
    positions = [p for _, p in series]
    speeds = smoothed_speed(positions, fps=stroke.calibration.fps)
    return max(speeds) if speeds else None


# --- BM-13: follow-through (bat angle change stance -> follow-through end) ------
def follow_through(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    stance_angle = _bat_angle(stroke, phases.stance.start)
    end_frame = phases.follow_through.end
    end_angle = _bat_angle(stroke, end_frame)
    if stance_angle is None or end_angle is None:
        return None
    return end_angle - stance_angle


# --- BM-14: balance recovery (ms from impact until CoM h-velocity < 0.1) --------
def _centre_of_mass(stroke: NormalisedStroke, frame: int) -> Point3D | None:
    f = stroke.pose_at(frame)
    if f is None:
        return None
    total_w = 0.0
    x = y = z = 0.0
    for joint, w in _COM_WEIGHTS.items():
        p = f.get(joint)
        if p is None:
            continue
        x += p.x * w
        y += p.y * w
        z += p.z * w
        total_w += w
    if total_w == 0.0:
        return None
    return Point3D(x / total_w, y / total_w, z / total_w)


def balance_recovery(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    fps = stroke.calibration.fps
    if fps <= 0:
        return None
    coms: list[tuple[int, Point3D]] = []
    for f in stroke.pose_frames:
        com = _centre_of_mass(stroke, f.frame_index)
        if com is not None:
            coms.append((f.frame_index, com))
    if len(coms) < 3:
        return None

    xs = savgol_smooth([c.x for _, c in coms])
    zs = savgol_smooth([c.z for _, c in coms])
    impact = phases.impact_frame
    for i in range(1, len(coms)):
        frame_index = coms[i][0]
        if frame_index <= impact:
            continue
        dt = (coms[i][0] - coms[i - 1][0]) / fps
        if dt <= 0:
            continue
        vx = (xs[i] - xs[i - 1]) / dt
        vz = (zs[i] - zs[i - 1]) / dt
        if math.hypot(vx, vz) < 0.1:
            return (frame_index - impact) / fps * 1000.0
    # Never settled within the clip.
    last = coms[-1][0]
    return (last - impact) / fps * 1000.0


# --- BM-15: weight transfer (estimated proxy from knee-flexion change) ----------
def weight_transfer(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    def flex(frame: int, left: bool) -> float | None:
        hip = _pt(stroke, frame, LEFT_HIP if left else RIGHT_HIP)
        knee = _pt(stroke, frame, LEFT_KNEE if left else RIGHT_KNEE)
        ankle = _pt(stroke, frame, LEFT_ANKLE if left else RIGHT_ANKLE)
        if hip is None or knee is None or ankle is None:
            return None
        v1 = Vector3D(hip.x - knee.x, hip.y - knee.y, hip.z - knee.z)
        v2 = Vector3D(ankle.x - knee.x, ankle.y - knee.y, ankle.z - knee.z)
        return angle_between(v1, v2)

    front_left = _front_foot_is_left(stroke, phases.impact_frame)
    fs = flex(phases.stance.start, front_left)
    fi = flex(phases.impact_frame, front_left)
    bs = flex(phases.stance.start, not front_left)
    bi = flex(phases.impact_frame, not front_left)
    if None in (fs, fi, bs, bi):
        return None
    assert fs is not None and fi is not None and bs is not None and bi is not None  # nosec B101
    # Front knee flexes MORE and back knee straightens as weight moves forward.
    # Map the differential into a [0, 1] proxy centred on 0.5 (balanced).
    delta = (fs - fi) + (bi - bs)
    return max(0.0, min(1.0, 0.5 + delta / 90.0))


# --- BM-16: centre-of-mass path length (cm, X-Z plane) -------------------------
def centre_of_mass_path(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    coms: list[Point3D] = []
    for f in stroke.pose_frames:
        com = _centre_of_mass(stroke, f.frame_index)
        if com is not None:
            coms.append(com)
    if len(coms) < 2:
        return None
    total = 0.0
    for a, b in itertools.pairwise(coms):
        total += math.hypot(b.x - a.x, b.z - a.z)
    return total * 100.0  # metres -> cm


# --- BM-17: ground contact timing (ms) -----------------------------------------
def _front_foot_plant_frame(stroke: NormalisedStroke, phases: AlignedPhases) -> int | None:
    """The front ankle's plant frame — the touchdown, up to impact.

    A plant is the first frame at which the ankle has stopped descending and
    STAYS down. Detected by looking forward: the earliest frame whose height
    matches the next frame's (stationary from here) is the touchdown, not the
    confirmation frame after it — so the timing anchor is the physical plant.
    """
    left = _front_foot_is_left(stroke, phases.impact_frame)
    joint = LEFT_ANKLE if left else RIGHT_ANKLE
    ys: list[tuple[int, float]] = []
    for f in stroke.pose_frames:
        if f.frame_index > phases.impact_frame:
            break
        p = f.get(joint)
        if p is not None:
            ys.append((f.frame_index, p.y))
    for i in range(len(ys) - 1):
        if abs(ys[i + 1][1] - ys[i][1]) < 0.01:
            return ys[i][0]
    return phases.impact_frame


def ground_contact_timing(stroke: NormalisedStroke, phases: AlignedPhases) -> float | None:
    fps = stroke.calibration.fps
    if fps <= 0:
        return None
    plant = _front_foot_plant_frame(stroke, phases)
    if plant is None:
        return None
    release = stroke.ball.release_frame
    if release is not None and stroke.ball.timing_reference == "release_relative":
        return (plant - release) / fps * 1000.0
    # Absolute timing fallback (solo / net, no reliable ball release).
    return plant / fps * 1000.0


def compute_metrics(stroke: NormalisedStroke, phases: AlignedPhases) -> dict[str, float | None]:
    """Run all seventeen formulas. None where inputs are missing."""
    return {
        BM_01: head_stability(stroke, phases),
        BM_02: shoulder_rotation(stroke, phases),
        BM_03: hip_rotation(stroke, phases),
        BM_04: x_factor(stroke, phases),
        BM_05: pelvic_tilt(stroke, phases),
        BM_06: front_knee_flexion(stroke, phases),
        BM_07: foot_alignment(stroke, phases),
        BM_08: stride_length(stroke, phases),
        BM_09: backlift(stroke, phases),
        BM_10: bat_path_linearity(stroke, phases),
        BM_11: bat_lag(stroke, phases),
        BM_12: hand_speed(stroke, phases),
        BM_13: follow_through(stroke, phases),
        BM_14: balance_recovery(stroke, phases),
        BM_15: weight_transfer(stroke, phases),
        BM_16: centre_of_mass_path(stroke, phases),
        BM_17: ground_contact_timing(stroke, phases),
    }
