"""Separate process liveness, core readiness and optional inference availability."""
import asyncio
import time

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from goldenstock.config import Settings
from goldenstock.models import WorkerHeartbeat

SCHEMA_REVISION = "0012"


def database_status(engine, settings: Settings) -> tuple[str, str]:
    try:
        with Session(engine) as session:
            revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar()
            if revision != SCHEMA_REVISION:
                return "migration_required", "unavailable"
            heartbeat = session.get(WorkerHeartbeat, settings.worker_id)
            age = time.time() - heartbeat.last_seen if heartbeat else None
            worker = "ready" if age is not None and 0 <= age <= settings.heartbeat_timeout else "stale"
            return "ready", worker
    except Exception:
        return "unavailable", "unavailable"


async def readiness(engine, settings: Settings) -> dict:
    db, worker = await asyncio.to_thread(database_status, engine, settings)
    return {"status": "ready" if db == worker == "ready" else "not_ready",
            "database": db, "worker": worker}


async def inference_status(settings: Settings) -> str:
    try:
        async with httpx.AsyncClient(timeout=2, trust_env=False, follow_redirects=False) as client:
            response = await client.get(f"{settings.inference_url}/api/tags")
            response.raise_for_status()
            models = response.json().get("models")
            if not isinstance(models, list):
                return "unavailable"
            return "available" if models else "no_model_loaded"
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return "unavailable"
