"""initial schema: users, marketplaces, orders, audit_logs

Revision ID: 20260213_initial
Revises:
Create Date: 2026-02-13

"""
from alembic import op
import sqlalchemy as sa


revision = "20260213_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("admin", "packer", name="userrole"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    # 2. marketplaces
    op.create_table(
        "marketplaces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.Enum("ozon", "wildberries", name="marketplacetype"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=True),
        sa.Column("is_kiz_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_marketplaces_type"), "marketplaces", ["type"], unique=False)
    op.create_index(op.f("ix_marketplaces_user_id"), "marketplaces", ["user_id"], unique=False)

    # 3. orders (без warehouse_id — добавляется в следующей миграции)
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("marketplace_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        sa.Column("posting_number", sa.String(255), nullable=False),
        sa.Column("article", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(500), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("warehouse_name", sa.String(255), nullable=True),
        sa.Column(
            "status",
            sa.Enum("awaiting_packaging", "packaging", "completed", "cancelled", name="orderstatus"),
            nullable=False,
            server_default="awaiting_packaging",
        ),
        sa.Column("marketplace_status", sa.String(100), nullable=True),
        sa.Column("marketplace_created_at", sa.DateTime(), nullable=True),
        sa.Column("assigned_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column("kiz_code", sa.String(255), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["marketplace_id"], ["marketplaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_orders_article"), "orders", ["article"], unique=False)
    op.create_index(op.f("ix_orders_external_id"), "orders", ["external_id"], unique=False)
    op.create_index(op.f("ix_orders_marketplace_id"), "orders", ["marketplace_id"], unique=False)
    op.create_index(op.f("ix_orders_posting_number"), "orders", ["posting_number"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)

    # 4. audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_user_id"), "audit_logs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_logs_user_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_posting_number"), table_name="orders")
    op.drop_index(op.f("ix_orders_marketplace_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_external_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_article"), table_name="orders")
    op.drop_table("orders")

    op.drop_index(op.f("ix_marketplaces_user_id"), table_name="marketplaces")
    op.drop_index(op.f("ix_marketplaces_type"), table_name="marketplaces")
    op.drop_table("marketplaces")

    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS orderstatus")
    op.execute("DROP TYPE IF EXISTS marketplacetype")
    op.execute("DROP TYPE IF EXISTS userrole")
