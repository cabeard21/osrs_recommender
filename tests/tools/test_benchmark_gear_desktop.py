"""Portable desktop measurements retain every nested result and frozen input."""

import json

import pytest

from tools.benchmark_gear_desktop import benchmark, load_benchmark_case, result_digest


def test_digest_preserves_auto_archives_and_work_but_ignores_timings():
    original = {
        "discipline_results": [
            {"curve": [1], "search": {"nodes": 2, "timings_seconds": {"total": 1}}}
        ]
    }
    timing = {
        "discipline_results": [
            {"curve": [1], "search": {"nodes": 2, "timings_seconds": {"total": 10}}}
        ]
    }
    changed = {"discipline_results": [{"curve": [2], "search": {"nodes": 2}}]}
    assert result_digest(original) == result_digest(timing)
    assert result_digest(original) != result_digest(changed)
    assert result_digest({"search": {"nodes": 2}}) != result_digest({"search": {"nodes": 3}})


@pytest.mark.parametrize(
    "name",
    [
        "single_melee",
        "single_ranged",
        "single_magic",
        "multi",
        "auto",
        "potions",
        "defence_roll",
        "ranged_diagnostic",
    ],
)
def test_named_cases_are_validated_and_explicit(name):
    case, provenance = load_benchmark_case(name)
    assert case.request.model_validate(case.request.model_dump()) == case.request
    assert provenance["account_source"] == (
        "fixture:melee_1m" if name != "multi" else "fixture:joint_four"
    )
    assert provenance["original_account_replayed"] is False
    assert len(provenance["inputs_sha256"]) == 64


def test_benchmark_repeats_writes_results_and_detects_parity_failure(tmp_path):
    case, provenance = load_benchmark_case("single_melee")
    calls = []

    def runner(*args, **kwargs):
        calls.append(kwargs)
        return {
            "selected_solution": {"id": "x"},
            "search": {"timings_seconds": {"total": len(calls)}},
        }

    report = benchmark(case, provenance, tmp_path, repeats=2, warmups=1, runner=runner)
    assert len(calls) == 3
    assert calls == [{"local_refinement": False}] * 3
    assert len(report["runs"]) == 2
    assert report["execution"] == "serial"
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert (tmp_path / "run-1.json").exists()
    assert (
        report["timing"]["minimum_seconds"]
        <= report["timing"]["median_seconds"]
        <= report["timing"]["maximum_seconds"]
    )

    with pytest.raises(ValueError, match="parity"):
        benchmark(
            case,
            provenance,
            tmp_path,
            repeats=2,
            warmups=0,
            runner=lambda *a, **k: {"id": len(calls.append(1) or calls)},
        )


@pytest.mark.parametrize("repeats,warmups", [(0, 1), (1, -1)])
def test_invalid_repetition_counts(tmp_path, repeats, warmups):
    case, provenance = load_benchmark_case("single_melee")
    with pytest.raises(ValueError, match="repeats"):
        benchmark(case, provenance, tmp_path, repeats=repeats, warmups=warmups)


def test_invalid_case():
    with pytest.raises(ValueError, match="Unknown"):
        load_benchmark_case("missing")


def test_diagnostic_and_cache_are_explicit(tmp_path):
    case, provenance = load_benchmark_case("ranged_diagnostic")

    def runner(*args, **kwargs):
        from tracker.gear.ranged_numerics import active

        assert active()
        assert kwargs == {
            "local_refinement": False,
            "_complete_frontiers": True,
            "_running_frontier": True,
        }
        return {"id": "unchanged"}

    report = benchmark(
        case, provenance, tmp_path, runner=runner, repeats=1, warmups=0, ranged_cache=4096
    )
    assert report["ranged_cache"] == 4096
    with pytest.raises(ValueError, match="serial"):
        benchmark(case, provenance, tmp_path, workers=2, ranged_cache=4096)


@pytest.mark.parametrize("frozen", [False, True])
def test_cli_portable_and_frozen_input_replay(tmp_path, monkeypatch, capsys, frozen):
    from tools import benchmark_gear_desktop as module

    case, _provenance = load_benchmark_case("single_ranged")
    if frozen:
        path = tmp_path / "frozen.json"
        path.write_text(module._json(module.frozen_inputs(case)))
        source = ["--frozen", str(path)]
    else:
        source = ["--case", "single_ranged"]
    captured = []

    def bench(replay, provenance, output, **kwargs):
        captured.append(replay)
        assert replay.request == case.request
        assert replay.snapshot.fingerprint == case.snapshot.fingerprint
        assert provenance["optimization_mode"] == "thorough"
        return {"timing": {}}

    monkeypatch.setattr(module, "benchmark", bench)
    monkeypatch.setattr("sys.argv", ["benchmark", *source, "--output", str(tmp_path), "--thorough"])
    module.main()
    assert len(captured) == 1
    assert json.loads(capsys.readouterr().out)["timing"] == {}


