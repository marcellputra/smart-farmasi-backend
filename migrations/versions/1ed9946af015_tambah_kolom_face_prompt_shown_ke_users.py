"""tambah kolom face prompt shown ke users

Revision ID: 1ed9946af015
Revises: 495f29376d6a
Create Date: 2026-07-07 22:56:04.455413

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1ed9946af015'
down_revision = '495f29376d6a'
branch_labels = None
depends_on = None


def upgrade():
    # Hanya menambahkan kolom face_prompt_shown ke tabel users secara aman
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('face_prompt_shown', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade():
    # Menghapus kembali kolom jika melakukan rollback
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('face_prompt_shown')