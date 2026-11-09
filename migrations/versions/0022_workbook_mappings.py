"""Private workbook versions and explicit mapping approvals."""
from alembic import op
import sqlalchemy as sa
revision='0022'
down_revision='0021'
branch_labels=depends_on=None


def upgrade():
    op.create_table('workbook_mappings',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('parent_id',sa.String(32),sa.ForeignKey('workbook_mappings.id'),nullable=True),
        sa.Column('version_id',sa.String(32),sa.ForeignKey('template_versions.id'),nullable=True,unique=True),
        sa.Column('title',sa.String(160),nullable=False),sa.Column('idem_key',sa.String(100),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),sa.Column('blob_key',sa.String(200),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),sa.Column('inspection',sa.Text,nullable=False),
        sa.Column('entries',sa.Text,nullable=False),sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('created',sa.Float,nullable=False),sa.UniqueConstraint('owner_id','idem_key'))
    for key in ('org_id','owner_id'): op.create_index('ix_workbook_mappings_'+key,'workbook_mappings',[key])


def downgrade(): op.drop_table('workbook_mappings')
