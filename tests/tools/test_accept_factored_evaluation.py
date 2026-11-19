import copy
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from tools import accept_factored_evaluation as module
from tools.benchmark_gear_desktop import load_benchmark_case


def inputs(name="fixed_ranged"):
    case, provenance = load_benchmark_case("single_ranged")
    return module.derive_case(case, provenance, name)


def evidence():
    from tests.tools.test_accept_fixed_reporting import evidence as fixed_evidence

    reports, _ = fixed_evidence()
    for report in reports:
        report["fixed_reporting"] = {"reference": True, "candidate": True}
        report["factored_evaluation"] = {"reference": False, "candidate": True}
    for name, workers in module.EXTRA_CASES:
        report = copy.deepcopy(reports[0])
        report["workers"] = workers
        report["provenance"] = {"case_name": name, "cohort_sha256": "cohort", "inputs_sha256": name}
        for run in report["runs"]:
            run["result_digest"] = name
        reports.append(report)
    memory = []
    for name, workers in module.MEMORY_CASES:
        for mode in module.MODES:
            for _ in range(3):
                memory.append(
                    {
                        "case_name": name,
                        "workers": workers,
                        "mode": mode,
                        "fresh_process": True,
                        "pid": len(memory) + 1,
                        "measurement_id": str(len(memory)),
                        "complete": True,
                        "failures": 0,
                        "samples": 10,
                        "sampled_peak_rss_bytes": 100,
                        "result_digest": name,
                        "inputs_sha256": name,
                        "fixed_reporting": True,
                        "factored_evaluation": mode == "candidate",
                    }
                )
    return reports, memory


def worker_evidence():
    return [
        {
            "case_name": name,
            "mode": mode,
            "serial_workers": 1,
            "workers": 3,
            "fixed_reporting": True,
            "factored_evaluation": mode == "candidate",
            "inputs_sha256": name,
            "serial_digest": name,
            "worker_digest": name,
            "passed": True,
        }
        for name in module.PARALLEL_CASES
        for mode in module.MODES
    ]


def test_cases_cover_original_matrix_and_configured_styles():
    from tools.accept_fixed_reporting import REQUIRED as old_required

    base, provenance = load_benchmark_case("single_ranged")
    assert set(old_required) <= set(module.REQUIRED)
    for name in dict(module.REQUIRED):
        case, metadata = module.derive_case(base, provenance, name)
        assert case.catalog is base.catalog and case.snapshot is base.snapshot
        assert case.prices is base.prices and case.at == base.at
        assert metadata["case_name"] == name
        if name == "configured_melee":
            assert case.request.roles[0].style == "slash"
            assert case.request.roles[0].combat_options is not None
        if name == "configured_magic":
            assert case.request.roles[0].style == "magic"
        if name == "configured_diagnostic":
            assert metadata["diagnostic"] is True
    with pytest.raises(ValueError):
        module.derive_case(base, provenance, "unknown")


