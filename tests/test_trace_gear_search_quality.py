import pytest

from tools import trace_gear_search_quality
from tools.gear_search_quality_fixture import load_case
from tools.trace_gear_search_quality import trace_case
from tracker.gear import optimizer


def test_owned_trace_identifies_retained_neck_beam_loss():
    result = trace_case(load_case("owned_slash"))
    row = next(r for r in result["stages"] if r["stage"] == "role" and r["slot"] == "neck")
    assert result["baseline_score"] == 2.642031114341672
    assert row["first_witness_rank"] == 420
    assert row["beam_width"] == 128
    assert row["witness_item_ids"]["melee"] == 1725
    assert row["witness_retained_in_pool"]


def test_joint_trace_identifies_branch_omission():
    result = trace_case(load_case("joint_four"))
    row = next(
        r
        for r in result["stages"]
        if r["stage"] == "joint" and r["slot"] == "head" and r["limit"] == 4
    )
    assert row["choices"][0] == [None, 3753, 1017, 6326]
    assert row["witness_retained_in_pool"]
    assert row["first_witness_rank"] is None


@pytest.mark.parametrize("name", ["melee_1m", "melee_5m"])
def test_budget_trace_identifies_retained_hand_beam_loss(name):
    result = trace_case(load_case(name), bracelet=True)
    row = next(r for r in result["stages"] if r["stage"] == "role" and r["slot"] == "hands")
    assert row["first_witness_rank"] == 160
    assert row["expanded"] == 896
    assert row["witness_item_ids"]["melee"] == 11126
    assert row["witness_retained_in_pool"]


def test_observer_restores_search_class_after_failure(monkeypatch):
    original = optimizer._Search

    def fail(*args, **kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(optimizer, "optimize", fail)
    with pytest.raises(RuntimeError, match="test failure"):
        trace_case(load_case("melee_1m"), bracelet=True)
    assert optimizer._Search is original


def test_observer_rejects_unrecognized_search_structure(monkeypatch):
    original = optimizer._Search
    monkeypatch.setattr(
        trace_gear_search_quality.inspect, "getsource", lambda _: "class _Search: pass"
    )
    with pytest.raises(RuntimeError, match="Expected 2 beam retention sites, found 0"):
        trace_case(load_case("melee_1m"), bracelet=True)
    assert optimizer._Search is original
