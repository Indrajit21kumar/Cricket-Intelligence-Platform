"""Channel adapters (M19 Step 3, FR-M19-02).

One Protocol + Fake per channel (email, push, in-app), the same
"adapters + fakes, defer real infra" pattern used throughout this
platform — no service in this build has a real provider (SMTP/APNs/FCM)
wired yet. :func:`dispatch` picks the right adapter for a channel string
and returns whatever provider reference the send produced, ready to be
recorded as a :mod:`delivery_attempts` row (Step 5).
"""

from __future__ import annotations

import uuid
from typing import Protocol

from notification_service.domain.templates import RenderedMessage

EMAIL = "email"
PUSH = "push"
IN_APP = "in_app"
CHANNELS = (EMAIL, PUSH, IN_APP)


class UnknownChannelError(ValueError):
    """Raised when asked to dispatch on a channel this service doesn't know."""


class EmailChannel(Protocol):
    async def send(self, *, recipient_ref: uuid.UUID, message: RenderedMessage) -> str:
        """Send an email; returns the provider's message id/ref."""
        ...


class PushChannel(Protocol):
    async def send(self, *, recipient_ref: uuid.UUID, message: RenderedMessage) -> str:
        """Send a push notification; returns the provider's message id/ref."""
        ...


class InAppChannel(Protocol):
    async def send(self, *, recipient_ref: uuid.UUID, message: RenderedMessage) -> str:
        """Record an in-app notification; returns its own generated ref."""
        ...


class FakeEmailChannel:
    """In-process email channel holding every send for dev + tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, RenderedMessage]] = []

    async def send(self, *, recipient_ref: uuid.UUID, message: RenderedMessage) -> str:
        self.sent.append((recipient_ref, message))
        return f"fake-email-{uuid.uuid4()}"


class FakePushChannel:
    """In-process push channel holding every send for dev + tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, RenderedMessage]] = []

    async def send(self, *, recipient_ref: uuid.UUID, message: RenderedMessage) -> str:
        self.sent.append((recipient_ref, message))
        return f"fake-push-{uuid.uuid4()}"


class FakeInAppChannel:
    """In-process in-app channel holding every send for dev + tests."""

    def __init__(self) -> None:
        self.sent: list[tuple[uuid.UUID, RenderedMessage]] = []

    async def send(self, *, recipient_ref: uuid.UUID, message: RenderedMessage) -> str:
        self.sent.append((recipient_ref, message))
        return f"fake-in-app-{uuid.uuid4()}"


async def dispatch(
    *,
    channel: str,
    recipient_ref: uuid.UUID,
    message: RenderedMessage,
    email_channel: EmailChannel,
    push_channel: PushChannel,
    in_app_channel: InAppChannel,
) -> str:
    """Send ``message`` over ``channel``, returning the provider's message ref."""
    if channel == EMAIL:
        return await email_channel.send(recipient_ref=recipient_ref, message=message)
    if channel == PUSH:
        return await push_channel.send(recipient_ref=recipient_ref, message=message)
    if channel == IN_APP:
        return await in_app_channel.send(recipient_ref=recipient_ref, message=message)
    raise UnknownChannelError(f"unknown channel: {channel!r}")
