"""orders sync guard + unique external_id per marketplace

Revision ID: 20260421_orders_sync_guard
Revises: 20260317_scale
Create Date: 2026-04-21
"""

from alembic import op


revision = "20260421_orders_sync_guard"
down_revision = "20260317_scale"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Удаляем дубли, оставляя запись с максимальным id (самая новая).
    op.execute(
        """
        DELETE FROM orders
        WHERE id NOT IN (
            SELECT keep_id FROM (
                SELECT MAX(id) AS keep_id
                FROM orders
                GROUP BY marketplace_id, external_id
            ) AS dedup_keep
        )
        """
    )

    op.create_unique_constraint(
        "uq_orders_marketplace_external_id",
        "orders",
        ["marketplace_id", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_orders_marketplace_external_id",
        "orders",
        type_="unique",
    )
