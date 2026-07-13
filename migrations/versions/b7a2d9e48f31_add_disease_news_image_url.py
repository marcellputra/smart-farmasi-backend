"""Add disease news image url

Revision ID: b7a2d9e48f31
Revises: 9b1f7a4d2c6e
Create Date: 2026-05-13 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b7a2d9e48f31'
down_revision = '9b1f7a4d2c6e'
branch_labels = None
depends_on = None


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "disease_news" not in inspector.get_table_names():
        return

    columns = _column_names("disease_news")
    if "image_url" not in columns:
        with op.batch_alter_table("disease_news", schema=None) as batch_op:
            batch_op.add_column(sa.Column("image_url", sa.String(length=1000), nullable=True))


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if "disease_news" not in inspector.get_table_names():
        return

    columns = _column_names("disease_news")
    if "image_url" in columns:
        with op.batch_alter_table("disease_news", schema=None) as batch_op:
            batch_op.drop_column("image_url")
