"""Versioned templates and separate private/sanitized files."""
from alembic import op
import sqlalchemy as sa
revision='0011'
down_revision='0010'
branch_labels=depends_on=None


def upgrade():
    op.create_table('model_templates',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('title',sa.String(160),nullable=False),sa.Column('shared',sa.Boolean,nullable=False),
        sa.Column('revision',sa.Integer,nullable=False))
    op.create_index('ix_model_templates_org_id','model_templates',['org_id'])
    op.create_table('template_versions',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('template_id',sa.String(32),sa.ForeignKey('model_templates.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),nullable=False),sa.Column('number',sa.Integer,nullable=False),
        sa.Column('idem_key',sa.String(100),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('sha256',sa.String(64),nullable=False),sa.Column('clean_sha256',sa.String(64),nullable=False),
        sa.Column('blob_key',sa.String(200),nullable=False),sa.Column('clean_key',sa.String(200),nullable=False),
        sa.Column('contract',sa.Text,nullable=False),sa.Column('created',sa.Float,nullable=False),
        sa.UniqueConstraint('template_id','number'),sa.UniqueConstraint('owner_id','idem_key'))
    op.create_index('ix_template_versions_template_id','template_versions',['template_id'])


def downgrade():
    op.drop_table('template_versions');op.drop_table('model_templates')
