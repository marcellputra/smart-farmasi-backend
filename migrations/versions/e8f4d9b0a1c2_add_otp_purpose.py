"""Add purpose to email OTPs

Revision ID: e8f4d9b0a1c2
Revises: c4b1a9f2d8e7
Create Date: 2026-05-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e8f4d9b0a1c2'
down_revision = 'c4b1a9f2d8e7'
branch_labels = None
depends_on = None


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'email_otps' not in inspector.get_table_names():
        return

    columns = _column_names('email_otps')
    if 'purpose' not in columns:
        with op.batch_alter_table('email_otps', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column(
                    'purpose',
                    sa.String(length=50),
                    nullable=False,
                    server_default='verify_email',
                )
            )

    indexes = _index_names('email_otps')
    if 'ix_email_otps_purpose' not in indexes:
        op.create_index(
            op.f('ix_email_otps_purpose'),
            'email_otps',
            ['purpose'],
            unique=False,
        )


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'email_otps' not in inspector.get_table_names():
        return

    indexes = _index_names('email_otps')
    if 'ix_email_otps_purpose' in indexes:
        op.drop_index(op.f('ix_email_otps_purpose'), table_name='email_otps')

    columns = _column_names('email_otps')
    if 'purpose' in columns:
        with op.batch_alter_table('email_otps', schema=None) as batch_op:
            batch_op.drop_column('purpose')
