"""tambah tabel face recognition

Revision ID: 495f29376d6a
Revises: 03fcf0915d0e
Create Date: 2026-07-07 22:46:24.642320

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '495f29376d6a'
down_revision = '03fcf0915d0e'
branch_labels = None
depends_on = None


def upgrade():
    # Hanya membuat tabel face_recognition baru
    op.create_table('face_recognition',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('face_encoding', sa.Text(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id')
    )


def downgrade():
    # Jika migrasi dibatalkan, cukup hapus tabel face_recognition kembali
    op.drop_table('face_recognition')