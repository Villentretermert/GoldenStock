"""Private dataset snapshots, experiments, blind annotations and split registry."""
from alembic import op
import sqlalchemy as sa

revision='0014'
down_revision='0013'
branch_labels=depends_on=None


def upgrade():
    op.create_table('lab_datasets',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('parent_id',sa.String(32),sa.ForeignKey('lab_datasets.id')),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('title',sa.String(160),nullable=False),
        sa.Column('split',sa.String(16),nullable=False),sa.Column('kind',sa.String(16),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('payload',sa.Text,nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('owner_id','fingerprint'))
    op.create_index('ix_lab_datasets_org_id','lab_datasets',['org_id'])
    op.create_table('lab_source_splits',
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),primary_key=True),
        sa.Column('source_hash',sa.String(64),primary_key=True),sa.Column('split',sa.String(16),nullable=False))
    op.create_table('lab_experiments',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('dataset_id',sa.String(32),sa.ForeignKey('lab_datasets.id'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('manifest',sa.Text,nullable=False),
        sa.Column('manifest_hash',sa.String(64),nullable=False),sa.Column('revealed',sa.Boolean,nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('owner_id','fingerprint'))
    op.create_index('ix_lab_experiments_org_id','lab_experiments',['org_id'])
    op.create_table('lab_annotations',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('experiment_id',sa.String(32),sa.ForeignKey('lab_experiments.id'),nullable=False),
        sa.Column('run_id',sa.String(32),sa.ForeignKey('ai_runs.id'),nullable=False),
        sa.Column('actor_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('verdict',sa.String(16),nullable=False),
        sa.Column('reason',sa.String(1000),nullable=False),sa.Column('output_hash',sa.String(64),nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('run_id','revision'))


def downgrade():
    for table in ['lab_annotations','lab_experiments','lab_source_splits','lab_datasets']:
        op.drop_table(table)
