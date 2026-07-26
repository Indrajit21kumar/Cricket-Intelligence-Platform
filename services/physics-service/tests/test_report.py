"""The assembled PhysicsReport (M11 Step 6, §7, AC-M11-01/03/06/08).

Proves compute_report emits all eleven PH quantities with the right provenance
split, propagates the M10 provisional/quality, adds mass-uncertainty quality,
flags out-of-range without rejecting, and is deterministic.
"""

from __future__ import annotations

from typing import Any

from physics_service.domain.anthropometry import Anthropometrics
from physics_service.domain.quantities import (
    ESTIMATED_IDS,
    MEASURED_IDS,
    PH_IDS,
    PROVENANCE_ESTIMATED,
    PROVENANCE_MEASURED,
)
from physics_service.domain.report import (
    FLAG_MASS_ESTIMATED,
    FLAG_NO_ANTHROPOMETRICS,
    compute_report,
    is_complete,
)

ANTHRO = Anthropometrics(height_cm=180.0, body_mass_kg=75.0)
ANTHRO_NO_MASS = Anthropometrics(height_cm=180.0)


class TestShape:
    def test_emits_all_eleven_quantities(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        assert set(report.quantities) == set(PH_IDS)
        assert is_complete(report) is True

    def test_provenance_split_is_correct(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        for mid in MEASURED_IDS:
            assert report.quantities[mid].provenance == PROVENANCE_MEASURED
        for eid in ESTIMATED_IDS:
            assert report.quantities[eid].provenance == PROVENANCE_ESTIMATED

    def test_every_estimate_with_a_value_carries_a_confidence(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        for eid in ESTIMATED_IDS:
            q = report.quantities[eid]
            if q.value is not None:
                assert q.confidence is not None

    def test_carries_shot_context_and_model_version(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        assert report.shot_type == "cover_drive"
        assert report.model_version == "phys-est-1.0.0"
        assert report.schema_version == "physics.metrics/1.0"


class TestQualityPropagation:
    def test_clean_report_is_not_provisional(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        assert report.provisional is False
        assert report.out_of_expected_range is False

    def test_provisional_propagates_from_m10(self, make_bio: Any) -> None:
        report = compute_report(make_bio(provisional=True), ANTHRO)
        assert report.provisional is True
        assert report.quality.provisional is True
        # Every value-bearing quantity is marked provisional.
        assert all(q.provisional for q in report.quantities.values() if q.value is not None)

    def test_m10_flags_are_propagated(self, make_bio: Any) -> None:
        report = compute_report(make_bio(flags=("ABSOLUTE_TIMING",)), ANTHRO)
        assert "ABSOLUTE_TIMING" in report.quality.flags

    def test_estimated_mass_is_flagged(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO_NO_MASS)
        assert FLAG_MASS_ESTIMATED in report.quality.flags
        assert report.quality.mass_is_estimated is True

    def test_no_anthropometrics_is_flagged(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), None)
        assert FLAG_NO_ANTHROPOMETRICS in report.quality.flags
        assert report.quality.mass_is_estimated is None


class TestPayloads:
    def test_quantities_payload_carries_provenance_and_confidence(self, make_bio: Any) -> None:
        payload = compute_report(make_bio(), ANTHRO).quantities_payload()
        assert set(payload) == set(PH_IDS)
        entry = payload["PH-06"]
        assert entry["provenance"] == "estimated"
        assert entry["confidence"] is not None

    def test_quality_and_chain_payloads_are_well_formed(self, make_bio: Any) -> None:
        report = compute_report(make_bio(), ANTHRO)
        quality = report.quality_payload()
        assert "mass_rel_uncertainty" in quality and "flags" in quality
        chain = report.kinetic_chain_payload()
        assert chain["provenance"] == "estimated" and "links" in chain


class TestDeterminism:
    def test_identical_input_yields_identical_output(self, make_bio: Any) -> None:
        """AC-M11-08: deterministic."""
        a = compute_report(make_bio(), ANTHRO)
        b = compute_report(make_bio(), ANTHRO)
        assert a.quantities_payload() == b.quantities_payload()
        assert a.kinetic_chain_payload() == b.kinetic_chain_payload()
        assert a.quality_payload() == b.quality_payload()
