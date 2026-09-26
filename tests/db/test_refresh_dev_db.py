"""Safety checks for the developer's production-to-local database refresh."""

from __future__ import annotations

import importlib.util
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "refresh_dev_db", Path(__file__).resolve().parents[2] / "scripts" / "refresh_dev_db.py"
)
assert SPEC and SPEC.loader
refresh = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refresh)


def database(path: Path, *, valid: bool = True) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE player (id INTEGER PRIMARY KEY, username TEXT)")
        connection.execute("INSERT INTO player VALUES (1, 'old')")
        if valid:
            for table in refresh.REQUIRED_TABLES - {"player"}:
                connection.execute(f'CREATE TABLE "{table}" (id INTEGER)')
        connection.commit()


def username(path: Path) -> str:
    with closing(sqlite3.connect(path)) as connection:
        return connection.execute("SELECT username FROM player").fetchone()[0]


def test_validate_rejects_missing_corrupt_and_wrong_schema(tmp_path: Path) -> None:
    with pytest.raises(refresh.RefreshError):
        refresh.validate(tmp_path / "missing.sqlite")
    corrupt = tmp_path / "corrupt.sqlite"
    corrupt.write_bytes(b"incomplete download")
    with pytest.raises(refresh.RefreshError):
        refresh.validate(corrupt)
    database(tmp_path / "wrong.sqlite", valid=False)
    with pytest.raises(refresh.RefreshError):
        refresh.validate(tmp_path / "wrong.sqlite")


def test_failure_before_install_preserves_existing_database(tmp_path: Path) -> None:
    destination = tmp_path / "tracker.db"
    database(destination)
    corrupt = tmp_path / "download.sqlite"
    corrupt.write_bytes(b"bad")
    with pytest.raises(refresh.RefreshError):
        refresh.install(corrupt, destination, tmp_path / "backups", "20260925-154500")
    assert username(destination) == "old"
    assert not (tmp_path / "backups").exists()


def test_install_preserves_backup_and_full_database(tmp_path: Path) -> None:
    destination = tmp_path / "tracker.db"
    staged = tmp_path / "staged.sqlite"
    database(destination)
    database(staged)
    with closing(sqlite3.connect(staged)) as connection:
        connection.execute("UPDATE player SET username='new'")
        connection.commit()
    backup = refresh.install(staged, destination, tmp_path / "backups", "20260925-154500")
    assert username(destination) == "new"
    assert username(backup) == "old"
    assert not staged.exists()


def test_backup_failure_preserves_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "tracker.db"
    staged = tmp_path / "staged.sqlite"
    database(destination)
    database(staged)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("backup failed")

    monkeypatch.setattr(refresh, "backup_database", fail)
    with pytest.raises(OSError, match="backup failed"):
        refresh.install(staged, destination, tmp_path / "backups", "20260925-154500")
    assert username(destination) == "old"


def test_same_source_and_destination_rejected(tmp_path: Path) -> None:
    database(tmp_path / "tracker.db")
    with pytest.raises(refresh.RefreshError, match="same file"):
        refresh.install(tmp_path / "tracker.db", tmp_path / "tracker.db", tmp_path / "backups", "x")


def test_ssh_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        refresh.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 255, "", "connection refused"),
    )
    with pytest.raises(refresh.RefreshError, match="connection refused"):
        refresh.ssh("pi", "docker compose ps")


@pytest.mark.parametrize("target", ["pi", "pi.local", "pi@pi.local", "user_name@host-1.local"])
def test_ssh_target_accepts_alias_and_user_host(target: str) -> None:
    refresh.validate_ssh_target(target)


@pytest.mark.parametrize(
    "target", ["-bad", "pi@-host", "pi@@host", "pi@", "pi host", "pi;echo bad", "pi@host/path"]
)
def test_ssh_target_rejects_option_and_shell_syntax(target: str) -> None:
    with pytest.raises(refresh.RefreshError, match="SSH alias"):
        refresh.validate_ssh_target(target)


def test_ssh_preserves_user_host_and_default_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(refresh.subprocess, "run", run)
    refresh.ssh("pi@pi.local", "docker compose ps")
    assert calls[0][0] == "ssh"
    assert calls[0][-2] == "pi@pi.local"
    assert "BatchMode=yes" not in calls[0]


def test_remote_snapshot_failure_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        refresh,
        "ssh",
        lambda *args, **kwargs: (_ for _ in ()).throw(refresh.RefreshError("snapshot failed")),
    )
    with pytest.raises(refresh.RefreshError, match="snapshot failed"):
        refresh.remote_helper("pi", "snapshot", "a" * 32)


def test_migration_failure_preserves_existing_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "tracker.db"
    stage = tmp_path / "stage.sqlite"
    database(destination)
    database(stage)
    monkeypatch.setattr(
        refresh.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1),
    )
    with pytest.raises(refresh.RefreshError, match="migration failed"):
        refresh.migrate(stage, tmp_path / "python.exe")
    assert username(destination) == "old"


def test_download_rejects_unexpected_remote_path(tmp_path: Path) -> None:
    with pytest.raises(refresh.RefreshError, match="Unexpected remote snapshot path"):
        refresh.download("pi", "/data/tracker.db", tmp_path / "copy.sqlite")
    assert not (tmp_path / "copy.sqlite").exists()


def test_transfer_failure_does_not_touch_dev_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "tracker.db"
    database(destination)
    monkeypatch.setattr(
        refresh.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 1, stderr=b"transfer failed"),
    )
    with pytest.raises(refresh.RefreshError, match="transfer failed"):
        refresh.download(
            "pi", "/data/backups/dev-refresh-" + "a" * 32 + ".sqlite", tmp_path / "stage.sqlite"
        )
    assert username(destination) == "old"


def test_missing_destination_directory_is_rejected(tmp_path: Path) -> None:
    stage = tmp_path / "stage.sqlite"
    database(stage)
    with pytest.raises(refresh.RefreshError, match="directory does not exist"):
        refresh.install(stage, tmp_path / "missing" / "tracker.db", tmp_path / "backups", "x")
    assert stage.exists()
