"""Add partial indexes for approved catalog image and flavor reads."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260801_0017"
down_revision: str | None = "20260731_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_APPROVED_LIVE = sa.text(
    "provider_attributes @> '{\"catalog_approved\": true}'::jsonb AND lifecycle_state <> 'DELETED'"
)


def upgrade() -> None:
    op.create_index(
        "ix_images_catalog_approved_name",
        "images",
        ["provider_connection_id", "name", "id"],
        postgresql_where=_APPROVED_LIVE,
    )
    op.create_index(
        "ix_flavors_catalog_approved_name",
        "flavors",
        ["provider_connection_id", "name", "id"],
        postgresql_where=_APPROVED_LIVE,
    )
    op.create_index(
        "ix_images_catalog_filters",
        "images",
        [
            "provider_connection_id",
            "provider_status",
            "visibility",
            "disk_format",
            "size_bytes",
            "min_disk_gib",
            "min_ram_mib",
        ],
        postgresql_where=_APPROVED_LIVE,
    )
    op.create_index(
        "ix_images_catalog_owner",
        "images",
        ["provider_connection_id", "project_provider_resource_id"],
        postgresql_where=_APPROVED_LIVE,
    )
    op.create_index(
        "ix_flavors_catalog_filters",
        "flavors",
        ["provider_connection_id", "provider_status", "is_public", "ram_mib", "root_disk_gib"],
        postgresql_where=_APPROVED_LIVE,
    )


def downgrade() -> None:
    op.drop_index("ix_flavors_catalog_filters", table_name="flavors")
    op.drop_index("ix_images_catalog_owner", table_name="images")
    op.drop_index("ix_images_catalog_filters", table_name="images")
    op.drop_index("ix_flavors_catalog_approved_name", table_name="flavors")
    op.drop_index("ix_images_catalog_approved_name", table_name="images")
