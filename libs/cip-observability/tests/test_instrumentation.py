"""Tests for :mod:`cip_observability.instrumentation`.

The instrumentors patch imported classes globally, so we test only that
:func:`install` is idempotent and does not raise. Behavioural end-to-end
verification (correlation_id threaded through a multi-hop call) is done in
the reference-service integration tests in Step 6.
"""

from __future__ import annotations

from cip_observability.instrumentation import install


class TestInstall:
    def test_without_app_does_not_raise(self) -> None:
        install(app=None)

    def test_idempotent(self) -> None:
        install(app=None)
        install(app=None)
        install(app=None)
