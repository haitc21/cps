"""CPS-103 Task 2: ORM metadata tests for persistence schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase

from cps.infrastructure.db.models.inbox_messages import InboxMessage
from cps.infrastructure.db.models.inventory import (
    AvailabilityZone,
    Flavor,
    Image,
    Instance,
    InstancePort,
    InstanceVolume,
    Network,
    Port,
    Project,
    Region,
    Subnet,
    Volume,
    VolumeSnapshot,
    VolumeType,
)
from cps.infrastructure.db.models.inventory_sync import InventoryBatch, InventorySync
from cps.infrastructure.db.models.operation_events import OperationEvent
from cps.infrastructure.db.models.operations import Operation
from cps.infrastructure.db.models.outbox_messages import OutboxMessage
from cps.infrastructure.db.models.provider_connections import ProviderConnection
from cps.infrastructure.db.models.providers import Provider

MODELS: tuple[type[DeclarativeBase], ...] = (
    Provider,
    ProviderConnection,
    Operation,
    OperationEvent,
    OutboxMessage,
    InboxMessage,
    Region,
    Project,
    Flavor,
    AvailabilityZone,
    Image,
    Instance,
    Network,
    Subnet,
    Port,
    Volume,
    VolumeType,
    VolumeSnapshot,
    InstancePort,
    InstanceVolume,
    InventorySync,
    InventoryBatch,
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
    ProviderConnection: "ck_provider_connections_version_positive",
    Operation: "ck_operations_version_positive",
    OutboxMessage: "ck_outbox_messages_version_positive",
}

UNIQUE_NAMES = {
    "uq_providers_encryption_key_version_password_nonce",
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


@pytest.mark.parametrize(
    "model",
    [
        Region,
        Project,
        Flavor,
        AvailabilityZone,
        Image,
        Instance,
        Network,
        Subnet,
        Port,
        Volume,
        VolumeType,
    ],
)
def test_inventory_models_have_common_identity_and_lifecycle_fields(model) -> None:
    columns = set(model.__table__.columns.keys())
    assert {
        "id",
        "provider_connection_id",
        "provider_resource_id",
        "lifecycle_state",
        "last_sync_id",
        "provider_attributes",
        "version",
    } <= columns


def test_inventory_identity_is_unique_per_connection() -> None:
    for model in (
        Region,
        Project,
        Flavor,
        AvailabilityZone,
        Image,
        Instance,
        Network,
        Subnet,
        Port,
        Volume,
        VolumeType,
    ):
        unique_constraints = {
            constraint.name for constraint in model.__table__.constraints if constraint.name
        }
        assert f"uq_{model.__tablename__}_connection_provider_resource" in unique_constraints


def test_instance_relationships_are_typed_and_unique() -> None:
    assert {"instance_id", "port_id", "device"} <= set(InstancePort.__table__.columns.keys())
    assert {"instance_id", "volume_id", "device", "boot_index", "delete_on_termination"} <= set(
        InstanceVolume.__table__.columns.keys()
    )


def test_volume_inventory_has_typed_storage_fields() -> None:
    assert {
        "volume_type_provider_resource_id",
        "size_gib",
        "bootable",
        "root",
        "encrypted",
        "metadata_values",
        "availability_zone",
        "attachments",
    } <= set(Volume.__table__.columns.keys())


def test_volume_api_projection_exposes_availability_zone() -> None:
    from cps.api.schemas.inventory import InventoryResourceView

    assert "availability_zone" in InventoryResourceView.model_fields


def test_inventory_sync_and_batch_constraints_are_named() -> None:
    assert "uq_inventory_batches_sync_resource_sequence" in {
        constraint.name for constraint in InventoryBatch.__table__.constraints
    }
    assert "operation_id" in InventorySync.__table__.columns


def test_catalog_inventory_projection_separates_typed_and_bounded_fields() -> None:
    from cps.infrastructure.db.repositories.inventory import catalog_inventory_projection

    image_values, image_attributes = catalog_inventory_projection(
        Image,
        {
            "visibility": "shared",
            "disk_format": "qcow2",
            "size_bytes": 2_147_483_648,
            "min_disk_gib": 20,
            "min_ram_mib": 2048,
            "checksum": "a" * 32,
            "catalog_approved": True,
            "is_protected": True,
            "container_format": "bare",
            "virtual_size_bytes": 10_737_418_240,
            "tags": ["ubuntu"],
            "properties": {"os_distro": "ubuntu"},
        },
    )
    flavor_values, flavor_attributes = catalog_inventory_projection(
        Flavor,
        {
            "vcpus": 4,
            "ram_mib": 8192,
            "root_disk_gib": 80,
            "ephemeral_disk_gib": 20,
            "swap_mib": 1024,
            "is_public": False,
            "enabled": True,
            "catalog_approved": True,
            "extra_specs": {"hw:cpu_policy": "dedicated"},
            "access_project_ids": ["project-1"],
        },
    )

    assert image_values == {
        "visibility": "shared",
        "disk_format": "qcow2",
        "size_bytes": 2_147_483_648,
        "min_disk_gib": 20,
        "min_ram_mib": 2048,
        "checksum": "a" * 32,
    }
    assert image_attributes == {
        "catalog_approved": True,
        "container_format": "bare",
        "is_protected": True,
        "properties": {"os_distro": "ubuntu"},
        "tags": ["ubuntu"],
        "virtual_size_bytes": 10_737_418_240,
    }
    assert flavor_values == {
        "vcpus": 4,
        "ram_mib": 8192,
        "root_disk_gib": 80,
        "ephemeral_disk_gib": 20,
        "swap_mib": 1024,
        "is_public": False,
        "enabled": True,
    }
    assert flavor_attributes == {
        "access_project_ids": ["project-1"],
        "catalog_approved": True,
        "extra_specs": {"hw:cpu_policy": "dedicated"},
    }


def test_catalog_query_index_migration_is_present_and_reversible() -> None:
    migration = (
        Path(__file__).resolve().parents[3]
        / "alembic"
        / "versions"
        / "20260801_0017_catalog_query_indexes.py"
    )
    assert migration.is_file()
    source = migration.read_text(encoding="utf-8")
    assert 'revision: str = "20260801_0017"' in source
    assert 'down_revision: str | None = "20260731_0016"' in source
    for index_name in (
        "ix_images_catalog_approved_name",
        "ix_flavors_catalog_approved_name",
        "ix_images_catalog_filters",
        "ix_images_catalog_owner",
        "ix_flavors_catalog_filters",
    ):
        assert f'"{index_name}"' in source
        assert f'op.drop_index("{index_name}"' in source
