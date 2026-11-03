"""Completed-assignment refinement preserves incumbents and counts bounded work."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tracker.gear.local_refinement import refine_completed
from tracker.gear.optimizer import OptimizationRequest, RoleConfig


def solution(equipment=None, score=1, actions=0):
    return {
        "score": score,
        "maximum_actions": actions,
        "loadouts": {"m": {"equipment": equipment or {"weapon": 100, "head": 1, "cape": 20}}},
    }


def key(row):
    return (-row["score"], tuple(sorted(row["loadouts"]["m"]["equipment"].items())))


class Search:
    def __init__(self, pair=False):
        self.request = OptimizationRequest(roles=(RoleConfig(id="m", style="slash"),))
        self.eligible = {
            i: SimpleNamespace(slot=s, bonuses=SimpleNamespace(melee_strength=0))
            for s, ids in {"weapon": (100,), "head": (1, 2), "cape": (20, 21)}.items()
            for i in ids
        }
        self.cancelled = None
        self.performance_cache = {}
        self.nodes = 15
        self.calls = []
        self.pair = pair

    def solution(self, assignments, limit):
        self.calls.append(deepcopy(assignments))
        e = assignments["m"]
        if "weapon" not in e:
            return None
        improved = e.get("head") == 2 and (not self.pair or e.get("cape") == 21)
        return solution(e, 2 if improved else 1)


def run(search, limit=2000):
    original = solution()
    return refine_completed(search, [original, original], original, key, limit=limit)


@pytest.mark.parametrize("pair", [False, True])
def test_exact_single_and_coordinated_pair_recovery_without_mutation(pair):
    search = Search(pair)
    before = solution()
    preserved = deepcopy(before)
    winners, unrestricted, diagnostic = refine_completed(search, [before, before], before, key)
    assert winners[0]["score"] == unrestricted["score"] == 2
    assert before == preserved
    assert diagnostic["baseline"] == {"curve_solutions": [before, before], "unrestricted": before}
    assert diagnostic["assignment_attempts"] == len(search.calls)
    assert diagnostic["objective_improvements"] > 0
    assert search.nodes == 15
    assert len({repr(sorted(a["m"].items())) for a in search.calls}) == len(search.calls)


@pytest.mark.parametrize("limit", [0, 1, 3, 5])
def test_work_budget_is_exact_and_incumbent_never_worsens(limit):
    search = Search(True)
    winners, unrestricted, diagnostic = run(search, limit)
    assert diagnostic["assignment_attempts"] == len(search.calls) <= limit
    assert diagnostic["work_budget_exhausted"]
    assert all(key(row) <= key(solution()) for row in [*winners, unrestricted])


@pytest.mark.parametrize("limit", [2001, 10_000])
def test_temporary_larger_budget_is_accepted(limit):
    _, _, diagnostic = run(Search(), limit)
    assert diagnostic["work_budget"] == limit
    assert diagnostic["assignment_attempts"] <= limit


@pytest.mark.parametrize("limit", [-1, 10_001, True, 1.0])
def test_invalid_budget(limit):
    with pytest.raises(ValueError, match="refinement limit"):
        run(Search(), limit)


def test_locked_and_utility_roles_are_unchanged():
    search = Search()
    search.request = search.request.model_copy(update={"locks": {"head": 1}})
    winners, _, diagnostic = run(search)
    assert all(e["m"].get("head") == 1 for e in search.calls)
    assert winners[0]["score"] == 1
    assert diagnostic["objective_improvements"] == 0


def test_no_feasible_seed_is_a_zero_work_skip():
    search = Search()
    winners, unrestricted, diagnostic = refine_completed(search, [None], None, key)
    assert winners == [None] and unrestricted is None
    assert diagnostic["assignment_attempts"] == 0
    assert diagnostic["reason"] == "no_valid_incumbent"


def test_cancellation_during_setup_and_evaluation():
    search = Search()
    search.cancelled = lambda: True
    with pytest.raises(ValueError, match="optimization_cancelled"):
        run(search)
    search = Search()
    search.cancelled = lambda: len(search.calls) >= 3
    with pytest.raises(ValueError, match="optimization_cancelled"):
        run(search)


def test_equal_dps_ties_are_counted_separately_and_deterministic():
    def tied_key(row):
        return (-row["score"], len(row["loadouts"]["m"]["equipment"]), key(row))

    first = refine_completed(Search(), [solution()], solution(), tied_key)
    second = refine_completed(Search(), [solution()], solution(), tied_key)
    assert first[:2] == second[:2]
    assert first[2]["tie_improvements"] > 0
    assert {k: v for k, v in first[2].items() if k != "duration_seconds"} == {
        k: v for k, v in second[2].items() if k != "duration_seconds"
    }


def test_accepted_neutral_history_survives_a_later_tie_breakpoint_valley():
    search = Search()
    search.eligible = {
        i: SimpleNamespace(slot=s, bonuses=SimpleNamespace(melee_strength=0))
        for s, ids in {
            "weapon": (100,),
            "head": (1, 2),
            "cape": (20, 21),
            "neck": (40, 41),
            "feet": (30, 31),
        }.items()
        for i in ids
    }
    original = solution({"weapon": 100, "head": 1, "cape": 20, "neck": 40, "feet": 30})

    def exact(assignments, limit):
        search.calls.append(deepcopy(assignments))
        e = assignments["m"]
        if e.get("weapon") != 100:
            return None
        if all(e.get(s) == i for s, i in {"head": 2, "cape": 21, "neck": 41, "feet": 30}.items()):
            return solution(e, 2)
        score = 1 if e.get("head") == 1 and e.get("neck") == 40 else 0.8
        return solution(e, score)

    def ordering(row):
        e = row["loadouts"]["m"]["equipment"]
        return (-row["score"], e.get("feet") != 31, e.get("cape") != 21, key(row))

    search.solution = exact
    winners, _, diagnostic = refine_completed(search, [original], original, ordering)
    assert winners[0]["score"] == 2
    assert diagnostic["tie_improvements"] > 0
    assert diagnostic["assignment_attempts"] <= diagnostic["work_budget"] == 10000
