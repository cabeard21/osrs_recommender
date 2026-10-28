"""Frozen measurement and comparison utility acceptance."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tools import measure_gear_coverage as measure
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.db.models import Base, Player
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import EquipmentDefinition

AT = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)


@pytest.fixture
def inputs():
    item = EquipmentDefinition(
        id=882, name="Synthetic head", slot="head", requirements_complete=True
    )
    snapshot = AccountSnapshot(
        1,
        "private-test-name",
        skills={
            key: SkillState(60, None, Source.MANUAL, AT)
            for key in ("attack", "strength", "defence", "ranged", "magic", "hitpoints")
        },
        observed_items={
            (882, Container.BANK): ObservedItemFact(882, Container.BANK, 1, "test", AT)
        },
    )
    return snapshot, Content(), EquipmentCatalog({882: item}, "synthetic")


def test_measurement_uses_owned_scenarios_and_reports_determinism(inputs):
    report, result = measure.measure_snapshot(*inputs, {}, AT, repeats=2)
    assert result["snapshot_id"] == inputs[0].fingerprint
    assert len(result["runs"]) == 5
    assert all(row["deterministic"] and len(row["seconds"]) == 2 for row in result["runs"])
    assert all(row["request"]["mode"] == "owned" for row in result["runs"])
    assert result["catalog_definitions"]["882"]["id"] == 882
    assert report["snapshot_id"] == result["snapshot_id"]
    assert "private-test-name" not in json.dumps(result)


def test_comparison_checks_input_identity_and_identifies_exact_metadata_delta(inputs):
    _, before = measure.measure_snapshot(*inputs, {}, AT, repeats=1)
    catalog = EquipmentCatalog({882: inputs[2].items[882].model_copy(update={"name": "Reviewed"})})
    _, after = measure.measure_snapshot(inputs[0], inputs[1], catalog, {}, AT, repeats=1)
    before = {**before, "frozen_database_sha256": "same"}
    after = {**after, "frozen_database_sha256": "same"}
    delta = measure.compare_measurements(before, after)
    assert delta["changed_catalog_ids"] == [882]
    assert delta["unexpected_catalog_ids"] == []
    assert len(delta["runtime"]) == 5
    with pytest.raises(ValueError, match="snapshot_id"):
        measure.compare_measurements(before, {**after, "snapshot_id": "different"})


@pytest.mark.parametrize(
    "field", ["frozen_database_sha256", "evaluated_at", "requests", "prices_sha256"]
)
def test_compare_refuses_nonmatching_frozen_inputs(inputs, field):
    _, result = measure.measure_snapshot(*inputs, {}, AT, repeats=1)
    result = {**result, "frozen_database_sha256": "same"}
    with pytest.raises(ValueError, match=field):
        measure.compare_measurements(result, {**result, field: "different"})


def test_unexpected_nonbatch_change_is_visible(inputs):
    _, before = measure.measure_snapshot(*inputs, {}, AT, repeats=1)
    item = EquipmentDefinition(id=999, name="Unexpected", slot="head")
    _, after = measure.measure_snapshot(
        inputs[0], inputs[1], EquipmentCatalog({999: item}), {}, AT, 1
    )
    assert measure.compare_measurements(before, after)["unexpected_catalog_ids"] == [999]


def test_nondeterministic_optimizer_response_is_rejected(inputs, monkeypatch):
    calls = iter(range(30))
    monkeypatch.setattr(measure, "optimize", lambda *args: {"value": next(calls)})
    with pytest.raises(ValueError, match="nondeterministic"):
        measure.measure_snapshot(*inputs, {}, AT, repeats=1)


@pytest.mark.parametrize("repeats", [0, -1])
def test_invalid_repeat_count_rejected(inputs, repeats):
    with pytest.raises(ValueError, match="repeats"):
        measure.measure_snapshot(*inputs, {}, AT, repeats=repeats)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "source.sqlite"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        session.add(Player(id=1, username="private-name", display_name="Private", created_at=AT))
        session.commit()
    engine.dispose()
    return path


def test_database_measurement_and_cli_preserve_source(database, tmp_path):
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    output = tmp_path / "output"
    command = [
        sys.executable,
        "-m",
        "tools.measure_gear_coverage",
        "--database",
        str(database),
        "--player-id",
        "1",
        "--at",
        AT.isoformat(),
        "--output-dir",
        str(output),
        "--repeats",
        "1",
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == digest
    result = json.loads((output / "measurement.json").read_text())
    assert len(result["frozen_database_sha256"]) == 64
    assert (output / "audit.json").exists() and (output / "audit.md").exists()
    assert "private-name" not in (output / "measurement.json").read_text()
    subprocess.run(
        [
            *command[:-4],
            "--output-dir",
            str(tmp_path / "after"),
            "--repeats",
            "1",
            "--compare",
            str(output / "measurement.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def test_cli_missing_database_not_created(tmp_path):
    missing = tmp_path / "missing.sqlite"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.measure_gear_coverage",
            "--database",
            str(missing),
            "--player-id",
            "1",
            "--at",
            AT.isoformat(),
            "--output-dir",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and not missing.exists()


@pytest.mark.parametrize(
    "arguments", [["--player-id", "0"], ["--at", "2026-10-19"], ["--repeats", "0"]]
)
def test_cli_rejects_invalid_arguments(tmp_path, monkeypatch, arguments):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure",
            "--database",
            str(tmp_path / "source"),
            "--player-id",
            "1",
            "--at",
            AT.isoformat(),
            "--output-dir",
            str(tmp_path / "out"),
            *arguments,
        ],
    )
    with pytest.raises(SystemExit):
        measure.main()


def test_main_writes_and_compares_database_reports(database, tmp_path, monkeypatch):
    # The shared checkout may receive an approved batch between these invocations.
    # Freeze catalog/content as well as the disposable account for this identity test.
    content = measure.load_content()
    catalog = measure.load_catalog(content)
    monkeypatch.setattr(measure, "load_content", lambda: content)
    monkeypatch.setattr(measure, "load_catalog", lambda _: catalog)
    output = tmp_path / "before"
    arguments = [
        "measure",
        "--database",
        str(database),
        "--player-id",
        "1",
        "--at",
        AT.isoformat(),
        "--output-dir",
        str(output),
        "--repeats",
        "1",
    ]
    monkeypatch.setattr(sys, "argv", arguments)
    measure.main()
    before = output / "measurement.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            *arguments[:-4],
            "--output-dir",
            str(tmp_path / "after"),
            "--repeats",
            "1",
            "--compare",
            str(before),
        ],
    )
    measure.main()
    result = json.loads((tmp_path / "after" / "measurement.json").read_text())
    assert result["comparison"]["changed_catalog_ids"] == []
    assert result["comparison"]["unexpected_authored_ids"] == []


def test_compare_refuses_pipeline_drift(inputs):
    _, result = measure.measure_snapshot(*inputs, {}, AT, repeats=1)
    changed = {**result, "provenance": {"source_file_sha256": {"wrong.py": "different"}}}
    with pytest.raises(ValueError, match="pipeline source"):
        measure.compare_measurements(result, changed)
    changed = {
        **result,
        "provenance": {**result["provenance"], "measurement_source_sha256": "changed"},
    }
    with pytest.raises(ValueError, match="measurement source"):
        measure.compare_measurements(result, changed)


def test_comparison_requires_explicit_identity_and_structure(inputs):
    _, result = measure.measure_snapshot(*inputs, {}, AT, repeats=1)
    with pytest.raises(ValueError, match="objects"):
        measure.compare_measurements([], result)
    with pytest.raises(ValueError, match="field missing"):
        measure.compare_measurements({}, {})
    with pytest.raises(ValueError, match="structure"):
        measure.compare_measurements(result, {**result, "runs": None})
    with pytest.raises(ValueError, match="provenance"):
        measure.compare_measurements(result, {**result, "provenance": {}})


def test_programmatic_validation(inputs, tmp_path):
    with pytest.raises(ValueError, match="timezone"):
        measure.measure_snapshot(*inputs, {}, AT.replace(tzinfo=None), repeats=1)
    with pytest.raises(ValueError, match="player_id"):
        measure.measure_database(tmp_path / "absent", 0, AT)


@pytest.mark.parametrize(
    "exception", [ValueError("invalid data"), measure.SQLAlchemyError("private sql")]
)
def test_main_reports_source_failure_without_sql_details(tmp_path, monkeypatch, capsys, exception):
    def broken(*args):
        raise exception

    monkeypatch.setattr(measure, "measure_database", broken)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure",
            "--database",
            "unused",
            "--player-id",
            "1",
            "--at",
            AT.isoformat(),
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )
    with pytest.raises(SystemExit):
        measure.main()
    assert "private sql" not in capsys.readouterr().err
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "out").exists()


def test_cli_refuses_input_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "measure",
            "--database",
            str(tmp_path / "measurement.json"),
            "--player-id",
            "1",
            "--at",
            AT.isoformat(),
            "--output-dir",
            str(tmp_path),
        ],
    )
    with pytest.raises(SystemExit):
        measure.main()