def test_separate_memory_pass_is_labeled_and_keeps_settings(tmp_path):
    case, provenance = load_benchmark_case("ranged_diagnostic")
    report = benchmark(
        case,
        provenance,
        tmp_path,
        repeats=1,
        warmups=0,
        memory=True,
        runner=lambda *a, **k: {"ok": [1] * 100},
    )
    assert report["memory"]["peak_bytes"] > 0
    assert report["memory"]["is_process_rss"] is False
    archived = json.loads((tmp_path / "inputs.json").read_text())
    assert archived["benchmark"]["diagnostic"] is True


def test_worker_pool_is_started_and_closed(tmp_path, monkeypatch):
    from tracker.gear import parallel

    events = []

    class Pool:
        def __init__(self, workers):
            events.append(workers)

        def start(self, content, catalog):
            events.append("start")

        def run_potions(self):
            pass

        def close(self):
            events.append("close")

    monkeypatch.setattr(parallel, "AutoProcessPool", Pool)
    case, provenance = load_benchmark_case("potions")
    benchmark(
        case, provenance, tmp_path, repeats=1, warmups=0, workers=2, runner=lambda *a, **k: {"x": 1}
    )
    assert events == [2, "start", "close"]


def test_frozen_prices_restore_datetimes(tmp_path):
    from tools.benchmark_gear_desktop import frozen_inputs, load_frozen_case
    from tools.gear_search_quality_fixture import load_case

    case = load_case("melee_1m")
    path = tmp_path / "inputs.json"
    path.write_text(
        json.dumps(
            {**frozen_inputs(case), "benchmark": {"optimization_mode": "thorough"}}, default=str
        )
    )
    replay, provenance = load_frozen_case(path)
    assert replay.prices
    for price in replay.prices.values():
        assert not isinstance(price.fetched_at, str)
    assert provenance["optimization_mode"] == "thorough"


def test_frozen_provenance_cannot_override_input_hash(tmp_path):
    from tools.benchmark_gear_desktop import case_provenance, frozen_inputs, load_frozen_case
    from tools.gear_search_quality_fixture import load_case

    case = load_case("melee_1m")
    payload = {**frozen_inputs(case), "benchmark": case_provenance(case)}
    payload["job"]["request"]["budget_gp"] += 1
    path = tmp_path / "changed.json"
    path.write_text(json.dumps(payload, default=str))
    replay, provenance = load_frozen_case(path)
    assert provenance["inputs_sha256"] == case_provenance(replay)["inputs_sha256"]
    assert provenance["inputs_sha256"] != payload["benchmark"]["inputs_sha256"]


def test_local_refinement_duration_is_observational_only():
    from tools.benchmark_gear_desktop import result_digest

    original = {
        "search": {"local_refinement": {"duration_seconds": 1, "evaluated_assignments": 8}},
        "selected_solution": {"duration_seconds": 3},
    }
    observed = {
        "search": {"local_refinement": {"duration_seconds": 9, "evaluated_assignments": 8}},
        "selected_solution": {"duration_seconds": 3},
    }
    assert result_digest(original) == result_digest(observed)
    observed["selected_solution"]["duration_seconds"] = 9
    assert result_digest(original) != result_digest(observed)


def test_refinement_materialization_counter_is_observation_not_search_budget():
    from tools.benchmark_gear_desktop import result_digest

    a = {
        "search": {"local_refinement": {"performance_cache_misses": 1, "assignment_attempts": 100}},
        "selected_solution": {"performance_cache_misses": 2},
    }
    b = {
        "search": {"local_refinement": {"performance_cache_misses": 9, "assignment_attempts": 100}},
        "selected_solution": {"performance_cache_misses": 2},
    }
    assert result_digest(a) == result_digest(b)
    b["search"]["local_refinement"]["assignment_attempts"] = 101
    assert result_digest(a) != result_digest(b)
    b["search"]["local_refinement"]["assignment_attempts"] = 100
    b["selected_solution"]["performance_cache_misses"] = 3
    assert result_digest(a) != result_digest(b)
