"""Add email OTP verification

Revision ID: c4b1a9f2d8e7
Revises: b7a2d9e48f31
Create Date: 2026-05-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c4b1a9f2d8e7'
down_revision = 'b7a2d9e48f31'
branch_labels = None
depends_on = None


def _column_names(table_name):
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade():
    inspector = sa.inspect(op.get_bind())
    users_columns = _column_names('users')

    with op.batch_alter_table('users', schema=None) as batch_op:
        if 'email_verified_at' not in users_columns:
            batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))
        if 'is_verified' not in users_columns:
            batch_op.add_column(sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.text('0')))

    if 'is_verified' not in users_columns:
        op.execute(
            "UPDATE users "
            "SET is_verified = 1, email_verified_at = COALESCE(email_verified_at, created_at, CURRENT_TIMESTAMP)"
        )

    if 'email_otps' not in inspector.get_table_names():
        op.create_table(
            'email_otps',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(length=120), nullable=False),
            sa.Column('otp_hash', sa.String(length=255), nullable=False),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('is_used', sa.Boolean(), nullable=False, server_default=sa.text('0')),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index(op.f('ix_email_otps_email'), 'email_otps', ['email'], unique=False)
        op.create_index(op.f('ix_email_otps_user_id'), 'email_otps', ['user_id'], unique=False)


def downgrade():
    inspector = sa.inspect(op.get_bind())
    if 'email_otps' in inspector.get_table_names():
        op.drop_index(op.f('ix_email_otps_user_id'), table_name='email_otps')
        op.drop_index(op.f('ix_email_otps_email'), table_name='email_otps')
        op.drop_table('email_otps')

    users_columns = _column_names('users')
    with op.batch_alter_table('users', schema=None) as batch_op:
        if 'is_verified' in users_columns:
            batch_op.drop_column('is_verified')
        if 'email_verified_at' in users_columns:
            batch_op.drop_column('email_verified_at')
