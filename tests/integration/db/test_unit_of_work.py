"""CPS-103 Task 2: real PostgreSQL unit-of-work rollback proof."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from cps.infrastructure.db.models.enums import ProviderStatus
from cps.infrastructure.db.models.providers import Provider
from cps.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_unit_of_work_rollback_discards_provider_insert(db_session_factory) -> None:
    provider_id = uuid.uuid4()
    uow = SqlAlchemyUnitOfWork(db_session_factory)

    with pytest.raises(RuntimeError, match="force rollback"):
        async with uow:
            uow.session.add(
                Provider(
                    id=provider_id,
                    name="rollback-proof",
                    provider_type="OPENSTACK",
                    status=ProviderStatus.ACTIVE,
                    version=1,
                )
            )
            await uow.session.flush()
            raise RuntimeError("force rollback")

    async with db_session_factory() as session:
        result = await session.execute(select(Provider).where(Provider.id == provider_id))
        assert result.scalar_one_or_none() is None
