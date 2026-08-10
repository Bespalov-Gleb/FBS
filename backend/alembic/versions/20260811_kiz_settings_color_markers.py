"""kiz_settings with color_markers

Revision ID: 20260811_kiz_settings
Revises: 20260501_auto_kiz_autofill
Create Date: 2026-08-11
"""
from alembic import op
import sqlalchemy as sa


revision = "20260811_kiz_settings"
down_revision = "20260501_auto_kiz_autofill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiz_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("color_markers", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(op.f("ix_kiz_settings_id"), "kiz_settings", ["id"], unique=False)
    op.create_index(op.f("ix_kiz_settings_user_id"), "kiz_settings", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_kiz_settings_user_id"), table_name="kiz_settings")
    op.drop_index(op.f("ix_kiz_settings_id"), table_name="kiz_settings")
    op.drop_table("kiz_settings")
