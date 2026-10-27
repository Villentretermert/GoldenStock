"""Immutable public SEC snapshots; never stores private uploads."""
from alembic import op
import sqlalchemy as sa
revision='0010'
down_revision='0009'
branch_labels=depends_on=None


def upgrade():
    op.create_table('public_snapshots',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('company_id',sa.String(32),nullable=False),sa.Column('sha256',sa.String(64),nullable=False),
        sa.Column('url',sa.Text,nullable=False),sa.Column('payload',sa.Text,nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.Column('checked',sa.Float,nullable=False),sa.UniqueConstraint('company_id','sha256'))


def downgrade():
    op.drop_table('public_snapshots')
