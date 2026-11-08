"""Retain observed SEC versions without fabricating earlier observation history."""
import hashlib
import time
import uuid
from alembic import op
import sqlalchemy as sa

revision='0020'
down_revision='0019'
branch_labels=depends_on=None


def upgrade():
    table=op.create_table('monitor_fact_versions',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('source_id',sa.String(40),sa.ForeignKey('monitor_sources.id'),nullable=False),
        sa.Column('item_key',sa.String(64),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('previous_id',sa.String(32),sa.ForeignKey('monitor_fact_versions.id'),nullable=True),
        sa.Column('snapshot_id',sa.String(32),sa.ForeignKey('monitor_snapshots.id'),nullable=False),
        sa.Column('reason',sa.String(32),nullable=False),sa.Column('payload',sa.Text,nullable=False),
        sa.Column('payload_sha256',sa.String(64),nullable=False),sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('source_id','item_key','revision'),sa.UniqueConstraint('previous_id'))
    op.create_index('ix_monitor_fact_versions_source_id','monitor_fact_versions',['source_id'])
    op.add_column('monitor_observations',sa.Column('history_id',sa.String(32),nullable=True))
    connection=op.get_bind();now=time.time()
    rows=connection.execute(sa.text("SELECT o.source_id,o.item_key,o.snapshot_id,o.payload FROM monitor_observations o JOIN monitor_sources s ON s.id=o.source_id WHERE s.kind='facts'")).mappings().all()
    for row in rows:
        key=uuid.uuid4().hex
        connection.execute(table.insert().values(**dict(row),id=key,revision=1,previous_id=None,
            reason='legacy_baseline',payload_sha256=hashlib.sha256(row['payload'].encode()).hexdigest(),created=now))
        connection.execute(sa.text('UPDATE monitor_observations SET history_id=:id WHERE source_id=:source AND item_key=:item'),
            dict(id=key,source=row['source_id'],item=row['item_key']))


def downgrade():
    op.drop_column('monitor_observations','history_id')
    op.drop_table('monitor_fact_versions')
