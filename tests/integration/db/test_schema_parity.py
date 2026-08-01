"""CPS-103 Task 2: model–migration parity integration test."""

from __future__ import annotations

import psycopg
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from cps.infrastructure.db.base import Base

pytestmark = pytest.mark.integration

DATABASE_ONLY_SCHEMA_OBJECTS = {
    "ix_floating_ips_project_id",
    "ix_floating_ips_project_provider_resource_id",
    "ix_images_project_id",
    "ix_images_project_provider_resource_id",
    "ix_images_catalog_approved_name",
    "ix_images_catalog_filters",
    "ix_images_catalog_owner",
    "ix_flavors_catalog_approved_name",
    "ix_flavors_catalog_filters",
    "ix_images_catalog_status",
    "ix_flavors_catalog_status",
    "ix_images_catalog_dims",
    "ix_images_catalog_member_projects",
    "ix_flavors_catalog_access_projects",
    "ix_instances_project_id",
    "ix_instances_project_provider_resource_id",
    "ix_networks_project_id",
    "ix_networks_project_provider_resource_id",
    "ix_ports_project_id",
    "ix_ports_project_provider_resource_id",
    "ix_projects_org_workspace",
    "uq_projects_provider_resource",
    "ix_quotas_project_id",
    "ix_quotas_project_provider_resource_id",
    "ix_routers_project_id",
    "ix_routers_project_provider_resource_id",
    "ix_security_group_rules_project_id",
    "ix_security_group_rules_project_provider_resource_id",
    "ix_security_groups_project_id",
    "ix_security_groups_project_provider_resource_id",
    "ix_subnets_project_id",
    "ix_subnets_project_provider_resource_id",
    "ix_volumes_project_id",
    "ix_volumes_project_provider_resource_id",
}


def _normalize_diff(diff: list[object]) -> list[tuple[str, ...]]:
    normalized: list[tuple[str, ...]] = []
    for item in diff:
        if isinstance(item, tuple):
            normalized.append(tuple(str(part) for part in item))
        else:
            normalized.append((str(item),))
    return normalized


def _database_only_object(item: tuple[str, ...]) -> str | None:
    rendered = " ".join(item)
    for object_name in DATABASE_ONLY_SCHEMA_OBJECTS:
        if object_name in rendered:
            return object_name
    if item[0] == "remove_constraint" and "projects" in rendered:
        return "uq_projects_provider_resource"
    return None


def test_model_migration_parity_has_no_unexpected_schema_diff(
    migrated_database: str,
    db_admin_conn: psycopg.Connection,
) -> None:
    sync_url = migrated_database.replace("postgresql+psycopg://", "postgresql+psycopg://", 1)
    engine = create_engine(sync_url)
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        diff = compare_metadata(context, Base.metadata)
    unexpected = [item for item in _normalize_diff(diff) if _database_only_object(item) is None]
    observed_database_only = {
        object_name
        for item in _normalize_diff(diff)
        if (object_name := _database_only_object(item)) is not None
    }
    assert observed_database_only == DATABASE_ONLY_SCHEMA_OBJECTS
    assert unexpected == []
