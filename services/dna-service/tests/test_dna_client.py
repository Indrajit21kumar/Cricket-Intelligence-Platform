"""M04 DNA read/write adapter (M16 Step 1, FR-M16-04)."""

from __future__ import annotations

import asyncio

from dna_service.domain.dna_client import (
    CurrentTrait,
    DNATraitWrite,
    FakeDNAReader,
    FakeDNAWriter,
)


class TestFakeDNAWriter:
    def test_write_returns_the_count_written(self) -> None:
        writer = FakeDNAWriter()
        updates = [
            DNATraitWrite(trait_key="trait.balance", value="83.0", provenance="measured"),
            DNATraitWrite(trait_key="trait.timing", value="79.5", provenance="measured"),
        ]
        written = asyncio.run(writer.write_traits(person_id="player-1", updates=updates))
        assert written == 2

    def test_writes_are_appended_not_replaced(self) -> None:
        """NFR-M16-04: append-only history, no destructive overwrite."""
        writer = FakeDNAWriter()
        first = [DNATraitWrite(trait_key="trait.balance", value="80.0", provenance="measured")]
        second = [DNATraitWrite(trait_key="trait.balance", value="83.0", provenance="measured")]
        asyncio.run(writer.write_traits(person_id="player-1", updates=first))
        asyncio.run(writer.write_traits(person_id="player-1", updates=second))
        assert len(writer.written["player-1"]) == 2
        assert [u.value for u in writer.written["player-1"]] == ["80.0", "83.0"]

    def test_writes_are_scoped_per_player(self) -> None:
        writer = FakeDNAWriter()
        asyncio.run(
            writer.write_traits(
                person_id="player-1",
                updates=[
                    DNATraitWrite(trait_key="trait.balance", value="80.0", provenance="measured")
                ],
            )
        )
        assert "player-2" not in writer.written


class TestFakeDNAReader:
    def test_no_history_returns_empty_dict(self) -> None:
        reader = FakeDNAReader()
        assert asyncio.run(reader.read_traits("player-1")) == {}

    def test_set_traits_is_returned_for_that_player_only(self) -> None:
        reader = FakeDNAReader()
        traits = {
            "trait.balance": CurrentTrait(trait_key="trait.balance", value="80.0", confidence=0.7)
        }
        reader.set_traits("player-1", traits)
        assert asyncio.run(reader.read_traits("player-1")) == traits
        assert asyncio.run(reader.read_traits("player-2")) == {}
