"""Network-enabled public connector; no uploaded files or inference work."""
import logging
import signal
import sys
import threading
import time
from sqlalchemy.orm import Session
from goldenstock.config import get_settings
from goldenstock.db import make_engine
from goldenstock.models import WorkerHeartbeat
from goldenstock.worker import beat
from goldenstock.monitoring import process_monitor

WORKER_ID='reporting-monitor'


def healthy(engine,timeout=30):
    with Session(engine) as db:
        heartbeat=db.get(WorkerHeartbeat,WORKER_ID)
        return bool(heartbeat and 0<=time.time()-heartbeat.last_seen<=timeout)


def main():
    settings=get_settings();engine=make_engine(settings)
    if '--health' in sys.argv:
        try: ok=healthy(engine,settings.heartbeat_timeout)
        except Exception: ok=False
        finally: engine.dispose()
        raise SystemExit(0 if ok else 1)
    logging.basicConfig(level=logging.INFO,format='%(levelname)s %(message)s')
    stop=threading.Event()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,lambda *_:stop.set())
    def heartbeat():
        while not stop.is_set():
            try: beat(engine,WORKER_ID)
            except Exception: logging.warning('Monitoring heartbeat unavailable')
            stop.wait(settings.heartbeat_interval)
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:
        while not stop.is_set():
            try: process_monitor(engine,settings)
            except Exception: logging.warning('Monitoring transaction failed; retrying')
            stop.wait(settings.heartbeat_interval)
    finally:
        stop.set();thread.join(timeout=5);engine.dispose()


if __name__=='__main__': main()
