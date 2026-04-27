"""kiz groups, pool and product mappings

Revision ID: 20260421_kiz_groups_pool
Revises: 20260421_orders_sync_guard
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260421_kiz_groups_pool"
down_revision = "20260421_orders_sync_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kiz_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("color", sa.String(length=120), nullable=True),
        sa.Column("size", sa.String(length=120), nullable=True),
        sa.Column("cut_type", sa.String(length=120), nullable=True),
        sa.Column("parser_markers", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_kiz_groups_user_name"),
    )
    op.create_index(op.f("ix_kiz_groups_id"), "kiz_groups", ["id"], unique=False)
    op.create_index(op.f("ix_kiz_groups_user_id"), "kiz_groups", ["user_id"], unique=False)

    op.create_table(
        "kiz_group_marketplaces",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("marketplace_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["kiz_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["marketplace_id"], ["marketplaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "marketplace_id"),
    )

    op.create_table(
        "kiz_pool_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("free", "used", name="kizcodestatus"),
            nullable=False,
            server_default="free",
        ),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("used_order_id", sa.Integer(), nullable=True),
        sa.Column("used_by_user_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["group_id"], ["kiz_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["used_order_id"], ["orders.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kiz_pool_items_id"), "kiz_pool_items", ["id"], unique=False)
    op.create_index(op.f("ix_kiz_pool_items_code"), "kiz_pool_items", ["code"], unique=True)
    op.create_index(op.f("ix_kiz_pool_items_group_id"), "kiz_pool_items", ["group_id"], unique=False)
    op.create_index(op.f("ix_kiz_pool_items_status"), "kiz_pool_items", ["status"], unique=False)
    op.create_index(
        op.f("ix_kiz_pool_items_used_order_id"), "kiz_pool_items", ["used_order_id"], unique=False
    )

    op.create_table(
        "kiz_product_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("marketplace_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("article", sa.String(length=255), nullable=False),
        sa.Column("size", sa.String(length=120), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(["group_id"], ["kiz_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["marketplace_id"], ["marketplaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "marketplace_id",
            "article",
            "size",
            name="uq_kiz_product_mapping_user_mp_article_size",
        ),
    )
    op.create_index(
        op.f("ix_kiz_product_mappings_id"), "kiz_product_mappings", ["id"], unique=False
    )
    op.create_index(
        op.f("ix_kiz_product_mappings_user_id"), "kiz_product_mappings", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_kiz_product_mappings_marketplace_id"),
        "kiz_product_mappings",
        ["marketplace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_kiz_product_mappings_group_id"), "kiz_product_mappings", ["group_id"], unique=False
    )
    op.create_index(
        op.f("ix_kiz_product_mappings_article"), "kiz_product_mappings", ["article"], unique=False
    )

    op.create_table(
        "kiz_parser_errors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["kiz_groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kiz_parser_errors_id"), "kiz_parser_errors", ["id"], unique=False)
    op.create_index(
        op.f("ix_kiz_parser_errors_user_id"), "kiz_parser_errors", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_kiz_parser_errors_group_id"), "kiz_parser_errors", ["group_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_kiz_parser_errors_group_id"), table_name="kiz_parser_errors")
    op.drop_index(op.f("ix_kiz_parser_errors_user_id"), table_name="kiz_parser_errors")
    op.drop_index(op.f("ix_kiz_parser_errors_id"), table_name="kiz_parser_errors")
    op.drop_table("kiz_parser_errors")

    op.drop_index(op.f("ix_kiz_product_mappings_article"), table_name="kiz_product_mappings")
    op.drop_index(op.f("ix_kiz_product_mappings_group_id"), table_name="kiz_product_mappings")
    op.drop_index(
        op.f("ix_kiz_product_mappings_marketplace_id"), table_name="kiz_product_mappings"
    )
    op.drop_index(op.f("ix_kiz_product_mappings_user_id"), table_name="kiz_product_mappings")
    op.drop_index(op.f("ix_kiz_product_mappings_id"), table_name="kiz_product_mappings")
    op.drop_table("kiz_product_mappings")

    op.drop_index(op.f("ix_kiz_pool_items_used_order_id"), table_name="kiz_pool_items")
    op.drop_index(op.f("ix_kiz_pool_items_status"), table_name="kiz_pool_items")
    op.drop_index(op.f("ix_kiz_pool_items_group_id"), table_name="kiz_pool_items")
    op.drop_index(op.f("ix_kiz_pool_items_code"), table_name="kiz_pool_items")
    op.drop_index(op.f("ix_kiz_pool_items_id"), table_name="kiz_pool_items")
    op.drop_table("kiz_pool_items")
    sa.Enum(name="kizcodestatus").drop(op.get_bind(), checkfirst=True)

    op.drop_table("kiz_group_marketplaces")

    op.drop_index(op.f("ix_kiz_groups_user_id"), table_name="kiz_groups")
    op.drop_index(op.f("ix_kiz_groups_id"), table_name="kiz_groups")
    op.drop_table("kiz_groups")
