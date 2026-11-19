"""Service-profile acceptance uses complete results and logical work counters."""

import pytest

from tools.accept_gear_desktop_profiles import CASES, compare_profiles, derive_case
from tools.benchmark_gear_desktop import load_benchmark_case


def test_matrix_preserves_frozen_facts():
    original, _ = load_benchmark_case("single_ranged")
    for name in CASES:
        case, provenance = derive_case(original, {"optimization_mode": "fast"}, name)
        assert case.snapshot is original.snapshot
        assert case.catalog is original.catalog
        assert case.prices is original.prices
        assert case.request.budget_gp == original.request.budget_gp
        assert provenance["case_name"] == name
    assert len(derive_case(original, {}, "multi")[0].request.roles) == 2
    assert derive_case(original, {}, "thorough")[1]["optimization_mode"] == "thorough"
    with pytest.raises(ValueError):
        derive_case(original, {}, "unknown")


def test_interleaving_parity_and_cleanup(tmp_path):
    case, p = load_benchmark_case("single_ranged")
    events = []

    class Service:
        def __init__(self, profile):
            self.profile = profile

        def optimize(self, *args, **kwargs):
            events.append(self.profile)
            return {"curve": [1], "search": {"timings_seconds": {"total": len(events)}}}

    report = compare_profiles(case, p, tmp_path, service_factory=lambda profile: Service(profile))
    assert events[:2] == ["baseline", "lazy"]
    assert events[2:6] == ["baseline", "lazy", "lazy", "baseline"]
    assert len(report["pairs"]) == 5
    assert report["execution"] == "service"
    assert (tmp_path / "inputs.json").exists()


def test_parity_failure_and_validation(tmp_path):
    case, p = load_benchmark_case("single_ranged")

    class Service:
        def __init__(self, profile):
            self.profile = profile

        def optimize(self, *args, **kwargs):
            return {"curve": [self.profile]}

    with pytest.raises(ValueError, match="parity"):
        compare_profiles(case, p, tmp_path, service_factory=lambda profile: Service(profile))
    for kw in (
        {"pairs": 4},
        {"workers": 2},
        {"candidate": "bad"},
        {"candidate": "lazy", "reference": "lazy"},
    ):
        with pytest.raises(ValueError):
            compare_profiles(case, p, tmp_path, **kw)


def test_pool_lifecycle_and_diagnostic(tmp_path, monkeypatch):
    from tools import accept_gear_desktop_profiles as module

    events = []

    class Pool:
        def __init__(self, workers):
            events.append(workers)

        def start(self, *args):
            events.append("start")

        def close(self):
            events.append("close")

    class Service:
        def optimize(self, *args, **kwargs):
            return {"curve": []}

    monkeypatch.setattr("tracker.gear.parallel.AutoProcessPool", Pool)
    monkeypatch.setattr(module, "profile_service", lambda *a: Service())
    case, p = load_benchmark_case("single_ranged")
    report = compare_profiles(case, p, tmp_path / "pool", workers=3)
    assert report["workers"] == 3
    assert events == [3, "start", "close"]
    called = []

    def optimize(*a, **kwargs):
        called.append(kwargs)
        return {"curve": []}

    monkeypatch.setattr(module, "optimize", optimize)
    report = compare_profiles(
        case,
        {**p, "diagnostic": True},
        tmp_path / "diagnostic",
        service_factory=lambda p: Service(),
    )
    assert report["execution"] == "direct_diagnostic"
    assert all(row["_complete_frontiers"] for row in called)
    with pytest.raises(ValueError, match="serial"):
        compare_profiles(case, {"diagnostic": True}, tmp_path / "invalid", workers=3)


