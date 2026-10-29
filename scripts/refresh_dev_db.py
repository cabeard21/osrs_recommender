"""One-way, online production SQLite snapshot to a local development database.

The remote program uses only Python's standard library and runs inside the existing
application container. It never opens the production database for writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

REPO = Path(__file__).resolve().parents[1]
REMOTE_STACK = "/opt/stacks/osrs-recommender"
SERVICE = "osrs-recommender"
REMOTE_DB = "/data/tracker.db"
SSH_TARGET = re.compile(r"(?:[A-Za-z0-9_][A-Za-z0-9_.-]*@)?[A-Za-z0-9_][A-Za-z0-9_.-]*")
REQUIRED_TABLES = {
    "player",
    "skill_snapshot",
    "quest_state",
    "observed_item",
    "container_scan",
    "alembic_version",
}


class RefreshError(RuntimeError):
    """An expected safety or operation failure."""


def validate_ssh_target(target: str) -> None:
    if not SSH_TARGET.fullmatch(target):
        raise RefreshError("Production host must be an SSH alias, hostname, or user@host")


def validate(path: Path) -> None:
    if not path.is_file() or path.stat().st_size < 100:
        raise RefreshError(f"Missing or incomplete SQLite database: {path}")
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            result = db.execute("PRAGMA quick_check").fetchone()
            if result != ("ok",):
                raise RefreshError(f"SQLite quick_check failed for {path}: {result}")
            tables = {
                row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            missing = REQUIRED_TABLES - tables
            if missing:
                raise RefreshError(
                    f"Missing account tables in {path}: {', '.join(sorted(missing))}"
                )
            if db.execute("SELECT id, username FROM player LIMIT 1").fetchone() is None:
                raise RefreshError(f"No account rows in {path}")
    except sqlite3.DatabaseError as exc:
        raise RefreshError(f"Invalid SQLite database {path}: {exc}") from exc


def backup_database(source: Path, target: Path) -> None:
    # An online backup includes committed WAL transactions and produces one self-contained file.
    with (
        closing(sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.backup(dst)


def compact_stage(stage: Path) -> None:
    """Flatten migration WAL writes into a single file before installing the copy."""
    compact = stage.with_name(stage.name + ".compact")
    try:
        backup_database(stage, compact)
        validate(compact)
        compact.replace(stage)
    finally:
        compact.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(stage) + suffix).unlink(missing_ok=True)


def install(staged: Path, destination: Path, backup_dir: Path, stamp: str) -> Path | None:
    if staged.resolve() == destination.resolve():
        raise RefreshError("Source and destination are the same file")
    if not destination.parent.is_dir():
        raise RefreshError(f"Development database directory does not exist: {destination.parent}")
    validate(staged)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"dev-before-refresh-{stamp}.sqlite" if destination.exists() else None
    if backup and backup.exists():
        raise RefreshError(f"Backup already exists: {backup}")
    if backup:
        backup_database(destination, backup)
        validate(backup)
    # Keep the original physical files as well, since an open SQLite WAL database
    # cannot be replaced safely with old sidecars left at the destination.
    originals = [
        p
        for p in (destination, Path(str(destination) + "-wal"), Path(str(destination) + "-shm"))
        if p.exists()
    ]
    moved: list[tuple[Path, Path]] = []
    try:
        for original in originals:
            retained = backup_dir / f"dev-before-refresh-{stamp}.original-{original.name}"
            if retained.exists():
                raise RefreshError(f"Recovery file already exists: {retained}")
            original.replace(retained)
            moved.append((original, retained))
        staged.replace(destination)
    except Exception:
        for original, retained in reversed(moved):
            retained.replace(original)
        raise
    return backup


REMOTE_PROGRAM = r"""import hashlib, os, pathlib, sqlite3, sys
action, ident = sys.argv[1:3]
assert len(ident) == 32 and all(c in '0123456789abcdef' for c in ident)
assert os.environ.get('TRACKER_DATABASE_URL') == 'sqlite:////data/tracker.db', (
    'unexpected production DB URL'
)
target = pathlib.Path('/data/backups') / ('dev-refresh-' + ident + '.sqlite')
if action == 'snapshot':
    source = pathlib.Path('/data/tracker.db')
    assert source.is_file(), 'production database missing'
    target.parent.mkdir(mode=0o700, exist_ok=True)
    assert not target.exists(), 'snapshot name collision'
    try:
        src = sqlite3.connect('file:/data/tracker.db?mode=ro', uri=True)
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
        target.chmod(0o600)
        check = sqlite3.connect('file:' + str(target) + '?mode=ro', uri=True)
        try:
            assert check.execute('PRAGMA quick_check').fetchone() == ('ok',), (
                'snapshot integrity failed'
            )
            players = check.execute(
                "SELECT count(*) FROM sqlite_master WHERE name='player'"
            ).fetchone()[0]
            assert players == 1, 'player table missing'
        finally:
            check.close()
        with target.open('rb') as snapshot_file:
            digest = hashlib.file_digest(snapshot_file, 'sha256').hexdigest()
        print(str(target) + ' ' + str(target.stat().st_size) + ' ' + digest)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
