"""CPS worker runtime acceptance tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from cps.config import Settings
from cps.infrastructure.messaging.constants import DEFAULT_PREFETCH_COUNT, QUEUE_CPS_EVENT
from cps.infrastructure.messaging.lifecycle import WorkerLifecycle as InfraWorkerLifecycle
from cps.messaging import lifecycle as messaging_lifecycle


class _FakeChannel:
    def __init__(self, *, close_raises: bool = False) -> None:
        self.is_closed = False
        self.closed = False
        self.close_raises = close_raises
        self.qos_prefetch: int | None = None
        self.publisher_confirms = False

    async def set_qos(self, prefetch_count: int, **_kwargs: Any) -> None:
        self.qos_prefetch = prefetch_count

    async def close(self) -> None:
        if self.close_raises:
            raise RuntimeError("channel close failed")
        self.closed = True
        self.is_closed = True


class _FakeQueue:
    name = QUEUE_CPS_EVENT
    consume_started = False

    async def consume(self, callback, *, no_ack: bool = False) -> str:
        self.consume_started = True
        return "consumer-tag"

    async def cancel(self, consumer_tag: str) -> None:
        return None


class _FakeTopology:
    def __init__(self) -> None:
        self.retry_exchange = object()
        self.event_queue = _FakeQueue()


class _FakeConnection:
    def __init__(self, channel: _FakeChannel | None = None) -> None:
        self.is_closed = False
        self.closed = False
        self._channel = channel or _FakeChannel()

    async def channel(self, *, publisher_confirms: bool = False) -> _FakeChannel:
        self._channel.publisher_confirms = publisher_confirms
        return self._channel

    async def close(self) -> None:
        self.closed = True
        self.is_closed = True


class _RecordingEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


def _patch_db(monkeypatch: pytest.MonkeyPatch, worker_runtime: Any) -> _RecordingEngine:
    engine = _RecordingEngine()
    monkeypatch.setattr(worker_runtime, "create_database_engine", lambda _url: engine)
    monkeypatch.setattr(worker_runtime, "create_session_factory", lambda _engine: object())
    return engine


@pytest.fixture(autouse=True)
def reset_recording_engine() -> None:
    return None


def _settings(**overrides: Any) -> Settings:
    return Settings(environment="test", _env_file=None, **overrides)


@pytest.mark.asyncio
async def test_worker_lifecycle_is_canonical_reexport() -> None:
    assert messaging_lifecycle.WorkerLifecycle is InfraWorkerLifecycle


@pytest.mark.asyncio
async def test_run_worker_once_declares_topology_without_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    calls: list[str] = []
    channel = _FakeChannel()
    connection = _FakeConnection(channel)

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        calls.append(f"connect:{url}")
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        calls.append("declare")
        return _FakeTopology()

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    engine = _patch_db(monkeypatch, worker_runtime)

    lifecycle = worker_runtime.WorkerLifecycle()
    settings = _settings(rabbitmq_url="amqp://cmp:cmp_dev_password@127.0.0.1:5672/cmp")

    await worker_runtime.run_worker(settings=settings, lifecycle=lifecycle, once=True)

    assert calls == [
        f"connect:{settings.require_rabbitmq_url}",
        "declare",
    ]
    assert channel.qos_prefetch == DEFAULT_PREFETCH_COUNT
    assert channel.publisher_confirms is True
    assert lifecycle.accepting_work is False
    assert not _FakeQueue.consume_started
    assert engine.disposed is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_run_worker_start_order_connect_channel_topology_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    calls: list[str] = []
    channel = _FakeChannel()
    connection = _FakeConnection(channel)
    stop_event = asyncio.Event()

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        calls.append("connect")
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        calls.append("declare")
        return _FakeTopology()

    original_create_consumer = worker_runtime._WorkerResources.create_consumer

    def recording_create_consumer(self: worker_runtime._WorkerResources) -> Any:
        calls.append("create_consumer")
        consumer = original_create_consumer(self)

        original_start = consumer.start

        async def recording_start(ch: Any, queue: Any) -> str:
            calls.append("start_consumer")
            return await original_start(ch, queue)

        consumer.start = recording_start  # type: ignore[method-assign]
        return consumer

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    monkeypatch.setattr(
        worker_runtime._WorkerResources, "create_consumer", recording_create_consumer
    )
    _patch_db(monkeypatch, worker_runtime)

    task = asyncio.create_task(
        worker_runtime.run_worker(
            settings=_settings(),
            lifecycle=worker_runtime.WorkerLifecycle(),
            once=False,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert calls == ["connect", "declare", "create_consumer", "start_consumer"]


@pytest.mark.asyncio
async def test_topology_failure_does_not_log_ready_and_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from cps.messaging import runtime as worker_runtime

    connection = _FakeConnection()

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        return connection

    async def failing_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        raise RuntimeError("topology failed")

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", failing_declare)
    engine = _patch_db(monkeypatch, worker_runtime)

    with pytest.raises(RuntimeError, match="topology failed"):
        await worker_runtime.run_worker(settings=_settings(), once=True)

    assert "cps worker ready" not in caplog.text
    assert engine.disposed is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_consumer_start_failure_cleans_up_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    channel = _FakeChannel()
    connection = _FakeConnection(channel)

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    async def failing_start(self: worker_runtime._WorkerResources) -> None:
        self.lifecycle.begin_shutdown()
        raise RuntimeError("consumer start failed")

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    monkeypatch.setattr(worker_runtime._WorkerResources, "start_consumer", failing_start)
    engine = _patch_db(monkeypatch, worker_runtime)

    with pytest.raises(RuntimeError, match="consumer start failed"):
        await worker_runtime.run_worker(
            settings=_settings(), once=False, stop_event=asyncio.Event()
        )

    assert engine.disposed is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_run_worker_cancellation_preserves_cancelled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    connection = _FakeConnection()

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    engine = _patch_db(monkeypatch, worker_runtime)

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker_runtime.run_worker(
            settings=_settings(),
            lifecycle=worker_runtime.WorkerLifecycle(),
            once=False,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.disposed is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_channel_close_error_still_closes_connection_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    channel = _FakeChannel(close_raises=True)
    connection = _FakeConnection(channel)

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    engine = _patch_db(monkeypatch, worker_runtime)

    await worker_runtime.run_worker(settings=_settings(), once=True)

    assert engine.disposed is True
    assert connection.closed is True


@pytest.mark.asyncio
async def test_signal_shutdown_uses_same_lifecycle_as_consumer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    shared_lifecycle = worker_runtime.WorkerLifecycle()
    captured: list[worker_runtime.WorkerLifecycle] = []

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        return _FakeConnection()

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    original_create_consumer = worker_runtime._WorkerResources.create_consumer

    def capture_lifecycle(self: worker_runtime._WorkerResources) -> Any:
        consumer = original_create_consumer(self)
        captured.append(self.lifecycle)
        return consumer

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    monkeypatch.setattr(worker_runtime._WorkerResources, "create_consumer", capture_lifecycle)
    _patch_db(monkeypatch, worker_runtime)

    stop_event = asyncio.Event()
    task = asyncio.create_task(
        worker_runtime.run_worker(
            settings=_settings(),
            lifecycle=shared_lifecycle,
            once=False,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert captured == [shared_lifecycle]
    assert shared_lifecycle.accepting_work is False


@pytest.mark.asyncio
async def test_session_failure_reconnects_without_final_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    connect_count = 0
    channel = _FakeChannel()
    connection = _FakeConnection(channel)
    stop_event = asyncio.Event()
    lifecycle = worker_runtime.WorkerLifecycle()
    accepting_on_reconnect: list[bool] = []

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        nonlocal connect_count, channel, connection
        connect_count += 1
        accepting_on_reconnect.append(lifecycle.accepting_work)
        if connect_count == 1:
            channel = _FakeChannel()
            connection = _FakeConnection(channel)
            return connection
        channel = _FakeChannel()
        connection = _FakeConnection(channel)
        stop_event.set()
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    original_start_consumer = worker_runtime._WorkerResources.start_consumer

    async def fail_first_start(self: worker_runtime._WorkerResources) -> None:
        if connect_count == 1:
            raise RuntimeError("session bootstrap failed")
        await original_start_consumer(self)

    monkeypatch.setattr(worker_runtime, "_reconnect_delay", lambda _attempt: asyncio.sleep(0))
    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    monkeypatch.setattr(worker_runtime._WorkerResources, "start_consumer", fail_first_start)
    _patch_db(monkeypatch, worker_runtime)

    await worker_runtime.run_worker(
        settings=_settings(),
        lifecycle=lifecycle,
        once=False,
        stop_event=stop_event,
    )

    assert connect_count == 2
    assert accepting_on_reconnect == [True, True]
    assert lifecycle.accepting_work is False


@pytest.mark.asyncio
async def test_two_session_failures_keep_accepting_work_until_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cps.messaging import runtime as worker_runtime

    connect_count = 0
    stop_event = asyncio.Event()
    lifecycle = worker_runtime.WorkerLifecycle()
    accepting_during_failures: list[bool] = []

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        nonlocal connect_count
        connect_count += 1
        accepting_during_failures.append(lifecycle.accepting_work)
        if connect_count >= 3:
            stop_event.set()
        return _FakeConnection()

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    async def always_fail_start(self: worker_runtime._WorkerResources) -> None:
        raise RuntimeError("consumer start failed")

    monkeypatch.setattr(worker_runtime, "_reconnect_delay", lambda _attempt: asyncio.sleep(0))
    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    monkeypatch.setattr(worker_runtime._WorkerResources, "start_consumer", always_fail_start)
    _patch_db(monkeypatch, worker_runtime)

    await worker_runtime.run_worker(
        settings=_settings(),
        lifecycle=lifecycle,
        once=False,
        stop_event=stop_event,
    )

    assert connect_count == 3
    assert accepting_during_failures == [True, True, True]
    assert lifecycle.accepting_work is False


@pytest.mark.asyncio
async def test_session_close_triggers_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    from cps.messaging import runtime as worker_runtime

    connect_count = 0
    channel = _FakeChannel()
    connection = _FakeConnection(channel)
    stop_event = asyncio.Event()

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        nonlocal connect_count, channel, connection
        connect_count += 1
        channel = _FakeChannel()
        connection = _FakeConnection(channel)
        if connect_count >= 2:
            stop_event.set()
        return connection

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    original_wait = worker_runtime._wait_for_session_end

    async def close_channel_then_wait(resources: worker_runtime._WorkerResources):
        if connect_count == 1:
            assert resources.channel is not None
            resources.channel.is_closed = True
        return await original_wait(resources)

    monkeypatch.setattr(worker_runtime, "_reconnect_delay", lambda _attempt: asyncio.sleep(0))
    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    monkeypatch.setattr(worker_runtime, "_wait_for_session_end", close_channel_then_wait)
    lifecycle = worker_runtime.WorkerLifecycle()
    _patch_db(monkeypatch, worker_runtime)

    await worker_runtime.run_worker(
        settings=_settings(),
        lifecycle=lifecycle,
        once=False,
        stop_event=stop_event,
    )

    assert connect_count == 2
    assert lifecycle.accepting_work is False


@pytest.mark.asyncio
async def test_stop_signal_does_not_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    from cps.messaging import runtime as worker_runtime

    connect_count = 0
    stop_event = asyncio.Event()

    async def fake_connect(url: str, **_kwargs: Any) -> _FakeConnection:
        nonlocal connect_count
        connect_count += 1
        return _FakeConnection()

    async def fake_declare(_self, _channel: Any, **_kwargs: Any) -> _FakeTopology:
        return _FakeTopology()

    monkeypatch.setattr(worker_runtime.aio_pika, "connect_robust", fake_connect)
    monkeypatch.setattr(worker_runtime.EventTopologyBuilder, "declare", fake_declare)
    _patch_db(monkeypatch, worker_runtime)

    task = asyncio.create_task(
        worker_runtime.run_worker(
            settings=_settings(),
            lifecycle=worker_runtime.WorkerLifecycle(),
            once=False,
            stop_event=stop_event,
        )
    )
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert connect_count == 1
