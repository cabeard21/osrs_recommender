import copy

import pytest

from tools.accept_fixed_reporting import REQUIRED, compare, derive_case, select_adoption
from tools.benchmark_gear_desktop import load_benchmark_case


def evidence():
    reports = []
    memory = []
    for name, workers in REQUIRED:
        pairs = [
            {
                "pair": i,
                "order": ["reference", "candidate"] if i % 2 else ["candidate", "reference"],
                "reference": 10 + i / 100,
                "candidate": 8 + i / 100,
            }
            for i in range(1, 6)
        ]
        runs = [
            {"pair": p["pair"], "profile": mode, "wall_seconds": p[mode], "result_digest": name}
            for p in pairs
            for mode in p["order"]
        ]
        reports.append(
            {
                "fixed_reporting": {"reference": False, "candidate": True},
                "reference": "reference",
                "candidate": "candidate",
                "workers": workers,
                "provenance": {"case_name": name, "cohort_sha256": "cohort", "inputs_sha256": name},
                "pairs": pairs,
                "runs": runs,
            }
        )
        if (name, workers) in [("fixed_ranged", 1), ("auto_control", 3), ("fixed_potions", 3)]:
            for mode in ("reference", "candidate"):
                for _i in range(3):
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
                            "sampled_peak_rss_bytes": 100 if mode == "reference" else 90,
                            "result_digest": name,
                            "inputs_sha256": name,
                        }
                    )
    return reports, memory


def test_derive_preserves_cohort_and_fixed_settings():
    base, p = load_benchmark_case("single_ranged")
    for name in dict(REQUIRED):
        case, provenance = derive_case(base, p, name)
        assert (
            case.snapshot is base.snapshot
            and case.catalog is base.catalog
            and case.prices is base.prices
        )
        assert case.at == base.at and case.request.budget_gp == base.request.budget_gp
        assert provenance["case_name"] == name
        if name.startswith("fixed_") or name == "auto_control":
            assert (case.request.roles[0].combat_options is None) == (name != "auto_control")
            assert case.request.roles[0].prayers.mode == "disabled"
    assert derive_case(base, p, "auto_control")[0].request.roles[0].allowed_disciplines
    assert derive_case(base, p, "fixed_thorough")[1]["optimization_mode"] == "thorough"
    with pytest.raises(ValueError):
        derive_case(base, p, "missing")


def test_valid_gate():
    reports, memory = evidence()
    assert select_adoption(reports, memory)["adopt"] is True


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate_report",
        "parity",
        "pair",
        "duration",
        "forged_decision",
        "cohort",
        "input",
        "memory_missing",
        "memory_duplicate",
        "memory_failed",
        "memory_digest",
        "memory_input",
        "memory_samples",
        "memory_peak",
        "memory_pid",
    ],
)
def test_gate_rejects_bad_evidence(fault):
    reports, memory = evidence()
    if fault == "missing":
        reports.pop()
    elif fault == "duplicate_report":
        reports.append(copy.deepcopy(reports[0]))
    elif fault == "parity":
        reports[0]["runs"][0]["result_digest"] = "different"
    elif fault == "pair":
        reports[0]["pairs"][1]["pair"] = 1
    elif fault == "duration":
        reports[0]["pairs"][0]["reference"] = float("nan")
    elif fault == "forged_decision":
        for r in reports[0]["runs"]:
            if r["profile"] == "candidate":
                r["wall_seconds"] = 20
        for p in reports[0]["pairs"]:
            p["candidate"] = 20
        reports[0]["decision"] = {"repeatable_gain": True, "no_material_regression": True}
    elif fault == "cohort":
        reports[0]["provenance"]["cohort_sha256"] = "other"
    elif fault == "input":
        reports[0]["provenance"]["inputs_sha256"] = ""
    elif fault == "memory_missing":
        memory.pop()
    elif fault == "memory_duplicate":
        memory[1]["measurement_id"] = memory[0]["measurement_id"]
    elif fault == "memory_failed":
        memory[0]["failures"] = 1
    elif fault == "memory_digest":
        memory[0]["result_digest"] = "other"
    elif fault == "memory_input":
        memory[0]["inputs_sha256"] = "other"
    elif fault == "memory_samples":
        memory[0]["samples"] = 0
    elif fault == "memory_peak":
        memory[3]["sampled_peak_rss_bytes"] = memory[4]["sampled_peak_rss_bytes"] = 101
    elif fault == "memory_pid":
        memory[1]["pid"] = memory[0]["pid"]
    assert select_adoption(reports, memory)["adopt"] is False


