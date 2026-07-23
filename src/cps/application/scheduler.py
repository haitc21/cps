"""Provider-free inventory scheduling primitives."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from cps.observability.metrics import metrics


@dataclass(frozen=True, slots=True)
class InventorySchedule:
    connection_id: str
    interval: timedelta
    next_run_at: datetime
    enabled: bool = True
    valid: bool = True


class InventoryScheduler:
    """Select due connections and compute the next jittered run.

    The scheduler only emits connection IDs. The caller owns normal CPS workflow
    creation, so this module cannot accidentally perform provider I/O.
    """

    def __init__(
        self,
        *,
        jitter_seconds: float = 10.0,
        random_fn: Callable[[], float] | None = None,
    ) -> None:
        if jitter_seconds < 0:
            raise ValueError("jitter must be non-negative")
        self._jitter_seconds = jitter_seconds
        self._random = random_fn or random.random

    def due_connections(
        self,
        schedules: Iterable[InventorySchedule],
        *,
        now: datetime | None = None,
    ) -> list[str]:
        current = now or datetime.now(UTC)
        due = [
            item.connection_id
            for item in schedules
            if item.enabled and item.valid and item.next_run_at <= current
        ]
        if due:
            metrics.increment("cps_inventory_schedule_due_total", len(due))
        return due

    @staticmethod
    def schedules_from_connections(connections: Iterable[object]) -> list[InventorySchedule]:
        """Build schedules from CPS-owned capability metadata.

        Validation remains the source of truth for whether a connection is usable.
        Missing or malformed schedule metadata is deliberately ignored, keeping
        the scheduler provider-free and safe when a connection is being repaired.
        """
        schedules: list[InventorySchedule] = []
        for connection in connections:
            source = cast(Any, connection)
            raw = source.capabilities
            if not isinstance(raw, Mapping):
                continue
            config = raw.get("inventory_schedule")
            if not isinstance(config, Mapping):
                continue
            try:
                interval = float(config.get("interval_seconds", 0))
                next_run_at = datetime.fromisoformat(str(config["next_run_at"]))
                connection_id = str(source.id)
            except (KeyError, TypeError, ValueError):
                continue
            if next_run_at.tzinfo is None or interval <= 0:
                continue
            schedules.append(
                InventorySchedule(
                    connection_id=connection_id,
                    interval=timedelta(seconds=interval),
                    next_run_at=next_run_at,
                    enabled=config.get("enabled", True) is True,
                    valid=getattr(source.status, "value", "") == "active",
                )
            )
        return schedules

    def next_run(self, schedule: InventorySchedule, *, now: datetime | None = None) -> datetime:
        current = now or datetime.now(UTC)
        jitter = self._random() * self._jitter_seconds
        return current + schedule.interval + timedelta(seconds=jitter)
