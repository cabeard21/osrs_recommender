"""Interleaved paired comparisons must preserve complete results and policy."""

import json
from contextlib import contextmanager

import pytest

from tools.benchmark_gear_desktop import frozen_inputs, load_benchmark_case
from tools.compare_gear_desktop import compare, decision, load_frozen


def test_interleaves_warmups_and_pairs_preserving_complete_results(tmp_path, monkeypatch):
    case, provenance = load_benchmark_case("ranged_diagnostic")
    active = []
    modes = []

    @contextmanager
    def experiment(capacity):
        active.append(capacity)
        yield
        active.pop()

    monkeypatch.setattr("tools.compare_gear_desktop.ranged_experiment", experiment)

    def runner(*args, **kwargs):
        modes.append(active[-1] if active else None)
        assert kwargs == {
            "local_refinement": False,
            "_complete_frontiers": True,
            "_running_frontier": True,
        }
        return {"curve": [1], "search": {"nodes": 2, "timings_seconds": len(modes)}}

    report = compare(case, provenance, tmp_path, pairs=5, runner=runner)
    assert modes == [None, 65536, None, 65536, 65536, None, None, 65536, 65536, None, None, 65536]
    assert len(report["pairs"]) == 5
    assert len({row["result_digest"] for row in report["runs"]}) == 1
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert (tmp_path / "pair-5-cached.json").exists()


def test_changed_nested_result_fails(tmp_path):
    case, provenance = load_benchmark_case("single_ranged")
    calls = []

    def runner(*args, **kwargs):
        calls.append(1)
        return {"discipline_results": [{"curve": [len(calls)]}]}

    with pytest.raises(ValueError, match="parity"):
        compare(case, provenance, tmp_path, runner=runner)


@pytest.mark.parametrize("pairs,warmups", [(4, 1), (5, -1)])
def test_invalid_counts(tmp_path, pairs, warmups):
    case, provenance = load_benchmark_case("single_ranged")
    with pytest.raises(ValueError, match="pairs"):
        compare(case, provenance, tmp_path, pairs=pairs, warmups=warmups)


def test_decision_requires_gain_above_both_noise_estimates():
    accepted = decision([10, 10, 10, 10, 10], [8, 8, 8, 8, 8])
    assert accepted["repeatable_gain"] is True
    rejected = decision([7, 8, 10, 12, 13], [9, 9, 9, 9, 9])
    assert rejected["repeatable_gain"] is False


def test_frozen_preserves_settings_and_revalidates_inputs(tmp_path):
    case, provenance = load_benchmark_case("ranged_diagnostic")
    data = {**frozen_inputs(case), "benchmark": {**provenance, "optimization_mode": "thorough"}}
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(data, default=str))
    replay, settings = load_frozen(path)
    assert settings["optimization_mode"] == "thorough"
    assert settings["diagnostic"] is True
    assert replay.request == case.request
    assert settings["inputs_sha256"] == provenance["inputs_sha256"]


def test_cli_named_and_frozen_inputs(tmp_path, monkeypatch, capsys):
    import sys

    from tools import compare_gear_desktop as tool

    case, provenance = load_benchmark_case("single_ranged")
    seen = []
    monkeypatch.setattr(tool, "load_frozen", lambda _: (case, provenance))

    def comparison(case, provenance, output, **kwargs):
        seen.append((provenance, kwargs))
        return {"decision": {"repeatable_gain": False}}

    monkeypatch.setattr(tool, "compare", comparison)
    monkeypatch.setattr(
        sys, "argv", ["compare", "--case", "single_ranged", "--output", str(tmp_path)]
    )
    tool.main()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            "--frozen",
            "x",
            "--output",
            str(tmp_path),
            "--thorough",
            "--diagnostic",
            "--experiment",
            "lazy-reporting",
        ],
    )
    tool.main()
    assert seen[1][0]["optimization_mode"] == "thorough"
    assert seen[1][0]["diagnostic"] is True
    assert seen[1][1]["experiment"] == "lazy-reporting"
    assert "repeatable_gain" in capsys.readouterr().out


def test_decision_rejects_unpaired_timings():
    with pytest.raises(ValueError, match="Paired"):
        decision([], [])


