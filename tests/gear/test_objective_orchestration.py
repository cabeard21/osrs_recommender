"""Complete objective archives survive all independent branch merges."""

from types import SimpleNamespace

import pytest

from tracker.gear.optimizer import OptimizationRequest, RoleConfig


def request(*, multi=False):
    return OptimizationRequest.model_validate(
        {
            "roles": [{"id": name, "style": "slash"} for name in (("a", "b") if multi else ("a",))],
            "max_swaps": 1,
            "max_dps_loss_pct": 0,
            "objectives": [{"kind": "prayer_bonus"}, {"kind": "magic_damage_bonus"}],
        }
    )


def solution(configured, name, dps, values, actions=0, potion=()):
    from tracker.gear.objectives import objective_definitions

    ids = [row["id"] for row in objective_definitions(configured.objectives)]
    return {
        "score": dps,
        "secondary_value": None,
        "secondary_priority": "default",
        "objective_values": dict(zip(ids, values, strict=True)),
        "maximum_actions": actions,
        "max_gear_inventory_slots": 0,
        "purchase_cost_gp": 0,
        "transitions": [],
        "potions": {"selected_ids": list(potion), "cost_per_application_gp": 0},
        "loadouts": {
            role.id: {
                "equipment": {"weapon": name},
                "combat_option": {"attack_type": "slash", "stance": "accurate"},
                "selected_prayer_ids": [],
            }
            for role in configured.roles
        },
    }


def branch(best, zero, rows):
    return {
        "selected_solution": best,
        "unrestricted": best,
        "curve": [{"solution": zero}, {"solution": best}],
        "objective_frontiers": [
            {
                "swap_limit": cap,
                "sampled": False,
                "points": [
                    {"solution": row}
                    for row in rows
                    if cap is None or row["maximum_actions"] <= cap
                ],
            }
            for cap in (0, 1, None)
        ],
        "secondary_frontiers": [],
        "running_cost_frontiers": [],
        "discipline_results": [],
        "items": [],
        "alternatives": [],
        "assumptions": {},
        "limitations": [],
        "search": {"explored_nodes": 1, "candidate_truncation": False},
    }


@pytest.mark.parametrize("mode", ["auto", "potion", "assignment"])
def test_merges_use_full_vectors_before_loss_filtering_and_keep_cap_feasibility(mode):
    configured = request(multi=mode == "assignment")
    high_dps = solution(configured, 1, 10, (1, 1), actions=1)
    low_cap = solution(configured, 2, 8, (1, 1))
    prayer = solution(configured, 3, 1, (20, 0))
    magic = solution(configured, 4, 1, (0, 20))
    dominated = solution(configured, 5, 0, (0, 0))
    branches = [
        branch(high_dps, low_cap, [high_dps, low_cap, dominated]),
        branch(prayer, prayer, [prayer, magic]),
    ]
    if mode == "auto":
        from tracker.gear.auto import merge_auto_results

        result = merge_auto_results(
            configured,
            list(zip(("melee", "magic"), branches, strict=True)),
            complete_frontiers=True,
        )
    elif mode == "assignment":
        from tracker.gear.discipline_assignments import merge_assignment_results

        result = merge_assignment_results(
            configured,
            list(zip(("a=melee", "a=magic"), branches, strict=True)),
            complete_frontiers=True,
        )
    else:
        from tracker.gear.potion_search import merge_results

        result = merge_results(configured, branches, complete_frontiers=True)
    groups = {row["swap_limit"]: row for row in result["objective_frontiers"]}
    for cap, expected in ((0, {2, 3, 4}), (1, {1, 3, 4}), (None, {1, 3, 4})):
        group = groups[cap]
        assert not group["sampled"]
        assert {
            next(iter(point["solution"]["loadouts"].values()))["equipment"]["weapon"]
            for point in group["points"]
        } == expected
        assert group["baseline_dps"] == (8 if cap == 0 else 10)
        assert any(point["dps_loss_pct"] > 0 for point in group["points"])


def test_vector_merge_uses_resource_ties_for_equal_vectors_and_keeps_selected_potions():
    from tracker.gear.potion_search import merge_results

    configured = request()
    first = solution(configured, 1, 10, (5, 5), potion=("strength",))
    second = solution(configured, 1, 10, (5, 5), potion=("super_strength",))
    third = solution(configured, 2, 10, (5, 5), potion=("strength",))
    result = merge_results(
        configured, [branch(first, first, [first]), branch(second, second, [second, third])]
    )
    assert all(len(group["points"]) == 1 for group in result["objective_frontiers"])
    assert all(group["points"][0]["solution"] == first for group in result["objective_frontiers"])


def test_finite_loss_cap_applies_after_combining_branch_baselines():
    from tracker.gear.potion_search import merge_results

    configured = request().model_copy(update={"max_dps_loss_pct": 15})
    high_dps = solution(configured, 1, 10, (1, 1), actions=1)
    low_cap = solution(configured, 2, 9, (2, 2))
    extreme = solution(configured, 3, 1, (20, 20))
    branches = [branch(high_dps, low_cap, [high_dps, low_cap]), branch(extreme, extreme, [extreme])]
    public = merge_results(configured, branches)
    complete = merge_results(configured, branches, complete_frontiers=True)
    assert [point["solution"]["score"] for point in public["objective_frontiers"][1]["points"]] == [
        10,
        9,
    ]
    assert len(complete["objective_frontiers"][1]["points"]) == 3
    assert len(public["objective_frontiers"][0]["points"]) == 1


