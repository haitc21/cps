"""Persist OpenStack project ownership on tenant resources."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0012"
down_revision: str | None = "20260726_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "instances",
    "networks",
    "subnets",
    "ports",
    "routers",
    "security_groups",
    "security_group_rules",
    "floating_ips",
    "volumes",
    "images",
    "quotas",
)


def upgrade() -> None:
    op.add_column("projects", sa.Column("provider_id", sa.Uuid(), nullable=True))
    op.add_column("projects", sa.Column("org_id", sa.String(255), nullable=True))
    op.add_column("projects", sa.Column("workspace_id", sa.String(255), nullable=True))
    op.add_column(
        "projects",
        sa.Column("ownership_state", sa.String(16), server_default="UNBOUND", nullable=True),
    )
    op.create_foreign_key(
        "fk_projects_provider_id_providers",
        "projects",
        "providers",
        ["provider_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE projects p
            SET provider_id = pc.provider_id
            FROM provider_connections pc
            WHERE pc.id = p.provider_connection_id
            """
        )
    )
    op.alter_column("projects", "provider_id", nullable=False)
    op.alter_column("projects", "ownership_state", nullable=False)
    op.create_check_constraint(
        "ck_projects_ownership_state",
        "projects",
        "ownership_state IN ('MANAGED', 'UNBOUND', 'DISABLED')",
    )
    op.create_unique_constraint(
        "uq_projects_provider_resource",
        "projects",
        ["provider_id", "provider_resource_id"],
    )
    op.create_index("ix_projects_org_workspace", "projects", ["org_id", "workspace_id"])

    for table in TENANT_TABLES:
        op.add_column(table, sa.Column("project_id", sa.Uuid(), nullable=True))
        op.add_column(
            table, sa.Column("project_provider_resource_id", sa.String(255), nullable=True)
        )
        op.create_foreign_key(
            f"fk_{table}_project_id_projects",
            table,
            "projects",
            ["project_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(f"ix_{table}_project_id", table, ["project_id"])
        op.create_index(
            f"ix_{table}_project_provider_resource_id",
            table,
            ["project_provider_resource_id"],
        )


def downgrade() -> None:
    for table in reversed(TENANT_TABLES):
        op.drop_index(f"ix_{table}_project_provider_resource_id", table_name=table)
        op.drop_index(f"ix_{table}_project_id", table_name=table)
        op.drop_constraint(f"fk_{table}_project_id_projects", table, type_="foreignkey")
        op.drop_column(table, "project_provider_resource_id")
        op.drop_column(table, "project_id")
    op.drop_index("ix_projects_org_workspace", table_name="projects")
    op.drop_constraint("uq_projects_provider_resource", "projects", type_="unique")
    op.drop_constraint("ck_projects_ownership_state", "projects", type_="check")
    op.drop_constraint("fk_projects_provider_id_providers", "projects", type_="foreignkey")
    op.drop_column("projects", "ownership_state")
    op.drop_column("projects", "workspace_id")
    op.drop_column("projects", "org_id")
    op.drop_column("projects", "provider_id")
