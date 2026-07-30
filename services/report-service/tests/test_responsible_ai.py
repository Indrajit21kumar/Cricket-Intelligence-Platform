"""Responsible-AI guardrail negative tests (M14 Step 8, §7, AC-M14-08).

Cross-cutting checks the M14 testing strategy calls out by name: provenance
honesty, non-medical language, age-appropriate tone, and legend-endorsement
safety. Each check here is mechanical (a blocklist scan or a structural
property), not a judgement call — the same kind of enforcement this build
already uses for grounding (UngroundedNarrativeError) and the endorsement
guardrail (EndorsementGuardrailError). A real LLM's wording will vary; these
tests exist so a regression in the deterministic fakes — or in the fixed
system copy — is caught immediately rather than relying on manual review.
"""

from __future__ import annotations

import asyncio

import pytest

from report_service.domain.coach import DEFER_MESSAGE, NOT_ENTITLED_MESSAGE, FakeCoachLLMClient, ask
from report_service.domain.evidence import EvidenceChunk
from report_service.domain.legend import (
    DISCLAIMER,
    EndorsementGuardrailError,
    LegendGap,
    LegendStyleComparison,
)
from report_service.domain.narrative import FakeLLMClient, build_narrative

# Diagnostic/clinical language the coach must never use (Book 0 SS11.3 — not medical).
_MEDICAL_TERMS = (
    "diagnos",
    "prescri",
    "treatment",
    "disease",
    "medical condition",
    "symptom",
    "you have a condition",
)

# Harsh/discouraging language that fails the age-appropriate, encouraging tone bar.
_DISCOURAGING_TERMS = (
    "useless",
    "hopeless",
    "give up",
    "you'll never",
    "worthless",
    "failure",
    "you are bad",
    "terrible player",
)


def _matches(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = text.lower()
    return [t for t in terms if t in lowered]


def _evidence() -> list[EvidenceChunk]:
    return [
        EvidenceChunk(
            citation="KG-A@v1",
            text="head falling outside off caused by weight staying back — impact: LBW risk",
            confidence=0.85,
            provenance="measured",
        ),
        EvidenceChunk(
            citation="PH-06@est",
            text="downswing power estimated from segment mass",
            confidence=0.6,
            provenance="estimated",
        ),
    ]


class TestNonMedicalLanguage:
    def test_defer_message_has_no_medical_claim(self) -> None:
        assert _matches(DEFER_MESSAGE, _MEDICAL_TERMS) == []

    def test_not_entitled_message_has_no_medical_claim(self) -> None:
        assert _matches(NOT_ENTITLED_MESSAGE, _MEDICAL_TERMS) == []

    def test_narrative_over_a_game_risk_finding_has_no_medical_claim(self) -> None:
        """'LBW risk' is a dismissal risk (a cricket rule), not a health claim —
        the narrative must not turn it into diagnostic language."""
        narrative = asyncio.run(build_narrative(_evidence(), FakeLLMClient()))
        assert _matches(narrative.text, _MEDICAL_TERMS) == []

    def test_coach_answer_has_no_medical_claim(self) -> None:
        answer = asyncio.run(
            ask("why does my head fall outside off?", _evidence(), FakeCoachLLMClient())
        )
        assert _matches(answer.text, _MEDICAL_TERMS) == []


class TestAgeAppropriateTone:
    def test_defer_message_is_not_discouraging(self) -> None:
        assert _matches(DEFER_MESSAGE, _DISCOURAGING_TERMS) == []

    def test_not_entitled_message_is_not_discouraging(self) -> None:
        assert _matches(NOT_ENTITLED_MESSAGE, _DISCOURAGING_TERMS) == []

    def test_narrative_is_not_discouraging(self) -> None:
        narrative = asyncio.run(build_narrative(_evidence(), FakeLLMClient()))
        assert _matches(narrative.text, _DISCOURAGING_TERMS) == []

    def test_coach_answer_is_not_discouraging(self) -> None:
        answer = asyncio.run(
            ask("why does my head fall outside off?", _evidence(), FakeCoachLLMClient())
        )
        assert _matches(answer.text, _DISCOURAGING_TERMS) == []


class TestProvenanceHonesty:
    def test_narrative_visibly_tags_every_non_measured_chunk(self) -> None:
        narrative = asyncio.run(build_narrative(_evidence(), FakeLLMClient()))
        assert "(estimated)" in narrative.text
        assert "(measured)" not in narrative.text  # measured is the silent default

    def test_coach_answer_visibly_tags_non_measured_evidence(self) -> None:
        answer = asyncio.run(ask("downswing power estimated?", _evidence(), FakeCoachLLMClient()))
        assert "(estimated)" in answer.text


class TestLegendEndorsementSafety:
    def test_disclaimer_never_claims_endorsement(self) -> None:
        assert "endorse" in DISCLAIMER.lower()
        assert "does not claim" in DISCLAIMER.lower()

    def test_a_legend_style_cannot_exist_without_driving_gaps(self) -> None:
        """Structural guardrail already enforced by legend.py — re-asserted here
        as part of the consolidated responsible-AI suite (AC-M14-05/08)."""
        with pytest.raises(EndorsementGuardrailError):
            LegendStyleComparison(
                style_label="cover-drive-style-A", similarity=90.0, driving_gaps=(), confidence=0.9
            )

    def test_a_legend_style_with_gaps_is_fine(self) -> None:
        style = LegendStyleComparison(
            style_label="cover-drive-style-A",
            similarity=72.0,
            driving_gaps=(
                LegendGap(
                    metric_id="BM-01",
                    description="later backlift",
                    player_value=12.0,
                    benchmark_value=8.0,
                ),
            ),
            confidence=0.8,
        )
        assert style.similarity == 72.0
