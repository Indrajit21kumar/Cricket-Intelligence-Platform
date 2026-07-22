"""Unit tests for :mod:`billing_service.domain.entitlements`."""

from __future__ import annotations

from billing_service.domain.entitlements import (
    ANALYSIS_QUOTA_MONTHLY,
    FEATURE_AI_COACH,
    SEATS_MAX,
    UNLIMITED,
    is_flag_enabled,
    is_unlimited,
    parse_bool,
    parse_int,
    quota_value,
)


class TestParsing:
    def test_parse_bool_truthy(self) -> None:
        for v in ("true", "True", "1", "yes", "on"):
            assert parse_bool(v) is True

    def test_parse_bool_falsy(self) -> None:
        for v in ("false", "0", "no", "", "off"):
            assert parse_bool(v) is False

    def test_parse_int(self) -> None:
        assert parse_int("5") == 5
        assert parse_int(" -1 ") == -1

    def test_is_unlimited(self) -> None:
        assert is_unlimited(UNLIMITED) is True
        assert is_unlimited(0) is False
        assert is_unlimited(100) is False


class TestFlagResolution:
    def test_flag_enabled(self) -> None:
        ents = {FEATURE_AI_COACH: "true"}
        assert is_flag_enabled(ents, FEATURE_AI_COACH) is True

    def test_flag_disabled(self) -> None:
        ents = {FEATURE_AI_COACH: "false"}
        assert is_flag_enabled(ents, FEATURE_AI_COACH) is False

    def test_flag_missing_is_false(self) -> None:
        assert is_flag_enabled({}, FEATURE_AI_COACH) is False


class TestQuotaResolution:
    def test_quota_present(self) -> None:
        ents = {ANALYSIS_QUOTA_MONTHLY: "5"}
        assert quota_value(ents, ANALYSIS_QUOTA_MONTHLY) == 5

    def test_quota_unlimited(self) -> None:
        ents = {ANALYSIS_QUOTA_MONTHLY: str(UNLIMITED)}
        assert quota_value(ents, ANALYSIS_QUOTA_MONTHLY) == UNLIMITED

    def test_quota_missing_uses_default(self) -> None:
        assert quota_value({}, SEATS_MAX, default=1) == 1
