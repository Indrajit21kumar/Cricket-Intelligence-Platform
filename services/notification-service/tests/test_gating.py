"""Send gating — preferences, quiet hours, consent/contactability (M19 Step 4)."""

from __future__ import annotations

import uuid

from notification_service.domain.gating import (
    ENGAGEMENT,
    TRANSACTIONAL,
    GateDecision,
    PreferenceRecord,
    QuietHours,
    gate_send,
    is_quiet_now,
)


class TestIsQuietNow:
    def test_no_quiet_hours_is_never_quiet(self) -> None:
        assert is_quiet_now(None, hour=3) is False

    def test_within_a_same_day_window(self) -> None:
        window = QuietHours(start_hour=13, end_hour=17)
        assert is_quiet_now(window, hour=14) is True
        assert is_quiet_now(window, hour=17) is False
        assert is_quiet_now(window, hour=12) is False

    def test_within_a_midnight_wrapping_window(self) -> None:
        window = QuietHours(start_hour=22, end_hour=7)
        assert is_quiet_now(window, hour=23) is True
        assert is_quiet_now(window, hour=2) is True
        assert is_quiet_now(window, hour=7) is False
        assert is_quiet_now(window, hour=12) is False

    def test_degenerate_equal_start_and_end_is_never_quiet(self) -> None:
        assert is_quiet_now(QuietHours(start_hour=9, end_hour=9), hour=9) is False


def _gate(**overrides: object) -> GateDecision:
    defaults: dict[str, object] = {
        "category": ENGAGEMENT,
        "recipient_ref": uuid.uuid4(),
        "is_contactable": True,
        "is_minor": False,
        "guardian_refs": (),
        "preference": PreferenceRecord(enabled=True, quiet_hours=None),
        "hour": 10,
    }
    defaults.update(overrides)
    return gate_send(**defaults)  # type: ignore[arg-type]


class TestGateSend:
    def test_not_contactable_is_always_refused(self) -> None:
        decision = _gate(is_contactable=False, category=TRANSACTIONAL)
        assert decision.allowed is False
        assert decision.reason == "not_contactable"

    def test_transactional_bypasses_opt_in(self) -> None:
        decision = _gate(category=TRANSACTIONAL, preference=None)
        assert decision.allowed is True
        assert decision.reason == "transactional"

    def test_transactional_bypasses_quiet_hours(self) -> None:
        decision = _gate(
            category=TRANSACTIONAL,
            preference=PreferenceRecord(enabled=False, quiet_hours=QuietHours(22, 7)),
            hour=23,
        )
        assert decision.allowed is True

    def test_engagement_with_no_preference_row_is_refused(self) -> None:
        decision = _gate(category=ENGAGEMENT, preference=None)
        assert decision.allowed is False
        assert decision.reason == "not_opted_in"

    def test_engagement_explicitly_disabled_is_refused(self) -> None:
        decision = _gate(
            category=ENGAGEMENT, preference=PreferenceRecord(enabled=False, quiet_hours=None)
        )
        assert decision.allowed is False
        assert decision.reason == "not_opted_in"

    def test_engagement_opted_in_outside_quiet_hours_is_allowed(self) -> None:
        decision = _gate(
            category=ENGAGEMENT,
            preference=PreferenceRecord(enabled=True, quiet_hours=QuietHours(22, 7)),
            hour=12,
        )
        assert decision.allowed is True
        assert decision.reason == "opted_in"

    def test_engagement_opted_in_during_quiet_hours_is_suppressed(self) -> None:
        decision = _gate(
            category=ENGAGEMENT,
            preference=PreferenceRecord(enabled=True, quiet_hours=QuietHours(22, 7)),
            hour=23,
        )
        assert decision.allowed is False
        assert decision.reason == "quiet_hours"

    def test_minor_with_a_guardian_is_redirected(self) -> None:
        guardian = uuid.uuid4()
        decision = _gate(category=TRANSACTIONAL, is_minor=True, guardian_refs=(guardian,))
        assert decision.allowed is True
        assert decision.effective_recipient_ref == guardian

    def test_minor_without_a_guardian_is_refused(self) -> None:
        decision = _gate(category=TRANSACTIONAL, is_minor=True, guardian_refs=())
        assert decision.allowed is False
        assert decision.reason == "minor_no_guardian"

    def test_adult_recipient_is_the_effective_recipient(self) -> None:
        recipient = uuid.uuid4()
        decision = _gate(category=TRANSACTIONAL, recipient_ref=recipient, is_minor=False)
        assert decision.effective_recipient_ref == recipient
