"""Kafka-wire implementation of :class:`EventBus` over ``aiokafka``.

Local dev uses Redpanda in docker (Kafka wire-compatible). Production uses
a managed Kafka (Confluent Cloud / MSK) or the cloud's native pub/sub with
a Kafka adapter. The wire format is JSON — schema versioning is enforced
by the envelope's ``schema_version`` field, not by an Avro registry (M01
scope; a registry integration lands with M05 when the vision pipeline
starts producing high-volume analytical events).

Consumer groups are managed by Kafka; committing offsets happens per-message
by the caller (typically :class:`cip_events.consumer.IdempotentConsumer`)
so a crash between "handle" and "commit" doesn't ack a message that was
never durably processed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import ConsumerRecord

from cip_events.envelope import EventEnvelope


class KafkaEventBus:
    """aiokafka-backed :class:`EventBus`."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None
        self._consumers: dict[tuple[str, str], AIOKafkaConsumer] = {}
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            enable_idempotence=True,  # broker-side dedup on producer side
            acks="all",  # wait for full ISR ack (durability > throughput)
        )
        await self._producer.start()
        self._running = True

    async def stop(self) -> None:
        if not self._running:
            return
        for consumer in self._consumers.values():
            await consumer.stop()
        self._consumers.clear()
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
        self._running = False

    async def publish(self, topic: str, envelope: EventEnvelope) -> None:
        if self._producer is None:
            raise RuntimeError("KafkaEventBus.publish before start()")
        # Partition-key by tenant_id so all a tenant's messages land on one
        # partition — preserves ordering within a tenant, and lets consumer
        # instances scale horizontally by tenant.
        key = str(envelope.tenant_id).encode("utf-8")
        value = envelope.model_dump_json().encode("utf-8")
        await self._producer.send_and_wait(topic, value=value, key=key)

    async def consume(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        key = (topic, group_id)
        consumer = self._consumers.get(key)
        if consumer is None:
            consumer = AIOKafkaConsumer(
                topic,
                bootstrap_servers=self._bootstrap,
                group_id=group_id,
                enable_auto_commit=False,  # caller commits after successful handle
                auto_offset_reset="earliest",
            )
            await consumer.start()
            self._consumers[key] = consumer

        try:
            async for record in consumer:
                yield _envelope_from_record(record)
        finally:
            # Explicit close on iterator exit; stop() also handles this if
            # the caller doesn't unwind cleanly.
            pass

    async def commit(self, topic: str, group_id: str) -> None:
        """Commit the current offset for the given (topic, group)."""
        key = (topic, group_id)
        consumer = self._consumers.get(key)
        if consumer is None:
            raise RuntimeError(f"No active consumer for {topic}/{group_id}")
        await consumer.commit()


def _envelope_from_record(record: ConsumerRecord[bytes, bytes]) -> EventEnvelope:
    """Deserialise a Kafka record into an :class:`EventEnvelope`."""
    if record.value is None:
        raise ValueError(f"Kafka record on {record.topic!r} has no value")
    return EventEnvelope.model_validate_json(record.value)
