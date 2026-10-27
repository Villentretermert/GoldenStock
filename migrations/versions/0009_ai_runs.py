"""Private immutable AI inputs and fenced task state."""
from alembic import op
import sqlalchemy as sa
revision='0009'
down_revision='0008'
branch_labels=depends_on=None


def upgrade():
    op.create_table('ai_runs',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),nullable=False),sa.Column('owner_id',sa.String(32),nullable=False),
        sa.Column('company_id',sa.String(32),nullable=False),sa.Column('kind',sa.String(24),nullable=False),
        sa.Column('profile',sa.String(32),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('input',sa.Text,nullable=False),sa.Column('output',sa.Text,nullable=False),
        sa.Column('state',sa.String(24),nullable=False),sa.Column('error',sa.String(80),nullable=False),
        sa.Column('attempts',sa.Integer,nullable=False),sa.Column('lease_until',sa.Float,nullable=False),
        sa.Column('lease_token',sa.String(32),nullable=False),sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('owner_id','fingerprint'))


def downgrade():
    op.drop_table('ai_runs')
