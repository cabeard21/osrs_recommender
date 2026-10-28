"""Additive omitted-head refinement validates complete, explicitly scoped trials."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tracker.gear.optimizer import OptimizationRequest, RoleConfig
from tracker.gear.targeted_retention import refine_omitted_heads


class Search:
    def __init__(self, *, heads=(12, 13), companions=None, invalid=()):
        self.request = OptimizationRequest(roles=(RoleConfig(id="m", style="slash"),))
        self.eligible = {
            i: SimpleNamespace(slot=s)
            for s, ids in {"head": (1, *heads), **(companions or {"cape": (20, 21)})}.items()
            for i in ids
        }
        self.pools = {"head": [None, 1]}
        self.cancelled = None
        self.nodes = 57
        self.performance_cache = {}
        self.calls = []
        self.invalid = invalid

    def solution(self, assignments, limit):
        equipment = assignments["m"]
        self.calls.append(deepcopy(equipment))
        if equipment.get("head") in self.invalid:
            return None
        score = 2 if equipment.get("head") == 12 and equipment.get("cape") == 21 else 1
        return solution(equipment, score)


def solution(equipment=None, score=1):
    return {
        "score": score,
        "loadouts": {
            "m": {
                "equipment": equipment or {"weapon": 100, "head": 1, "cape": 20},
                "performance": {"supported": True},
            }
        },
        "maximum_actions": 0,
    }


def key(row):
    return (-row["score"],)


def run(search, limit=2000):
    original = solution()
    return refine_omitted_heads(search, [original, original], original, key, limit=limit)


def test_pair_recovery_preserves_inputs_and_uses_all_companion_options():
    search = Search()
    original = solution()
    saved = deepcopy(original)
    winners, unrestricted, diagnostic = refine_omitted_heads(
        search, [original, original], original, key
    )
    assert winners[0]["score"] == unrestricted["score"] == 2
    assert original == saved
    assert diagnostic["baseline"] == {"curve_solutions": [saved, saved], "unrestricted": saved}
    assert diagnostic["assignment_attempts"] == len(search.calls) == 6
    assert diagnostic["valid_assignments"] == 6
    assert diagnostic["improvements_accepted"] == 1
    assert diagnostic["incumbent_replacements"] == 3
    assert diagnostic["inspected_item_ids"] == [12, 13]
    assert not diagnostic["work_budget_exhausted"]
    assert search.nodes == 57 and search.pools == {"head": [None, 1]}
    assert all(e["weapon"] == 100 for e in search.calls)


def test_round_robin_heads_and_slot_groups_and_true_exhaustion():
    search = Search(companions={"cape": (20, 21, 22, 23), "ring": (30, 31)})
    _, _, diagnostic = run(search, limit=6)
    assert [e["head"] for e in search.calls] == [12, 13, 12, 13, 12, 13]
    assert "cape" not in search.calls[2]
    assert search.calls[4]["ring"] == 30
    assert diagnostic["work_budget_exhausted"]
    assert diagnostic["assignment_attempts"] == 6
    assert run(Search(), limit=6)[2]["work_budget_exhausted"] is False


def test_invalid_trials_never_replace_original_and_zero_budget_is_exact():
    search = Search(invalid=(12, 13))
    winners, unrestricted, diagnostic = run(search)
    assert winners == [solution(), solution()] and unrestricted == solution()
    assert diagnostic["valid_assignments"] == diagnostic["improvements_accepted"] == 0
    untouched = Search()
    diagnostic = run(untouched, limit=0)[2]
    assert not untouched.calls and diagnostic["assignment_attempts"] == 0
    assert diagnostic["work_budget_exhausted"]


@pytest.mark.parametrize("limit", [-1, 2001, True])
def test_invalid_work_budget(limit):
    with pytest.raises(ValueError, match="refinement limit"):
        run(Search(), limit)


@pytest.mark.parametrize(
    "reason,update",
    [
        ("unsupported_scenario", {"roles": (RoleConfig(id="m", style="ranged"),)}),
        ("unsupported_scenario", {"loop": True}),
        ("unsupported_scenario", {"ordered_roles": ("m",)}),
        ("head_locked", {"locks": {"head": None}}),
    ],
)
def test_skip_conditions_preserve_every_incumbent(reason, update):
    search = Search()
    search.request = search.request.model_copy(update=update)
    winners, unrestricted, diagnostic = run(search)
    assert diagnostic["reason"] == reason and not diagnostic["triggered"]
    assert winners == [solution(), solution()] and unrestricted == solution()
    assert not search.calls


def test_no_omitted_heads_and_no_supported_baseline():
    search = Search(heads=())
    assert run(search)[2]["reason"] == "no_eligible_omitted_heads"
    search = Search()
    assert refine_omitted_heads(search, [None], None, key)[2]["reason"] == "no_supported_baseline"
    unsupported = solution()
    unsupported["loadouts"]["m"]["performance"]["supported"] = False
    assert (
        refine_omitted_heads(search, [unsupported], None, key)[2]["reason"]
        == "no_supported_baseline"
    )


def test_companion_locks_and_physical_trial_scope():
    search = Search()
    search.request = search.request.model_copy(update={"locks": {"cape": 20}})
    _, _, diagnostic = run(search)
    assert diagnostic["assignment_attempts"] == 2
    assert all(e["cape"] == 20 for e in search.calls)
    assert all(set(e) == {"weapon", "head", "cape"} for e in search.calls)


@pytest.mark.parametrize("cancel_at", [1, 5, 20, 45])
def test_cooperative_cancellation_during_preparation_and_trials(cancel_at):
    search = Search(companions={"cape": tuple(range(20, 80)), "ring": (90, 91)})
    checks = 0

    def cancelled():
        nonlocal checks
        checks += 1
        return checks == cancel_at

    search.cancelled = cancelled
    with pytest.raises(ValueError, match="optimization_cancelled"):
        run(search)


def test_determinism_and_distinct_seed_deduplication():
    search = Search()
    first = run(search)
    reversed_search = Search(heads=(13, 12), companions={"cape": (21, 20)})
    second = run(reversed_search)
    assert first[:2] == second[:2]
    assert search.calls == reversed_search.calls
    assert {k: v for k, v in first[2].items() if k != "duration_seconds"} == {
        k: v for k, v in second[2].items() if k != "duration_seconds"
    }


def test_distinct_seeds_produce_no_duplicate_complete_assignments():
    search = Search()
    search.eligible[2] = SimpleNamespace(slot="head")
    search.pools["head"].append(2)
    first = solution()
    second = solution({"weapon": 100, "head": 2, "cape": 20})
    _, _, diagnostic = refine_omitted_heads(search, [first, second], first, key, limit=6)
    assert diagnostic["assignment_attempts"] == 6
    assert not diagnostic["work_budget_exhausted"]
    assert len({tuple(sorted(e.items())) for e in search.calls}) == len(search.calls)


def test_multiple_roles_skip_before_interpreting_baseline():
    search = Search()
    search.request = search.request.model_copy(
        update={"roles": (RoleConfig(id="m", style="slash"), RoleConfig(id="r", style="ranged"))}
    )
    assert run(search)[2]["reason"] == "unsupported_scenario"
    assert not search.calls


def test_default_budget_caps_two_thousand_distinct_trials_without_starving_groups():
    search = Search(
        companions={"cape": (20, *range(1000, 3100)), "ring": (4000, 4001), "feet": (5000,)}
    )
    original = solution()
    baseline = deepcopy(original)
    pools = deepcopy(search.pools)
    _, _, diagnostic = refine_omitted_heads(search, [original, original], original, key)
    assert diagnostic["work_budget"] == diagnostic["assignment_attempts"] == 2000
    assert diagnostic["work_budget_exhausted"]
    assert len(search.calls) == len({tuple(sorted(e.items())) for e in search.calls}) == 2000
    assert diagnostic["inspected_item_ids"] == [12, 13]
    for head in (12, 13):
        trials = [e for e in search.calls if e["head"] == head]
        assert any(e.get("cape") == 1000 for e in trials)
        assert any(e.get("ring") == 4000 for e in trials)
        assert any(e.get("feet") == 5000 for e in trials)
    assert original == baseline
    assert diagnostic["baseline"] == {
        "curve_solutions": [baseline, baseline],
        "unrestricted": baseline,
    }
    assert search.nodes == 57 and search.pools == pools
