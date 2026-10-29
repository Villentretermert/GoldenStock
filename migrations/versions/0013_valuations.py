"""Private immutable valuation snapshots and methodology receipts."""
from alembic import op
import sqlalchemy as sa
revision='0013'
down_revision='0012'
branch_labels=depends_on=None


def upgrade():
    op.create_table('valuation_runs',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('company_id',sa.String(32),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('calculation_id',sa.String(32),sa.ForeignKey('calculation_runs.id'),nullable=False),
        sa.Column('title',sa.String(160),nullable=False),sa.Column('method',sa.String(16),nullable=False),
        sa.Column('policy',sa.String(32),nullable=False),sa.Column('state',sa.String(24),nullable=False),
        sa.Column('idem_key',sa.String(100),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('input_hash',sa.String(64),nullable=False),sa.Column('result_hash',sa.String(64),nullable=False),
        sa.Column('input',sa.Text,nullable=False),sa.Column('output',sa.Text,nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('owner_id','idem_key'))
    op.create_index('ix_valuation_runs_org_id','valuation_runs',['org_id'])


def downgrade():
    op.drop_table('valuation_runs')
