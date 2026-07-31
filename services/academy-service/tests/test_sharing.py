"""Report sharing under consent + M19 notify intent (M18 Step 6)."""

from __future__ import annotations

import uuid

import pytest

from academy_service.domain.sharing import (
    COACH,
    GUARDIAN,
    NOTIFY_TOPIC,
    InvalidRecipientError,
    ShareRecipient,
    build_notification_intent,
    evaluate_share,
    parse_recipient,
)
from cip_core import AccessDecision


class TestParseRecipient:
    def test_parses_a_guardian_recipient(self) -> None:
        recipient_id = uuid.uuid4()
        recipient = parse_recipient(f"guardian:{recipient_id}")
        assert recipient == ShareRecipient(kind=GUARDIAN, recipient_id=recipient_id)

    def test_parses_a_coach_recipient(self) -> None:
        recipient_id = uuid.uuid4()
        recipient = parse_recipient(f"coach:{recipient_id}")
        assert recipient == ShareRecipient(kind=COACH, recipient_id=recipient_id)

    def test_unknown_kind_raises(self) -> None:
        with pytest.raises(InvalidRecipientError):
            parse_recipient(f"parent:{uuid.uuid4()}")

    def test_malformed_uuid_raises(self) -> None:
        with pytest.raises(InvalidRecipientError):
            parse_recipient("guardian:not-a-uuid")

    def test_missing_id_raises(self) -> None:
        with pytest.raises(InvalidRecipientError):
            parse_recipient("guardian:")

    def test_no_separator_raises(self) -> None:
        with pytest.raises(InvalidRecipientError):
            parse_recipient("guardian")

    def test_to_ref_round_trips(self) -> None:
        recipient_id = uuid.uuid4()
        recipient = ShareRecipient(kind=GUARDIAN, recipient_id=recipient_id)
        assert recipient.to_ref() == f"guardian:{recipient_id}"


class TestEvaluateShare:
    def test_denied_access_is_denied_regardless_of_assignment(self) -> None:
        recipient = ShareRecipient(kind=GUARDIAN, recipient_id=uuid.uuid4())
        access = AccessDecision(allowed=False, reason="no_consent")
        decision = evaluate_share(recipient=recipient, access=access, is_assigned_coach=True)
        assert decision.allowed is False
        assert decision.reason == "no_consent"

    def test_guardian_is_allowed_on_access_alone(self) -> None:
        recipient = ShareRecipient(kind=GUARDIAN, recipient_id=uuid.uuid4())
        access = AccessDecision(allowed=True, reason="guardian")
        decision = evaluate_share(recipient=recipient, access=access, is_assigned_coach=False)
        assert decision.allowed is True
        assert decision.reason == "guardian"

    def test_coach_with_access_but_not_assigned_is_denied(self) -> None:
        recipient = ShareRecipient(kind=COACH, recipient_id=uuid.uuid4())
        access = AccessDecision(allowed=True, reason="sharing_consent")
        decision = evaluate_share(recipient=recipient, access=access, is_assigned_coach=False)
        assert decision.allowed is False
        assert decision.reason == "coach_not_assigned"

    def test_coach_with_access_and_assignment_is_allowed(self) -> None:
        recipient = ShareRecipient(kind=COACH, recipient_id=uuid.uuid4())
        access = AccessDecision(allowed=True, reason="sharing_consent")
        decision = evaluate_share(recipient=recipient, access=access, is_assigned_coach=True)
        assert decision.allowed is True
        assert decision.reason == "sharing_consent"

    def test_to_dict_shape(self) -> None:
        recipient = ShareRecipient(kind=GUARDIAN, recipient_id=uuid.uuid4())
        access = AccessDecision(allowed=True, reason="guardian")
        decision = evaluate_share(recipient=recipient, access=access, is_assigned_coach=False)
        assert decision.to_dict() == {"allowed": True, "reason": "guardian"}


class TestBuildNotificationIntent:
    def test_shapes_the_intent(self) -> None:
        tenant_id = uuid.uuid4()
        player_ref = uuid.uuid4()
        recipient = ShareRecipient(kind=GUARDIAN, recipient_id=uuid.uuid4())
        intent = build_notification_intent(
            tenant_id=tenant_id,
            player_ref=player_ref,
            recipient=recipient,
            report_ref="report-123",
        )
        assert intent.topic == NOTIFY_TOPIC
        assert intent.tenant_id == tenant_id
        assert intent.player_ref == player_ref
        assert intent.recipient_ref == recipient.to_ref()
        assert intent.report_ref == "report-123"

    def test_to_dict_shape(self) -> None:
        tenant_id = uuid.uuid4()
        player_ref = uuid.uuid4()
        recipient = ShareRecipient(kind=COACH, recipient_id=uuid.uuid4())
        intent = build_notification_intent(
            tenant_id=tenant_id,
            player_ref=player_ref,
            recipient=recipient,
            report_ref="report-123",
        )
        assert intent.to_dict() == {
            "topic": "report.shared",
            "tenant_id": str(tenant_id),
            "player_ref": str(player_ref),
            "recipient_ref": recipient.to_ref(),
            "report_ref": "report-123",
        }
