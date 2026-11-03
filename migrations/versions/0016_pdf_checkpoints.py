"""Durable PDF prefixes, isolated from complete evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = depends_on = None


def upgrade():
    op.create_table('extraction_checkpoints',
        sa.Column('version_id', sa.String(32), sa.ForeignKey('document_versions.id'), primary_key=True),
        sa.Column('parser_version', sa.String(40), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('completed_pages', sa.Integer, nullable=False),
        sa.Column('total_pages', sa.Integer, nullable=False),
        sa.Column('payload', sa.Text, nullable=False),
        sa.Column('payload_sha256', sa.String(64), nullable=False))


def downgrade():
    op.drop_table('extraction_checkpoints')
