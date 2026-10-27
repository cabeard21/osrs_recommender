"""Physical exclusions apply before every search path and final publication."""

import pytest

from tests.gear.test_optimizer import run, weapon
from tracker.gear.optimizer import OptimizationRequest, RoleConfig


def test_empty_exclusions_preserve_results_and_alternatives():
    items = [weapon(1, "slash"), weapon(2, "slash", 50)]
    roles = (RoleConfig(id="single", style="slash"),)
    assert run(items, roles) == run(items, roles, excluded_item_ids=())


@pytest.mark.parametrize(
    "roles",
    [
        (RoleConfig(id="single", style="slash"),),
        (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="slash")),
        (RoleConfig(id="a", style="slash"), RoleConfig(id="b", style="ranged")),
        (
            RoleConfig(id="a", style="slash"),
            RoleConfig(id="s", style="special", parent_role="a", locks={"weapon": 1}),
        ),
    ],
)
def test_excluded_best_item_never_in_any_solution_or_alternative(roles):
    result = run(
        [weapon(1, "slash"), weapon(2, "slash", 50), weapon(3, "ranged")],
        roles,
        max_swaps=4,
        excluded_item_ids=(2,),
    )
    for solution in [
        result["selected_solution"],
        result["unrestricted"],
        *(p["solution"] for p in result["curve"]),
    ]:
        if solution:
            assert 2 not in solution["carried_item_ids"]
    assert all(row["item_id"] != 2 for rows in result["alternatives"].values() for row in rows)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"excluded_item_ids": (999,)},
        {"excluded_item_ids": (1,), "locks": {"weapon": 1}},
        {
            "excluded_item_ids": (1,),
            "roles": (RoleConfig(id="single", style="slash", locks={"weapon": 1}),),
        },
        {"assumed_item_ids": (999,), "mode": "future"},
    ],
)
def test_unknown_exclusions_assumptions_and_lock_conflicts_rejected(kwargs):
    roles = kwargs.pop("roles", (RoleConfig(id="single", style="slash"),))
    if "mode" in kwargs:
        # The direct request validator is shared by service and browser callers.
        from datetime import UTC, datetime
        from types import SimpleNamespace

        from tracker.accounts.snapshot import AccountSnapshot
        from tracker.content.loader import Content
        from tracker.gear.optimizer import optimize

        with pytest.raises(ValueError):
            optimize(
                AccountSnapshot(1, "test"),
                OptimizationRequest(roles=roles, **kwargs),
                SimpleNamespace(items={1: weapon(1, "slash")}),
                Content(),
                {},
                datetime.now(UTC),
            )
    else:
        with pytest.raises(ValueError):
            run([weapon(1, "slash")], roles, **kwargs)


def test_final_validation_and_contextual_alternatives_recheck_exclusions():
    from datetime import UTC, datetime

    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.facts import equipment_fact
    from tracker.gear.optimizer import _Search, _slot_alternatives

    now = datetime(2026, 10, 27, tzinfo=UTC)
    items = {1: weapon(1, "slash"), 2: weapon(2, "slash", 50)}
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={key: SkillState(70, None, Source.MANUAL, now) for key in ("attack", "strength")},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", now) for i in items
        },
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="single", style="slash"),), mode="owned", excluded_item_ids=(2,)
    )
    facts = {i: equipment_fact(snapshot, item, Content(), {}, now) for i, item in items.items()}
    search = _Search(snapshot, request, items, facts, None)
    assert search.solution({"single": {"weapon": 2}}, None) is None
    accepted = search.solution({"single": {"weapon": 1}}, None)
    assert accepted is not None
    search.pools["weapon"] = [2]
    assert _slot_alternatives(search, accepted)["weapon"] == []