def test_profile_service_injects_catalog(monkeypatch):
    from tools.accept_gear_desktop_profiles import profile_service

    calls = []

    class Service:
        def __init__(self, content, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr("tracker.gear.service.GearService", Service)
    case, _ = load_benchmark_case("single_ranged")
    service = profile_service(case, "combined")
    assert service._equipment is case.catalog
    assert calls[0]["optimization_profile"] == "combined"


def test_ambient_context_rejected(tmp_path):
    from tracker.gear.lazy_reporting import lazy_reporting

    case, p = load_benchmark_case("single_ranged")
    with lazy_reporting(), pytest.raises(ValueError, match="Ambient"):
        compare_profiles(case, p, tmp_path)


def test_cli_preserves_selection(tmp_path, monkeypatch, capsys):
    from tools import accept_gear_desktop_profiles as module

    case, p = load_benchmark_case("single_ranged")
    monkeypatch.setattr(module, "load_frozen_case", lambda path: (case, p))
    captured = []

    def compare(case, provenance, output, **kwargs):
        captured.append(kwargs)
        return {"decision": {"repeatable_gain": True}}

    monkeypatch.setattr(module, "compare_profiles", compare)
    monkeypatch.setattr(
        "sys.argv",
        [
            "accept",
            "--frozen",
            "private.json",
            "--output",
            str(tmp_path),
            "--case",
            "auto",
            "--workers",
            "3",
            "--candidate",
            "combined",
            "--reference",
            "lazy",
        ],
    )
    module.main()
    assert captured[0]["workers"] == 3
    assert captured[0]["candidate"] == "combined"
    assert captured[0]["reference"] == "lazy"
    assert "repeatable_gain" in capsys.readouterr().out


def selection_inputs():
    from tools.accept_gear_desktop_profiles import CASES

    reports, memory = [], []

    def report(case, workers, reference, candidate):
        pairs, runs = [], []
        for i in range(1, 6):
            times = {reference: 10.0 + i / 100, candidate: 8.0 + i / 100}
            pairs.append({"pair": i, "order": [reference, candidate], **times})
            runs.extend(
                {
                    "pair": i,
                    "profile": profile,
                    "wall_seconds": times[profile],
                    "result_digest": case,
                }
                for profile in (reference, candidate)
            )
        return {
            "reference": reference,
            "candidate": candidate,
            "workers": workers,
            "provenance": {"case_name": case, "inputs_sha256": case, "cohort_sha256": "cohort"},
            "pairs": pairs,
            "runs": runs,
            "decision": {},
        }

    for profile in ("lazy", "combined"):
        reports.extend(
            report(case, workers, "baseline", profile)
            for case, workers in [(name, 1) for name in CASES] + [("auto", 3), ("potions", 3)]
        )
    reports.append(report("ranged", 1, "lazy", "combined"))
    for case, workers in [("ranged", 1), ("auto", 3), ("potions", 3)]:
        for profile in ("baseline", "lazy", "combined"):
            for _ in range(3):
                memory.append(
                    {
                        "case_name": case,
                        "workers": workers,
                        "profile": profile,
                        "fresh_process": True,
                        "pid": 1000 + len(memory),
                        "measurement_id": str(len(memory)),
                        "inputs_sha256": case,
                        "complete": True,
                        "samples": 20,
                        "failures": 0,
                        "sampled_peak_rss_bytes": 100 if profile == "baseline" else 90,
                        "result_digest": case,
                    }
                )
    return reports, memory


def set_time(report, profile, seconds):
    for row in report["runs"]:
        if row["profile"] == profile:
            row["wall_seconds"] = seconds
    for row in report["pairs"]:
        row[profile] = seconds


def test_default_selection_requires_complete_evidence():
    from tools.accept_gear_desktop_profiles import select_default

    assert select_default([], [])["selected_profile"] == "baseline"
    reports, memory = selection_inputs()
    assert select_default(reports, memory)["selected_profile"] == "combined"
    missing = [
        r
        for r in reports
        if not (r["candidate"] == "combined" and r["provenance"]["case_name"] == "auto")
    ]
    assert select_default(missing, memory)["selected_profile"] == "lazy"
    memory = [r for r in memory if r["profile"] != "lazy"]
    assert select_default(missing, memory)["selected_profile"] == "baseline"


@pytest.mark.parametrize(
    "defect",
    [
        "regression",
        "parity",
        "memory",
        "fresh",
        "primary",
        "incremental",
        "duplicate_pair",
        "empty_pair",
        "duplicate_run",
        "negative_time",
        "nan_time",
        "pair_time_mismatch",
        "cohort",
        "case_hash",
        "incremental_hash",
        "measurement_id",
        "memory_hash",
    ],
)
def test_default_selection_rejects_failed_gates(defect):
    from tools.accept_gear_desktop_profiles import select_default

    reports, memory = selection_inputs()
    if defect == "regression":
        for r in reports:
            set_time(r, r["candidate"], 20.0)
    elif defect == "primary":
        for r in reports:
            set_time(r, r["candidate"], 10.03)
    elif defect == "incremental":
        set_time(reports[-1], "combined", 20.0)
        assert select_default(reports, memory)["selected_profile"] == "lazy"
        return
    elif defect == "memory":
        for r in memory:
            if r["profile"] != "baseline":
                r["sampled_peak_rss_bytes"] = 1000
    elif defect == "fresh":
        for r in memory:
            r["fresh_process"] = False
    elif defect == "cohort":
        reports[0]["provenance"]["cohort_sha256"] = "other"
    elif defect == "case_hash":
        reports[0]["provenance"]["inputs_sha256"] = "other"
    elif defect == "incremental_hash":
        reports[-1]["provenance"]["inputs_sha256"] = "other"
    elif defect == "measurement_id":
        memory[1]["measurement_id"] = memory[0]["measurement_id"]
    elif defect == "memory_hash":
        for r in memory:
            r["inputs_sha256"] = "other"
    else:
        for r in reports:
            if defect == "parity":
                r["runs"][0]["result_digest"] = "different"
            elif defect == "duplicate_pair":
                r["pairs"][1] = dict(r["pairs"][0])
            elif defect == "empty_pair":
                r["pairs"] = [{}] * 5
            elif defect == "duplicate_run":
                r["runs"][1] = dict(r["runs"][0])
            elif defect == "negative_time":
                set_time(r, r["candidate"], -1.0)
            elif defect == "nan_time":
                set_time(r, r["candidate"], float("nan"))
            else:
                r["runs"][0]["wall_seconds"] += 1
    assert select_default(reports, memory)["selected_profile"] == "baseline"


def test_selection_recomputes_flags_and_cohort_excludes_request():
    from tools.accept_gear_desktop_profiles import cohort_hash, select_default

    case, _ = load_benchmark_case("single_ranged")
    other = case.request.model_copy(update={"budget_gp": case.request.budget_gp + 1})
    from dataclasses import replace

    assert cohort_hash(case) == cohort_hash(replace(case, request=other))
    reports, memory = selection_inputs()
    for row in reports:
        row["decision"] = {"repeatable_gain": False, "no_material_regression": False}
    assert select_default(reports, memory)["selected_profile"] == "combined"