def test_service_flags_keep_old_combined_as_reference(monkeypatch):
    calls = []

    class Service:
        def __init__(self, content, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("tracker.gear.service.GearService", Service)
    case, _ = inputs()
    for enabled in (False, True):
        service = module.factored_service(case, enabled, "pool")
        assert service._equipment is case.catalog
    assert calls == [
        {
            "optimization_profile": "combined",
            "fixed_reporting": True,
            "factored_evaluation": enabled,
            "auto_pool": "pool",
        }
        for enabled in (False, True)
    ]


def test_compare_realistic_service_interleave_and_parity(tmp_path):
    calls = []

    class Service:
        def __init__(self, enabled):
            self.enabled = enabled

        def optimize(self, *args, **kwargs):
            calls.append(self.enabled)
            return {"curve": [1], "search": {"timings_seconds": {"total": len(calls)}}}

    report = module.compare(*inputs(), tmp_path, service_factory=Service)
    assert calls[:6] == [False, True, False, True, True, False]
    assert len(calls) == 12
    assert report["factored_evaluation"] == {"reference": False, "candidate": True}
    assert report["fixed_reporting"] == {"reference": True, "candidate": True}
    assert report["execution"] == "service"
    assert module.timing_decision(report) is not None
    assert (tmp_path / "inputs.json").exists()


def test_actual_service_complete_fixture_parity(tmp_path):
    case, provenance = inputs()
    report = module.compare(case, provenance, tmp_path)
    assert len(report["runs"]) == 10
    assert len({row["result_digest"] for row in report["runs"]}) == 1
    assert module.timing_decision(report) is not None


def test_diagnostic_flags_and_pool_cleanup(tmp_path, monkeypatch):
    calls = []
    case, provenance = inputs("configured_diagnostic")

    def optimize(*args, **kwargs):
        calls.append(kwargs)
        return {"curve": []}

    monkeypatch.setattr(module, "optimize", optimize)
    report = module.compare(case, provenance, tmp_path, service_factory=lambda enabled: None)
    assert report["execution"] == "direct_diagnostic"
    assert [c["_factored_evaluation"] for c in calls[:6]] == [False, True, False, True, True, False]
    assert all(
        c["_fixed_reporting"] and c["_complete_frontiers"] and c["_execution_profile"] == "combined"
        for c in calls
    )
    with pytest.raises(ValueError, match="serial"):
        module.compare(case, provenance, tmp_path, workers=3)

    events = []

    class Pool:
        def __init__(self, workers):
            events.append(workers)

        def start(self, *args):
            events.append("start")

        def close(self):
            events.append("close")

    monkeypatch.setattr("tracker.gear.parallel.AutoProcessPool", Pool)
    monkeypatch.setattr(
        module,
        "factored_service",
        lambda *a: SimpleNamespace(optimize=lambda *a, **kw: {"curve": []}),
    )
    module.compare(*inputs("auto_control"), tmp_path / "pool", workers=3)
    assert events == [3, "start", "close"]


def test_bad_configuration_and_parity_fail_closed(tmp_path):
    for kwargs in ({"workers": 2}, {"pairs": 4}, {"warmups": -1}, {"pairs": True}):
        with pytest.raises(ValueError):
            module.compare(*inputs(), tmp_path, **kwargs)

    def factory(enabled):
        return SimpleNamespace(optimize=lambda *a, **k: {"value": enabled})

    with pytest.raises(ValueError, match="parity"):
        module.compare(*inputs(), tmp_path, service_factory=factory)


def test_failed_comparison_preserves_both_results_and_measurements(tmp_path):
    def factory(enabled):
        return SimpleNamespace(optimize=lambda *a, **k: {"value": enabled})

    with pytest.raises(ValueError, match="warmup-1-candidate"):
        module.compare(*inputs(), tmp_path, service_factory=factory)
    for mode, value in (("reference", False), ("candidate", True)):
        result = json.loads((tmp_path / f"warmup-1-{mode}.json").read_text())
        measurement = json.loads((tmp_path / f"warmup-1-{mode}-measurement.json").read_text())
        assert result == {"value": value}
        assert measurement["result_digest"] == module.result_digest(result)
        assert measurement["profile"] == mode and measurement["wall_seconds"] > 0
    assert not (tmp_path / "report.json").exists()


def test_selector_accepts_complete_evidence():
    assert module.select_adoption(*evidence(), worker_evidence()) == {"adopt": True, "reasons": []}


@pytest.mark.parametrize("mode", module.MODES)
@pytest.mark.parametrize("count", [0, 2])
def test_multi_requires_three_fresh_memory_measurements_per_mode(mode, count):
    reports, memory = evidence()
    multi = [row for row in memory if row["case_name"] == "multi" and row["mode"] == mode]
    retained = [row for row in memory if row not in multi] + multi[:count]
    decision = module.select_adoption(reports, retained, worker_evidence())
    assert not decision["adopt"]
    assert f"Missing/incomplete fresh-process memory: multi/1/{mode}" in decision["reasons"]


def test_multi_memory_uses_same_freshness_and_peak_gates():
    reports, memory = evidence()
    multi = [row for row in memory if row["case_name"] == "multi"]
    assert len(multi) == 6
    multi[0]["fresh_process"] = False
    assert not module.select_adoption(reports, memory, worker_evidence())["adopt"]
    multi[0]["fresh_process"] = True
    for row in multi:
        if row["mode"] == "candidate":
            row["sampled_peak_rss_bytes"] = 101
    decision = module.select_adoption(reports, memory, worker_evidence())
    assert "Memory regression: multi/1" in decision["reasons"]


def test_gain_can_be_established_by_magic_instead_of_fixed_ranged():
    reports, memory = evidence()
    for report in reports:
        if report["provenance"]["case_name"] != "configured_magic":
            for pair in report["pairs"]:
                pair["candidate"] = pair["reference"]
            for run in report["runs"]:
                run["wall_seconds"] = report["pairs"][run["pair"] - 1][run["profile"]]
    assert module.select_adoption(reports, memory, worker_evidence())["adopt"]
    reports = [r for r in reports if r["provenance"]["case_name"] != "configured_magic"]
    assert (
        "No substantive case established a repeatable gain"
        in module.select_adoption(reports, memory, worker_evidence())["reasons"]
    )


@pytest.mark.parametrize(
    "context_name", ["fixed", "lazy", "ranged", "finalization", "prepared", "costs", "variants"]
)
def test_all_ambient_experiments_rejected(tmp_path, context_name):
    from tracker.gear.compact_costs import compact_running_costs
    from tracker.gear.fixed_reporting import fixed_reporting
    from tracker.gear.lazy_reporting import lazy_reporting
    from tracker.gear.prepared_combat import prepared_combat
    from tracker.gear.ranged_numerics import ranged_experiment
    from tracker.gear.ranged_score_finalization import ranged_score_finalization
    from tracker.gear.variant_reporting import lazy_variants

    context = {
        "fixed": fixed_reporting,
        "lazy": lazy_reporting,
        "ranged": ranged_experiment,
        "finalization": ranged_score_finalization,
        "prepared": prepared_combat,
        "costs": compact_running_costs,
        "variants": lazy_variants,
    }[context_name]
    with context(), pytest.raises(ValueError, match="Ambient"):
        module.compare(*inputs(), tmp_path)


@pytest.mark.parametrize(
    "fault",
    [
        "report",
        "provenance",
        "name",
        "workers",
        "input",
        "cohort",
        "memory",
        "memory_duplicate",
        "memory_mode",
        "memory_regression",
    ],
)
def test_malformed_reports_are_rejected(fault):
    reports, memory = evidence()
    if fault == "report":
        reports[0] = None
    elif fault == "provenance":
        reports[0]["provenance"] = []
    elif fault in ("name", "input", "cohort"):
        key = {"name": "case_name", "input": "inputs_sha256", "cohort": "cohort_sha256"}[fault]
        reports[0]["provenance"][key] = []
    elif fault == "workers":
        reports[0]["workers"] = True
    elif fault == "memory":
        memory[0] = None
    elif fault == "memory_duplicate":
        memory[1]["measurement_id"] = memory[0]["measurement_id"]
    elif fault == "memory_mode":
        memory[0]["mode"] = "unknown"
    else:
        memory[3]["sampled_peak_rss_bytes"] = memory[4]["sampled_peak_rss_bytes"] = 101
    assert module.select_adoption(reports, memory, worker_evidence())["adopt"] is False


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra_parity",
        "extra_regression",
        "extra_cohort",
        "duplicate",
        "flags",
        "missing_memory",
        "old_evidence",
    ],
)
def test_selector_rejects_incomplete_or_misidentified_evidence(fault):
    reports, memory = evidence()
    if fault == "missing":
        reports.pop()
    elif fault == "extra_parity":
        reports[-1]["runs"][0]["result_digest"] = "different"
    elif fault == "extra_regression":
        for row in reports[-1]["pairs"]:
            row["candidate"] = 99
        for row in reports[-1]["runs"]:
            if row["profile"] == "candidate":
                row["wall_seconds"] = 99
    elif fault == "extra_cohort":
        reports[-1]["provenance"]["cohort_sha256"] = "different"
    elif fault == "duplicate":
        reports.append(copy.deepcopy(reports[-1]))
    elif fault == "flags":
        reports[-1]["fixed_reporting"]["reference"] = False
    elif fault == "missing_memory":
        memory.pop()
    else:
        reports[0].pop("factored_evaluation")
    assert not module.select_adoption(reports, memory, worker_evidence())["adopt"]


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "digest", "inputs", "profile", "malformed"]
)
def test_worker_parity_required_and_bound_to_same_evidence(fault):
    rows = worker_evidence()
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows.append(copy.deepcopy(rows[0]))
    elif fault == "digest":
        rows[0]["worker_digest"] = "other"
    elif fault == "inputs":
        rows[0]["inputs_sha256"] = "other"
    elif fault == "profile":
        rows[0]["factored_evaluation"] = True
    else:
        rows[0] = None
    assert not module.select_adoption(*evidence(), rows)["adopt"]
    assert not module.select_adoption(*evidence())["adopt"]


