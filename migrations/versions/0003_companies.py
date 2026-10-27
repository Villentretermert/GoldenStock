"""Seed labels are research candidates, not verified securities identifiers."""
from alembic import op
import sqlalchemy as sa
revision = '0003'
down_revision = '0002'
branch_labels = depends_on = None


def upgrade():
    table = op.create_table('companies', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('name', sa.String(160), nullable=False), sa.Column('identifier', sa.String(120), nullable=False),
        sa.Column('candidate', sa.Boolean, nullable=False), sa.Column('source_url', sa.String(300), nullable=False),
        sa.Column('source_checked', sa.Float, nullable=True))
    op.bulk_insert(table, [dict(id=key, name=name, identifier='Issuer identifiers pending verification', candidate=candidate, source_url='', source_checked=None)
        for key, name, candidate in [('sber', 'Sberbank', False), ('tinkoff', 'Tinkoff / T-Bank', False),
            ('jpm', 'JPMorgan Chase', True), ('hsbc', 'HSBC', True), ('nu', 'Nu Holdings', True)]])
    op.create_table('favorites', sa.Column('user_id', sa.String(32), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('company_id', sa.String(32), sa.ForeignKey('companies.id'), primary_key=True))


def downgrade():
    op.drop_table('favorites')
    op.drop_table('companies')
