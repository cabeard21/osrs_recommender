from tests.gear.test_optimizer import NOW, run, weapon
from tracker.gear.optimizer import RoleConfig
from tracker.gear.potions import potion_setups


def test_fixed_potions_increase_score_without_changing_gear():
    items = [weapon(1, "slash", 40)]
    roles = (RoleConfig(id="a", style="slash"),)
    base = run(items, roles, max_swaps=0)
    boosted = run(
        items, roles, max_swaps=0, potions={"mode": "fixed", "selected_ids": ("super_strength",)}
    )
    assert boosted["selected_solution"]["score"] > base["selected_solution"]["score"]
    assert boosted["selected_solution"]["potions"]["selected_ids"] == ["super_strength"]


def test_optimized_potions_merge_curve_and_preserve_setup():
    result = run(
        [weapon(1, "slash", 40)],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=1,
        potions={"mode": "optimize", "allowed_ids": ("super_strength",)},
    )
    assert result["selected_solution"]["potions"]["selected_ids"] == ["super_strength"]
    assert all(
        p["solution"]["potions"] == result["selected_solution"]["potions"] for p in result["curve"]
    )
    assert result["search"]["potion_selection"]["branch_count"] == 2


def test_empty_potion_allowlist_preserves_unboosted_score():
    items = [weapon(1, "slash", 40)]
    roles = (RoleConfig(id="a", style="slash"),)
    base = run(items, roles, max_swaps=0)
    result = run(items, roles, max_swaps=0, potions={"mode": "optimize"})
    assert result["selected_solution"]["score"] == base["selected_solution"]["score"]


def test_potion_frontier_point_ids_are_unique_across_caps_and_disciplines():
    from tests.gear.test_auto_disciplines import OPTIONS

    for auto in (False, True):
        role = RoleConfig(
            id="a",
            style="slash",
            combat_options=OPTIONS,
            allowed_disciplines=("melee",) if auto else None,
        )
        result = run(
            [weapon(1, "slash", 40, attack_profiles=(("slash", "accurate"),))],
            (role,),
            max_swaps=2,
            secondary_priority="balanced_defence",
            potions={"mode": "optimize", "allowed_ids": ("super_strength",)},
        )
        ids = [
            point["id"]
            for detail in [result, *result.get("discipline_results", [])]
            for field in ("secondary_frontiers", "running_cost_frontiers")
            for group in detail.get(field, [])
            for point in group["points"]
        ]
        assert len(ids) >= 4
        assert len(ids) == len(set(ids)), (auto, ids)


def test_potion_profiles_prepare_account_facts_once(monkeypatch):
    import tracker.gear.optimizer as optimizer

    original = optimizer.equipment_fact
    calls = []

    def counted(*args, **kwargs):
        calls.append(args[1].id)
        return original(*args, **kwargs)

    monkeypatch.setattr(optimizer, "equipment_fact", counted)
    result = run(
        [weapon(1, "slash", 40)],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        potions={"mode": "optimize", "allowed_ids": ("strength", "super_strength")},
    )
    assert result["search"]["potion_selection"]["branch_count"] == 3
    assert calls == [1]
    assert result["search"]["potion_selection"]["timings_seconds"]["preparation"] >= 0


def test_potion_progress_reports_completed_profiles_and_phase_timings():
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.optimizer import optimize
    from tracker.gear.potions import PotionPolicy

    args = context()
    role = args[1].roles[0].model_copy(update={"allowed_disciplines": None})
    request = args[1].model_copy(
        update={
            "roles": (role,),
            "potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength",)),
        }
    )
    events = []
    result = optimize(args[0], request, *args[2:], progress=events.append)
    completed = [e["completed_profiles"] for e in events if e["phase"] == "profile_completed"]
    assert completed == [1, 2]
    assert events[-1]["phase"] == "complete"
    assert events[-1]["total_profiles"] == 2
    assert all(value >= 0 for value in result["search"]["timings_seconds"].values())


def test_small_multi_oracle_matches_every_gear_and_potion_assignment():
    from itertools import product

    items = [weapon(1, "slash", 40), weapon(2, "slash", 55)]
    roles = (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="slash"))
    allowed = ("strength", "super_strength")
    result = run(items, roles, max_swaps=1, potions={"mode": "optimize", "allowed_ids": allowed})
    rows = []
    for setup, left, right in product(
        potion_setups({"strength": 70}, allowed, {}, NOW), (1, 2), (1, 2)
    ):
        fixed_roles = tuple(
            r.model_copy(update={"locks": {"weapon": item}})
            for r, item in zip(roles, (left, right), strict=True)
        )
        fixed = run(
            items, fixed_roles, max_swaps=1, potions={"mode": "fixed", "selected_ids": setup}
        )
        if fixed["selected_solution"]:
            rows.append(fixed["selected_solution"])
    assert result["selected_solution"]["score"] == max(r["score"] for r in rows)
    setup = result["selected_solution"]["potions"]
    assert setup["boosted_levels"]["strength"] == 85
    assert len(result["selected_solution"]["loadouts"]) == 2


