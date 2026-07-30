"""Grounded narrative generation + the grounding guardrail (M14 Step 5, NFR-M14-02)."""

from __future__ import annotations

import asyncio

import pytest

from report_service.domain.evidence import EvidenceChunk
from report_service.domain.narrative import (
    FakeLLMClient,
    UngroundedNarrativeError,
    build_narrative,
)


def _chunk(citation: str = "KG-A@v1", provenance: str | None = "measured") -> EvidenceChunk:
    return EvidenceChunk(
        citation=citation, text="head falling outside off", confidence=0.85, provenance=provenance
    )


class TestFakeLLMClient:
    def test_no_evidence_reports_a_clean_stroke_without_fabricating(self) -> None:
        narrative = asyncio.run(build_narrative([], FakeLLMClient()))
        assert narrative.citations == ()
        assert "clean" in narrative.text.lower()

    def test_every_evidence_chunk_produces_a_cited_sentence(self) -> None:
        evidence = [_chunk("KG-A@v1"), _chunk("KG-B@v1")]
        narrative = asyncio.run(build_narrative(evidence, FakeLLMClient()))
        assert narrative.citations == ("KG-A@v1", "KG-B@v1")
        assert "[KG-A@v1]" in narrative.text
        assert "[KG-B@v1]" in narrative.text

    def test_estimated_provenance_is_visibly_tagged(self) -> None:
        narrative = asyncio.run(build_narrative([_chunk(provenance="estimated")], FakeLLMClient()))
        assert "(estimated)" in narrative.text

    def test_measured_provenance_is_not_tagged(self) -> None:
        narrative = asyncio.run(build_narrative([_chunk(provenance="measured")], FakeLLMClient()))
        assert "(measured)" not in narrative.text


class TestGroundingGuardrail:
    class _HallucinatingLLMClient:
        async def narrate(self, evidence: object) -> str:
            return "the player has excellent timing [NOT-IN-EVIDENCE]"

    def test_a_citation_outside_the_evidence_set_is_rejected(self) -> None:
        with pytest.raises(UngroundedNarrativeError):
            asyncio.run(build_narrative([_chunk("KG-A@v1")], self._HallucinatingLLMClient()))

    class _SilentLLMClient:
        async def narrate(self, evidence: object) -> str:
            return "everything looks great"

    def test_ungrounded_text_with_no_citation_marker_at_all_is_allowed_through(self) -> None:
        """The mechanical check only catches bracketed markers outside evidence —
        it cannot prove every claim in free text is grounded. That is why Step 6's
        AI Coach adds adversarial/negative tests on top of this structural check."""
        narrative = asyncio.run(build_narrative([_chunk("KG-A@v1")], self._SilentLLMClient()))
        assert narrative.citations == ()
