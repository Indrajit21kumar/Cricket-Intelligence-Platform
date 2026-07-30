"""M04 DNA read/write adapter (M16 Step 1, §8/§10).

M16 is the ONLY writer of trait values (FR-M16-04, AC-M16-02) but never
stores them itself — M04 does (the store/engine split, §8). This mirrors
M04's real write path exactly (``profile-service``'s
``POST /v1/players/{person_id}/dna``, ``domain/dna.py::TraitUpdate``):
trait values are STRINGS on the wire (M04's ``dna_traits.value`` is text — a
trait-typed stringified score/label), each write carries provenance +
optional confidence + an optional ``source_ref``. Following the "adapters +
fakes, defer real infra" pattern used throughout this build, the real HTTP
call to M04 is deferred; :class:`FakeDNAWriter`/:class:`FakeDNAReader` are
deterministic stand-ins.

:class:`FakeDNAWriter` records every write by APPENDING to a per-player
list — never replacing — the same structural proof of append-only history
(NFR-M16-04) that M04's own ``dna_trait_history`` table gives: even the fake
cannot "forget" a prior write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DNATraitWrite:
    """One trait update, shaped exactly like M04's ``TraitUpdateIn``."""

    trait_key: str
    value: str
    provenance: str
    confidence: float | None = None
    source_ref: str | None = None


class DNAWriter(Protocol):
    async def write_traits(self, *, person_id: str, updates: list[DNATraitWrite]) -> int:
        """Write trait updates via M04's write path; returns the count written."""
        ...


class FakeDNAWriter:
    """In-process DNA writer for dev + tests; append-only per player."""

    def __init__(self) -> None:
        self.written: dict[str, list[DNATraitWrite]] = {}

    async def write_traits(self, *, person_id: str, updates: list[DNATraitWrite]) -> int:
        self.written.setdefault(person_id, []).extend(updates)
        return len(updates)


@dataclass(frozen=True, slots=True)
class CurrentTrait:
    """A trait's current stored state, as M16 would read it back from M04."""

    trait_key: str
    value: str
    confidence: float | None = None


class DNAReader(Protocol):
    async def read_traits(self, person_id: str) -> dict[str, CurrentTrait]:
        """Current trait state for this player, keyed by trait_key; {} if none yet."""
        ...


class FakeDNAReader:
    """In-process DNA reader holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.traits: dict[str, dict[str, CurrentTrait]] = {}

    def set_traits(self, person_id: str, traits: dict[str, CurrentTrait]) -> None:
        self.traits[person_id] = traits

    async def read_traits(self, person_id: str) -> dict[str, CurrentTrait]:
        return self.traits.get(person_id, {})