def test_compare_interleaves_actual_service_flags(tmp_path):
    base, p = load_benchmark_case("single_ranged")
    case, p = derive_case(base, p, "fixed_ranged")
    events = []

    class Service:
        def __init__(self, enabled):
            self.enabled = enabled

        def optimize(self, *args, **kwargs):
            events.append(self.enabled)
            return {"curve": [1], "search": {"timings_seconds": {"total": len(events)}}}

    report = compare(case, p, tmp_path, service_factory=lambda enabled: Service(enabled))
    assert events[:6] == [False, True, False, True, True, False]
    assert len(report["pairs"]) == 5
    assert report["reference"] == "reference"
    assert report["execution"] == "service"
    assert (tmp_path / "inputs.json").exists()


def test_compare_rejects_parity_and_invalid_config(tmp_path):
    base, p = load_benchmark_case("single_ranged")

    class Service:
        def __init__(self, enabled):
            self.enabled = enabled

        def optimize(self, *a, **k):
            return {"value": self.enabled}

    with pytest.raises(ValueError, match="parity"):
        compare(base, p, tmp_path, service_factory=Service)
    for options in ({"pairs": 4}, {"workers": 2}, {"warmups": -1}):
        with pytest.raises(ValueError):
            compare(base, p, tmp_path, **options)


def test_pool_cleanup_and_diagnostic_flags(tmp_path, monkeypatch):
    from tools import accept_fixed_reporting as module

    base, p = load_benchmark_case("single_ranged")
    events = []

    class Pool:
        def __init__(self, workers):
            events.append(workers)

        def start(self, *a):
            events.append("start")

        def close(self):
            events.append("close")

    class Service:
        def optimize(self, *a, **kw):
            return {"curve": []}

    monkeypatch.setattr("tracker.gear.parallel.AutoProcessPool", Pool)
    monkeypatch.setattr(module, "fixed_service", lambda *a: Service())
    report = compare(base, p, tmp_path / "pool", workers=3)
    assert events == [3, "start", "close"]
    assert report["fixed_reporting"] == {"reference": False, "candidate": True}
    called = []

    def optimize(*a, **kw):
        called.append(kw)
        return {"curve": []}

    monkeypatch.setattr(module, "optimize", optimize)
    report = compare(base, {**p, "diagnostic": True}, tmp_path / "diagnostic")
    assert report["execution"] == "direct_diagnostic"
    assert [r["_fixed_reporting"] for r in called[:6]] == [False, True, False, True, True, False]
    assert all(r["_execution_profile"] == "combined" and r["_complete_frontiers"] for r in called)
    with pytest.raises(ValueError, match="serial"):
        compare(base, {**p, "diagnostic": True}, tmp_path / "invalid", workers=3)


def test_service_flag_and_catalog_injection(monkeypatch):
    from tools.accept_fixed_reporting import fixed_service

    observed = []

    class Service:
        def __init__(self, content, **kw):
            observed.append(kw)

    monkeypatch.setattr("tracker.gear.service.GearService", Service)
    case, _ = load_benchmark_case("single_ranged")
    service = fixed_service(case, True, "pool")
    assert service._equipment is case.catalog
    assert observed == [
        {"optimization_profile": "combined", "fixed_reporting": True, "auto_pool": "pool"}
    ]


