"""Offline profiling preserves requests and compares complete frontier solutions."""

import json
from dataclasses import replace

import pytest

from tools.gear_search_quality_fixture import load_case
from tools.profile_gear_frontiers import load_profile_case, profile_case, solution_digest


def write_dump(tmp_path, case):
    path = tmp_path / "dump.json"
    path.write_text(
        json.dumps(
            {
                "result": {
                    "live": {
                        "evaluated_at": case.at.isoformat(),
                        "scenario": {
                            **case.request.model_dump(mode="json"),
                            "optimization_mode": "fast",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def test_fixture_scenario_override_is_explicit_and_preserves_search_filters(tmp_path):
    original = load_case("melee_1m")
    request = original.request.model_copy(update={"secondary_priority": "balanced_defence"})
    case, provenance = load_profile_case(
        write_dump(tmp_path, replace(original, request=request)),
        fixture="melee_1m",
        discipline="ranged",
        potions=("divine_ranging",),
    )
    assert case.snapshot is not None
    assert case.snapshot.fingerprint == original.snapshot.fingerprint
    assert case.request.secondary_priority == "balanced_defence"
    assert case.request.budget_gp == original.request.budget_gp
    assert case.request.roles[0].style == "ranged"
    assert case.request.roles[0].stance == "rapid"
    assert case.request.potions.selected_ids == ("divine_ranging",)
    assert provenance["account_source"] == "fixture:melee_1m"
    assert provenance["original_account_replayed"] is False


def test_dump_cannot_supply_missing_account_facts(tmp_path):
    path = write_dump(tmp_path, load_case("melee_1m"))
    with pytest.raises(ValueError, match="snapshot or an explicit fixture"):
        load_profile_case(path)


def test_solution_digest_ignores_diagnostics_but_preserves_every_tradeoff():
    result = {
        "selected_solution": {"score": 3},
        "curve": [],
        "unrestricted": None,
        "secondary_frontiers": [{"points": [{"solution": {"score": 2}}]}],
        "running_cost_frontiers": [],
        "search": {"timings_seconds": {"total": 1}},
    }
    changed_timing = {**result, "search": {"timings_seconds": {"total": 100}}}
    assert solution_digest(result) == solution_digest(changed_timing)
    changed_point = {**result, "secondary_frontiers": [{"points": [{"solution": {"score": 1}}]}]}
    assert solution_digest(result) != solution_digest(changed_point)


@pytest.mark.parametrize("mismatch", [False, True])
def test_snapshot_input_validates_fingerprint_and_records_catalog(tmp_path, monkeypatch, mismatch):
    from tracker.gear.data_source import SnapshotEnvelope

    case = load_case("melee_1m")
    envelope = SnapshotEnvelope.from_facts(case.snapshot, {})
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(envelope.model_dump_json(), encoding="utf-8")
    request = case.request.model_copy(
        update={"expected_snapshot_id": "wrong" if mismatch else case.snapshot.fingerprint}
    )
    path = write_dump(tmp_path, replace(case, request=request))
    monkeypatch.setattr("tracker.content.loader.load_content", lambda: case.content)
    monkeypatch.setattr("tracker.gear.catalog.load_catalog", lambda _: case.catalog)
    if mismatch:
        with pytest.raises(ValueError, match="fingerprints differ"):
            load_profile_case(path, snapshot=snapshot)
    else:
        replay, provenance = load_profile_case(path, snapshot=snapshot)
        assert replay.snapshot.fingerprint == case.snapshot.fingerprint
        assert provenance["original_account_replayed"] is True
        assert provenance["catalog_items"] == len(case.catalog.items)


@pytest.mark.parametrize("cprofile", [False, True])
def test_profile_writes_complete_archives_and_optional_call_profile(
    tmp_path, monkeypatch, cprofile
):
    case = load_case("melee_1m")
    result = {"search": {}, "secondary_frontiers": [{"points": [1, 2]}]}
    options = []

    def optimize(*args, **kwargs):
        assert args[0] is case.snapshot
        options.append(kwargs)
        return result

    monkeypatch.setattr("tools.profile_gear_frontiers.optimize", optimize)
    report = profile_case(case, {"optimization_mode": "fast"}, tmp_path, cprofile=cprofile)
    assert json.loads((tmp_path / "result.json").read_text()) == result
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert options == [
        {"_complete_frontiers": True, "_running_frontier": True, "local_refinement": False}
    ]
    assert (tmp_path / "calls.prof").exists() == cprofile
    assert (tmp_path / "calls.txt").exists() == cprofile


def test_cli_passes_explicit_overrides_and_reports_provenance(tmp_path, monkeypatch, capsys):
    from tools.profile_gear_frontiers import main

    case = load_case("melee_1m")
    path = write_dump(tmp_path, case)
    monkeypatch.setattr(
        "sys.argv",
        [
            "profile",
            "--dump",
            str(path),
            "--fixture",
            "melee_1m",
            "--discipline",
            "ranged",
            "--potion",
            "ranging",
            "--output",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        "tools.profile_gear_frontiers.profile_case",
        lambda case, provenance, output, **kwargs: {"provenance": provenance, "search": {}},
    )
    main()
    report = json.loads(capsys.readouterr().out)
    assert report["provenance"]["potion_override"] == ["ranging"]
    assert "search" not in report
