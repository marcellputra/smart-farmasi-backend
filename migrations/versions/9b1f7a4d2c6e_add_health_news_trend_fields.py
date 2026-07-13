"""Add health news trend fields

Revision ID: 9b1f7a4d2c6e
Revises: 5ceeeb281277
Create Date: 2026-05-13 19:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '9b1f7a4d2c6e'
down_revision = '5ceeeb281277'
branch_labels = None
depends_on = None


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "disease_news" not in inspector.get_table_names():
        op.create_table(
            "disease_news",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("disease_name", sa.String(length=200), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("country", sa.String(length=200), nullable=True),
            sa.Column("source_name", sa.String(length=100), nullable=False),
            sa.Column("source_url", sa.String(length=1000), nullable=True),
            sa.Column("alert_level", sa.Enum("low", "medium", "high"), nullable=False),
            sa.Column("badge", sa.String(length=50), nullable=True),
            sa.Column("region_scope", sa.String(length=30), nullable=False, server_default="international"),
            sa.Column("trend_score", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("trend_keyword", sa.String(length=200), nullable=True),
            sa.Column("is_trending", sa.Boolean(), nullable=True),
            sa.Column("view_count", sa.Integer(), nullable=True),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            sa.Column("fetched_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        return

    columns = _column_names("disease_news")
    with op.batch_alter_table("disease_news", schema=None) as batch_op:
        if "region_scope" not in columns:
            batch_op.add_column(sa.Column("region_scope", sa.String(length=30), nullable=False, server_default="international"))
        if "trend_score" not in columns:
            batch_op.add_column(sa.Column("trend_score", sa.Integer(), nullable=True, server_default="0"))
        if "trend_keyword" not in columns:
            batch_op.add_column(sa.Column("trend_keyword", sa.String(length=200), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "disease_news" not in inspector.get_table_names():
        return

    columns = _column_names("disease_news")
    with op.batch_alter_table("disease_news", schema=None) as batch_op:
        if "trend_keyword" in columns:
            batch_op.drop_column("trend_keyword")
        if "trend_score" in columns:
            batch_op.drop_column("trend_score")
        if "region_scope" in columns:
            batch_op.drop_column("region_scope")
