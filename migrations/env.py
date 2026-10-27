"""Use runtime configuration instead of putting credentials in alembic.ini."""
from alembic import context
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.models import Base

settings = get_settings()
if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=Base.metadata,
                      literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = make_engine(settings)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
