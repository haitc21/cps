"""CPS-103 Task 2: ORM metadata tests for persistence schema."""

from __future__ import annotations

import pytest
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase

from cps.infrastructure.db.models.credentials import Credential
from cps.infrastructure.db.models.inbox_messages import InboxMessage
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.outbox_messages import OutboxMessage
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider

MODELS: tuple[type[DeclarativeBase], ...] = (
    Provider,
    Credential,
    ProviderConnection,
    Operation,
    OperationEvent,
    OutboxMessage,
    InboxMessage,
)

TIMESTAMPTZ_COLUMNS: dict[type[DeclarativeBase], set[str]] = {
    ProviderConnection: {"validated_at", "created_at", "updated_at"},
    Operation: {"timeout_at", "created_at", "updated_at"},
    OperationEvent: {"occurred_at"},
    OutboxMessage: {"next_attempt_at", "claim_expires_at", "published_at", "created_at"},
    InboxMessage: {"received_at", "processed_at"},
}

VERSION_CHECK_MODELS: dict[type[DeclarativeBase], str] = {
    Provider: "ck_providers_version_positive",
    Credential: "ck_credentials_version_positive",
    ProviderConnection: "ck_provider_connections_version_positive",
    Operation: "ck_operations_version_positive",
    OutboxMessage: "ck_outbox_messages_version_positive",
}

UNIQUE_NAMES = {
    "uq_credentials_encryption_key_version_password_nonce",
    "uq_provider_connections_provider_domain_project_region",
    "uq_operation_events_operation_sequence",
    "uq_inbox_messages_consumer_message",
    "uq_operations_idempotency",
    "uq_outbox_messages_message_id",
}


def _column(model: type[DeclarativeBase], name: str):
    return model.__table__.c[name]


@pytest.mark.parametrize("model", MODELS)
def test_models_do_not_use_naive_datetime(model: type[DeclarativeBase]) -> None:
    for column in model.__table__.columns:
        column_type = column.type
        if isinstance(column_type, DateTime):
            assert column_type.timezone is True, f"{model.__tablename__}.{column.name}"


@pytest.mark.parametrize("model,columns", list(TIMESTAMPTZ_COLUMNS.items()))
def test_explicit_timestamptz_columns(
    model: type[DeclarativeBase],
    columns: set[str],
) -> None:
    for column_name in columns:
        column_type = _column(model, column_name).type
        assert isinstance(column_type, DateTime)
        assert column_type.timezone is True


def test_outbox_has_created_at_only_timestamp_mixin_fields() -> None:
    column_names = {column.name for column in OutboxMessage.__table__.columns}
    assert "created_at" in column_names
    assert "updated_at" not in column_names


@pytest.mark.parametrize("model,check_name", list(VERSION_CHECK_MODELS.items()))
def test_version_positive_check_present(model: type[DeclarativeBase], check_name: str) -> None:
    check_names = {
        constraint.name
        for constraint in model.__table__.constraints
        if constraint.name is not None and constraint.name.startswith("ck_")
    }
    assert check_name in check_names


def test_named_unique_constraints_present() -> None:
    all_unique_names: set[str] = set()
    for model in MODELS:
        for constraint in model.__table__.constraints:
            if constraint.name and constraint.name.startswith("uq_"):
                all_unique_names.add(constraint.name)
        for index in model.__table__.indexes:
            if index.unique and index.name:
                all_unique_names.add(index.name)
    assert UNIQUE_NAMES.issubset(all_unique_names)


def test_outbox_created_at_uses_server_default() -> None:
    created_at = _column(OutboxMessage, "created_at")
    assert created_at.server_default is not None