def test_vector_merges_do_not_sample_large_archives_or_per_discipline_results():
    from tracker.gear.auto import merge_auto_results
    from tracker.gear.potion_search import merge_results

    configured = request()
    rows = [solution(configured, index + 1, 1, (index, 79 - index)) for index in range(80)]
    child = branch(rows[0], rows[0], rows)
    auto = merge_auto_results(configured, [("melee", child), ("magic", child)])
    result = merge_results(configured, [auto])
    for detail in [result, *result["discipline_results"]]:
        assert all(len(group["points"]) == 80 for group in detail["objective_frontiers"])
        assert all(not group["sampled"] for group in detail["objective_frontiers"])
    point_ids = [
        point["id"]
        for detail in [result, *result["discipline_results"]]
        for group in detail["objective_frontiers"]
        for point in group["points"]
    ]
    assert len(point_ids) == len(set(point_ids))


def test_merge_rejects_sampled_or_missing_vector_branch_archives():
    from tracker.gear.potion_search import merge_objective_frontiers

    configured = request()
    with pytest.raises(ValueError, match="complete vector archives"):
        merge_objective_frontiers(configured, [{}])
    with pytest.raises(ValueError, match="complete vector archives"):
        merge_objective_frontiers(
            configured, [{"objective_frontiers": [{"swap_limit": 0, "sampled": True}]}]
        )


@pytest.mark.parametrize("case", ["shared", "conflicting_identity", "distinct_caps"])
def test_native_vector_merge_preserves_reference_and_shares_equivalent_caps(case):
    pytest.importorskip("tracker.gear.native._frontier")
    from tracker.gear.potion_search import merge_objective_frontiers
    from tracker.gear.vector_archive import VectorArchive, own_vector_archives
    from tracker.gear.vector_publish import FrontierPoints

    configured = request().model_copy(update={"max_dps_loss_pct": 50})
    rows = [
        [solution(configured, 1, 10, (1, 1)), solution(configured, 2, 6, (3, 3))],
        [solution(configured, 3, 10, (1, 1)), solution(configured, 4, 4, (5, 5))],
    ]
    if case == "conflicting_identity":
        rows[1][1] = solution(configured, 1, 4, (5, 5))
    elif case == "distinct_caps":
        rows[0][0]["maximum_actions"] = 1

    @own_vector_archives
    def compare():
        source = []
        for members in rows:
            archive = VectorArchive(tuple(objective.id for objective in configured.objectives))
            for row in members:
                archive.add(row)
            source.append(
                {
                    "objective_frontiers": [
                        {"swap_limit": cap, "points": FrontierPoints(archive, cap)}
                        for cap in (0, 1, None)
                    ],
                }
            )
        expected = merge_objective_frontiers(configured, source, id_prefix="discipline-test-")
        actual = merge_objective_frontiers(
            configured, source, id_prefix="discipline-test-", native_merge=True
        )
        actual_groups, expected_groups = (
            result["objective_frontiers"] for result in (actual, expected)
        )
        for actual_group, expected_group in zip(actual_groups, expected_groups, strict=True):
            assert {**actual_group, "points": list(actual_group["points"])} == {
                **expected_group,
                "points": list(expected_group["points"]),
            }
        assert len({group["points"].archive.path for group in actual_groups}) == (
            2 if case == "distinct_caps" else 1
        )
        discipline = merge_objective_frontiers(configured, source[:1], native_merge=True)
        assert (
            discipline["objective_frontiers"][1]["points"].archive
            is source[0]["objective_frontiers"][1]["points"].archive
        )

    compare()


def test_objective_skills_retain_defensive_potion_branches_and_validate_missing_magic():
    from tracker.gear.evaluation import validate_request_context
    from tracker.gear.potions import relevant_boost_skills

    configured = OptimizationRequest.model_validate(
        {
            "roles": [{"id": "a", "style": "slash"}],
            "objectives": [
                {"kind": "defence_roll", "styles": ["stab"], "aggregation": "minimum"},
                {"kind": "defence_roll", "styles": ["magic"], "aggregation": "mean"},
            ],
        }
    )
    assert relevant_boost_skills(configured) == {"attack", "strength", "defence", "magic"}
    snapshot = SimpleNamespace(skills={"defence": SimpleNamespace(level=70)})
    with pytest.raises(ValueError, match="unknown magic level"):
        validate_request_context(configured, snapshot, {}, None)


def test_branch_requests_keep_shared_typed_objective_configuration():
    from tests.gear.test_auto_disciplines import OPTIONS
    from tracker.gear.auto import branch_requests

    configured = request().model_copy(
        update={
            "roles": (
                RoleConfig(
                    id="a",
                    style="slash",
                    allowed_disciplines=("melee", "magic"),
                    combat_options=OPTIONS,
                ),
            )
        }
    )
    assert all(
        branch.objectives == configured.objectives for _, branch in branch_requests(configured)
    )