@pytest.mark.parametrize("context_name", ["fixed", "lazy", "ranged"])
def test_ambient_contexts_rejected(tmp_path, context_name):
    from tracker.gear.fixed_reporting import fixed_reporting
    from tracker.gear.lazy_reporting import lazy_reporting
    from tracker.gear.ranged_numerics import ranged_experiment

    case, p = load_benchmark_case("single_ranged")
    context = {
        "fixed": fixed_reporting,
        "lazy": lazy_reporting,
        "ranged": lambda: ranged_experiment(16),
    }[context_name]
    with context(), pytest.raises(ValueError, match="Ambient"):
        compare(case, p, tmp_path)


def test_cli_and_matrix_validation(tmp_path, monkeypatch, capsys):
    from tools import accept_fixed_reporting as module

    case, p = load_benchmark_case("single_ranged")
    monkeypatch.setattr(module, "load_frozen_case", lambda path: (case, p))
    called = []

    def fake(case, provenance, output, **kw):
        called.append((provenance, kw))
        return {"decision": {"repeatable_gain": True}}

    monkeypatch.setattr(module, "compare", fake)
    args = [
        "accept",
        "--frozen",
        "private.json",
        "--output",
        str(tmp_path),
        "--case",
        "auto_control",
        "--workers",
        "3",
    ]
    monkeypatch.setattr("sys.argv", args)
    module.main()
    assert called[0][0]["case_name"] == "auto_control"
    assert called[0][1]["workers"] == 3
    assert "repeatable_gain" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", [*args[:-4], "--case", "fixed_ranged", "--workers", "3"])
    with pytest.raises(SystemExit):
        module.main()


def test_selector_additional_identity_and_mode_checks():
    reports, memory = evidence()
    reports[0]["fixed_reporting"] = {"reference": True, "candidate": True}
    assert not select_adoption(reports, memory)["adopt"]
    reports, memory = evidence()
    memory[0]["mode"] = "unknown"
    assert not select_adoption(reports, memory)["adopt"]
    reports, memory = evidence()
    for row in reports:
        if row["workers"] == 3 and row["provenance"]["case_name"] == "auto_control":
            row["provenance"]["inputs_sha256"] = "changed"
    assert not select_adoption(reports, memory)["adopt"]


@pytest.mark.parametrize(
    "fault",
    [
        "report",
        "provenance",
        "name",
        "workers_bool",
        "cohort",
        "pair_bool",
        "run_pair_bool",
        "run_seconds_bool",
        "flags_reference",
        "flags_candidate",
        "flags_extra",
        "memory",
        "memory_workers_bool",
    ],
)
def test_selector_malformed_evidence_fails_closed(fault):
    reports, memory = evidence()
    if fault == "report":
        reports[0] = None
    elif fault == "provenance":
        reports[0]["provenance"] = []
    elif fault == "name":
        reports[0]["provenance"]["case_name"] = []
    elif fault == "workers_bool":
        reports[0]["workers"] = True
    elif fault == "cohort":
        reports[0]["provenance"]["cohort_sha256"] = []
    elif fault == "pair_bool":
        reports[0]["pairs"][0]["pair"] = True
    elif fault == "run_pair_bool":
        reports[0]["runs"][0]["pair"] = True
    elif fault == "run_seconds_bool":
        reports[0]["runs"][0]["wall_seconds"] = True
    elif fault == "flags_reference":
        reports[0]["fixed_reporting"]["reference"] = 0
    elif fault == "flags_candidate":
        reports[0]["fixed_reporting"]["candidate"] = 1
    elif fault == "flags_extra":
        reports[0]["fixed_reporting"]["extra"] = False
    elif fault == "memory":
        memory[0] = None
    elif fault == "memory_workers_bool":
        memory[0]["workers"] = True
    assert select_adoption(reports, memory)["adopt"] is False
