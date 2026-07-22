"""Entitlement value model + typed parsing.

Entitlements are stored as ``(key, value)`` text pairs on a plan. Feature
modules consume stable keys; the value is interpreted per key type:

- quota keys (``*.quota_*``, ``seats.max``) are integers; ``-1`` means
  unlimited (fair-use).
- feature flags (``feature.*``) are booleans (``"true"`` / ``"false"``).

Keeping the interpretation in one place means feature modules never parse
raw strings — they call :func:`is_flag_enabled` / :func:`quota_value`.
"""

from __future__ import annotations

UNLIMITED = -1

# Stable entitlement keys consumed across the platform (M03 §5).
ANALYSIS_QUOTA_MONTHLY = "analysis.quota_monthly"
FEATURE_AI_COACH = "feature.ai_coach"
FEATURE_LEGEND_COMPARISON = "feature.legend_comparison"
FEATURE_PARTNER_API = "feature.partner_api"
SEATS_MAX = "seats.max"


def parse_bool(value: str) -> bool:
    """Parse a stored flag value to bool."""
    return value.strip().lower() in {"true", "1", "yes", "on"}


def parse_int(value: str) -> int:
    """Parse a stored quota value to int (``-1`` = unlimited)."""
    return int(value.strip())


def is_unlimited(quota: int) -> bool:
    return quota == UNLIMITED


def is_flag_enabled(entitlements: dict[str, str], key: str) -> bool:
    """True if the boolean entitlement ``key`` is present and truthy."""
    raw = entitlements.get(key)
    return raw is not None and parse_bool(raw)


def quota_value(entitlements: dict[str, str], key: str, *, default: int = 0) -> int:
    """Return the integer quota for ``key`` (``-1`` = unlimited)."""
    raw = entitlements.get(key)
    return parse_int(raw) if raw is not None else default
