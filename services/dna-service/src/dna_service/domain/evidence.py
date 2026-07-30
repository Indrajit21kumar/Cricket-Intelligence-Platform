"""Per-session trait evidence assembly (M16 Step 2, FR-M16-01, §4-5).

Cricket DNA's Performance trait group (timing, power, balance, footwork)
maps directly onto Book 4 Ch. 8's category scores, which M14's report-service
already computes (0-100, from M13 findings) — so this module consumes M14's
published report scores as the per-session evidence signal, rather than
re-deriving a normalized trait score from raw BM/PH metrics a second time.

M14's per-category ``ScoreEntry`` does not carry its own confidence (only
the report-level "confidence" entry does — see
``report_service.domain.scoring._category_score``), so every trait derived
from a report's category scores shares that ONE report-level confidence: how
sure the report's findings were is the honest confidence to attach to
whatever those findings implied about the player's traits.

``trait.aggression`` has no established, measured signal anywhere in this
codebase (no module computes an "aggression" score) and is deliberately NOT
evidenced here — a documented scope decision, not an oversight, the same
"never fabricate a formula the codebase hasn't earned" principle M14/M15
already applied (e.g. M14's ``HIGHER_IS_BETTER`` allow-list).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

EVIDENCE_MODEL_VERSION = "dna-evidence-1.0.0"

#: trait_key -> the M14 report-score category it evidences (Book 4 Ch. 8).
#: A category-derived value is always labelled "modelled" (Book 0 SS8): it's
#: a computed output of findings, never a direct measurement.
TRAIT_SCORE_MAP: dict[str, str] = {
    "trait.timing": "timing",
    "trait.power": "power",
    "trait.balance": "balance",
    "trait.footwork": "footwork",
}


@dataclass(frozen=True, slots=True)
class TraitEvidence:
    """One trait's signal from a single session, ready for the EMA update."""

    trait_key: str
    value: float
    confidence: float
    provenance: str
    source_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "trait_key": self.trait_key,
            "value": self.value,
            "confidence": self.confidence,
            "provenance": self.provenance,
            "source_ref": self.source_ref,
        }


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def gather_evidence(*, report_scores: Mapping[str, Any], source_ref: str) -> list[TraitEvidence]:
    """One TraitEvidence per Performance trait with a usable category score.

    ``report_scores`` is M14's ``Scores.to_dict()`` shape. No report-level
    confidence at all means nothing here is trustworthy enough to evidence a
    trait with — an honest empty result, not a guessed one.
    """
    confidence_entry = report_scores.get("confidence")
    report_confidence = (
        _as_float(confidence_entry.get("confidence"))
        if isinstance(confidence_entry, Mapping)
        else None
    )
    if report_confidence is None:
        return []

    evidence: list[TraitEvidence] = []
    for trait_key, category in TRAIT_SCORE_MAP.items():
        entry = report_scores.get(category)
        if not isinstance(entry, Mapping):
            continue
        value = _as_float(entry.get("value"))
        if value is None:
            continue
        evidence.append(
            TraitEvidence(
                trait_key=trait_key,
                value=value,
                confidence=report_confidence,
                provenance="modelled",
                source_ref=source_ref,
            )
        )
    return evidence
