"""Shot feature vector — the classifier's input (M09 §11).

The full builder (from pose keypoints + optional bat/ball) is Step 2. This is
the SHAPE of what it produces: a compact, model-agnostic description of the
stroke that a classifier reasons over.

Every feature is nullable, and which signals were present is recorded in
:attr:`signals`, because M09's defining behaviour is degrading gracefully to
pose-only (FR-M09-04). A missing bat signal is ``None`` and named absent — it
is never a zero, which the classifier would read as "a bat that did not move".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ShotFeatures:
    """Compact description of a stroke for classification.

    Values are in the CIP frame (Y-up, resolution-independent) where they come
    from geometry. Angles are degrees.
    """

    frame_count: int
    #: Which upstream signals contributed — subset of {pose, bat, ball}.
    signals: tuple[str, ...]

    # --- pose-derived (always present) ---
    #: +1 committed to the front foot, -1 to the back foot, 0 balanced.
    footedness: float = 0.0
    #: Peak wrist height above the stance, in CIP units — high for a lofted
    #: shot, low for a sweep.
    wrist_peak_height: float = 0.0
    #: Horizontal wrist travel across the stroke (across-body reach).
    wrist_lateral_travel: float = 0.0
    #: Shoulder rotation range across the stroke, degrees.
    shoulder_rotation: float = 0.0
    #: Contact height relative to the stance (knee-low vs chest-high).
    contact_height: float = 0.0

    # --- bat-derived (present when M07 ran) ---
    #: Swing-plane inclination from vertical, degrees. Vertical ~ drive,
    #: horizontal ~ pull/cut. None when no bat signal.
    swing_plane_inclination: float | None = None
    #: Total bat-angle sweep across the stroke, degrees.
    bat_angle_range: float | None = None

    # --- ball-derived (present when M08 ran with a usable track) ---
    #: Ball line relative to stumps at contact, e.g. outside_off. None absent.
    ball_line: str | None = None
    #: Ball length band, e.g. short/full. None absent.
    ball_length: str | None = None

    @property
    def has_bat(self) -> bool:
        return "bat" in self.signals

    @property
    def has_ball(self) -> bool:
        return "ball" in self.signals
