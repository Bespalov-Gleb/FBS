"""add collected_in_app to orders

Revision ID: 20260307_collected
Revises: 20260305_print_dims
Create Date: 2026-03-07

"""
from alembic import op


revision = "20260307_collected"
down_revision = "20260305_print_dims"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: IF NOT EXISTS для идемпотентности при повторном запуске
    op.execute(
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS collected_in_app BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_orders_collected_in_app ON orders(collected_in_app)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_orders_collected_in_app")
    op.drop_column("orders", "collected_in_app")
