"""Evidence assembly for the RAG-grounded narrative (M14 Step 5, FR-M14-02).

The narrative may assert only what the report's own already-assembled
evidence supports (NFR-M14-02): every claim traces to exactly one finding or
legend style already present in the assembled report (``findings`` +
``legend_view``, taken as plain data rather than importing
``ReportStructure`` itself, to avoid a report.py <-> narrative.py <->
evidence.py import cycle). "Retrieval" here means *selecting and citing*
that evidence, not fetching anything new — M13's findings already carry
pinned M12 rule citations, and M12's own RAG endpoint (M12 Step 6) is for the
AI Coach's open-ended questions (Step 6 of this module), not this fixed
per-report narrative.

Each :class:`EvidenceChunk` is the unit a narrative sentence may draw from;
its ``citation`` is the marker (rule id or style label) that sentence must
carry, so grounding can be checked mechanically (see ``narrative.py``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceChunk:
    """One grounded, citable fact the narrative may build a sentence from."""

    citation: str
    text: str
    confidence: float | None
    provenance: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "citation": self.citation,
            "text": self.text,
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _finding_citation(finding: Mapping[str, Any]) -> str:
    citation_info = finding.get("citation")
    if isinstance(citation_info, Mapping) and citation_info.get("rule_id") is not None:
        return f"{citation_info['rule_id']}@v{citation_info.get('version')}"
    return str(finding.get("finding_id", ""))


def _finding_chunk(finding: Mapping[str, Any]) -> EvidenceChunk:
    parts = [str(finding.get("what", ""))]
    why = finding.get("why")
    if why:
        parts.append(f"caused by {why}")
    impact = finding.get("impact")
    if isinstance(impact, Mapping) and impact.get("statement"):
        parts.append(f"impact: {impact['statement']}")
    drill = finding.get("drill")
    if isinstance(drill, Mapping) and drill.get("name"):
        parts.append(f"recommended drill: {drill['name']}")

    return EvidenceChunk(
        citation=_finding_citation(finding),
        text=" — ".join(parts),
        confidence=_as_float(finding.get("confidence")),
        provenance=_as_str(finding.get("provenance")),
    )


def _legend_chunk(style: Mapping[str, Any]) -> EvidenceChunk:
    gaps = style.get("driving_gaps", [])
    gap_text = "; ".join(
        str(g.get("description", ""))
        for g in gaps
        if isinstance(gaps, Sequence) and isinstance(g, Mapping)
    )
    text = f"{style.get('style_label')} similarity {style.get('similarity')}% — {gap_text}"
    return EvidenceChunk(
        citation=str(style.get("style_label", "")),
        text=text,
        confidence=_as_float(style.get("confidence")),
        provenance="modelled",
    )


def build_evidence(
    *,
    findings: Sequence[Mapping[str, Any]],
    legend_view: Mapping[str, Any] | None,
) -> list[EvidenceChunk]:
    """Every citable fact the narrative may reference — nothing else."""
    chunks = [_finding_chunk(f) for f in findings]
    if legend_view is not None:
        styles = legend_view.get("styles", [])
        if isinstance(styles, Sequence):
            chunks.extend(_legend_chunk(s) for s in styles if isinstance(s, Mapping))
    return chunks
