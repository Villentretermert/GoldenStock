"""Organizations, revocable sessions and model metadata ACL."""
from alembic import op
import sqlalchemy as sa
revision = '0002'
down_revision = '0001'
branch_labels = depends_on = None


def upgrade():
    op.create_table('organizations', sa.Column('id', sa.String(32), primary_key=True), sa.Column('name', sa.String(120), nullable=False))
    op.create_table('users', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('org_id', sa.String(32), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('login', sa.String(120), unique=True, nullable=False), sa.Column('password_hash', sa.String(256), nullable=False),
        sa.Column('active', sa.Boolean, nullable=False), sa.Column('account_admin', sa.Boolean, nullable=False))
    op.create_index('ix_users_org_id', 'users', ['org_id'])
    op.create_table('login_sessions', sa.Column('token_hash', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(32), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('csrf', sa.String(64), nullable=False), sa.Column('expires', sa.Float, nullable=False))
    op.create_index('ix_login_sessions_user_id', 'login_sessions', ['user_id'])
    op.create_table('audit_events', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('org_id', sa.String(32), nullable=False), sa.Column('actor_id', sa.String(32), nullable=False),
        sa.Column('action', sa.String(80), nullable=False), sa.Column('target', sa.String(32), nullable=False),
        sa.Column('detail', sa.Text, nullable=False), sa.Column('created', sa.Float, nullable=False))
    op.create_index('ix_audit_events_org_id', 'audit_events', ['org_id'])
    op.create_table('workspace_models', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('org_id', sa.String(32), sa.ForeignKey('organizations.id'), nullable=False),
        sa.Column('owner_id', sa.String(32), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('title', sa.String(160), nullable=False), sa.Column('shared', sa.Boolean, nullable=False),
        sa.Column('revision', sa.Integer, nullable=False))
    op.create_index('ix_workspace_models_org_id', 'workspace_models', ['org_id'])


def downgrade():
    for table in ['workspace_models', 'audit_events', 'login_sessions', 'users', 'organizations']:
        op.drop_table(table)
