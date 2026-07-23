from datetime import UTC, datetime, timedelta

from cps.application.scheduler import InventorySchedule, InventoryScheduler


def test_scheduler_selects_only_due_enabled_valid_connections() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    scheduler = InventoryScheduler(jitter_seconds=0)
    schedules = [
        InventorySchedule("due", timedelta(minutes=5), now - timedelta(seconds=1)),
        InventorySchedule("future", timedelta(minutes=5), now + timedelta(seconds=1)),
        InventorySchedule("disabled", timedelta(minutes=5), now, enabled=False),
        InventorySchedule("invalid", timedelta(minutes=5), now, valid=False),
    ]
    assert scheduler.due_connections(schedules, now=now) == ["due"]


def test_scheduler_jitter_is_injected_and_does_not_touch_provider() -> None:
    now = datetime(2026, 7, 23, tzinfo=UTC)
    schedule = InventorySchedule("connection", timedelta(minutes=5), now)
    scheduler = InventoryScheduler(jitter_seconds=10, random_fn=lambda: 0.5)
    assert scheduler.next_run(schedule, now=now) == now + timedelta(minutes=5, seconds=5)


def test_scheduler_reads_only_valid_connection_capability_metadata() -> None:
    class Connection:
        id = "active-connection"
        capabilities = {
            "inventory_schedule": {
                "interval_seconds": 60,
                "next_run_at": "2026-07-23T10:00:00+00:00",
                "enabled": True,
            }
        }

        class Status:
            value = "active"

        status = Status()

    class Invalid:
        id = "invalid-connection"
        capabilities = {"inventory_schedule": {"interval_seconds": 0}}

    schedules = InventoryScheduler.schedules_from_connections([Connection(), Invalid()])
    assert [item.connection_id for item in schedules] == ["active-connection"]