def test_worker_parity_helper_compares_both_profiles_and_workers(tmp_path):
    calls = []

    def factory(enabled, workers):
        calls.append((enabled, workers))
        return SimpleNamespace(optimize=lambda *a, **kw: {"curve": []})

    rows = module.compare_workers(*inputs("configured_auto"), tmp_path, service_factory=factory)
    assert calls == [(False, 1), (False, 3), (True, 1), (True, 3)]
    assert len(rows) == 2 and all(row["passed"] for row in rows)
    assert all(row["serial_digest"] == row["worker_digest"] for row in rows)
    assert (tmp_path / "worker-parity.json").exists()
    with pytest.raises(ValueError):
        module.compare_workers(*inputs(), tmp_path)


def test_worker_parity_helper_fails_on_changed_results(tmp_path):
    def factory(enabled, workers):
        return SimpleNamespace(optimize=lambda *a, **kw: {"workers": workers})

    with pytest.raises(ValueError, match="parity"):
        module.compare_workers(*inputs("configured_potions"), tmp_path, service_factory=factory)


def test_memory_child_separates_sampling_from_timing(tmp_path, monkeypatch):
    calls = []

    @contextmanager
    def measure(**kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(
            report=lambda: {
                "complete": True,
                "samples": 8,
                "failures": 0,
                "sampled_peak_rss_bytes": 100,
            }
        )

    monkeypatch.setattr(module, "measure_process_tree", measure)
    monkeypatch.setattr(
        module,
        "factored_service",
        lambda *args: SimpleNamespace(optimize=lambda *a, **kw: {"curve": []}),
    )
    row = module.memory_once(*inputs(), tmp_path, mode="candidate", interval=0.02)
    assert row["fresh_process"] is False  # Only the subprocess wrapper certifies freshness.
    assert row["factored_evaluation"] is True and row["fixed_reporting"] is True
    assert row["samples"] == 8 and row["measurement_id"]
    assert calls == [{"interval": 0.02}]


def test_memory_wrapper_launches_fresh_interpreter(tmp_path, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        (tmp_path / "memory.json").write_text('{"pid": 123, "fresh_process": false}')

    monkeypatch.setattr(module.subprocess, "run", run)
    row = module.measure_memory("frozen.json", tmp_path, case_name="fixed_ranged", mode="reference")
    assert row["fresh_process"] is True
    assert "--memory-child" in calls[0][0]
    assert calls[0][1]["check"] is True


def test_cli_uses_requested_case_and_mode(tmp_path, monkeypatch, capsys):
    case, provenance = load_benchmark_case("single_ranged")
    monkeypatch.setattr(module, "load_frozen_case", lambda path: (case, provenance))
    calls = []
    monkeypatch.setattr(
        module,
        "compare",
        lambda c, p, out, **kw: (
            calls.append((p["case_name"], kw)) or {"decision": {"passed": True}}
        ),
    )
    args = [
        "accept",
        "--frozen",
        "inputs.json",
        "--output",
        str(tmp_path),
        "--case",
        "configured_magic",
    ]
    monkeypatch.setattr("sys.argv", args)
    module.main()
    assert calls[0][0] == "configured_magic"
    assert "passed" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", [*args, "--workers", "3"])
    with pytest.raises(SystemExit):
        module.main()
