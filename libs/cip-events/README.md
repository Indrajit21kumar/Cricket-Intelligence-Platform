# cip-events

Event-bus client — publish/subscribe over a Kafka-wire event bus, with idempotent
consumers and dead-letter-queue routing. Built during M01 Step 5.

Every event MUST carry `correlation_id`, `schema_version`, `produced_at`, and
`quality/provenance` fields (Book 2 Ch. 4, Book 3 Ch. 3).
