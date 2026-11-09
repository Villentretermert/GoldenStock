"""Retain already shared structures without sending historical notifications."""
import hashlib
import json
import time
import uuid
from alembic import op
import sqlalchemy as sa

revision='0021'
down_revision='0020'
branch_labels=depends_on=None


def upgrade():
    publications=op.create_table('template_publications',
        sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('template_id',sa.String(32),sa.ForeignKey('model_templates.id'),nullable=False),
        sa.Column('version_id',sa.String(32),sa.ForeignKey('template_versions.id'),nullable=False,unique=True),
        sa.Column('publisher_id',sa.String(32),sa.ForeignKey('users.id'),nullable=False),
        sa.Column('payload',sa.Text,nullable=False),sa.Column('payload_sha256',sa.String(64),nullable=False),
        sa.Column('legacy',sa.Boolean,nullable=False),sa.Column('created',sa.Float,nullable=False))
    for key in ('org_id','template_id'): op.create_index('ix_template_publications_'+key,'template_publications',[key])
    op.create_table('template_notifications',sa.Column('id',sa.String(32),primary_key=True),
        sa.Column('org_id',sa.String(32),sa.ForeignKey('organizations.id'),nullable=False),
        sa.Column('owner_id',sa.String(32),nullable=False),
        sa.Column('publication_id',sa.String(32),sa.ForeignKey('template_publications.id'),nullable=False),
        sa.Column('read_at',sa.Float,nullable=True),sa.UniqueConstraint('owner_id','publication_id'))
    for key in ('org_id','owner_id'): op.create_index('ix_template_notifications_'+key,'template_notifications',[key])
    connection=op.get_bind();now=time.time()
    rows=connection.execute(sa.text('SELECT t.id AS template_id,t.org_id,t.owner_id,t.title,v.id AS version_id,v.number,v.clean_sha256 FROM model_templates t JOIN template_versions v ON v.template_id=t.id WHERE t.shared=true')).mappings()
    for row in rows:
        payload=json.dumps(dict(title=row['title'],number=row['number'],previous_number=None,clean_sha256=row['clean_sha256'],
            changes=['Structure was already shared before publication history began.']),sort_keys=True,ensure_ascii=False)
        connection.execute(publications.insert().values(id=uuid.uuid4().hex,org_id=row['org_id'],template_id=row['template_id'],
            version_id=row['version_id'],publisher_id=row['owner_id'],payload=payload,
            payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),legacy=True,created=now))


def downgrade():
    op.drop_table('template_notifications');op.drop_table('template_publications')
