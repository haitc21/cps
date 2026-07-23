from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cps.application import recovery
from cps.infrastructure.db.models.enums import OperationState


class _FakeOperations:
    def __init__(self) -> None:
        self.operations = [
            SimpleNamespace(id="one", version=1, state=OperationState.RUNNING),
            SimpleNamespace(id="two", version=2, state=OperationState.WAITING_PROVIDER),
        ]
        self.timed_out: list[str] = []

    async def list_expired_nonterminal(self, *, now: datetime, limit: int) -> list[object]:
        return self.operations[:limit]

    async def apply_terminal_failure(self, *, operation: object, **kwargs: object) -> None:
        self.timed_out.append(str(operation.id))
        assert kwargs["to_state"] is OperationState.TIMED_OUT


class _FakeUow:
    def __init__(self, operations: _FakeOperations) -> None:
        self.operations = operations
        self.committed = False

    async def __aenter__(self) -> "_FakeUow":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True


@pytest.mark.asyncio
async def test_timeout_sweeper_transitions_expired_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations = _FakeOperations()
    uow = _FakeUow(operations)
    monkeypatch.setattr(recovery, "SqlAlchemyUnitOfWork", lambda _factory: uow)

    count = await recovery.timeout_expired_operations(
        object(), now=datetime(2026, 7, 23, tzinfo=UTC), batch_size=10
    )

    assert count == 2
    assert operations.timed_out == ["one", "two"]
    assert uow.committed
