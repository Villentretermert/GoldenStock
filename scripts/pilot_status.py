"""Operator-only pilot metrics. Run via stdin inside web."""
import asyncio
import json
import shutil
from sqlalchemy import text
from sqlalchemy.orm import Session
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.health import readiness, inference_status
from goldenstock.monitor_worker import healthy

settings = get_settings()
engine = make_engine(settings)
with Session(engine) as db:
    row = db.execute(text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")).one()
    db_bytes = db.scalar(text("SELECT pg_database_size(current_database())"))
    counts = dict(db.execute(text("SELECT state,count(*) FROM ai_runs GROUP BY state")).all())
    sessions = db.scalar(text("SELECT count(*) FROM login_sessions WHERE expires > extract(epoch FROM now())"))
    rls = db.scalar(text("SELECT count(*) FROM pg_tables WHERE schemaname='public' AND rowsecurity"))
    role = db.scalar(text("SELECT current_user"))
disk = shutil.disk_usage(settings.data_dir)
status = dict(core=asyncio.run(readiness(engine,settings)), monitor_ready=healthy(engine),
              inference=asyncio.run(inference_status(settings)), ai_runs=counts, active_sessions=sessions,
              db_bytes=db_bytes, app_volume_free_bytes=disk.free,
              disk_warning=disk.free < max(10*1024**3, disk.total//10),
              upload_limit_bytes=settings.max_file_bytes, runtime_role=role, superuser=row[0],
              bypass_rls=row[1], rls_tables=rls, secure_cookie=settings.secure_cookie)
print(json.dumps(status,sort_keys=True))
engine.dispose()
