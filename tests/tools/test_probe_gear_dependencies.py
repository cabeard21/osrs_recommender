"""Bounded LRU measurements preserve chronological access order."""

import pytest

from tools.probe_gear_dependencies import summarize_accesses


def test_lru_counts_and_equivalence():
    report = summarize_accesses([((1,), (2,)), ((2,), (3,)), ((1,), (2,))], (1, 2))
    assert report["calls"] == 3
    assert report["distinct_keys"] == 2
    assert report["capacities"]["1"] == {"hits": 0, "misses": 3, "evictions": 2, "entries": 1}
    assert report["capacities"]["2"]["hits"] == 1
    with pytest.raises(ValueError, match="different"):
        summarize_accesses([((1,), (2,)), ((1,), (3,))])


def test_empty_and_invalid_capacity():
    assert summarize_accesses([])["calls"] == 0
    with pytest.raises(ValueError, match="positive"):
        summarize_accesses([], (0,))


def test_cli_portable_observation(tmp_path, monkeypatch, capsys):
    import sys
    from contextlib import contextmanager
    from types import SimpleNamespace

    from tools import probe_gear_dependencies as probe
    from tools.gear_search_quality_fixture import load_case

    case = load_case("melee_1m")
    monkeypatch.setattr(
        "tools.benchmark_gear_desktop.load_benchmark_case",
        lambda _: (case, {"optimization_mode": "fast"}),
    )
    monkeypatch.setattr("tracker.gear.optimizer.optimize", lambda *a, **k: {"curve": []})

    @contextmanager
    def observation(**kwargs):
        yield SimpleNamespace(accesses=[((1,), (2,)), ((1,), (2,))], key_seconds=0.0)

    monkeypatch.setattr("tracker.gear.ranged_numerics.ranged_experiment", observation)
    monkeypatch.setattr(
        sys, "argv", ["probe", "--case", "single_ranged", "--output", str(tmp_path)]
    )
    probe.main()
    import json

    report = json.loads((tmp_path / "probe.json").read_text())
    assert report["reuse"]["calls"] == 2
    assert report["reuse"]["capacities"]["4096"]["hits"] == 1
    assert "solution_digest" in capsys.readouterr().out
