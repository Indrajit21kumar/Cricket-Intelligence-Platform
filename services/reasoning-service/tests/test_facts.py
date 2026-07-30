"""Fact assembly from M10/M11/M09 payloads (M13 Step 2, §4, FR-M13-01)."""

from __future__ import annotations

from typing import Any

from reasoning_service.domain.facts import build_fact_set


def _biomechanics() -> dict[str, Any]:
    return {
        "correlation_id": "stroke-1",
        "person_id": "11111111-1111-1111-1111-111111111111",
        "shot_type": "cover_drive",
        "shot_confidence": 0.8,
        "phase_boundaries": {"downswing": 8, "impact": 14},
        "metrics": {
            "BM-01": {"value": 5.0, "provenance": "measured", "confidence": 0.9},
            "BM-17": {"value": 60.0, "provenance": "measured", "confidence": 0.75},
            # A disabled metric (no value) must NOT become a fact.
            "BM-07": {"value": None, "provenance": "measured", "confidence": 0.0},
        },
        "provisional": False,
    }


def _physics() -> dict[str, Any]:
    return {
        "correlation_id": "stroke-1",
        "quantities": {
            "PH-06": {"value": 42.0, "provenance": "estimated", "confidence": 0.66},
            # An omitted estimate (no value) must NOT become a fact.
            "PH-10": {"value": None, "provenance": "estimated", "confidence": None},
        },
        "provisional": False,
    }


class TestBuildFactSet:
    def test_merges_bm_and_ph_value_bearing_facts(self) -> None:
        fs = build_fact_set(biomechanics=_biomechanics(), physics=_physics())
        assert set(fs.facts) == {"BM-01", "BM-17", "PH-06"}  # None-valued dropped
        assert fs.fact("PH-06").is_estimated is True
        assert fs.fact("BM-01").provenance == "measured"

    def test_carries_confidence_and_shot_context(self) -> None:
        fs = build_fact_set(biomechanics=_biomechanics(), physics=_physics())
        assert fs.fact("BM-17").confidence == 0.75
        assert fs.shot_type == "cover_drive" and fs.shot_confidence == 0.8
        assert fs.phases == {"downswing": 8, "impact": 14}
        assert fs.correlation_id == "stroke-1"

    def test_provisional_if_either_report_provisional(self) -> None:
        bio = {**_biomechanics(), "provisional": True}
        assert build_fact_set(biomechanics=bio, physics=_physics()).provisional is True

    def test_direction_lifted_from_detail(self) -> None:
        bio = _biomechanics()
        bio["metrics"]["BM-01"]["detail"] = {"direction": "outside_off"}
        fs = build_fact_set(biomechanics=bio)
        assert fs.fact("BM-01").direction == "outside_off"

    def test_shot_context_from_shot_payload(self) -> None:
        fs = build_fact_set(
            biomechanics=_biomechanics(),
            shot={"context": {"delivery": "full", "line": "outside_off"}},
        )
        assert fs.context == {"delivery": "full", "line": "outside_off"}

    def test_biomechanics_only_still_builds(self) -> None:
        fs = build_fact_set(biomechanics=_biomechanics())
        assert set(fs.facts) == {"BM-01", "BM-17"}


class TestMatchPayload:
    def test_shapes_the_m12_match_request(self) -> None:
        bio = _biomechanics()
        bio["metrics"]["BM-01"]["detail"] = {"direction": "outside_off"}
        payload = build_fact_set(biomechanics=bio, physics=_physics()).match_payload()
        assert payload["metrics"]["BM-17"] == 60.0
        assert payload["metrics"]["PH-06"] == 42.0
        assert payload["directions"] == {"BM-01": "outside_off"}
        assert payload["shot"] == "cover_drive"
