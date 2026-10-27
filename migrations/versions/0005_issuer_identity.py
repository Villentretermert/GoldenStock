"""Confirm pilot issuers without replacing stable company IDs or private evidence."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = depends_on = None


def upgrade():
    companies = sa.table('companies', sa.column('id'), sa.column('name'),
                         sa.column('identifier'), sa.column('candidate', sa.Boolean))
    for key, name, identifier in [
        ('sber', 'Sberbank', 'INN 7707083893 · consolidated group (working scope)'),
        ('tinkoff', 'T-Technologies', 'INN 2540283195 · whole holding'),
        ('jpm', 'JPMorgan Chase & Co.', 'NYSE JPM · consolidated group'),
        ('hsbc', 'HSBC Holdings plc', 'CIK 1089113 · consolidated group'),
        ('nu', 'Nu Holdings Ltd.', 'CIK 1691493 · NYSE NU · consolidated group'),
    ]:
        op.execute(companies.update().where(companies.c.id == key).values(
            name=name, identifier=identifier, candidate=False))


def downgrade():
    companies = sa.table('companies', sa.column('id'), sa.column('name'),
                         sa.column('identifier'), sa.column('candidate', sa.Boolean))
    for key, name in [('sber', 'Sberbank'), ('tinkoff', 'Tinkoff / T-Bank'),
                      ('jpm', 'JPMorgan Chase'), ('hsbc', 'HSBC'), ('nu', 'Nu Holdings')]:
        op.execute(companies.update().where(companies.c.id == key).values(name=name,
            identifier='Issuer identifiers pending verification', candidate=key in {'jpm', 'hsbc', 'nu'}))
