"""Read-only database integration and command-line audit acceptance."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tools import audit_gear_equipment as audit
from tracker.content.loader import Content
from tracker.db.models import Base, ContainerScan, ObservedItem, Player, SyncEvent
from tracker.domain.types import Container, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentDefinition

AT = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)
FIXTURE = Path("tests/fixtures/gear_equipment_audit.json")


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "account.sqlite"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add(Player(id=1, username="private-name", display_name="Private", created_at=AT))
        session.flush()
        session.add(
            ContainerScan(
                player_id=1, container=Container.BANK, scanned_at=AT, source=Source.RUNELITE
            )
        )
        session.add(
            ObservedItem(
                player_id=1,
                item_id=1,
                container=Container.BANK,
                quantity=1,
                observed_at=AT,
                source=Source.RUNELITE,
            )
        )
        session.add(
            SyncEvent(
                player_id=1,
                source=Source.RUNELITE,
                received_at=AT,
                accepted=True,
                remote_addr="private-address",
            )
        )
        session.add(
            SyncEvent(
                player_id=1,
                source=Source.RUNELITE,
                received_at=AT,
                accepted=False,
                reason="private-reason",
            )
        )
        session.commit()
    engine.dispose()
    return path


def test_frozen_reader_refuses_writes_and_does_not_change_source(database):
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    with audit.frozen_database(database) as (sessions, identity):
        with sessions() as session:
            assert session.connection().exec_driver_sql("select count(*) from player").scalar() == 1
            with pytest.raises(Exception, match="readonly"):
                session.connection().exec_driver_sql("delete from player")
        assert len(identity) == 64
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_database_audit_has_evidence_without_private_identifiers(database):
    item = EquipmentDefinition(id=1, name="Test head", slot="head", requirements_complete=True)
    result = audit.audit_database(database, 1, AT, Content(), EquipmentCatalog({1: item}))
    assert result["provenance"]["accepted_sync_events"] == 1
    assert result["provenance"]["rejected_sync_events"] == 1
    assert result["provenance"]["source_kind"] == "local_database_snapshot"
    assert result["items"][0]["item_id"] == 1
    serialized = json.dumps(result)
    assert "private-name" not in serialized
    assert "private-address" not in serialized
    assert "private-reason" not in serialized


def test_missing_database_is_not_created(tmp_path):
    missing = tmp_path / "absent.sqlite"
    with pytest.raises(FileNotFoundError), audit.frozen_database(missing):
        pass
    assert not missing.exists()


def test_reader_includes_committed_wal(database):
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("UPDATE player SET members=1")
    connection.commit()
    try:
        with audit.frozen_database(database) as (sessions, _), sessions() as session:
            assert session.connection().exec_driver_sql("select members from player").scalar() == 1
    finally:
        connection.close()


def test_fixture_cli_is_reproducible_and_reports_every_observed_id(tmp_path):
    command = [
        sys.executable,
        "-m",
        "tools.audit_gear_equipment",
        "--fixture",
        str(FIXTURE),
        "--output-dir",
        str(tmp_path),
    ]
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    before = (tmp_path / "audit.json").read_bytes()
    subprocess.run(command, capture_output=True, text=True, check=True)
    assert (tmp_path / "audit.json").read_bytes() == before
    report = json.loads(before)
    assert {r["item_id"] for r in report["items"]} >= {12, 900001, 900002}
    assert len(report["scenarios"]) == 5
    markdown = (tmp_path / "audit.md").read_text(encoding="utf-8")
    assert "900001" in markdown and "900002" in markdown
    assert "not_measured" in markdown
    assert "audit.json" in first.stdout


def test_naive_time_rejected_before_output(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.audit_gear_equipment",
            "--fixture",
            str(FIXTURE),
            "--at",
            "2026-10-19",
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert not list(tmp_path.iterdir())


def test_exact_request_and_fixture_validation(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps(
            {
                "roles": [{"id": "slash", "style": "slash"}],
                "mode": "owned",
                "excluded_item_ids": [12],
            }
        )
    )
    result = audit.audit_fixture(FIXTURE, requests=audit.read_requests(request))
    assert len(result["scenarios"]) == 1
    head = next(r for r in result["items"] if r["item_id"] == 12)
    assert not head["scenario_results"][0]["access_eligible"]
    bad = tmp_path / "bad.json"
    bad.write_text('{"at":"2026-10-19T22:05:44Z","equipment":[],"unexpected":true}')
    with pytest.raises(ValueError):
        audit.audit_fixture(bad)


def test_renderer_escapes_item_text_and_preserves_unknown(tmp_path):
    result = audit.audit_fixture(FIXTURE)
    result["items"][0]["name"] = "A|B <script>\nnext"
    markdown = audit.render_markdown(result)
    assert "A\\|B &lt;script&gt; next" in markdown
    assert "unclassified" in markdown
    assert "Unknown physical item" in markdown
    missing = markdown.split("### 900001 —", 1)[1].split("## Unclassified", 1)[0]
    ownership = next(line for line in missing.splitlines() if "Concrete ownership" in line)
    assert '"status": "owned"' in ownership
    assert "Physical catalog revision: `synthetic`" in markdown


def test_main_fixture_and_exact_request(tmp_path, monkeypatch):
    request = tmp_path / "request.json"
    request.write_text(
        json.dumps([{"roles": [{"id": "slash", "style": "slash"}], "mode": "owned"}])
    )
    output = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit",
            "--fixture",
            str(FIXTURE),
            "--request",
            str(request),
            "--output-dir",
            str(output),
        ],
    )
    audit.main()
    assert len(json.loads((output / "audit.json").read_text())["scenarios"]) == 1


def test_main_database_defaults_time_from_scans(database, tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "load_content", Content)
    monkeypatch.setattr(audit, "load_catalog", lambda _: EquipmentCatalog({}))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "audit",
            "--database",
            str(database),
            "--player-id",
            "1",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    audit.main()
    report = json.loads((tmp_path / "out" / "audit.json").read_text())
    assert report["evaluated_at"] == AT.isoformat()


def test_main_rejects_missing_player_invalid_source_and_input_overwrite(tmp_path, monkeypatch):
    commands = [
        ["--database", "missing.sqlite"],
        ["--database", "missing.sqlite", "--player-id", "1"],
        ["--fixture", str(tmp_path / "audit.json"), "--output-dir", str(tmp_path)],
    ]
    for command in commands:
        monkeypatch.setattr(sys, "argv", ["audit", *command])
        with pytest.raises(SystemExit) as error:
            audit.main()
        assert error.value.code != 0
    assert not list(tmp_path.iterdir())


def test_database_without_observations_needs_time(database):
    connection = sqlite3.connect(database)
    connection.execute("DELETE FROM observed_item")
    connection.execute("DELETE FROM container_scan")
    connection.commit()
    connection.close()
    with pytest.raises(ValueError, match="explicit --at"):
        audit.audit_database(database, 1, None, Content(), EquipmentCatalog({}))


@pytest.mark.parametrize(
    "change,match",
    [
        ({"observations": [{"item_id": 1}, {"item_id": 1}]}, "Duplicate fixture observation"),
        (
            {"equipment": [{"id": 1, "name": "Head", "slot": "head"}] * 2},
            "Duplicate fixture physical",
        ),
        ({"skills": {"attack": 100}}, "Fixture skill levels"),
    ],
)
def test_fixture_rejects_ambiguous_inputs(tmp_path, change, match):
    payload = {**json.loads(FIXTURE.read_text()), **change}
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match=match):
        audit.audit_fixture(path)


def test_empty_exact_request_list_is_rejected(tmp_path):
    path = tmp_path / "requests.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="at least one"):
        audit.read_requests(path)
