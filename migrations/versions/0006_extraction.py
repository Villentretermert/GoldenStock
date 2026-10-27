"""Version-linked raw evidence; original verification remains a separate job phase."""
from alembic import op
import sqlalchemy as sa
revision = '0006'
down_revision = '0005'
branch_labels = depends_on = None


def upgrade():
    op.add_column('jobs', sa.Column('kind', sa.String(24), nullable=False, server_default='verify_original'))
    op.create_table('extractions',
        sa.Column('version_id', sa.String(32), sa.ForeignKey('document_versions.id'), primary_key=True),
        sa.Column('parser_version', sa.String(40), nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.Column('payload', sa.Text, nullable=False),
        sa.Column('created', sa.Float, nullable=False))


def downgrade():
    op.drop_table('extractions')
    op.drop_column('jobs', 'kind')
