"""Platform event -> notification type mapping (M19 Step 2, FR-M19-01, AC-M19-01)."""

from __future__ import annotations

import uuid

import pytest

from notification_service.domain.event_mapping import (
    BILLING_PAYMENT_FAILED,
    BILLING_PAYMENT_RECOVERED,
    BILLING_PAYMENT_SUSPENDED,
    DNA_UPDATED,
    ENGAGEMENT,
    PLAN_UPDATED,
    REPORT_READY,
    SESSION_SCHEDULED,
    TRANSACTIONAL,
    UnmappedEventError,
    map_event,
)


class TestFixedTopics:
    def test_report_ready_maps_to_engagement_type_with_person_id(self) -> None:
        person_id = uuid.uuid4()
        mapped = map_event(
            topic="report.ready",
            payload={"person_id": str(person_id), "correlation_id": "corr-1"},
            event_ref="corr-1",
        )
        assert mapped.notification_type == REPORT_READY
        assert mapped.notification_type.category == ENGAGEMENT
        assert mapped.recipient_ref == person_id
        assert mapped.event_ref == "corr-1"

    def test_dna_updated_maps_correctly(self) -> None:
        person_id = uuid.uuid4()
        mapped = map_event(
            topic="dna.updated", payload={"person_id": str(person_id)}, event_ref="e-1"
        )
        assert mapped.notification_type == DNA_UPDATED
        assert mapped.recipient_ref == person_id

    def test_plan_updated_maps_correctly(self) -> None:
        person_id = uuid.uuid4()
        mapped = map_event(
            topic="plan.updated", payload={"person_id": str(person_id)}, event_ref="e-2"
        )
        assert mapped.notification_type == PLAN_UPDATED
        assert mapped.recipient_ref == person_id

    def test_session_scheduled_extracts_coach_ref_not_person_id(self) -> None:
        coach_ref = uuid.uuid4()
        mapped = map_event(
            topic="session.scheduled",
            payload={"coach_ref": str(coach_ref), "tenant_id": str(uuid.uuid4())},
            event_ref="e-3",
        )
        assert mapped.notification_type == SESSION_SCHEDULED
        assert mapped.recipient_ref == coach_ref

    def test_missing_recipient_field_yields_none_not_an_error(self) -> None:
        mapped = map_event(topic="report.ready", payload={}, event_ref="e-4")
        assert mapped.recipient_ref is None

    def test_malformed_recipient_uuid_yields_none_not_an_error(self) -> None:
        mapped = map_event(
            topic="report.ready", payload={"person_id": "not-a-uuid"}, event_ref="e-5"
        )
        assert mapped.recipient_ref is None

    def test_unknown_topic_raises(self) -> None:
        with pytest.raises(UnmappedEventError):
            map_event(topic="some.unknown.topic", payload={}, event_ref="e-6")


class TestBillingNotificationRequested:
    def test_payment_failed_template_maps_to_transactional(self) -> None:
        mapped = map_event(
            topic="billing.notification.requested",
            payload={"template": "billing.payment_failed", "subscription_id": str(uuid.uuid4())},
            event_ref="e-7",
        )
        assert mapped.notification_type == BILLING_PAYMENT_FAILED
        assert mapped.notification_type.category == TRANSACTIONAL

    def test_payment_suspended_template_maps_correctly(self) -> None:
        mapped = map_event(
            topic="billing.notification.requested",
            payload={"template": "billing.payment_suspended"},
            event_ref="e-8",
        )
        assert mapped.notification_type == BILLING_PAYMENT_SUSPENDED

    def test_payment_recovered_template_maps_correctly(self) -> None:
        mapped = map_event(
            topic="billing.notification.requested",
            payload={"template": "billing.payment_recovered"},
            event_ref="e-9",
        )
        assert mapped.notification_type == BILLING_PAYMENT_RECOVERED

    def test_billing_recipient_is_none_no_resolver_yet(self) -> None:
        """Billing's payload carries no person_id — recipient resolution is deferred."""
        mapped = map_event(
            topic="billing.notification.requested",
            payload={"template": "billing.payment_failed", "subscription_id": str(uuid.uuid4())},
            event_ref="e-10",
        )
        assert mapped.recipient_ref is None

    def test_unrecognised_template_raises(self) -> None:
        with pytest.raises(UnmappedEventError):
            map_event(
                topic="billing.notification.requested",
                payload={"template": "billing.something_else"},
                event_ref="e-11",
            )

    def test_missing_template_raises(self) -> None:
        with pytest.raises(UnmappedEventError):
            map_event(topic="billing.notification.requested", payload={}, event_ref="e-12")
