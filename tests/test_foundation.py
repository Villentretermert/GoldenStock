"""Regression tests for startup, health semantics and the public service boundary."""
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
import yaml

from goldenstock.api import create_app
from goldenstock.config import Settings
from goldenstock.db import make_engine
from goldenstock.worker import beat
from scripts.bootstrap import write_env


@pytest.fixture
def configured(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("GS_DATABASE_URL", url)
    from goldenstock.config import get_settings
    get_settings.cache_clear()
    settings = Settings(_env_file=None, database_url=url, data_dir=tmp_path)
    yield settings
    get_settings.cache_clear()


def migrate():
    command.upgrade(Config("alembic.ini"), "head")


def test_live_does_not_claim_database_ready(configured):
    with TestClient(create_app(configured)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503


def test_migration_idempotency_and_worker_staleness(configured):
    migrate()
    migrate()
    engine = make_engine(configured)
    with TestClient(create_app(configured)) as client:
        assert client.get("/health/ready").status_code == 503
        beat(engine, configured.worker_id)
        assert client.get("/health/ready").status_code == 200
        beat(engine, configured.worker_id, now=time.time()-100)
        assert client.get("/health/ready").json()["worker"] == "stale"
    command.downgrade(Config("alembic.ini"), "base")
    migrate()
    engine.dispose()


def test_wrong_schema_is_not_ready(configured):
    migrate()
    engine = make_engine(configured)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='future'"))
    with TestClient(create_app(configured)) as client:
        assert client.get("/health/ready").json()["database"] == "migration_required"
    engine.dispose()


def test_no_business_or_inference_proxy_routes(configured):
    with TestClient(create_app(configured)) as client:
        for path in ["/documents", "/api/generate", "/api/tags"]:
            assert client.post(path, json={}).status_code == 404
        assert client.post('/api/v1/documents').status_code == 401


@pytest.mark.parametrize("url", [
    "https://external.example", "http://inference.evil", "http://user:pass@localhost",
    "http://localhost/api", "http://127.0.0.1?x=y", "file:///tmp/model",
])
def test_external_inference_configuration_rejected(url):
    with pytest.raises(ValueError):
        Settings(_env_file=None, inference_url=url)


def test_bootstrap_does_not_replace_existing_secret(tmp_path):
    assert write_env(tmp_path)
    original = (tmp_path/".env").read_text()
    assert not write_env(tmp_path)
    assert (tmp_path/".env").read_text() == original
    assert "POSTGRES_PASSWORD=" in original


def test_compose_has_only_loopback_web_port():
    config = yaml.safe_load(Path("compose.yaml").read_text())
    for name, service in config["services"].items():
        if name == "web":
            assert all(p.startswith("127.0.0.1:") for p in service["ports"])
        else:
            assert not service.get("ports")
    assert config["networks"]["private"]["internal"] is True
    assert config["services"]["inference"]["profiles"] == ["ai"]
    assert config["services"]["web"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
