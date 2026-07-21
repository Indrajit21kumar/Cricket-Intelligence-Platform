"""FastAPI entrypoint for the CIP reference service.

Step 1 exposes only the three endpoints the module spec (§9) mandates:
liveness, readiness, and internal version. Real middleware (tenancy,
correlation, error envelope) and real dependency checks (DB, Kafka, Redis)
are wired in during M01 Step 6.
"""

from __future__ import annotations

from fastapi import FastAPI

from reference_service import __version__

app = FastAPI(
    title="CIP reference-service",
    version=__version__,
    description="Template service. Health + version endpoints only in Step 1.",
)


@app.get("/health/live", tags=["health"])
def health_live() -> dict[str, str]:
    """Liveness probe: the process is up."""
    return {"status": "live"}


@app.get("/health/ready", tags=["health"])
def health_ready() -> dict[str, str]:
    """Readiness probe: dependencies are reachable.

    Step 1 has no dependencies to check; Step 6 replaces this with real
    DB / Kafka / Redis probes.
    """
    return {"status": "ready"}


@app.get("/internal/version", tags=["internal"])
def internal_version() -> dict[str, str]:
    """Build/version info for platform ops."""
    return {"service": "reference-service", "version": __version__}
