"""Grounded narrative generation (M14 Step 5, FR-M14-02, NFR-M14-02).

Adapter + fake, the same pattern as every other deferred external call in
this build: :class:`LLMClient` is the seam for the real provider,
:class:`FakeLLMClient` a deterministic stand-in that composes one templated
sentence per :class:`~report_service.domain.evidence.EvidenceChunk` — it
never invents a number, claim, or citation that wasn't already in the
evidence.

Grounding is checked mechanically, not just by convention: every ``[marker]``
in the generated text must match a citation from the evidence that was
retrieved for this call. If a swapped-in real LLM ever cites something
outside that set, :func:`build_narrative` raises rather than shipping an
ungrounded claim (NFR-M14-02).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from report_service.domain.evidence import EvidenceChunk

_CITATION_PATTERN = re.compile(r"\[([^\[\]]+)]")

_CLEAN_STROKE_TEXT = "No findings were identified in this stroke — technique looked clean."


class UngroundedNarrativeError(ValueError):
    """Raised when narrative text cites something outside the retrieved evidence."""


@dataclass(frozen=True, slots=True)
class Narrative:
    text: str
    citations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "citations": list(self.citations)}


class LLMClient(Protocol):
    async def narrate(self, evidence: Sequence[EvidenceChunk]) -> str:
        """Compose grounded narrative text; every claim must cite its evidence chunk."""
        ...


def _provenance_tag(provenance: str | None) -> str:
    return "" if provenance is None or provenance == "measured" else f" ({provenance})"


def _sentence_for(chunk: EvidenceChunk) -> str:
    return f"{chunk.text}{_provenance_tag(chunk.provenance)} [{chunk.citation}]"


class FakeLLMClient:
    """Deterministic narrator: one templated, cited sentence per evidence chunk."""

    async def narrate(self, evidence: Sequence[EvidenceChunk]) -> str:
        if not evidence:
            return _CLEAN_STROKE_TEXT
        return " ".join(_sentence_for(c) for c in evidence)


def _citations_in(text: str) -> set[str]:
    return set(_CITATION_PATTERN.findall(text))


async def build_narrative(evidence: Sequence[EvidenceChunk], llm: LLMClient) -> Narrative:
    """Generate the narrative and verify every cited marker is in ``evidence``."""
    text = await llm.narrate(evidence)
    known = {chunk.citation for chunk in evidence}
    cited = _citations_in(text)
    if not cited <= known:
        raise UngroundedNarrativeError(
            f"narrative cites {sorted(cited - known)} outside the retrieved evidence"
        )
    return Narrative(text=text, citations=tuple(sorted(cited)))
