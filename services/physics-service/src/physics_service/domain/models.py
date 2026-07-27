"""Estimation-model registry + production readiness (M11 §13, Step 8, NFR-M11-04).

The dynamics (PH-06..PH-11) are produced by estimation models, and §13 is
strict: an unvalidated model MUST NOT serve in production. So every model
version is registered with an explicit ``validated`` flag — validated meaning it
has passed the ENG-007 release gate (accuracy against ground truth +
determinism, see :mod:`validation`). Production readiness is a property of the
registered version, not an assumption, so shipping an ungated model is a
deliberate registry change a reviewer can see, never an accident.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    version: str
    #: True once the version has passed the ENG-007 release gate.
    validated: bool
    notes: str = ""


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "phys-est-1.0.0": ModelSpec(
        version="phys-est-1.0.0",
        validated=True,
        notes=(
            "Initial physics estimation models (momentum, torque, energy, GRF, "
            "ball-exit, sweet-spot). Gated against labelled fixture reports; the "
            "gate re-arms on the force-plate / sensor-fused corpus when it lands."
        ),
    ),
}

#: The version stamped on every report this build produces.
ACTIVE_MODEL_VERSION = "phys-est-1.0.0"


def spec(version: str) -> ModelSpec | None:
    return MODEL_REGISTRY.get(version)


def is_production_ready(version: str) -> bool:
    """True only when the version is registered AND validated."""
    model = MODEL_REGISTRY.get(version)
    return model is not None and model.validated
