"""Explicit device requests and private execution attempts."""
from alembic import op
import sqlalchemy as sa

revision='0018'
down_revision='0017'
branch_labels=depends_on=None


def upgrade():
    op.add_column('ai_runs',sa.Column('device',sa.String(8),nullable=False,server_default='gpu'))
    op.create_table('ai_executions',
        sa.Column('run_id',sa.String(32),sa.ForeignKey('ai_runs.id'),primary_key=True),
        sa.Column('attempt',sa.Integer,primary_key=True),
        sa.Column('state',sa.String(24),nullable=False),
        sa.Column('started',sa.Float,nullable=False),
        sa.Column('finished',sa.Float,nullable=True),
        sa.Column('receipt',sa.Text,nullable=False))


def downgrade():
    op.drop_table('ai_executions')
    op.drop_column('ai_runs','device')
