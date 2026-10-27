"""Create local credentials once and optionally launch the Compose foundation."""
import argparse
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def write_env(root: Path) -> bool:
    path = root / ".env"
    # Exclusive creation never overwrites a user's existing credentials.
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nGS_WEB_PORT=8080\n")
    except FileExistsError:
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--up", action="store_true")
    parser.add_argument("--ai", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    args = parser.parse_args()
    write_env(ROOT)
    print("Local configuration ready. Credentials were not printed.")
    if args.up:
        if not shutil.which("docker"):
            if sys.platform == "win32" and shutil.which("wsl"):
                raise SystemExit("Docker is available only inside WSL? Run: wsl -d Ubuntu -- python3 scripts/bootstrap.py --up")
            raise SystemExit("Docker is not available. Install/start Docker Desktop with WSL2 and retry.")
        command = ["docker", "compose", "-f", "compose.yaml"]
        if args.gpu:
            command += ["-f", "compose.gpu.yaml"]
        if args.ai or args.gpu:
            command += ["--profile", "ai"]
        subprocess.run(command + ["up", "--build", "-d", "--wait"], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
