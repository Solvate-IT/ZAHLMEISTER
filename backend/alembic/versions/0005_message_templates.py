"""message templates and collection message override

Revision ID: 0005_message_templates
Revises: 0004_communication_hub
Create Date: 2026-09-06
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_message_templates"
down_revision = "0004_communication_hub"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_templates",
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("translations_json", sa.Text(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_templates_org", "message_templates", ["organization_id"])
    op.create_index("ix_message_templates_org_name", "message_templates", ["organization_id", "name"])

    op.add_column("collections", sa.Column("message_template_id", postgresql.UUID(as_uuid=True)))
    op.add_column("collections", sa.Column("message_body_override", sa.Text()))
    op.create_foreign_key(
        "fk_collections_message_template_id",
        "collections",
        "message_templates",
        ["message_template_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_collections_message_template_id", "collections", ["message_template_id"])


def downgrade() -> None:
    op.drop_index("ix_collections_message_template_id", table_name="collections")
    op.drop_constraint("fk_collections_message_template_id", "collections", type_="foreignkey")
    op.drop_column("collections", "message_body_override")
    op.drop_column("collections", "message_template_id")
    op.drop_index("ix_message_templates_org_name", table_name="message_templates")
    op.drop_index("ix_message_templates_org", table_name="message_templates")
    op.drop_table("message_templates")
