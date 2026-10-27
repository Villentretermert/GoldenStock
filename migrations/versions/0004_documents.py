"""Immutable originals and a persistent leased verification queue."""
from alembic import op
import sqlalchemy as s
revision = '0004'
down_revision = '0003'
branch_labels = depends_on = None


def upgrade():
    op.create_table('documents', s.Column('id',s.String(32),primary_key=True),
        s.Column('org_id',s.String(32),s.ForeignKey('organizations.id'),nullable=False),
        s.Column('owner_id',s.String(32),s.ForeignKey('users.id'),nullable=False),
        s.Column('company_id',s.String(32),s.ForeignKey('companies.id'),nullable=False),
        s.Column('shared',s.Boolean,nullable=False),s.Column('filename',s.String(200),nullable=False),s.Column('revision',s.Integer,nullable=False))
    op.create_index('ix_documents_org_id','documents',['org_id'])
    op.create_table('document_versions',s.Column('id',s.String(32),primary_key=True),
        s.Column('document_id',s.String(32),s.ForeignKey('documents.id'),nullable=False),
        s.Column('org_id',s.String(32),nullable=False),s.Column('owner_id',s.String(32),nullable=False),
        s.Column('number',s.Integer,nullable=False),s.Column('filename',s.String(200),nullable=False),
        s.Column('sha256',s.String(64),nullable=False),s.Column('size',s.Integer,nullable=False),
        s.Column('blob_key',s.String(200),nullable=False),s.Column('idem_key',s.String(100),nullable=False),
        s.Column('request_hash',s.String(64),nullable=False),s.Column('created',s.Float,nullable=False),
        s.UniqueConstraint('document_id','number'),s.UniqueConstraint('owner_id','idem_key'))
    op.create_index('ix_document_versions_document_id','document_versions',['document_id'])
    op.create_table('jobs',s.Column('id',s.String(32),primary_key=True),s.Column('org_id',s.String(32),nullable=False),
        s.Column('actor_id',s.String(32),nullable=False),s.Column('version_id',s.String(32),s.ForeignKey('document_versions.id'),unique=True,nullable=False),
        s.Column('state',s.String(24),nullable=False),s.Column('attempts',s.Integer,nullable=False),
        s.Column('lease_until',s.Float,nullable=False),s.Column('lease_token',s.String(32),nullable=False),
        s.Column('available_at',s.Float,nullable=False),s.Column('error_code',s.String(40),nullable=False),s.Column('created',s.Float,nullable=False))
    op.create_index('ix_jobs_org_id','jobs',['org_id'])
    op.create_table('job_events',s.Column('id',s.String(32),primary_key=True),
        s.Column('job_id',s.String(32),s.ForeignKey('jobs.id'),nullable=False),s.Column('state',s.String(24),nullable=False),
        s.Column('attempt',s.Integer,nullable=False),s.Column('created',s.Float,nullable=False))
    op.create_index('ix_job_events_job_id','job_events',['job_id'])


def downgrade():
    for table in ['job_events','jobs','document_versions','documents']:
        op.drop_table(table)