@pytest.mark.parametrize("mode", ["single", "multi", "auto"])
@pytest.mark.parametrize("potions", [False, True])
@pytest.mark.parametrize("include_cost", [False, True])
def test_real_vector_branches_match_native_without_fallback(mode, potions, include_cost):
    pytest.importorskip("tracker.gear.native._stages")
    from tests.gear.test_auto_disciplines import context
    from tests.gear.test_factored_multi import multi_case
    from tools.benchmark_objectives import _close_result, result_summary
    from tracker.gear.native import capture
    from tracker.gear.optimizer import optimize

    args = list(context() if mode == "auto" else multi_case(True))
    roles = args[1].roles[:1] if mode == "single" else args[1].roles
    args[1] = OptimizationRequest.model_validate(
        {
            **args[1].model_dump(mode="json"),
            "roles": [role.model_dump(mode="json") for role in roles],
            "secondary_priority": "default",
            "objectives": [
                {"kind": "defence_roll", "styles": ["stab", "magic"], "aggregation": "minimum"},
                {"kind": "prayer_bonus"},
                {"kind": "accuracy"},
                *([{"kind": "gp_per_damage"}] if include_cost else []),
            ],
            "potions": {"mode": "optimize", "allowed_ids": ["super_defence", "magic"]}
            if potions
            else {"mode": "disabled"},
        }
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
    }
    reference = actual = None
    try:
        reference = optimize(*args, **flags)
        with capture() as evidence:
            actual = optimize(*args, **flags, _native_search=True)
        assert result_summary(actual) == result_summary(reference)
        assert evidence.snapshot()["native_requests"] >= 1
        assert evidence.snapshot()["fallback_requests"] == 0
    finally:
        _close_result(reference)
        _close_result(actual)


@pytest.mark.parametrize("unpriced_dps", [9, 10])
def test_unpriced_dps_winner_survives_merge_and_defines_cap(unpriced_dps):
    from tracker.gear.objectives import ObjectiveDescriptor, objective_definitions
    from tracker.gear.potion_search import merge_results

    configured = request().model_copy(
        update={"objectives": (ObjectiveDescriptor(kind="gp_per_damage"),)}
    )
    definitions = objective_definitions(configured.objectives)
    numeric = {**solution(configured, 1, 9, (3,)), "objective_definitions": definitions}
    baseline = {
        **solution(configured, 2, unpriced_dps, (0,)),
        "objective_definitions": definitions,
        "objective_values": {},
    }
    children = [branch(baseline, baseline, []), branch(numeric, numeric, [numeric])]
    for child in children:
        for group in child["objective_frontiers"]:
            row = child["selected_solution"]
            group.update(baseline_dps=row["score"], baseline_solution=row)
    expected = baseline if unpriced_dps > 9 else numeric
    result = merge_results(configured, children)
    try:
        assert result["selected_solution"] == expected
        for group in result["objective_frontiers"]:
            assert group["baseline_solution"] == expected
            assert group["baseline_dps"] == expected["score"]
            assert [p["solution"] for p in group["points"]] == (
                [] if unpriced_dps > 9 else [numeric]
            )
    finally:
        for group in result["objective_frontiers"]:
            group["points"].close()


@pytest.mark.parametrize("mode", ["auto", "potion", "assignment"])
def test_lower_wilderness_loss_survives_branch_merge_with_running_cost(mode):
    from tracker.gear.auto import merge_auto_results
    from tracker.gear.discipline_assignments import merge_assignment_results
    from tracker.gear.objective_store import close_result_archives
    from tracker.gear.potion_search import merge_results

    configured = OptimizationRequest.model_validate(
        {
            **request(multi=mode == "assignment").model_dump(),
            "wilderness": {"skulled": True},
            "objectives": [{"kind": "gp_per_damage"}, {"kind": "wilderness_loss_gp"}],
            "max_dps_loss_pct": 100,
        }
    )
    fastest = solution(configured, 1, 10, (2, 100))
    safe = solution(configured, 2, 8, (2, 0))
    efficient = solution(configured, 3, 9, (1, 150))
    dominated = solution(configured, 4, 8, (3, 90))
    branches = [
        branch(fastest, fastest, [fastest, dominated]),
        branch(efficient, efficient, [efficient, safe]),
    ]
    if mode == "auto":
        result = merge_auto_results(
            configured, list(zip(("melee", "magic"), branches, strict=True))
        )
    elif mode == "assignment":
        result = merge_assignment_results(
            configured, list(zip(("a=melee", "a=magic"), branches, strict=True))
        )
    else:
        result = merge_results(configured, branches)
    try:
        for g in result["objective_frontiers"]:
            assert g["baseline_dps"] == 10
            assert {
                (p["solution"]["score"], p["solution"]["objective_values"]["wilderness_loss_gp"])
                for p in g["points"]
            } == {(10, 100), (8, 0), (9, 150)}
    finally:
        close_result_archives(result)
