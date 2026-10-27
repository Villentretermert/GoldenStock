"""Container health probe for a database-backed worker heartbeat."""
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.health import database_status


def main():
    settings = get_settings()
    engine = make_engine(settings)
    try:
        db, worker = database_status(engine, settings)
        raise SystemExit(0 if db == worker == "ready" else 1)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
