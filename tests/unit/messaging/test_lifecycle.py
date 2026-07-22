"""Unit tests for worker lifecycle drain tracking."""

from __future__ import annotations

import asyncio

import pytest

from cps.infrastructure.messaging.lifecycle import WorkerLifecycle

pytestmark = pytest.mark.asyncio


async def test_wait_drained_returns_when_in_flight_finishes() -> None:
    lifecycle = WorkerLifecycle()
    lifecycle.mark_in_flight("msg-1")

    async def finish_later() -> None:
        await asyncio.sleep(0.01)
        lifecycle.finish_or_nack("msg-1", completed=True)

    task = asyncio.create_task(finish_later())
    drained = await lifecycle.wait_drained(1.0)
    await task

    assert drained is True
    assert lifecycle.is_drained


async def test_wait_drained_times_out_with_stuck_in_flight() -> None:
    lifecycle = WorkerLifecycle()
    lifecycle.mark_in_flight("msg-1")

    drained = await lifecycle.wait_drained(0.01)

    assert drained is False
    assert not lifecycle.is_drained


async def test_duplicate_message_id_tracks_refcount() -> None:
    lifecycle = WorkerLifecycle()
    lifecycle.mark_in_flight("msg-1")
    lifecycle.mark_in_flight("msg-1")
    assert lifecycle.in_flight == {"msg-1"}

    lifecycle.finish_or_nack("msg-1", completed=True)
    assert lifecycle.in_flight == {"msg-1"}

    lifecycle.finish_or_nack("msg-1", completed=True)
    assert lifecycle.is_drained
