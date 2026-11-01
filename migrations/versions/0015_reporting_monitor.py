"""Public monitoring provenance and private website notifications."""
from alembic import op
import sqlalchemy as sa
revision='0015'
down_revision='0014'
branch_labels=depends_on=None


def upgrade():
    sources=op.create_table('monitor_sources',sa.Column('id',sa.String(40),primary_key=True),
        sa.Column('company_id',sa.String(32),sa.ForeignKey('companies.id'),nullable=False),
        sa.Column('kind',sa.String(16),nullable=False),sa.Column('next_check',sa.Float,nullable=False),
        sa.Column('last_attempt',sa.Float),sa.Column('last_success',sa.Float),
        sa.Column('error',sa.String(80),nullable=False),sa.Column('failures',sa.Integer,nullable=False),sa.Column('snapshot_id',sa.String(32)))
    op.create_table('monitor_snapshots',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('source_id',sa.String(40),sa.ForeignKey('monitor_sources.id'),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),sa.Column('url',sa.Text,nullable=False),
        sa.Column('payload',sa.Text,nullable=False),sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('source_id','sha256'))
    op.create_table('monitor_observations',
        sa.Column('source_id',sa.String(40),sa.ForeignKey('monitor_sources.id'),primary_key=True),
        sa.Column('item_key',sa.String(64),primary_key=True),sa.Column('payload',sa.Text,nullable=False),
        sa.Column('snapshot_id',sa.String(32),sa.ForeignKey('monitor_snapshots.id'),nullable=False))
    op.create_table('monitor_events',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('source_id',sa.String(40),sa.ForeignKey('monitor_sources.id'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('kind',sa.String(32),nullable=False),
        sa.Column('payload',sa.Text,nullable=False),sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('source_id','fingerprint'))
    op.create_table('site_notifications',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('event_id',sa.String(32),sa.ForeignKey('monitor_events.id'),nullable=False),sa.Column('read_at',sa.Float),
        sa.UniqueConstraint('owner_id','event_id'))
    op.create_index('ix_site_notifications_org_id','site_notifications',['org_id'])
    op.bulk_insert(sources,[dict(id=f'{c}-{k}',company_id=c,kind=k,next_check=0,error='',failures=0)
        for c in ('jpm','hsbc','nu') for k in ('submissions','facts')])


def downgrade():
    for table in ('site_notifications','monitor_events','monitor_observations','monitor_snapshots','monitor_sources'): op.drop_table(table)
