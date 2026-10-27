"""Immutable evidence-backed facts; explicit supersession preserves history."""
from alembic import op
import sqlalchemy as sa
revision='0007'
down_revision='0006'
branch_labels=depends_on=None


def upgrade():
    op.create_table('facts',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('company_id',sa.String(32),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('version_id',sa.String(32),sa.ForeignKey('document_versions.id'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('supersedes',sa.String(32),sa.ForeignKey('facts.id'),nullable=True,unique=True),
        sa.Column('payload',sa.Text,nullable=False),sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('owner_id','fingerprint'))
    op.create_index('ix_facts_owner_company','facts',['org_id','owner_id','company_id'])


def downgrade():
    op.drop_table('facts')
