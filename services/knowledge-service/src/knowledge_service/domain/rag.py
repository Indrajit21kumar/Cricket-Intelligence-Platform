"""RAG grounding — knowledge query -> cited knowledge (M12 Step 6, §11, FR-M12-06).

M14's AI coach must never speak ungrounded: every claim it makes has to trace to
a released rule. This module answers a knowledge query with the released rules'
content, each carrying a CITATION (rule_id + exact version) so the report can
attribute the claim to the precise rule that produced it (AC-M12-05, ENG-005).

Retrieval here is structured, not vector search (embeddings are a future
enhancement): a query filters the released graph by rule id and/or a keyword
over the human-readable fields. Because it draws only from released snapshots,
the coach can never cite a draft.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RagQuery:
    rule_ids: tuple[str, ...] = ()
    keyword: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> RagQuery:
        raw_ids = payload.get("rule_ids", [])
        rule_ids = tuple(str(r) for r in raw_ids) if isinstance(raw_ids, list) else ()
        keyword = payload.get("keyword")
        return cls(rule_ids=rule_ids, keyword=str(keyword).strip().lower() if keyword else None)


@dataclass(frozen=True, slots=True)
class GroundedItem:
    rule_id: str
    version: int
    fault: str | None
    cause: str | None
    risk: dict[str, Any]
    drill: dict[str, Any]
    confidence: float | None
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "fault": self.fault,
            "cause": self.cause,
            "risk": self.risk,
            "drill": self.drill,
            "confidence": self.confidence,
            # Book 10 evidence — tier, who validated it, and the cited sources.
            "evidence": self.evidence,
            # The citation makes the claim traceable to an exact rule version.
            "citation": {"rule_id": self.rule_id, "version": self.version},
        }


def _haystack(snapshot: Mapping[str, Any]) -> str:
    risk = snapshot.get("risk", {})
    drill = snapshot.get("drill", {})
    parts = [
        str(snapshot.get("fault") or ""),
        str(snapshot.get("cause") or ""),
        str(risk.get("statement") or "") if isinstance(risk, Mapping) else "",
        str(drill.get("name") or "") if isinstance(drill, Mapping) else "",
        str(drill.get("objective") or "") if isinstance(drill, Mapping) else "",
    ]
    return " ".join(parts).lower()


def ground(released_snapshots: Sequence[Mapping[str, Any]], query: RagQuery) -> list[GroundedItem]:
    """Return the released knowledge matching the query, each with a citation."""
    items: list[GroundedItem] = []
    for row in released_snapshots:
        rule_id = str(row.get("rule_id", ""))
        if query.rule_ids and rule_id not in query.rule_ids:
            continue
        snapshot = row.get("snapshot", {})
        if not isinstance(snapshot, Mapping):
            continue
        if query.keyword and query.keyword not in _haystack(snapshot):
            continue
        items.append(
            GroundedItem(
                rule_id=rule_id,
                version=int(row.get("version", snapshot.get("version", 0))),
                fault=snapshot.get("fault"),
                cause=snapshot.get("cause"),
                risk=snapshot.get("risk", {}) if isinstance(snapshot.get("risk"), Mapping) else {},
                drill=snapshot.get("drill", {})
                if isinstance(snapshot.get("drill"), Mapping)
                else {},
                confidence=snapshot.get("confidence"),
                evidence=snapshot.get("evidence", {})
                if isinstance(snapshot.get("evidence"), Mapping)
                else {},
            )
        )
    items.sort(key=lambda i: i.confidence if i.confidence is not None else -1.0, reverse=True)
    return items
