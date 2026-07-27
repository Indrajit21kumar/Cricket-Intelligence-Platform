"""RAG grounding + citations (M12 Step 6, §11, AC-M12-05)."""

from __future__ import annotations

from typing import Any

from knowledge_service.domain.rag import RagQuery, ground


def _released(rule_id: str, *, fault: str, conf: float) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "version": 2,
        "snapshot": {
            "fault": fault,
            "cause": "weight staying back",
            "risk": {"statement": "LBW risk"},
            "drill": {"name": "closed-shoulder drill", "objective": "head over knee"},
            "confidence": conf,
        },
    }


_CORPUS = [
    _released("KG-A", fault="head falling outside off", conf=0.9),
    _released("KG-B", fault="front elbow collapse", conf=0.8),
]


class TestGround:
    def test_every_result_carries_a_version_citation(self) -> None:
        results = ground(_CORPUS, RagQuery())
        assert results  # no filter -> whole released corpus
        for item in results:
            cite = item.to_dict()["citation"]
            assert cite == {"rule_id": item.rule_id, "version": item.version}

    def test_keyword_filters_the_corpus(self) -> None:
        results = ground(_CORPUS, RagQuery(keyword="elbow"))
        assert [i.rule_id for i in results] == ["KG-B"]

    def test_keyword_searches_drill_and_risk_text(self) -> None:
        assert {i.rule_id for i in ground(_CORPUS, RagQuery(keyword="closed-shoulder"))} == {
            "KG-A",
            "KG-B",
        }
        assert {i.rule_id for i in ground(_CORPUS, RagQuery(keyword="lbw"))} == {"KG-A", "KG-B"}

    def test_rule_ids_filter(self) -> None:
        results = ground(_CORPUS, RagQuery(rule_ids=("KG-A",)))
        assert [i.rule_id for i in results] == ["KG-A"]

    def test_results_are_best_confidence_first(self) -> None:
        assert [i.rule_id for i in ground(_CORPUS, RagQuery())] == ["KG-A", "KG-B"]

    def test_payload_parsing(self) -> None:
        q = RagQuery.from_payload({"rule_ids": ["KG-A"], "keyword": "  ELBOW "})
        assert q.rule_ids == ("KG-A",) and q.keyword == "elbow"
