"""Index-only catalog query performance migration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0017"
down_revision: str | None = "20260731_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPROVED_PREDICATE = sa.text(
    "provider_attributes @> '{\"catalog_approved\": true}'::jsonb"
)
_LIVE_PREDICATE = sa.text("lifecycle_state <> 'DELETED'")


def upgrade() -> None:
    op.create_index(
        "ix_images_catalog_approved_name",
        "images",
        ["name"],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_flavors_catalog_approved_name",
        "flavors",
        ["name"],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_images_catalog_filters",
        "images",
        ["provider_connection_id", "visibility", "disk_format", "size_bytes"],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_images_catalog_owner",
        "images",
        ["provider_connection_id", "project_provider_resource_id"],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_flavors_catalog_filters",
        "flavors",
        ["provider_connection_id", "is_public", "ram_mib", "root_disk_gib"],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_images_catalog_status",
        "images",
        ["provider_connection_id", sa.text("lower(provider_status)")],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_flavors_catalog_status",
        "flavors",
        ["provider_connection_id", sa.text("lower(provider_status)")],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_images_catalog_dims",
        "images",
        ["provider_connection_id", "min_disk_gib", "min_ram_mib"],
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_images_catalog_member_projects",
        "images",
        [sa.text("(provider_attributes -> 'member_project_ids')")],
        postgresql_using="gin",
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )
    op.create_index(
        "ix_flavors_catalog_access_projects",
        "flavors",
        [sa.text("(provider_attributes -> 'access_project_ids')")],
        postgresql_using="gin",
        postgresql_where=_APPROVED_PREDICATE & _LIVE_PREDICATE,
    )


def downgrade() -> None:
    op.drop_index("ix_flavors_catalog_access_projects", table_name="flavors")
    op.drop_index("ix_images_catalog_member_projects", table_name="images")
    op.drop_index("ix_images_catalog_dims", table_name="images")
    op.drop_index("ix_flavors_catalog_status", table_name="flavors")
    op.drop_index("ix_images_catalog_status", table_name="images")
    op.drop_index("ix_flavors_catalog_filters", table_name="flavors")
    op.drop_index("ix_images_catalog_owner", table_name="images")
    op.drop_index("ix_images_catalog_filters", table_name="images")
    op.drop_index("ix_flavors_catalog_approved_name", table_name="flavors")
    op.drop_index("ix_images_catalog_approved_name", table_name="images")
