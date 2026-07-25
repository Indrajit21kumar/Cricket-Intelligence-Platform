"""The CIP-STD metric catalogue — the vocabulary M10 speaks (M10 §7, Book 4 Ch. 3).

Seventeen canonical biomechanical measures, each with a stable ID, a unit, and a
*metric class* that fixes its accuracy tolerance band (M10 §10). The class is
not decoration: the golden-dataset gate (Step 8) checks a different tolerance
per class (angular ±5°, timing ±2 frames, linear ±3 cm, velocity ±10%), so the
class travels with the metric from definition through to the release gate.

One honesty rule is encoded here rather than left to convention: every metric is
MEASURED except BM-15, which is an explicit ESTIMATED proxy (weight transfer
cannot be measured from a single camera, only inferred from knee flexion). The
provenance is a property of the metric ID, so it cannot drift per call site.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- provenance (Book 4 trust doctrine) ---
PROVENANCE_MEASURED = "measured"
PROVENANCE_ESTIMATED = "estimated"

# --- metric classes, each with its own tolerance band ---
CLASS_ANGULAR = "angular"  # ± 5°
CLASS_TIMING = "timing"  # ± 2 frames
CLASS_LINEAR = "linear"  # ± 3 cm (high spatial_confidence only)
CLASS_VELOCITY = "velocity"  # ± 10%
CLASS_RATIO = "ratio"  # unitless (linearity, weight-transfer proxy)


@dataclass(frozen=True, slots=True)
class MetricDef:
    """Static definition of one BM metric."""

    id: str
    name: str
    unit: str
    metric_class: str
    provenance: str = PROVENANCE_MEASURED
    #: Physiologically plausible range [lo, hi]; values outside are FLAGGED for
    #: review, never rejected (Step 6). None where a hard range is ill-defined.
    expected_range: tuple[float, float] | None = None
    #: True when the value depends on the X (across-crease) axis, which a
    #: non-side-on camera cannot resolve — disabled at low spatial confidence.
    x_axis_dependent: bool = False
    #: True when the value needs the bat (M07); provisional on bat loss.
    bat_dependent: bool = False


BM_01 = "BM-01"
BM_02 = "BM-02"
BM_03 = "BM-03"
BM_04 = "BM-04"
BM_05 = "BM-05"
BM_06 = "BM-06"
BM_07 = "BM-07"
BM_08 = "BM-08"
BM_09 = "BM-09"
BM_10 = "BM-10"
BM_11 = "BM-11"
BM_12 = "BM-12"
BM_13 = "BM-13"
BM_14 = "BM-14"
BM_15 = "BM-15"
BM_16 = "BM-16"
BM_17 = "BM-17"

CATALOGUE: dict[str, MetricDef] = {
    BM_01: MetricDef(BM_01, "head_stability", "cm", CLASS_LINEAR, expected_range=(0.0, 30.0)),
    BM_02: MetricDef(
        BM_02, "shoulder_rotation", "deg", CLASS_ANGULAR, expected_range=(-10.0, 120.0)
    ),
    BM_03: MetricDef(BM_03, "hip_rotation", "deg", CLASS_ANGULAR, expected_range=(-10.0, 100.0)),
    BM_04: MetricDef(BM_04, "x_factor", "deg", CLASS_ANGULAR, expected_range=(-20.0, 80.0)),
    BM_05: MetricDef(BM_05, "pelvic_tilt", "deg", CLASS_ANGULAR, expected_range=(-45.0, 45.0)),
    BM_06: MetricDef(
        BM_06, "front_knee_flexion", "deg", CLASS_ANGULAR, expected_range=(90.0, 180.0)
    ),
    BM_07: MetricDef(
        BM_07,
        "foot_alignment",
        "deg",
        CLASS_ANGULAR,
        expected_range=(-90.0, 90.0),
        x_axis_dependent=True,
    ),
    BM_08: MetricDef(
        BM_08,
        "stride_length",
        "pct_height",
        CLASS_LINEAR,
        expected_range=(0.0, 120.0),
        x_axis_dependent=True,
    ),
    BM_09: MetricDef(
        BM_09, "backlift", "deg", CLASS_ANGULAR, expected_range=(-30.0, 180.0), bat_dependent=True
    ),
    BM_10: MetricDef(
        BM_10,
        "bat_path_linearity",
        "ratio",
        CLASS_RATIO,
        expected_range=(0.0, 1.0),
        bat_dependent=True,
    ),
    BM_11: MetricDef(
        BM_11, "bat_lag", "deg", CLASS_ANGULAR, expected_range=(-30.0, 120.0), bat_dependent=True
    ),
    BM_12: MetricDef(
        BM_12,
        "hand_speed",
        "m_per_s",
        CLASS_VELOCITY,
        expected_range=(0.0, 40.0),
        bat_dependent=True,
    ),
    BM_13: MetricDef(
        BM_13,
        "follow_through",
        "deg",
        CLASS_ANGULAR,
        expected_range=(-180.0, 180.0),
        bat_dependent=True,
    ),
    BM_14: MetricDef(BM_14, "balance_recovery", "ms", CLASS_TIMING, expected_range=(0.0, 3000.0)),
    # The one estimated proxy: weight transfer inferred from knee flexion.
    BM_15: MetricDef(
        BM_15,
        "weight_transfer",
        "ratio",
        CLASS_RATIO,
        provenance=PROVENANCE_ESTIMATED,
        expected_range=(0.0, 1.0),
    ),
    BM_16: MetricDef(BM_16, "centre_of_mass_path", "cm", CLASS_LINEAR, expected_range=(0.0, 100.0)),
    BM_17: MetricDef(
        BM_17, "ground_contact_timing", "ms", CLASS_TIMING, expected_range=(-500.0, 1000.0)
    ),
}

BM_IDS: tuple[str, ...] = tuple(CATALOGUE.keys())

#: Bat-dependent metrics, marked provisional on M07 downswing detection loss.
BAT_DEPENDENT_IDS: tuple[str, ...] = tuple(m.id for m in CATALOGUE.values() if m.bat_dependent)
#: X-axis-dependent metrics, disabled when the camera is not side-on.
X_AXIS_DEPENDENT_IDS: tuple[str, ...] = tuple(
    m.id for m in CATALOGUE.values() if m.x_axis_dependent
)

# --- quality flag slugs (M10 §14) ---
FLAG_LOW_CONFIDENCE_INPUT = "LOW_CONFIDENCE_INPUT"
FLAG_BAT_LOSS = "BAT_DETECTION_LOSS"
FLAG_NON_STANDARD_ANGLE = "NON_STANDARD_ANGLE"
FLAG_OUT_OF_RANGE = "OUT_OF_EXPECTED_RANGE"
FLAG_ABSOLUTE_TIMING = "ABSOLUTE_TIMING"

SCHEMA_VERSION = "biomechanics.metrics/1.0"
