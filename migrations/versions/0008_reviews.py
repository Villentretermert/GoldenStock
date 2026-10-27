"""Append-only analyst decisions and immutable input snapshots."""
from alembic import op
import sqlalchemy as sa
revision='0008'
down_revision='0007'
branch_labels=depends_on=None


def upgrade():
    op.create_table('fact_reviews',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('fact_id',sa.String(32),sa.ForeignKey('facts.id'),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('actor_id',sa.String(32),nullable=False),
        sa.Column('decision',sa.String(20),nullable=False),sa.Column('note',sa.Text,nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('fact_id','revision'))
    op.create_table('input_snapshots',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),nullable=False),sa.Column('owner_id',sa.String(32),nullable=False),
        sa.Column('company_id',sa.String(32),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('title',sa.String(160),nullable=False),sa.Column('state_hash',sa.String(64),nullable=False),
        sa.Column('payload',sa.Text,nullable=False),sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('owner_id','company_id','state_hash'))


def downgrade():
    op.drop_table('input_snapshots')
    op.drop_table('fact_reviews')
