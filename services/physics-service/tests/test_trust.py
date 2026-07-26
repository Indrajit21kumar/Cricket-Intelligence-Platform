"""Trust Doctrine + range flags (M11 Step 6, §13, AC-M11-03, FR-M11-09).

The negative tests that make the hard rule real: an estimate can never be
labelled measured, and an estimate with a value can never lack a confidence. And
the range check flags, never rejects.
"""

from __future__ import annotations

from typing import Any

import pytest

from physics_service.domain.anthropometry import Anthropometrics
from physics_service.domain.biomech_input import BM_HAND_SPEED, MetricInput
from physics_service.domain.quantities import (
    PH_01,
    PH_06,
    PROVENANCE_ESTIMATED,
    PROVENANCE_MEASURED,
    PhysicsQuantity,
)
from physics_service.domain.ranges import check_ranges
from physics_service.domain.report import compute_report
from physics_service.domain.trust import TrustDoctrineError, enforce_trust

ANTHRO = Anthropometrics(height_cm=180.0, body_mass_kg=75.0)


class TestEnforceTrust:
    def test_a_real_report_passes(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        enforce_trust(report.quantities)  # must not raise

    def test_an_estimate_labelled_measured_is_rejected(self) -> None:
        tampered = {
            PH_06: PhysicsQuantity(
                PH_06, value=42.0, unit="kg_m_per_s", provenance=PROVENANCE_MEASURED, confidence=0.6
            )
        }
        with pytest.raises(TrustDoctrineError):
            enforce_trust(tampered)

    def test_an_estimate_without_a_confidence_is_rejected(self) -> None:
        tampered = {
            PH_06: PhysicsQuantity(
                PH_06,
                value=42.0,
                unit="kg_m_per_s",
                provenance=PROVENANCE_ESTIMATED,
                confidence=None,
            )
        }
        with pytest.raises(TrustDoctrineError):
            enforce_trust(tampered)

    def test_a_measured_labelled_estimated_is_rejected(self) -> None:
        tampered = {
            PH_01: PhysicsQuantity(
                PH_01, value=20.0, unit="m_per_s", provenance=PROVENANCE_ESTIMATED, confidence=0.8
            )
        }
        with pytest.raises(TrustDoctrineError):
            enforce_trust(tampered)


class TestRangeFlags:
    def test_a_normal_report_is_in_range(self, make_bio: Any) -> None:
        assert check_ranges(compute_report(make_bio(), ANTHRO).quantities) == ()

    def test_an_out_of_range_value_is_flagged_but_kept(self, make_bio: Any) -> None:
        # An impossible 100 m/s hand speed -> PH-01 out of (0,45), never dropped.
        wild = make_bio(overrides={BM_HAND_SPEED: MetricInput(100.0, "measured", 0.8)})
        report = compute_report(wild, ANTHRO)
        assert PH_01 in report.quality.out_of_expected_range_quantities
        assert report.out_of_expected_range is True
        # Flagged for review, NOT rejected — the value is still there.
        assert report.quantities[PH_01].value == 100.0
