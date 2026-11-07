"""Private selected-page batches with immutable source/run manifests."""
from alembic import op
import sqlalchemy as sa

revision='0017'
down_revision='0016'
branch_labels=depends_on=None


def upgrade():
    op.create_table('ai_proposal_batches',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('company_id',sa.String(32),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('version_id',sa.String(32),sa.ForeignKey('document_versions.id'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('manifest',sa.Text,nullable=False),
        sa.Column('manifest_hash',sa.String(64),nullable=False),
        sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('owner_id','fingerprint'))
    op.create_index('ix_ai_proposal_batches_org_id','ai_proposal_batches',['org_id'])


def downgrade():
    op.drop_table('ai_proposal_batches')
