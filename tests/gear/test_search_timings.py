"""Orchestration wall time is distinct from every concrete profile's work."""

import pytest

from tests.gear.test_auto_disciplines import context
from tracker.gear import auto, optimizer, potion_search
from tracker.gear.potions import PotionPolicy


@pytest.mark.parametrize("parallel", [False, True])
def test_potion_summary_reports_whole_run_and_preserves_each_profile(monkeypatch, parallel):
    args = list(context())
    role = args[1].roles[0].model_copy(update={"allowed_disciplines": None})
    request = args[1].model_copy(
        update={
            "roles": (role,),
            "potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength",)),
        }
    )
    clock = [0.0]
    original = optimizer.optimize

    def profile(snapshot, fixed, *rest, **options):
        result = original(snapshot, fixed, *rest, **options)
        clock[0] += 4
        return {
            **result,
            "search": {
                **result["search"],
                "timings_seconds": {"gear_search": 1.0, "frontiers": 3.0, "total": 4.0},
            },
        }

    def worker(snapshot, submitted, *rest, branches, **options):
        rows = [profile(snapshot, fixed, *rest) for fixed in branches]
        clock[0] = 5.0  # Overlapping workers have less wall time than summed profile time.
        return rows

    monkeypatch.setattr(optimizer, "optimize", profile)
    monkeypatch.setattr(potion_search, "perf_counter", lambda: clock[0])
    result = potion_search.optimize_potions(
        args[0], request, *args[2:], branch_runner=worker if parallel else None
    )
    search = result["search"]
    selection = search["potion_selection"]
    total = 5.0 if parallel else 8.0
    assert search["timings_seconds"] == {
        "preparation": 0.0,
        "branches": total,
        "merge": 0.0,
        "total": total,
    }
    assert search["timings_seconds"] == selection["timings_seconds"]
    assert [p["selected_ids"] for p in selection["profiles"]] == [[], ["super_strength"]]
    assert all(p["discipline"] == "melee" for p in selection["profiles"])
    assert [p["search"]["timings_seconds"]["total"] for p in selection["profiles"]] == [4.0, 4.0]


@pytest.mark.parametrize("parallel", [False, True])
def test_auto_summary_reports_whole_run_without_relabelling_winner_phases(monkeypatch, parallel):
    args = context()
    clock = [0.0]
    original = optimizer.optimize

    def profile(*branch_args, **options):
        result = original(*branch_args, **options)
        clock[0] += 4
        return {
            **result,
            "search": {
                **result["search"],
                "timings_seconds": {"gear_search": 1.0, "frontiers": 3.0, "total": 4.0},
            },
        }

    def worker(snapshot, request, *rest, **options):
        rows = [(d, profile(snapshot, fixed, *rest)) for d, fixed in auto.branch_requests(request)]
        clock[0] = 5.0
        return rows

    monkeypatch.setattr(optimizer, "optimize", profile)
    monkeypatch.setattr(auto, "perf_counter", lambda: clock[0])
    result = auto.optimize_auto(*args, branch_runner=worker if parallel else None)
    search = result["search"]
    total = 5.0 if parallel else 12.0
    assert search["timings_seconds"] == {
        "branches": total,
        "merge": 0.0,
        "total": total,
    }
    assert all(
        branch["timings_seconds"]["total"] == 4.0
        for branch in search["discipline_selection"]["branches"].values()
    )


def test_merges_do_not_publish_a_selected_child_timer_as_the_whole_run():
    args = context()
    rows = []
    for discipline, request in auto.branch_requests(args[1]):
        result = optimizer.optimize(args[0], request, *args[2:])
        rows.append(
            (
                discipline,
                {**result, "search": {**result["search"], "timings_seconds": {"total": 4}}},
            )
        )
    merged_auto = auto.merge_auto_results(args[1], rows)
    merged_potions = potion_search.merge_results(args[1], [r for _, r in rows])
    assert "timings_seconds" not in merged_auto["search"]
    assert "timings_seconds" not in merged_potions["search"]
    assert all(
        "timings_seconds" in branch
        for branch in merged_auto["search"]["discipline_selection"]["branches"].values()
    )


def test_auto_potions_preserve_timings_for_all_concrete_profiles():
    args = list(context())
    args[1] = args[1].model_copy(
        update={"potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength",))}
    )
    result = optimizer.optimize(*args)
    profiles = result["search"]["potion_selection"]["profiles"]
    assert [(p["discipline"], p["selected_ids"]) for p in profiles] == [
        ("melee", []),
        ("melee", ["super_strength"]),
        ("ranged", []),
        ("magic", []),
    ]
    assert all(p["search"]["timings_seconds"]["total"] >= 0 for p in profiles)
    assert all(
        "timings_seconds" not in branch
        for branch in result["search"]["discipline_selection"]["branches"].values()
    )
