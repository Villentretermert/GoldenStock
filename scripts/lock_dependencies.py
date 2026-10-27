"""Snapshot installed dependencies after resolution, keeping dev tools out of runtime."""
from importlib.metadata import distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = {"pytest", "pytest-asyncio", "iniconfig", "pluggy"}
EXCLUDE = {"pip", "setuptools", "goldenstock"}
packages = sorted((d.metadata["Name"].lower().replace("_", "-"), d.version)
                  for d in distributions() if d.metadata["Name"].lower() not in EXCLUDE)
runtime = [f"{name}=={version}" for name, version in packages if name not in DEV]
# uvicorn[standard] adds uvloop only on Linux; the container path must also be pinned.
runtime += ['uvloop==0.22.1; sys_platform != "win32" and sys_platform != "cygwin"']
(ROOT / "requirements.lock").write_text(
    "# Runtime snapshot; resolved on Python 3.14. See docs/RUN_LOCAL.md.\n"
    + "\n".join(runtime) + "\n", encoding="utf-8")
(ROOT / "requirements-dev.lock").write_text(
    "-r requirements.lock\n"
    + "\n".join(f"{name}=={version}" for name, version in packages if name in DEV)
    + "\n", encoding="utf-8")
