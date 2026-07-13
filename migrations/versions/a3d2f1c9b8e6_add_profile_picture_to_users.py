"""add profile picture to users

Revision ID: a3d2f1c9b8e6
Revises: b75462a371d3
Create Date: 2026-05-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3d2f1c9b8e6'
down_revision = 'b75462a371d3'
branch_labels = None
depends_on = None


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    columns = _column_names('users')
    if 'profile_picture' not in columns:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.add_column(sa.Column('profile_picture', sa.String(length=255), nullable=True))


def downgrade():
    columns = _column_names('users')
    if 'profile_picture' in columns:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.drop_column('profile_picture')
