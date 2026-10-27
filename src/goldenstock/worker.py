"""Heartbeat, persistent original verification jobs and graceful shutdown."""
import logging
import signal
import threading
import time

from sqlalchemy.orm import Session

from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.models import WorkerHeartbeat
from goldenstock.jobs import process_one
from goldenstock.ai_runs import process_ai

logger = logging.getLogger(__name__)


def beat(engine, worker_id: str, now: float | None = None) -> None:
    with Session(engine) as session, session.begin():
        session.merge(WorkerHeartbeat(worker_id=worker_id, last_seen=time.time() if now is None else now))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings()
    engine = make_engine(settings)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger.info("Worker started; original verification queue enabled")
    try:
        while not stop.is_set():
            try:
                beat(engine, settings.worker_id)
                process_one(engine, settings)
                # Inference may take minutes; readiness must still observe a live worker.
                ai_done=threading.Event()
                def ai_heartbeat():
                    while not ai_done.wait(settings.heartbeat_interval):
                        try: beat(engine,settings.worker_id)
                        except Exception: logger.warning('AI heartbeat unavailable')
                heartbeat=threading.Thread(target=ai_heartbeat,daemon=True)
                heartbeat.start()
                try: process_ai(engine, settings)
                finally: ai_done.set();heartbeat.join(timeout=5)
            except Exception:
                # Never log credentials or database exception strings.
                logger.warning("Heartbeat unavailable; retrying")
            stop.wait(settings.heartbeat_interval)
    finally:
        engine.dispose()
        logger.info("Worker stopped")


if __name__ == "__main__":
    main()
