"""Native loopback-only smoke mode, with SQLite instead of production PostgreSQL."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), GS_INFERENCE_URL="http://127.0.0.1:11434", GS_PUBLIC_URL='http://127.0.0.1:8080')
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env, check=True)
    worker = subprocess.Popen([sys.executable, "-m", "goldenstock.worker"], env=env)
    try:
        subprocess.run([sys.executable, "-m", "uvicorn", "goldenstock.main:app",
                        "--host", "127.0.0.1", "--port", "8080", "--no-proxy-headers"],
                       env=env, check=True)
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=5)
        except subprocess.TimeoutExpired:
            worker.kill()
            worker.wait()


if __name__ == "__main__":
    main()
