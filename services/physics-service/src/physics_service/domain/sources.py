"""Input source adapter (M11 Step 7, §4).

M11's compute is a pure function of two things: the M10 BiomechanicsReport and
the player's M04 anthropometrics. The seam that supplies them is a single
``BiomechanicsSource`` that assembles both into :class:`PhysicsInputs`, keyed by
correlation_id (the stroke id).

The real implementation reads the persisted M10 report (the source of truth,
not the trigger event) and fetches M04 anthropometrics by person; the fake holds
one a test provides, so the whole pipeline runs with no upstream service — which
is exactly the purity boundary (AC-M11-02): the compute never reaches past the
report + anthropometrics.

A None return means the inputs are not assembleable — the M10 report has not
landed, or was rejected — so M11 produces no physics report, which is correct:
there is no biomechanics to turn into physics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from physics_service.domain.anthropometry import Anthropometrics
from physics_service.domain.biomech_input import BiomechanicsInput


@dataclass(frozen=True, slots=True)
class PhysicsInputs:
    """Everything the physics compute needs — and nothing more."""

    bio: BiomechanicsInput
    #: None when the player supplied no body data (no height); the compute then
    #: omits the mass-dependent dynamics honestly.
    anthropometrics: Anthropometrics | None


class BiomechanicsSource(Protocol):
    async def load(self, correlation_id: str) -> PhysicsInputs | None:
        """Assemble the inputs for a stroke, or None when they cannot be built."""
        ...


class FakeBiomechanicsSource:
    """In-process source holding pre-assembled inputs for dev + tests."""

    def __init__(self) -> None:
        self.inputs: dict[str, PhysicsInputs] = {}
        self.missing = False

    def set_inputs(self, correlation_id: str, inputs: PhysicsInputs) -> None:
        self.inputs[correlation_id] = inputs

    async def load(self, correlation_id: str) -> PhysicsInputs | None:
        if self.missing:
            return None
        return self.inputs.get(correlation_id)
