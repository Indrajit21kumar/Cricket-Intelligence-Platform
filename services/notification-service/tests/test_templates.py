"""Message templating (M19 Step 3, FR-M19-02)."""

from __future__ import annotations

import pytest

from notification_service.domain.event_mapping import (
    BILLING_PAYMENT_FAILED,
    BILLING_PAYMENT_RECOVERED,
    BILLING_PAYMENT_SUSPENDED,
    DNA_UPDATED,
    PLAN_UPDATED,
    REPORT_READY,
    SESSION_SCHEDULED,
    NotificationType,
)
from notification_service.domain.templates import UnknownTemplateError, render_message


class TestRenderMessage:
    def test_report_ready_renders_a_subject_and_body(self) -> None:
        message = render_message(REPORT_READY, {"person_id": "x"})
        assert message.subject == "Your batting analysis is ready"
        assert "ready" in message.body.lower()

    def test_plan_updated_includes_stage_when_present(self) -> None:
        message = render_message(PLAN_UPDATED, {"stage": "associative"})
        assert "associative" in message.body

    def test_plan_updated_omits_stage_clause_when_absent(self) -> None:
        message = render_message(PLAN_UPDATED, {})
        assert "new training plan" in message.body
        assert "None" not in message.body

    def test_dna_updated_renders_an_immediate_message_not_a_digest(self) -> None:
        message = render_message(DNA_UPDATED, {})
        assert "updated" in message.body.lower()

    def test_session_scheduled_includes_time_when_present(self) -> None:
        message = render_message(SESSION_SCHEDULED, {"scheduled_at": "2026-08-01T10:00:00"})
        assert "2026-08-01T10:00:00" in message.body

    def test_session_scheduled_omits_time_clause_when_absent(self) -> None:
        message = render_message(SESSION_SCHEDULED, {})
        assert "None" not in message.body

    def test_billing_payment_failed_includes_attempt_number(self) -> None:
        message = render_message(BILLING_PAYMENT_FAILED, {"attempt_number": 2})
        assert "attempt 2" in message.body

    def test_billing_payment_suspended_renders(self) -> None:
        message = render_message(BILLING_PAYMENT_SUSPENDED, {})
        assert "suspended" in message.body.lower()

    def test_billing_payment_recovered_renders(self) -> None:
        message = render_message(BILLING_PAYMENT_RECOVERED, {})
        assert "successful" in message.body.lower()

    def test_unknown_notification_type_raises(self) -> None:
        with pytest.raises(UnknownTemplateError):
            render_message(NotificationType(key="not_a_real_type", category="engagement"), {})
