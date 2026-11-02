"""WSL/Linux scheduler entry point. Require the intended mount and repository before writing."""
import argparse
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("action", choices=("init","backup","list","check","status"))
args = parser.parse_args()
mount = Path(os.environ["GS_BACKUP_MOUNT"]).resolve(strict=True)
repo = Path(os.environ["GS_BACKUP_REPO"]).resolve(strict=True)
key = Path(os.environ["GS_BACKUP_PASSWORD_FILE"]).resolve(strict=True)
if mount == Path("/") or not mount.is_mount() or not repo.is_dir() or mount not in repo.parents:
    raise SystemExit("Backup repository must be a directory below the selected mounted medium")
if mount in ROOT.parents or repo == ROOT or ROOT in repo.parents or ROOT in key.parents or mount in key.parents:
    raise SystemExit("Use an external repository and keep its credential separately outside the checkout")
if not key.is_file() or key.stat().st_mode & 0o077:
    raise SystemExit("Repository credential must be a private file on a permissions-aware filesystem")
env = dict(os.environ, GS_BACKUP_REPO=str(repo), GS_BACKUP_PASSWORD_FILE=str(key))
compose = ["docker","compose","-f","compose.yaml","-f","compose.backup.yaml"]
if env.get("GS_RECOVERED_VOLUMES") == "1":
    if not env.get("COMPOSE_PROJECT_NAME"):
        raise SystemExit("Set the promoted project name for recovered volumes")
    compose += ["-f","compose.recovered-volumes.yaml"]
subprocess.run([*compose,"run","--rm","--no-deps","-T","backup",args.action],
               cwd=ROOT, env=env, check=True)
