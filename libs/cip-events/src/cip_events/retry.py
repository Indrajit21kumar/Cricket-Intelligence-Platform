"""Retry policy for the idempotent consumer.

Bounded exponential backoff. On the ``max_attempts + 1``th failure the
consumer routes the message to the DLQ instead of retrying — one of the
central Book 2 §4.2 invariants ("failed processing routes to a per-stage
DLQ; never silently dropped").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff with a hard cap."""

    #: Number of retry attempts before giving up and routing to DLQ.
    #: Attempts include the initial try. ``max_attempts=3`` means try, retry,
    #: retry — 3 total attempts.
    max_attempts: int = 3
    #: Base delay in seconds for the first retry.
    initial_delay_seconds: float = 0.5
    #: Doubling factor per retry. ``2.0`` gives 0.5s, 1.0s, 2.0s, ...
    backoff_factor: float = 2.0
    #: Hard ceiling per retry (prevents runaway waits under many failures).
    max_delay_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be >= 0")
        if self.backoff_factor < 1.0:
            raise ValueError("backoff_factor must be >= 1.0")
        if self.max_delay_seconds < self.initial_delay_seconds:
            raise ValueError("max_delay_seconds must be >= initial_delay_seconds")

    def delay_for_attempt(self, attempt: int) -> float:
        """Return the delay in seconds before ``attempt`` (1-indexed).

        ``attempt=1`` returns ``0.0`` (no delay before the first try).
        ``attempt=2`` returns ``initial_delay_seconds``.
        ``attempt=N`` returns ``initial_delay_seconds * backoff_factor^(N-2)``,
        capped at ``max_delay_seconds``.
        """
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        if attempt == 1:
            return 0.0
        delay = self.initial_delay_seconds * (self.backoff_factor ** (attempt - 2))
        return min(delay, self.max_delay_seconds)

    def should_retry(self, attempt: int) -> bool:
        """True if a further attempt should be scheduled after ``attempt``."""
        return attempt < self.max_attempts