elif action == 'cleanup':
    target.unlink(missing_ok=True)
else:
    raise ValueError('unknown action')
"""


def remote_command(command: str) -> str:
    stack = shlex.quote(REMOTE_STACK)
    return f'cd {stack} && test "$(pwd -P)" = {stack} && {command}'


def ssh(
    host: str, command: str, *, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", host, remote_command(command)],
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RefreshError(
            f"SSH/production command failed ({result.returncode}): {result.stderr.strip()}"
        )
    return result


def production_preflight(host: str) -> None:
    result = ssh(host, "docker compose config --format json")
    try:
        service = json.loads(result.stdout)["services"][SERVICE]
        env = service["environment"]
        volumes = service["volumes"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RefreshError("Could not verify the production Compose service") from exc
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    if env.get("TRACKER_DATABASE_URL") != "sqlite:////data/tracker.db":
        raise RefreshError("Unexpected production database URL in Compose")
    if not any(
        v.get("target") == "/data"
        and Path(v.get("source", "")).as_posix() == f"{REMOTE_STACK}/data"
        for v in volumes
        if isinstance(v, dict)
    ):
        raise RefreshError("Unexpected production /data volume in Compose")
    running = ssh(host, "docker compose ps --status running --services").stdout.splitlines()
    if SERVICE not in running:
        raise RefreshError(f"Production service is not running: {SERVICE}")


def remote_helper(host: str, action: str, ident: str) -> str:
    command = f"docker compose exec -T {SERVICE} python - {action} {ident}"
    return ssh(host, command, input_text=REMOTE_PROGRAM).stdout.strip()


def download(host: str, remote_path: str, target: Path) -> None:
    if not re.fullmatch(r"/data/backups/dev-refresh-[0-9a-f]{32}\.sqlite", remote_path):
        raise RefreshError("Unexpected remote snapshot path")
    command = remote_command(f"docker compose exec -T {SERVICE} cat {remote_path}")
    with target.open("xb") as output:
        process = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", host, command],
            stdout=output,
            stderr=subprocess.PIPE,
            check=False,
        )
    if process.returncode:
        raise RefreshError(
            f"Snapshot download failed: {process.stderr.decode(errors='replace').strip()}"
        )


def local_destination() -> Path:
    from tracker.config.settings import load_settings

    url = make_url(load_settings().database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise RefreshError("Development configuration must select a file-backed SQLite database")
    destination = (REPO / url.database).resolve()
    if not destination.is_relative_to(REPO):
        raise RefreshError("Development database must be inside this repository")
    return destination


def migrate(staged: Path, python: Path) -> None:
    environment = os.environ.copy()
    environment["TRACKER_DATABASE_URL"] = f"sqlite:///{staged.as_posix()}"
    result = subprocess.run(
        [str(python), "-m", "alembic", "upgrade", "head"], cwd=REPO, env=environment
    )
    if result.returncode:
        raise RefreshError("Local staged-copy migration failed; existing dev DB is unchanged")


def development_python() -> Path:
    relative = ".venv/Scripts/python.exe" if sys.platform == "win32" else ".venv/bin/python"
    python = REPO / relative
    if not python.is_file():
        raise RefreshError(f"Development virtual environment missing: {python}")
    return python


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production-host", default="pi")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-migrations", action="store_true")
    args = parser.parse_args()
    validate_ssh_target(args.production_host)
    destination = local_destination()
    if not destination.parent.is_dir():
        raise RefreshError(f"Development database directory does not exist: {destination.parent}")
    if destination == Path(REMOTE_DB):
        raise RefreshError("Production and development database resolve to the same path")
    python = development_python()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = REPO / "backups"
    print("[1/6] Checking production connection and Compose identity...", flush=True)
    production_preflight(args.production_host)
    print(f"Production: {args.production_host}:{REMOTE_STACK} -> {REMOTE_DB}")
    print(f"Development: {destination}")
    print(f"Previous dev backup: {backup_dir / f'dev-before-refresh-{stamp}.sqlite'}")
    print(f"Migration: {python} -m alembic upgrade head (staged local copy)")
    if args.dry_run:
        print("Dry run complete; no snapshot or local files changed.")
        return 0
    ident = uuid.uuid4().hex
    remote_path = f"/data/backups/dev-refresh-{ident}.sqlite"
    stage: Path | None = None
    created = False
    try:
        print("[2/6] Creating online production snapshot...", flush=True)
        created = True  # Also clean up if the remote snapshot succeeds but its reply is lost.
        line = remote_helper(args.production_host, "snapshot", ident)
        fields = line.split()
        if (
            len(fields) != 3
            or fields[0] != remote_path
            or not fields[1].isdigit()
            or not re.fullmatch(r"[0-9a-f]{64}", fields[2])
        ):
            raise RefreshError("Unexpected production snapshot result")
        with tempfile.NamedTemporaryFile(
            prefix="dev-refresh-", suffix=".sqlite", dir=destination.parent, delete=False
        ) as temp:
            stage = Path(temp.name)
        stage.unlink()
        print("[3/6] Downloading and validating snapshot...", flush=True)
        download(args.production_host, remote_path, stage)
        with stage.open("rb") as downloaded:
            digest = hashlib.file_digest(downloaded, "sha256").hexdigest()
        if stage.stat().st_size != int(fields[1]) or digest != fields[2]:
            raise RefreshError("Downloaded snapshot size or SHA-256 does not match production")
        validate(stage)
        if not args.skip_migrations:
            print("[4/6] Migrating staged development copy...", flush=True)
            migrate(stage, python)
            validate(stage)
        compact_stage(stage)
        print("[5/6] Backing up existing dev database and installing copy...", flush=True)
        backup = install(stage, destination, backup_dir, stamp)
        stage = None
        print(f"Previous dev backup: {backup or 'none'}", flush=True)
        print("[6/6] Running final sanity checks...", flush=True)
        validate(destination)
        print(f"Development database refreshed successfully. Previous copy: {backup or 'none'}")
        return 0
    finally:
        if stage and stage.exists():
            stage.unlink()
        if stage:
            for suffix in ("-wal", "-shm"):
                Path(str(stage) + suffix).unlink(missing_ok=True)
        if created:
            try:
                remote_helper(args.production_host, "cleanup", ident)
            except Exception as exc:
                print(
                    f"WARNING: remote snapshot cleanup failed: {remote_path}: {exc}",
                    file=sys.stderr,
                )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RefreshError, OSError, sqlite3.Error) as exc:
        print(f"Refresh failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
