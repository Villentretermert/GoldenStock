"""Encrypted PostgreSQL + immutable blob snapshots. Run in the isolated ops container."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import uuid

import psycopg2
from psycopg2 import sql


DATA = Path("/data")
SCRATCH = Path("/scratch")
REPO = Path("/repository")
TRANSIENT = {"login_sessions", "worker_heartbeats"}
SUPPORTED_REVISION = "0019"
REFERENCES = """
 SELECT blob_key, sha256 FROM document_versions
 UNION ALL SELECT blob_key, sha256 FROM template_versions
 UNION ALL SELECT clean_key, clean_sha256 FROM template_versions
"""


def checksum(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def blob_path(root, key):
    path = PurePosixPath(key)
    if not key or path.is_absolute() or path.as_posix() != key or ".." in path.parts or "\\" in key:
        raise ValueError("Unsafe blob reference")
    candidate = root / "originals" / path
    if candidate.resolve() != candidate or not candidate.is_file():
        raise ValueError("Referenced blob missing or linked")
    return candidate


def inventory(cursor):
    cursor.execute(REFERENCES)
    files = {}
    for key, expected in cursor:
        if not re.fullmatch("[0-9a-f]{64}", expected) or files.setdefault(key, expected) != expected:
            raise ValueError("Inconsistent blob references")
    return files


def counts(cursor):
    cursor.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
    result = {}
    for (name,) in cursor.fetchall():
        cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier("public", name)))
        result[name] = cursor.fetchone()[0]
    return result


def restic(*args, capture=False):
    # A partial-read exit code (including 3) fails this operation.
    return subprocess.run(["restic", *args], check=True, stdout=subprocess.PIPE if capture else None)


def backup():
    started = time.monotonic()
    with psycopg2.connect("") as conn, conn.cursor() as cursor:
        conn.set_session(isolation_level="REPEATABLE READ", readonly=True)
        cursor.execute("SELECT pg_export_snapshot()")
        point = cursor.fetchone()[0]
        files = inventory(cursor)
        rows = counts(cursor)
        cursor.execute("SELECT version_num FROM alembic_version")
        revision = cursor.fetchone()[0]
        if revision != SUPPORTED_REVISION:
            raise ValueError("This schema requires a matching backup file inventory")
        dump = SCRATCH / "database.dump"
        command = ["pg_dump", "-Fc", "--schema=public", "--no-owner", "--no-acl", "--snapshot", point, "-f", str(dump)]
        for table in TRANSIENT:
            command.append("--exclude-table-data=public." + table)
            rows[table] = 0
        subprocess.run(command, check=True)
    paths = [dump, SCRATCH / "manifest.json"]
    for key, expected in sorted(files.items()):
        path = blob_path(DATA, key)
        if checksum(path) != expected:
            raise ValueError("Original differs from its database checksum")
        paths.append(path)
    originals = DATA / "originals"
    orphans = sum(1 for p in originals.rglob("*") if p.is_file() and p.relative_to(originals).as_posix() not in files)
    manifest = dict(format=1, revision=revision, files=files, rows=rows, dump_sha256=checksum(dump))
    paths[1].write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    listing = SCRATCH / "files.list"
    listing.write_bytes(b"".join(os.fsencode(p) + b"\0" for p in paths))
    run_tag = "run-" + uuid.uuid4().hex
    log = restic("backup", "--json", "--host", "goldenstock", "--tag", run_tag,
                 "--files-from-raw", str(listing), capture=True).stdout
    short_id = next(entry["snapshot_id"] for line in log.splitlines()
                    if (entry := json.loads(line)).get("message_type") == "summary")
    # restic can write a partial snapshot and return exit code 3. Publish only after exit 0.
    restic("tag", "--add", "gs023-v1", short_id, capture=True)
    snapshots = json.loads(restic("snapshots", "--json", "--tag", run_tag, capture=True).stdout)
    if len(snapshots) != 1:
        raise ValueError("Backup receipt is ambiguous")
    print(json.dumps(dict(snapshot=snapshots[0]["id"], revision=revision, verified_blobs=len(files),
                          unreferenced_files=orphans, seconds=round(time.monotonic()-started, 1))))


def restore(snapshot):
    if not re.fullmatch("[0-9a-f]{64}", snapshot):
        raise ValueError("Select an exact full snapshot ID")
    if os.environ.get("PGDATABASE") != "goldenstock_recovery" or any(DATA.iterdir()):
        raise ValueError("Recovery requires an empty dedicated destination")
    entries = json.loads(restic("--no-lock", "snapshots", "--json", snapshot, capture=True).stdout)
    if len(entries) != 1 or "gs023-v1" not in entries[0].get("tags", []):
        raise ValueError("Select a completed GoldenStock snapshot")
    with closing(psycopg2.connect("")) as guard:
        guard.autocommit = True
        with guard.cursor() as cursor:
            cursor.execute("""SELECT current_database(), pg_try_advisory_lock(7423023),
                EXISTS (SELECT 1 FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema')),
                EXISTS (SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace),
                EXISTS (SELECT 1 FROM pg_proc WHERE pronamespace='public'::regnamespace)""")
            if cursor.fetchone() != ("goldenstock_recovery", True, False, False, False):
                raise ValueError("Recovery database is occupied or being restored")
        marker = DATA / ".restore-in-progress"
        with marker.open("x") as claim:
            claim.write(snapshot)
        install_snapshot(snapshot)
        marker.unlink()


def install_snapshot(snapshot):
    started = time.monotonic()
    restic("--no-lock", "restore", snapshot, "--target", str(DATA), "--verify", capture=True)
    metadata = DATA / "scratch"
    restored = DATA / "data"
    manifest = json.loads((metadata / "manifest.json").read_text(encoding="utf-8"))
    dump = metadata / "database.dump"
    if (manifest["format"] != 1 or manifest["revision"] != SUPPORTED_REVISION
            or checksum(dump) != manifest["dump_sha256"]):
        raise ValueError("Invalid backup manifest or database dump")
    for key, expected in manifest["files"].items():
        if checksum(blob_path(restored, key)) != expected:
            raise ValueError("Restored blob checksum mismatch")
    # A new PostgreSQL database already contains the public schema. Restore its contents.
    toc = subprocess.check_output(["pg_restore", "--list", str(dump)])
    selection = SCRATCH / "restore.list"
    selection.write_bytes(b"".join(line for line in toc.splitlines(keepends=True)
                                   if not re.match(rb"^\d+; \d+ \d+ SCHEMA - public ", line)))
    subprocess.run(["pg_restore", "--use-list", str(selection), "--single-transaction", "--exit-on-error", "--no-owner", "--no-acl",
                    "-d", "goldenstock_recovery", str(dump)], check=True)
    with psycopg2.connect("") as conn, conn.cursor() as cursor:
        if counts(cursor) != manifest["rows"] or inventory(cursor) != manifest["files"]:
            raise ValueError("Recovered database does not match manifest")
    if manifest["files"]:
        (restored / "originals").rename(DATA / "originals")
        restored.rmdir()
    dump.unlink()
    (metadata / "manifest.json").unlink()
    metadata.rmdir()
    # Empty volumes originate in the ops image. The web process owns its storage root.
    os.chown(DATA, 10001, 10001)
    print(json.dumps(dict(restored=snapshot, revision=manifest["revision"],
                          verified_blobs=len(manifest["files"]), verified_tables=len(manifest["rows"]),
                          seconds=round(time.monotonic()-started, 1))))


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("init", "backup", "list", "status", "check", "restore"))
    parser.add_argument("snapshot", nargs="?")
    args = parser.parse_args()
    if not REPO.is_mount() or not SCRATCH.is_mount():
        raise SystemExit("Dedicated repository and scratch mounts required")
    if args.action == "init":
        if any(REPO.iterdir()):
            raise SystemExit("Initialize a new, empty repository directory")
        restic("init", "--repository-version", "2")
    repository_id = json.loads(restic("--no-lock", "cat", "config", capture=True).stdout)["id"]
    if args.action == "init":
        print(json.dumps(dict(repository_id=repository_id)))
        return
    if os.environ.get("GS_BACKUP_REPOSITORY_ID") != repository_id:
        raise SystemExit("Repository identity differs from the selected backup medium")
    if args.action == "backup":
        backup()
    elif args.action == "restore":
        restore(args.snapshot or "")
    elif args.action == "check":
        restic("check", "--read-data")
    elif args.action == "list":
        restic("--no-lock", "snapshots", "--json", "--tag", "gs023-v1")
    else:
        snapshots = json.loads(restic("--no-lock", "snapshots", "--json", "--tag", "gs023-v1", capture=True).stdout)
        latest = max((datetime.fromisoformat(s["time"].replace("Z", "+00:00")) for s in snapshots), default=None)
        age = (datetime.now(timezone.utc) - latest).total_seconds()/3600 if latest else None
        print(json.dumps(dict(snapshots=len(snapshots), latest_utc=latest.isoformat() if latest else None,
                              age_hours=round(age,2) if age is not None else None)))
        if age is None or age > 24:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
