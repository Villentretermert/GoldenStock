"""Exercise production backup and recovery commands on two disposable Compose projects (Linux/WSL)."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="goldenstock-drill-") as directory:
        staging = Path(directory)
        repo = staging / "repository"
        repo.mkdir(mode=0o700)
        key = staging / "password"
        key.write_text(secrets.token_urlsafe(40))
        key.chmod(0o600)
        tls = staging / "tls"
        tls.mkdir()
        subprocess.run(["openssl","req","-x509","-newkey","rsa:2048","-nodes","-days","1",
                        "-subj","/CN=recovered-web","-addext","subjectAltName=DNS:recovered-web",
                        "-keyout",str(tls/"key.pem"),"-out",str(tls/"cert.pem")],check=True,stderr=subprocess.DEVNULL)
        # Disposable fixture under a private temporary directory, mounted only in the QA web service.
        (tls/"key.pem").chmod(0o444)
        env = dict(os.environ, GS_BACKUP_REPO=str(repo), GS_BACKUP_PASSWORD_FILE=str(key),
                   GS_BACKUP_RUN_AS=f"{os.getuid()}:{os.getgid()}", GS_DRILL_TLS=str(tls),
                   GS_RECOVERY_DB_PASSWORD=secrets.token_hex(24), POSTGRES_PASSWORD=secrets.token_hex(24),
                   GS_RUNTIME_PASSWORD=secrets.token_hex(32), GS_QA_PASSWORD=secrets.token_urlsafe(24), GS_SEC_CONTACT="")
        suffix = secrets.token_hex(8)
        def project(prefix, files):
            cmd = ["docker","compose","--env-file","/dev/null","-p",prefix+suffix]
            for file in files:
                cmd += ["-f",str(ROOT/file)]
            return cmd
        source = project("gsdrillsrc",["compose.yaml","compose.backup.yaml"])
        target = project("gsdrilldst",["ops/compose.recovery.yaml","ops/compose.drill-tls.yaml"])

        def run(base, *args, stdin=None, capture=False, must_pass=True):
            result = subprocess.run([*base,*args], cwd=ROOT, env=env, input=stdin, text=True,
                                    stdout=subprocess.PIPE if capture else None, check=must_pass)
            return result
        try:
            run(source,"up","-d","--wait","db")
            run(source,"run","--rm","--no-deps","-T","web","python","-m","alembic","upgrade","head")
            data = run(source,"run","--rm","--no-deps","-T","-e","GS_QA_PASSWORD","web","python","-",
                       stdin=(ROOT/"scripts/drill_fixture.py").read_text(),capture=True)
            receipt = json.loads(data.stdout)
            initialized = run(source,"run","--rm","--no-deps","-T","backup","init",capture=True)
            env["GS_BACKUP_REPOSITORY_ID"] = json.loads(initialized.stdout.strip().splitlines()[-1])["repository_id"]
            result = run(source,"run","--rm","--no-deps","-T","backup","backup",capture=True)
            saved = json.loads(result.stdout.strip().splitlines()[-1])
            assert saved["verified_blobs"] == 6
            print(json.dumps(saved), flush=True)
            run(source,"run","--rm","--no-deps","-T","backup","status")
            run(source,"run","--rm","--no-deps","-T","backup","check")
            # Simulate damaged source media after the good snapshot. Never publish the bad backup.
            damage = """from pathlib import Path
files = [p for p in Path('/app/data/originals').rglob('*') if p.is_file()]
assert len(files) == 6
files[0].write_bytes(b'synthetic damage')
"""
            run(source,"run","--rm","--no-deps","-T","web","python","-c",damage)
            failed = run(source,"run","--rm","--no-deps","-T","backup","backup",must_pass=False)
            if not failed.returncode:
                raise RuntimeError("Damaged source file accepted")
            listing = run(source,"run","--rm","--no-deps","-T","backup","list",capture=True)
            assert [s["id"] for s in json.loads(listing.stdout)] == [saved["snapshot"]]
            run(target,"up","-d","--wait","recovery-db")
            run(target,"run","--rm","-T","restore","restore",saved["snapshot"])
            # A second restore must refuse to replace the recovered database/files.
            refused = run(target,"run","--rm","-T","restore","restore",saved["snapshot"],must_pass=False)
            if refused.returncode == 0:
                raise RuntimeError("Nonempty recovery target accepted a second restore")
            env["GS_DATABASE_URL"] = ("postgresql+psycopg://goldenstock:"+env["GS_RECOVERY_DB_PASSWORD"]+
                                      "@recovery-db/goldenstock_recovery")
            run(target,"run","--rm","--no-deps","-T","-e","GS_DATABASE_URL","-e","GS_RUNTIME_PASSWORD",
                "recovered-web","python","-",stdin=(ROOT/"scripts/provision_runtime.py").read_text())
            run(target,"up","-d","recovered-web","drill-worker")
            run(target,"run","--rm","--no-deps","-T","probe","python","-c",
                (ROOT/"scripts/drill_probe.py").read_text(),stdin=json.dumps(receipt))
            metrics = run(target,"exec","-T","recovered-web","python","-",
                          stdin=(ROOT/"scripts/pilot_status.py").read_text(),capture=True)
            posture = json.loads(metrics.stdout)
            assert posture["runtime_role"] == "goldenstock_runtime" and not posture["superuser"] and not posture["bypass_rls"]
            assert posture["secure_cookie"] and posture["core"]["status"] == "ready"
            print("Recovery rehearsal PASS. PostgreSQL, original PDF, template and accepted knowledge verified.")
        finally:
            # Both names are generated here. Operator deployments never use these projects.
            for stack in (target, source):
                run(stack,"--profile","*","down","--volumes","--remove-orphans")


if __name__ == "__main__":
    main()