def test_auto_discipline_first_matches_potion_first():
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.auto import optimize_auto
    from tracker.gear.optimizer import optimize
    from tracker.gear.potions import PotionPolicy

    args = context("melee")
    request = args[1].model_copy(
        update={"potions": PotionPolicy(mode="optimize", allowed_ids=("super_strength",))}
    )
    potion_first = optimize(args[0], request, *args[2:])

    # Same ordering as spawned workers: each discipline runs its potion search.
    def worker(*worker_args, **options):
        from tracker.gear.auto import branch_requests

        return [
            (d, optimize(worker_args[0], r, *worker_args[2:]))
            for d, r in branch_requests(worker_args[1])
        ]

    discipline_first = optimize_auto(args[0], request, *args[2:], branch_runner=worker)
    assert potion_first["selected_solution"] == discipline_first["selected_solution"]


def test_auto_potions_search_only_discipline_relevant_profiles():
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.optimizer import optimize
    from tracker.gear.potions import PotionPolicy

    args = context()
    request = args[1].model_copy(
        update={
            "potions": PotionPolicy(
                mode="optimize",
                allowed_ids=(
                    "attack",
                    "strength",
                    "defence",
                    "combat",
                    "super_attack",
                    "super_strength",
                    "super_defence",
                    "super_combat",
                    "ranging",
                    "magic",
                ),
            )
        }
    )
    jobs = []
    events = []

    def runner(snapshot, original, *rest, branches, progress, **options):
        jobs.extend(branches)
        return [optimize(snapshot, branch, *rest, **options) for branch in branches]

    result = optimize(
        *[args[0], request, *args[2:]], potion_branch_runner=runner, progress=events.append
    )
    assert len(jobs) == 13
    assert all(job.roles[0].allowed_disciplines is None for job in jobs)
    assert result["search"]["potion_selection"]["branch_count"] == 13
    assert events[-1]["total_profiles"] == 13
    assert {d["discipline"] for d in result["discipline_results"]} == {
        "melee",
        "ranged",
        "magic",
    }
    assert result["search"]["discipline_selection"]["branch_count"] == 3


def test_relevant_auto_profiles_match_full_cartesian_oracle():
    from tests.gear.test_auto_disciplines import context
    from tracker.gear.optimizer import _solution_key, optimize
    from tracker.gear.potions import PotionPolicy

    args = context()
    allowed = ("attack", "strength", "super_attack", "super_strength", "ranging", "magic")
    request = args[1].model_copy(
        update={"potions": PotionPolicy(mode="optimize", allowed_ids=allowed)}
    )
    result = optimize(args[0], request, *args[2:])
    levels = {key: skill.level for key, skill in args[0].skills.items()}
    exhaustive = [
        optimize(
            args[0],
            request.model_copy(
                update={
                    "potions": PotionPolicy(mode="fixed", selected_ids=setup),
                }
            ),
            *args[2:],
        )
        for setup in potion_setups(levels, allowed, {}, args[-1])
    ]
    expected = min((r["selected_solution"] for r in exhaustive), key=_solution_key)
    assert result["selected_solution"] == expected
    for discipline in result["discipline_results"]:
        expected = min(
            (
                d["selected_solution"]
                for r in exhaustive
                for d in r["discipline_results"]
                if d["discipline"] == discipline["discipline"]
                and d["selected_solution"] is not None
            ),
            key=_solution_key,
            default=None,
        )
        assert discipline["selected_solution"] == expected


def test_complete_potion_merge_defers_loss_cap_until_outer_merge():
    from tracker.gear.optimizer import OptimizationRequest
    from tracker.gear.potion_search import merge_results

    result = run(
        [weapon(1, "slash", 40)],
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
    )
    best = {**result["selected_solution"], "score": 10, "secondary_value": 1}
    defensive = {**best, "score": 1, "secondary_value": 100}
    branch = {
        **result,
        "secondary_frontiers": [
            {
                "swap_limit": 0,
                "points": [{"solution": best}, {"solution": defensive}],
            }
        ],
    }
    request = OptimizationRequest(roles=(RoleConfig(id="a", style="slash"),), max_swaps=0)
    full = merge_results(request, [branch], complete_frontiers=True)
    public = merge_results(request, [branch])
    assert len(full["secondary_frontiers"][0]["points"]) == 2
    assert len(public["secondary_frontiers"][0]["points"]) == 1


def test_running_frontier_breaks_equivalent_rows_by_potion_cost():
    from tracker.gear.running_frontier import cost_pareto

    result = run([weapon(1, "slash", 40)], (RoleConfig(id="a", style="slash"),), max_swaps=0)
    row = result["selected_solution"]
    expensive = {
        **row,
        "running_cost": {"gp_per_damage": 1},
        "potions": {"selected_ids": ["strength"], "cost_per_application_gp": 100},
    }
    cheap = {**expensive, "potions": {"selected_ids": ["strength"], "cost_per_application_gp": 10}}
    assert cost_pareto([expensive, cheap]) == [cheap]


def test_potion_secondary_and_running_frontiers_preserve_selected_setup():
    result = run(
        [],
        (RoleConfig(id="a", style="magic"),),
        max_swaps=0,
        secondary_priority="prayer_bonus",
        max_dps_loss_pct=100,
        potions={"mode": "optimize", "allowed_ids": ("magic",)},
    )
    assert result["secondary_frontiers"]
    assert result["running_cost_frontiers"]
    for group in result["secondary_frontiers"]:
        for point in group["points"]:
            assert "potions" in point["solution"]
