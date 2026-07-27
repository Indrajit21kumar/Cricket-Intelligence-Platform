"""Ontology vocabulary + edge validation (M12 Step 2, §5, Book 4 Ch. 5)."""

from __future__ import annotations

from knowledge_service.domain.ontology import (
    ENTITY_CAUSE,
    ENTITY_DRILL,
    ENTITY_FAULT,
    ENTITY_METRIC,
    ENTITY_RISK,
    ENTITY_TYPES,
    REL_CAUSED_BY,
    REL_CORRECTED_BY,
    REL_IMPROVES,
    REL_INDICATES,
    is_entity_type,
    is_valid_edge,
)


class TestEntityTypes:
    def test_the_nine_ontology_types_are_present(self) -> None:
        assert len(ENTITY_TYPES) == 9
        assert is_entity_type(ENTITY_FAULT)
        assert not is_entity_type("Nonsense")


class TestEdges:
    def test_the_coaching_chain_edges_are_valid(self) -> None:
        assert is_valid_edge(ENTITY_METRIC, REL_INDICATES, ENTITY_FAULT)
        assert is_valid_edge(ENTITY_FAULT, REL_CAUSED_BY, ENTITY_CAUSE)
        assert is_valid_edge(ENTITY_FAULT, REL_CORRECTED_BY, ENTITY_DRILL)
        assert is_valid_edge(ENTITY_DRILL, REL_IMPROVES, ENTITY_METRIC)

    def test_a_nonsense_edge_is_rejected(self) -> None:
        # A drill does not "cause" a fault, nor does a risk "indicate" anything.
        assert not is_valid_edge(ENTITY_DRILL, REL_CAUSED_BY, ENTITY_FAULT)
        assert not is_valid_edge(ENTITY_RISK, REL_INDICATES, ENTITY_FAULT)