def test_lazy_reporting_context_is_candidate_only(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    from tools import compare_gear_desktop as tool
    from tracker.gear.ranged_numerics import active

    selected = []
    observed = []

    @contextmanager
    def lazy_reporting():
        selected.append(True)
        try:
            yield
        finally:
            selected.pop()

    monkeypatch.setitem(
        sys.modules, "tracker.gear.lazy_reporting", SimpleNamespace(lazy_reporting=lazy_reporting)
    )

    def no_ranged_cache(*args):
        raise AssertionError("Numerical cache must be disabled")

    monkeypatch.setattr(tool, "ranged_experiment", no_ranged_cache)

    def runner(*args, **kwargs):
        assert not active()
        observed.append(bool(selected))
        return {"curve": [1]}

    case, provenance = load_benchmark_case("single_ranged")
    report = compare(case, provenance, tmp_path, experiment="lazy-reporting", runner=runner)
    assert observed == [
        False,
        True,
        False,
        True,
        True,
        False,
        False,
        True,
        True,
        False,
        False,
        True,
    ]
    assert report["experiment"] == "lazy-reporting"
    assert report["capacity"] is None
    assert report["decision"]["lazy_median_seconds"] > 0
    assert (tmp_path / "pair-5-lazy.json").exists()
    assert "cache" not in report["runs"][1]


def test_unknown_experiment_rejected(tmp_path):
    case, provenance = load_benchmark_case("single_ranged")
    with pytest.raises(ValueError, match="experiment"):
        compare(case, provenance, tmp_path, experiment="other")


def test_lazy_rejects_active_numerical_cache(tmp_path):
    from tracker.gear.ranged_numerics import ranged_experiment

    case, provenance = load_benchmark_case("single_ranged")
    with ranged_experiment(1), pytest.raises(ValueError, match="disabled"):
        compare(case, provenance, tmp_path, experiment="lazy-reporting")


@pytest.mark.parametrize("experiment", ["ranged-cache", "lazy-reporting"])
def test_ambient_lazy_context_rejected_for_all_experiments(tmp_path, experiment):
    from tracker.gear.lazy_reporting import lazy_reporting

    case, provenance = load_benchmark_case("single_ranged")
    with lazy_reporting(), pytest.raises(ValueError, match="Lazy reporting must be disabled"):
        compare(case, provenance, tmp_path, experiment=experiment)


def test_fixed_comparison_uses_combined_both_sides(tmp_path):
    from tracker.gear.fixed_reporting import active, fixed_reporting

    case, provenance = load_benchmark_case("single_ranged")
    modes = []

    def runner(*args, **kwargs):
        assert kwargs["_execution_profile"] == "combined"
        modes.append(active())
        return {"curve": [1]}

    report = compare(case, provenance, tmp_path, experiment="fixed-reporting", runner=runner)
    assert modes == [False, True, False, True, True, False, False, True, True, False, False, True]
    assert report["experiment"] == "fixed-reporting"
    assert "fixed_median_seconds" in report["decision"]
    with pytest.raises(ValueError, match="Fixed reporting"), fixed_reporting():
        compare(case, provenance, tmp_path, runner=runner)


def test_ranged_finalization_context_is_candidate_only_with_combined_fixed_execution(tmp_path):
    from tracker.gear.ranged_score_finalization import active

    case, provenance = load_benchmark_case("ranged_diagnostic")
    observed = []

    def runner(*args, **kwargs):
        assert kwargs == {
            "local_refinement": False,
            "_execution_profile": "combined",
            "_fixed_reporting": True,
            "_complete_frontiers": True,
            "_running_frontier": True,
        }
        observed.append(active())
        return {"curve": [1]}

    report = compare(
        case, provenance, tmp_path, experiment="ranged-score-finalization", runner=runner
    )
    assert observed == [
        False,
        True,
        False,
        True,
        True,
        False,
        False,
        True,
        True,
        False,
        False,
        True,
    ]
    assert not active()
    assert report["experiment"] == "ranged-score-finalization"
    assert report["reference_implementation"] == "current_source_context_disabled"
    assert report["capacity"] is None
    assert "finalized_median_seconds" in report["decision"]
    assert (tmp_path / "pair-5-finalized.json").exists()
    assert len({row["result_digest"] for row in report["runs"]}) == 1
    assert all("cache" not in row for row in report["runs"])


@pytest.mark.parametrize(
    "experiment", ["ranged-cache", "lazy-reporting", "fixed-reporting", "ranged-score-finalization"]
)
def test_ambient_finalization_rejected_for_all_experiments(tmp_path, experiment):
    from tracker.gear.ranged_score_finalization import ranged_score_finalization

    case, provenance = load_benchmark_case("single_ranged")

    def unexpected(*args, **kwargs):
        pytest.fail("Ambient finalization must be rejected before optimization")

    with (
        ranged_score_finalization(),
        pytest.raises(ValueError, match="Finalization must be disabled"),
    ):
        compare(case, provenance, tmp_path, experiment=experiment, runner=unexpected)


def test_finalization_rejects_ambient_numerical_cache(tmp_path):
    from tracker.gear.ranged_numerics import ranged_experiment

    case, provenance = load_benchmark_case("single_ranged")
    with (
        ranged_experiment(1),
        pytest.raises(ValueError, match="Numerical experiment must be disabled"),
    ):
        compare(case, provenance, tmp_path, experiment="ranged-score-finalization")


@pytest.mark.parametrize("failure", ["runner", "parity"])
def test_finalization_context_resets_on_comparison_failure(tmp_path, failure):
    from tracker.gear.ranged_score_finalization import active

    case, provenance = load_benchmark_case("single_ranged")

    def runner(*args, **kwargs):
        if active() and failure == "runner":
            raise RuntimeError("fixture runner failure")
        return {"curve": [int(active())]}

    error = RuntimeError if failure == "runner" else ValueError
    with pytest.raises(error):
        compare(case, provenance, tmp_path, experiment="ranged-score-finalization", runner=runner)
    assert not active()


def test_cli_accepts_ranged_finalization_choice(tmp_path, monkeypatch):
    import sys

    from tools import compare_gear_desktop as tool

    observed = []

    def comparison(case, provenance, output, **kwargs):
        observed.append(kwargs["experiment"])
        return {"decision": {"repeatable_gain": False}}

    monkeypatch.setattr(tool, "compare", comparison)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "compare",
            "--case",
            "single_ranged",
            "--output",
            str(tmp_path),
            "--experiment",
            "ranged-score-finalization",
        ],
    )
    tool.main()
    assert observed == ["ranged-score-finalization"]
