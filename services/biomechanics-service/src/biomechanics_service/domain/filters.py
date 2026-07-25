"""Savitzky-Golay smoothing for velocity metrics (M10 §7, REQ-BIO-021, FR-M10-04).

Keypoint positions jitter frame to frame. Taking a raw finite difference of a
jittery signal amplifies that jitter and overstates peak speed by 15-30%
(REQ-BIO-021) - so hand speed (BM-12) MUST be smoothed before differentiation,
or it lies.

This is the fixed 5-point, second-order Savitzky-Golay smoother: a local
quadratic least-squares fit, whose closed-form weights for a window of 5 are
``[-3, 12, 17, 12, -3] / 35``. Implemented in pure Python (no numpy) with those
constants directly - deterministic to the last bit, which NFR-M10-03 requires.

Edges (the first and last two samples, where the full window does not fit) keep
their raw value rather than a shortened asymmetric fit. Peak hand speed lands in
the middle of the downswing, well away from the edges, so the untouched
endpoints do not affect the metric that matters.
"""

from __future__ import annotations

# Normalised 5-point quadratic Savitzky-Golay smoothing coefficients.
_SG5_WEIGHTS = (-3.0, 12.0, 17.0, 12.0, -3.0)
_SG5_NORM = 35.0
_HALF = 2  # (window - 1) // 2


def savgol_smooth(values: list[float]) -> list[float]:
    """Smooth a 1-D series with the fixed 5-point quadratic SG filter.

    Series shorter than the window are returned unchanged (nothing to fit).
    """
    n = len(values)
    if n < 5:
        return list(values)
    out = list(values)
    for i in range(_HALF, n - _HALF):
        acc = 0.0
        for k, w in enumerate(_SG5_WEIGHTS):
            acc += w * values[i - _HALF + k]
        out[i] = acc / _SG5_NORM
    return out


def smoothed_speed(
    positions: list[tuple[float, float, float]],
    *,
    fps: float,
) -> list[float]:
    """Per-frame speed (m/s) of a 3D point series, SG-smoothed before differencing.

    Each coordinate is smoothed independently, then a central finite difference
    gives velocity; speed is its magnitude. The result is per-frame so callers
    can take the peak (BM-12) or inspect the profile (BM-14).
    """
    n = len(positions)
    if n < 2 or fps <= 0:
        return [0.0] * n

    xs = savgol_smooth([p[0] for p in positions])
    ys = savgol_smooth([p[1] for p in positions])
    zs = savgol_smooth([p[2] for p in positions])

    speeds: list[float] = []
    for i in range(n):
        lo = max(i - 1, 0)
        hi = min(i + 1, n - 1)
        span = hi - lo
        if span == 0:
            speeds.append(0.0)
            continue
        dt = span / fps
        vx = (xs[hi] - xs[lo]) / dt
        vy = (ys[hi] - ys[lo]) / dt
        vz = (zs[hi] - zs[lo]) / dt
        speeds.append((vx * vx + vy * vy + vz * vz) ** 0.5)
    return speeds


def raw_speed(
    positions: list[tuple[float, float, float]],
    *,
    fps: float,
) -> list[float]:
    """Unsmoothed per-frame speed - used only to demonstrate the jitter the
    smoother removes (the BM-12 test asserts raw >= smoothed peak)."""
    n = len(positions)
    if n < 2 or fps <= 0:
        return [0.0] * n
    speeds = [0.0]
    for i in range(1, n):
        dt = 1.0 / fps
        dx = (positions[i][0] - positions[i - 1][0]) / dt
        dy = (positions[i][1] - positions[i - 1][1]) / dt
        dz = (positions[i][2] - positions[i - 1][2]) / dt
        speeds.append((dx * dx + dy * dy + dz * dz) ** 0.5)
    return speeds
