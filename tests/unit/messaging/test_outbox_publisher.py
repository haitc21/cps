"""Publisher-confirm regression tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pamqp.commands import Basic

from cps.domain.messaging.outbox import ClaimedOutboxMessage, OutboxClaim
from cps.identifiers import new_uuid7
from cps.infrastructure.messaging import outbox_publisher as publisher_module
from cps.infrastructure.messaging.outbox_publisher import (
    OutboxPublisher,
    PublishConfirmError,
    _close_resources,
)


def _message() -> ClaimedOutboxMessage:
    now = datetime.now(UTC)
    message_id = new_uuid7()
    correlation_id = new_uuid7()
    operation_id = new_uuid7()
    return ClaimedOutboxMessage(
        claim=OutboxClaim(
            row_id=new_uuid7(), claimed_by="test-publisher", claim_token=uuid.uuid4()
        ),
        message_id=message_id,
        message_type="openstack.connection.validate",
        routing_key="openstack.connection.validate",
        payload={
            "message_id": str(message_id),
            "message_type": "openstack.connection.validate",
            "schema_version": "1.0",
            "occurred_at": now.isoformat(),
            "correlation_id": str(correlation_id),
            "operation_id": str(operation_id),
            "provider_id": str(new_uuid7()),
            "provider_connection_id": str(new_uuid7()),
        },
        correlation_id=correlation_id,
        attempt_count=1,
        max_attempts=3,
        claim_expires_at=now + timedelta(seconds=60),
        occurred_at=now,
    )


class _Exchange:
    def __init__(self, confirmation: object) -> None:
        self.confirmation = confirmation

    async def publish(self, *args, **kwargs):
        return self.confirmation


class _CancelledChannelConnection:
    def __init__(self) -> None:
        self.close_calls = 0
        self.original = asyncio.CancelledError()

    async def channel(self, **kwargs):
        raise self.original

    async def close(self) -> None:
        self.close_calls += 1
        raise RuntimeError("close must not mask cancellation")


class _CancelledCloseConnection(_CancelledChannelConnection):
    async def close(self) -> None:
        self.close_calls += 1
        raise asyncio.CancelledError()


class _RuntimeChannelConnection:
    def __init__(self) -> None:
        self.close_calls = 0
        self.error = RuntimeError("declaration programming error")

    async def channel(self, **kwargs):
        raise self.error

    async def close(self) -> None:
        self.close_calls += 1


class _KeyboardChannelConnection:
    def __init__(self) -> None:
        self.close_calls = 0
        self.error = KeyboardInterrupt()

    async def channel(self, **kwargs):
        raise self.error

    async def close(self) -> None:
        self.close_calls += 1


class _CloseResource:
    def __init__(self, name: str, calls: list[str], error: BaseException | None = None) -> None:
        self.name = name
        self.calls = calls
        self.error = error

    async def close(self) -> None:
        self.calls.append(self.name)
        if self.error is not None:
            raise self.error


class _DeclarationChannel:
    def __init__(self, error: BaseException) -> None:
        self.error = error
        self.close_calls = 0

    async def declare_exchange(self, *args, **kwargs):
        raise self.error

    async def close(self) -> None:
        self.close_calls += 1


class _DeclarationConnection:
    def __init__(self, channel: _DeclarationChannel) -> None:
        self.channel_value = channel
        self.close_calls = 0

    async def channel(self, **kwargs):
        return self.channel_value

    async def close(self) -> None:
        self.close_calls += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cleanup_error",
    [
        RuntimeError("close failed"),
        asyncio.CancelledError(),
        KeyboardInterrupt(),
        SystemExit(),
    ],
)
async def test_cleanup_failure_never_masks_primary_base_exception(
    cleanup_error: BaseException,
) -> None:
    calls: list[str] = []
    channel = _CloseResource("channel", calls, cleanup_error)
    connection = _CloseResource("connection", calls)

    await _close_resources(channel, connection, RuntimeError("primary"))

    assert calls == ["channel", "connection"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_error", [KeyboardInterrupt(), SystemExit()])
async def test_cleanup_base_exception_propagates_without_primary(
    cleanup_error: BaseException,
) -> None:
    calls: list[str] = []
    channel = _CloseResource("channel", calls, cleanup_error)
    connection = _CloseResource("connection", calls)

    with pytest.raises(type(cleanup_error)) as raised:
        await _close_resources(channel, connection, None)

    assert raised.value is cleanup_error
    assert calls == ["channel", "connection"]


@pytest.mark.asyncio
async def test_ordinary_cleanup_failure_without_primary_is_stable_error() -> None:
    calls: list[str] = []
    channel = _CloseResource("channel", calls, RuntimeError("must-not-leak"))
    connection = _CloseResource("connection", calls)

    with pytest.raises(PublishConfirmError, match="PUBLISH_CLEANUP_ERROR"):
        await _close_resources(channel, connection, None)

    assert calls == ["channel", "connection"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "primary",
    [RuntimeError("declaration failed"), asyncio.CancelledError(), SystemExit()],
)
async def test_exchange_declaration_failure_closes_channel_and_connection_once(
    primary: BaseException,
) -> None:
    channel = _DeclarationChannel(primary)
    connection = _DeclarationConnection(channel)
    publisher = object.__new__(OutboxPublisher)
    publisher._connect = lambda *args, **kwargs: _return(connection)
    publisher._rabbitmq_url = "amqp://redacted"

    with pytest.raises(type(primary)) as raised:
        await publisher._open_exchange()

    assert raised.value is primary
    assert channel.close_calls == 1
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_only_basic_ack_is_a_positive_confirmation() -> None:
    publisher = object.__new__(OutboxPublisher)
    await publisher._publish_confirmed(_Exchange(Basic.Ack(delivery_tag=1)), _message())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "confirmation",
    [Basic.Nack(delivery_tag=1), Basic.Reject(delivery_tag=1), None],
)
async def test_negative_or_missing_confirmation_is_not_success(confirmation: object) -> None:
    publisher = object.__new__(OutboxPublisher)
    with pytest.raises(PublishConfirmError):
        await publisher._publish_confirmed(_Exchange(confirmation), _message())


@pytest.mark.asyncio
async def test_cancelled_channel_creation_preserves_cancellation_when_close_fails() -> None:
    connection = _CancelledChannelConnection()
    publisher = object.__new__(OutboxPublisher)
    publisher._connect = lambda *args, **kwargs: _return(connection)
    publisher._rabbitmq_url = "amqp://redacted"

    with pytest.raises(asyncio.CancelledError) as raised:
        await publisher._open_exchange()

    assert raised.value is connection.original
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_channel_creation_preserves_cancellation_when_close_cancels() -> None:
    connection = _CancelledCloseConnection()
    publisher = object.__new__(OutboxPublisher)
    publisher._connect = lambda *args, **kwargs: _return(connection)
    publisher._rabbitmq_url = "amqp://redacted"

    with pytest.raises(asyncio.CancelledError) as raised:
        await publisher._open_exchange()

    assert raised.value is connection.original
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_unexpected_channel_error_closes_connection_without_normalization() -> None:
    connection = _RuntimeChannelConnection()
    publisher = object.__new__(OutboxPublisher)
    publisher._connect = lambda *args, **kwargs: _return(connection)
    publisher._rabbitmq_url = "amqp://redacted"

    with pytest.raises(RuntimeError) as raised:
        await publisher._open_exchange()

    assert raised.value is connection.error
    assert connection.close_calls == 1


@pytest.mark.asyncio
async def test_channel_keyboard_interrupt_closes_connection_and_preserves_same_error() -> None:
    connection = _KeyboardChannelConnection()
    publisher = object.__new__(OutboxPublisher)
    publisher._connect = lambda *args, **kwargs: _return(connection)
    publisher._rabbitmq_url = "amqp://redacted"

    with pytest.raises(KeyboardInterrupt) as raised:
        await publisher._open_exchange()

    assert raised.value is connection.error
    assert connection.close_calls == 1


@pytest.mark.parametrize(
    ("publisher_id", "rabbitmq_url", "max_attempts", "message"),
    [
        ("", "amqp://redacted", 3, "publisher id is required"),
        ("publisher", "", 3, "rabbitmq url is required"),
        ("publisher", "amqp://redacted", 2, "maximum attempts must equal canonical default"),
        ("publisher", "amqp://redacted", 4, "maximum attempts must equal canonical default"),
    ],
)
def test_constructor_reports_stable_specific_validation_errors(
    publisher_id: str,
    rabbitmq_url: str,
    max_attempts: int,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        OutboxPublisher(
            session_factory=object(),  # type: ignore[arg-type]
            rabbitmq_url=rabbitmq_url,
            publisher_id=publisher_id,
            max_attempts=max_attempts,
        )


@pytest.mark.asyncio
async def test_network_publish_runs_after_claim_uow_exit_and_before_finalize_uow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    message = _message()

    class TrackedOutbox:
        async def claim_due(self, **kwargs):
            events.append("claim")
            return [message]

        async def mark_published(self, *args, **kwargs):
            events.append("finalize")
            return type("Result", (), {"finalized": True})()

    class TrackedUow:
        count = 0

        def __init__(self, *args) -> None:
            TrackedUow.count += 1
            self.phase = "claim" if TrackedUow.count == 1 else "finalize"
            self.outbox = TrackedOutbox()

        async def __aenter__(self):
            events.append(f"{self.phase}-enter")
            return self

        async def commit(self) -> None:
            events.append(f"{self.phase}-commit")

        async def __aexit__(self, *args) -> bool:
            events.append(f"{self.phase}-exit")
            return False

    class Exchange:
        async def publish(self, *args, **kwargs):
            assert events == ["claim-enter", "claim", "claim-commit", "claim-exit", "connect"]
            events.append("publish")
            return Basic.Ack(delivery_tag=1)

    class Channel:
        async def declare_exchange(self, *args, **kwargs):
            return Exchange()

        async def close(self):
            return None

    class Connection:
        async def channel(self, **kwargs):
            return Channel()

        async def close(self):
            return None

    async def connect(*args, **kwargs):
        events.append("connect")
        return Connection()

    monkeypatch.setattr(publisher_module, "SqlAlchemyUnitOfWork", TrackedUow)
    publisher = OutboxPublisher(
        session_factory=object(),  # type: ignore[arg-type]
        rabbitmq_url="amqp://redacted",
        publisher_id="tracker",
        connect=connect,
    )

    assert await publisher.publish_due(batch_size=1) == 1
    assert events == [
        "claim-enter",
        "claim",
        "claim-commit",
        "claim-exit",
        "connect",
        "publish",
        "finalize-enter",
        "finalize",
        "finalize-commit",
        "finalize-exit",
    ]


@pytest.mark.asyncio
async def test_publish_due_keeps_finalize_error_when_connection_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _message()

    class Outbox:
        async def claim_due(self, **kwargs):
            return [message]

    class Uow:
        count = 0

        def __init__(self, *args) -> None:
            Uow.count += 1
            self.outbox = Outbox()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args) -> bool:
            return False

        async def commit(self) -> None:
            return None

    class Exchange:
        async def publish(self, *args, **kwargs):
            return Basic.Ack(delivery_tag=1)

    class Channel:
        async def declare_exchange(self, *args, **kwargs):
            return Exchange()

        async def close(self) -> None:
            return None

    class Connection:
        async def channel(self, **kwargs):
            return Channel()

        async def close(self) -> None:
            raise RuntimeError("close failure")

    async def connect(*args, **kwargs):
        return Connection()

    monkeypatch.setattr(publisher_module, "SqlAlchemyUnitOfWork", Uow)
    publisher = OutboxPublisher(
        session_factory=object(),  # type: ignore[arg-type]
        rabbitmq_url="amqp://redacted",
        publisher_id="primary-error",
        connect=connect,
    )

    async def fail_finalize(_message: ClaimedOutboxMessage) -> int:
        raise PublishConfirmError("FINALIZE_FAILURE")

    publisher._record_success = fail_finalize  # type: ignore[method-assign]
    with pytest.raises(PublishConfirmError, match="FINALIZE_FAILURE"):
        await publisher.publish_due(batch_size=1)


async def _return(value):
    return value
