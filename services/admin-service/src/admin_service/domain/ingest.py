"""Warehouse topic classification (M20 Step 1, FR-M20-03/04).

Every event on the real platform bus is one of two things for the
warehouse: a billing signal (revenue) or a pipeline/adoption signal (usage).
This module is the single place that decides which — the ingestion worker
and its tests both import these constants rather than re-deriving the split.

``billing.notification.requested`` is deliberately excluded: it is an
internal billing -> notification-service signal (M19), not itself a revenue
delta or a usage event, so it does not belong in either fact table.
"""

from __future__ import annotations

from typing import Final

#: Pipeline/adoption topics ingested into ``fact_usage_event`` (FR-M20-04).
USAGE_TOPICS: Final[tuple[str, ...]] = (
    "video.normalized",
    "pose.keypoints",
    "bat.tracked",
    "ball.events",
    "shot.classified",
    "biomechanics.metrics",
    "physics.metrics",
    "analysis.reasoned",
    "report.ready",
    "report.shared",
    "benchmark.compared",
    "dna.updated",
    "plan.updated",
    "session.scheduled",
)

#: M03 billing topics ingested into ``fact_revenue_event`` (FR-M20-03).
REVENUE_TOPICS: Final[tuple[str, ...]] = (
    "billing.invoice.paid",
    "billing.subscription.changed",
    "billing.usage.recorded",
)

ALL_INGESTED_TOPICS: Final[tuple[str, ...]] = USAGE_TOPICS + REVENUE_TOPICS

#: Shared DLQ for the warehouse's own secondary consumption of these topics —
#: distinct from each producing service's own DLQ, since this is an
#: independent consumer group replaying the same topics for a different
#: purpose (Book 2 §4.2: DLQ is per-consumer, not per-topic).
WAREHOUSE_DLQ_TOPIC: Final[str] = "admin.warehouse.dlq"

#: One shared consumer group for every warehouse subscription. Kafka tracks
#: offsets per (group, topic-partition), so one group safely spans many
#: topics without cross-topic interference.
WAREHOUSE_CONSUMER_GROUP: Final[str] = "admin-warehouse"


def is_revenue_topic(topic: str) -> bool:
    return topic in REVENUE_TOPICS


def is_usage_topic(topic: str) -> bool:
    return topic in USAGE_TOPICS
