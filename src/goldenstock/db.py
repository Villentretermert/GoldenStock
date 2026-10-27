"""Database factory shared by the API and background worker."""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from goldenstock.config import Settings


def make_engine(settings: Settings) -> Engine:
    if settings.database_url.startswith("sqlite:"):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        return create_engine(settings.database_url, connect_args={"check_same_thread": False}, pool_pre_ping=True)
    return create_engine(settings.database_url, connect_args={"connect_timeout": 3}, pool_pre_ping=True)
