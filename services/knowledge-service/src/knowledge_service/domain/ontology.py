"""The CIP coaching ontology — the vocabulary M12 speaks (M12 §5, Book 4 Ch. 5).

The typed entities and the relationships that connect them. Encoded here as
constants + a validator so an edge that is not part of the ontology (a Drill
that "causes" a Fault, say) is rejected rather than silently stored — the graph
stays a graph of *meaning*, not arbitrary links.

The five entity-to-entity edges are the coaching chain:

    Metric --indicates--> Fault --caused_by--> Cause
    Fault  --increases--> Risk
    Fault  --corrected_by--> Drill --improves--> Metric

``supported_by`` / ``contradicted_by`` (Book 10) connect a *rule* to a *Source*,
not two entities, so they live on the rule_sources table (Step 8), not here;
their constants are defined for that step to reuse.
"""

from __future__ import annotations

from typing import Final

# --- entity types (Book 4 Ch. 5 §5) ---
ENTITY_SHOT: Final[str] = "Shot"
ENTITY_PHASE: Final[str] = "Phase"
ENTITY_METRIC: Final[str] = "Metric"
ENTITY_FAULT: Final[str] = "Fault"
ENTITY_CAUSE: Final[str] = "Cause"
ENTITY_RISK: Final[str] = "Risk"
ENTITY_DRILL: Final[str] = "Drill"
ENTITY_DELIVERY: Final[str] = "Delivery"
ENTITY_SOURCE: Final[str] = "Source"

ENTITY_TYPES: Final[frozenset[str]] = frozenset(
    {
        ENTITY_SHOT,
        ENTITY_PHASE,
        ENTITY_METRIC,
        ENTITY_FAULT,
        ENTITY_CAUSE,
        ENTITY_RISK,
        ENTITY_DRILL,
        ENTITY_DELIVERY,
        ENTITY_SOURCE,
    }
)

# --- relationship types ---
REL_INDICATES: Final[str] = "indicates"
REL_CAUSED_BY: Final[str] = "caused_by"
REL_INCREASES: Final[str] = "increases"
REL_CORRECTED_BY: Final[str] = "corrected_by"
REL_IMPROVES: Final[str] = "improves"
# Rule <-> Source (Book 10) — stored on rule_sources, not the entity edge table.
REL_SUPPORTED_BY: Final[str] = "supported_by"
REL_CONTRADICTED_BY: Final[str] = "contradicted_by"

#: Legal entity-to-entity edges: (from_type, rel_type, to_type).
VALID_EDGES: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        (ENTITY_METRIC, REL_INDICATES, ENTITY_FAULT),
        (ENTITY_FAULT, REL_CAUSED_BY, ENTITY_CAUSE),
        (ENTITY_FAULT, REL_INCREASES, ENTITY_RISK),
        (ENTITY_FAULT, REL_CORRECTED_BY, ENTITY_DRILL),
        (ENTITY_DRILL, REL_IMPROVES, ENTITY_METRIC),
    }
)


def is_entity_type(type_: str) -> bool:
    return type_ in ENTITY_TYPES


def is_valid_edge(from_type: str, rel_type: str, to_type: str) -> bool:
    return (from_type, rel_type, to_type) in VALID_EDGES
