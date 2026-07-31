"""Channel adapters + dispatch (M19 Step 3, FR-M19-02)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from notification_service.domain.channels import (
    EMAIL,
    IN_APP,
    PUSH,
    FakeEmailChannel,
    FakeInAppChannel,
    FakePushChannel,
    UnknownChannelError,
    dispatch,
)
from notification_service.domain.templates import RenderedMessage

_MESSAGE = RenderedMessage(subject="Subject", body="Body")


def _dispatch(channel: str, *, email=None, push=None, in_app=None, recipient=None):
    return asyncio.run(
        dispatch(
            channel=channel,
            recipient_ref=recipient or uuid.uuid4(),
            message=_MESSAGE,
            email_channel=email or FakeEmailChannel(),
            push_channel=push or FakePushChannel(),
            in_app_channel=in_app or FakeInAppChannel(),
        )
    )


class TestDispatch:
    def test_email_channel_receives_the_send(self) -> None:
        email = FakeEmailChannel()
        recipient = uuid.uuid4()
        ref = _dispatch(EMAIL, email=email, recipient=recipient)
        assert ref.startswith("fake-email-")
        assert email.sent == [(recipient, _MESSAGE)]

    def test_push_channel_receives_the_send(self) -> None:
        push = FakePushChannel()
        recipient = uuid.uuid4()
        ref = _dispatch(PUSH, push=push, recipient=recipient)
        assert ref.startswith("fake-push-")
        assert push.sent == [(recipient, _MESSAGE)]

    def test_in_app_channel_receives_the_send(self) -> None:
        in_app = FakeInAppChannel()
        recipient = uuid.uuid4()
        ref = _dispatch(IN_APP, in_app=in_app, recipient=recipient)
        assert ref.startswith("fake-in-app-")
        assert in_app.sent == [(recipient, _MESSAGE)]

    def test_unknown_channel_raises(self) -> None:
        with pytest.raises(UnknownChannelError):
            _dispatch("carrier_pigeon")

    def test_only_the_targeted_channel_receives_a_send(self) -> None:
        email, push, in_app = FakeEmailChannel(), FakePushChannel(), FakeInAppChannel()
        _dispatch(EMAIL, email=email, push=push, in_app=in_app)
        assert len(email.sent) == 1
        assert push.sent == []
        assert in_app.sent == []
