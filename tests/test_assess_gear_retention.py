"""Acceptance and reporting contracts for the isolated assessment command."""

import hashlib
import json
import subprocess
import sys

import pytest

from tools.assess_gear_retention import account_cases, compare, main, measure, semantic_response


def response(score=1):
    solution = {
        "score": score,
        "loadouts": {
            "m": {"equipment": {"weapon": 1}, "performance": {"dps": score, "max_hit": 8}}
        },
        "purchase_cost_gp": 0,
        "carried_item_ids": [1],
        "maximum_actions": 0,
        "max_gear_inventory_slots": 0,
    }
    return {
        "selected_solution": solution,
        "unrestricted": solution,
        "curve": [{"swap_limit": 0, "solution": solution}],
        "search": {"explored_nodes": 1},
        "research": {"evaluations": 2},
    }


def test_measure_detects_nondeterminism():
    calls = iter([response(1), response(2)])
    with pytest.raises(ValueError, match="nondeterministic"):
        measure(None, "baseline", 1, lambda *_: next(calls))


@pytest.mark.parametrize("strategy", ["targeted", "refinement"])
def test_measure_separates_refinement_timing_from_semantic_determinism(strategy):
    def timed(duration):
        result = response()
        if strategy == "targeted":
            result["search"]["targeted_head_refinement"] = {
                "duration_seconds": duration,
                "assignment_attempts": 2,
            }
        else:
            result["research"]["refinement_duration_seconds"] = duration
        return result

    calls = iter([timed(0.1), timed(0.2), timed(0.3)])
    measured = measure(None, strategy, 2, lambda *_: next(calls))
    assert measured["refinement_seconds"] == [0.2, 0.3]
    assert measured["median_refinement_seconds"] == 0.25
    assert measured["min_refinement_seconds"] == 0.2
    assert measured["max_refinement_seconds"] == 0.3
    assert measured["response"] == timed(0.1)


def test_measure_still_checks_semantic_diagnostics_and_unknown_duration_fields():
    for path, key in [("research", "assignment_attempts"), ("search", "other_duration_seconds")]:
        first, second = response(), response()
        first[path][key], second[path][key] = 1, 2
        calls = iter([first, second])
        with pytest.raises(ValueError, match="nondeterministic"):
            measure(None, "targeted", 1, lambda *_, calls=calls: next(calls))


def test_semantic_normalization_keeps_source_and_all_other_facts():
    original = response()
    original["search"]["targeted_head_refinement"] = {
        "duration_seconds": 0.1,
        "assignment_attempts": 9,
        "baseline": {"duration_seconds": 8},
    }
    original["research"]["refinement_duration_seconds"] = 0.1
    normalized = semantic_response(original)
    assert original["research"]["refinement_duration_seconds"] == 0.1
    assert original["search"]["targeted_head_refinement"]["duration_seconds"] == 0.1
    assert normalized["search"]["targeted_head_refinement"] == {
        "assignment_attempts": 9,
        "baseline": {"duration_seconds": 8},
    }


def test_measure_and_oracle_comparison():
    result = measure(None, "baseline", 2, lambda *_: response())
    assert len(result["seconds"]) == 2
    assert result["refinement_seconds"] == [0.0, 0.0]
    oracle = {"curve": [{"swap_limit": 0, "score": 1}], "unrestricted": {"score": 1}}
    assert compare(result["response"], oracle)["score_gaps"] == [0]
    assert compare(response(0.5), oracle)["score_gaps"] == [0.5]
    assert compare(response(), {"curve": [{"score": None}], "unrestricted": None})[
        "score_gaps"
    ] == [None]


def test_cli_rejects_invalid_repeats_and_existing_output(tmp_path):
    with pytest.raises(SystemExit):
        main(["--tiny", "--repeats", "0", "--output", str(tmp_path / "bad.json")])
    existing = tmp_path / "existing.json"
    existing.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        main(["--tiny", "--output", str(existing)])
    assert existing.read_text() == "keep"


@pytest.mark.parametrize("strategy", ["baseline", "targeted", "refinement"])
def test_cli_tiny_subprocess(tmp_path, strategy):
    target = tmp_path / "result.json"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.assess_gear_retention",
            "--tiny",
            "--case",
            "breakpoint",
            "--strategy",
            strategy,
            "--repeats",
            "1",
            "--output",
            str(target),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    result = json.loads(target.read_text(encoding="utf-8"))
    assert result["cases"][0]["oracle"]["curve"][0]["max_hits"]
    measured = result["cases"][0]["runs"][strategy]
    gap = measured["comparison"]["score_gaps"][0]
    assert gap > 0 if strategy == "baseline" else gap == 0
    assert len(measured["refinement_seconds"]) == 1
    assert measured["median_refinement_seconds"] >= 0


def test_database_capture_is_read_only_and_omits_private_name(tmp_path):
    from datetime import UTC, datetime

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from tracker.db.models import Base, Player

    path = tmp_path / "input.sqlite"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    Base.metadata.create_all(engine)
    at = datetime(2026, 10, 19, 22, 5, 44, tzinfo=UTC)
    with sessionmaker(bind=engine)() as session:
        session.add(Player(id=1, username="private-name", display_name="Private", created_at=at))
        session.commit()
    engine.dispose()
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    cases, identity = account_cases(path, 1, at)
    assert len(cases) == 5
    assert identity["source_unchanged_after_capture"]
    assert identity["source_hashes"][str(path)] == before
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    assert "private-name" not in json.dumps(identity)
    with pytest.raises(ValueError, match="positive player"):
        account_cases(path, 0, at)


def test_main_rejects_unknown_case_and_missing_database(tmp_path):
    with pytest.raises(SystemExit):
        main(["--tiny", "--case", "missing", "--output", str(tmp_path / "unused.json")])
    with pytest.raises(FileNotFoundError):
        account_cases(
            tmp_path / "missing.sqlite",
            1,
            __import__("datetime").datetime.fromisoformat("2026-10-19T22:05:44+00:00"),
        )


def test_repeats_must_be_positive():
    with pytest.raises(ValueError, match="repeats"):
        measure(None, "baseline", 0)


def test_main_writes_reproducible_tiny_evidence(tmp_path):
    output = tmp_path / "tiny.json"
    assert (
        main(
            [
                "--tiny",
                "--case",
                "breakpoint",
                "--strategy",
                "baseline",
                "--repeats",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    evidence = json.loads(output.read_text())
    assert evidence["source_sha256"]["tracker/gear/optimizer.py"]
    assert evidence["cases"][0]["runs"]["baseline"]["comparison"]["feasibility_matches"] == [True]


def test_main_account_path_and_drift_rejection(tmp_path, monkeypatch):
    from tools import assess_gear_retention as module
    from tools.gear_retention_oracle import tiny_cases

    monkeypatch.setattr(module, "account_cases", lambda *_: ([tiny_cases()[0]], {}))
    output = tmp_path / "account.json"
    assert (
        main(
            [
                "--database",
                "unused.sqlite",
                "--strategy",
                "baseline",
                "--repeats",
                "1",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["cases"][0]["oracle"] is None
    hashes = iter([{"before": "a"}, {"after": "b"}])
    monkeypatch.setattr(module, "provenance", lambda: next(hashes))
    with pytest.raises(ValueError, match="changed during"):
        main(
            [
                "--tiny",
                "--case",
                "breakpoint",
                "--strategy",
                "baseline",
                "--repeats",
                "1",
                "--output",
                str(tmp_path / "drift.json"),
            ]
        )
