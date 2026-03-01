"""rename order metadata to extra_data

Revision ID: 20260219_metadata
Revises: 20260213_print
Create Date: 2026-02-19

"""
from alembic import op
import sqlalchemy as sa


revision = "20260219_metadata"
down_revision = "20260213_print"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "orders" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("orders")]
        if "metadata" in cols:
            op.alter_column(
                "orders",
                "metadata",
                new_column_name="extra_data",
            )
        elif "extra_data" not in cols:
            op.add_column(
                "orders",
                sa.Column("extra_data", sa.JSON(), nullable=True),
            )


def downgrade() -> None:
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "orders" in insp.get_table_names():
        cols = [c["name"] for c in insp.get_columns("orders")]
        if "extra_data" in cols:
            op.alter_column(
                "orders",
                "extra_data",
                new_column_name="metadata",
            )
