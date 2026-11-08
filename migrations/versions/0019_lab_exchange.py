"""Private workbook drafts and explicit imports with retained originals."""
from alembic import op
import sqlalchemy as sa

revision='0019'
down_revision='0018'
branch_labels=depends_on=None


def upgrade():
    op.create_table('lab_exchanges',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('payload',sa.Text,nullable=False),sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('owner_id','fingerprint'))
    op.create_index('ix_lab_exchanges_org_id','lab_exchanges',['org_id'])
    op.create_table('lab_imports',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('exchange_id',sa.String(32),sa.ForeignKey('lab_exchanges.id'),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),sa.Column('original',sa.LargeBinary,nullable=False),
        sa.Column('candidate',sa.Text,nullable=False),sa.Column('candidate_hash',sa.String(64),nullable=False),
        sa.Column('dataset_id',sa.String(32),sa.ForeignKey('lab_datasets.id'),nullable=True),
        sa.Column('confirmation_note',sa.Text,nullable=False),sa.Column('confirmed_at',sa.Float,nullable=True),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('exchange_id','sha256'))
    op.create_index('ix_lab_imports_org_id','lab_imports',['org_id'])


def downgrade():
    op.drop_table('lab_imports');op.drop_table('lab_exchanges')
