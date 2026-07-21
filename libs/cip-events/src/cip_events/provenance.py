"""Trust Doctrine (Book 0 §8) — every stored quantity carries one of these labels.

Enforcing provenance at the message layer means downstream stores cannot
accidentally strip it. Report / analytics services persist the label
alongside the value, so the UI can always render "measured" vs
"estimated (confidence 0.87)" vs "modelled" honestly.
"""

from __future__ import annotations

from enum import StrEnum


class Provenance(StrEnum):
    """How a quantity was obtained. Values are the canonical wire strings."""

    #: Directly computed from what the camera observed (e.g. joint angles).
    MEASURED = "measured"
    #: Inferred through a validated model; always paired with a confidence.
    ESTIMATED = "estimated"
    #: Forward-looking simulation or forecast (Digital Twin, vulnerability).
    MODELLED = "modelled"
