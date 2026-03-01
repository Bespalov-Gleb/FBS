"""add print_settings table

Revision ID: 20260213_print
Revises: 20260213_warehouses
Create Date: 2026-02-13

"""
from alembic import op
import sqlalchemy as sa


revision = "20260213_print"
down_revision = "20260213_warehouses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "print_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("default_printer", sa.String(255), nullable=True),
        sa.Column("label_format", sa.String(20), nullable=True),
        sa.Column("label_template", sa.Text(), nullable=True),
        sa.Column("auto_print_on_click", sa.String(10), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_print_settings_user_id"),
    )
    op.create_index(op.f("ix_print_settings_user_id"), "print_settings", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_print_settings_user_id"), table_name="print_settings")
    op.drop_table("print_settings")
