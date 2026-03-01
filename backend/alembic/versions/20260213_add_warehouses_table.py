"""add warehouses table and multi-warehouse support

Revision ID: 20260213_warehouses
Revises: 
Create Date: 2026-02-13

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260213_warehouses"
down_revision = "20260213_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Создаём таблицу warehouses
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("marketplace_id", sa.Integer(), nullable=False),
        sa.Column("external_warehouse_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("color", sa.String(7), nullable=True),
        sa.ForeignKeyConstraint(
            ["marketplace_id"],
            ["marketplaces.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "marketplace_id",
            "external_warehouse_id",
            name="uq_warehouse_marketplace_external",
        ),
    )
    op.create_index(
        op.f("ix_warehouses_external_warehouse_id"),
        "warehouses",
        ["external_warehouse_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_warehouses_marketplace_id"),
        "warehouses",
        ["marketplace_id"],
        unique=False,
    )

    # 2. Добавляем warehouse_id в orders
    op.add_column(
        "orders",
        sa.Column("warehouse_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_orders_warehouse_id",
        "orders",
        "warehouses",
        ["warehouse_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_orders_warehouse_id"),
        "orders",
        ["warehouse_id"],
        unique=False,
    )

    # 3. Удаляем warehouse_id и warehouse_color из marketplaces
    #    (данные переносятся при следующей синхронизации складов)
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "marketplaces" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("marketplaces")]
        if "warehouse_id" in cols:
            op.drop_column("marketplaces", "warehouse_id")
        if "warehouse_color" in cols:
            op.drop_column("marketplaces", "warehouse_color")


def downgrade() -> None:
    # Возвращаем колонки в marketplaces
    op.add_column(
        "marketplaces",
        sa.Column("warehouse_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "marketplaces",
        sa.Column("warehouse_color", sa.String(7), nullable=True),
    )

    # Удаляем warehouse_id из orders
    op.drop_constraint("fk_orders_warehouse_id", "orders", type_="foreignkey")
    op.drop_index(op.f("ix_orders_warehouse_id"), table_name="orders")
    op.drop_column("orders", "warehouse_id")

    # Удаляем таблицу warehouses
    op.drop_index(op.f("ix_warehouses_marketplace_id"), table_name="warehouses")
    op.drop_index(op.f("ix_warehouses_external_warehouse_id"), table_name="warehouses")
    op.drop_table("warehouses")
