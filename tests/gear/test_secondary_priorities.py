"""Secondary ordering never trades away ordinary-attack DPS."""

import pytest

from tests.gear.test_optimizer import run, weapon
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _solution_key


def armour(item_id, **bonuses):
    return EquipmentDefinition(
        id=item_id,
        name=str(item_id),
        slot="head",
        requirements_complete=True,
        bonuses=EquipmentBonuses(**bonuses),
    )


@pytest.mark.parametrize(
    "priority,bonuses,expected",
    [
        ("balanced_defence", {"defence_stab": 5, "defence_magic": 10}, 3),
        ("stab_defence", {"defence_stab": 7}, 7),
        ("slash_defence", {"defence_slash": 7}, 7),
        ("crush_defence", {"defence_crush": 7}, 7),
        ("ranged_defence", {"defence_ranged": 7}, 7),
        ("magic_defence", {"defence_magic": 7}, 7),
        ("magic_ranged_defence", {"defence_magic": 8, "defence_ranged": 3}, 3),
        ("prayer_bonus", {"prayer": 7}, 7),
        ("melee_strength_bonus", {"melee_strength": 1}, 1),
        ("ranged_strength_bonus", {"ranged_strength": 1}, 1),
        ("magic_damage_bonus", {"magic_damage": 1}, 1),
    ],
)
def test_equal_dps_prefers_selected_bonus(priority, bonuses, expected):
    items = [weapon(1, "slash"), armour(20, **bonuses)]
    result = run(
        items, (RoleConfig(id="a", style="slash"),), max_swaps=0, secondary_priority=priority
    )
    selected = result["selected_solution"]
    assert selected["loadouts"]["a"]["equipment"]["head"] == 20
    assert selected["secondary_priority"] == priority
    assert selected["secondary_value"] == expected


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_priority_switch_and_default_preservation_for_one_to_four_roles(count):
    roles = tuple(RoleConfig(id=f"r{i}", style="slash", weight=i + 1) for i in range(count))
    items = [weapon(1, "slash"), armour(20, prayer=9), armour(30, defence_stab=12)]
    ordinary = run(items, roles, max_swaps=0)
    explicit = run(items, roles, max_swaps=0, secondary_priority="default")
    assert ordinary == explicit
    for priority, item, value in [("prayer_bonus", 20, 9), ("stab_defence", 30, 12)]:
        result = run(items, roles, max_swaps=0, secondary_priority=priority)
        assert result["selected_solution"]["score"] == ordinary["selected_solution"]["score"]
        assert all(
            row["equipment"]["head"] == item
            for row in result["selected_solution"]["loadouts"].values()
        )
        assert result["selected_solution"]["secondary_value"] == value


def test_secondary_never_beats_even_the_smallest_primary_difference():
    base = {
        "max_gear_inventory_slots": 0,
        "purchase_cost_gp": 0,
        "transitions": [],
        "loadouts": {},
        "secondary_priority": "prayer_bonus",
    }
    lower = {**base, "score": 1.0, "secondary_value": 999}
    higher = {**base, "score": 1.0000000000000002, "secondary_value": 0}
    assert _solution_key(higher) < _solution_key(lower)


def test_unknown_priority_is_rejected():
    with pytest.raises(ValueError):
        OptimizationRequest(
            roles=(RoleConfig(id="a", style="slash"),), secondary_priority="survival"
        )


@pytest.mark.parametrize(
    "bonuses,expected",
    [
        ({}, 0),
        ({"defence_magic": 7}, 0),
        ({"defence_ranged": 7}, 0),
        ({"defence_magic": -8, "defence_ranged": 3}, -8),
        ({"defence_magic": 3, "defence_ranged": -8}, -8),
        ({"defence_magic": 8, "defence_ranged": 8}, 8),
        ({"defence_magic": 3, "defence_ranged": 8}, 3),
        ({"defence_magic": 8, "defence_ranged": 3, "defence_stab": 999}, 3),
    ],
)
def test_magic_ranged_defence_formula(bonuses, expected):
    from tracker.gear.priorities import secondary_value

    assert secondary_value("magic_ranged_defence", {"bonuses": bonuses}) == expected


def test_magic_ranged_defence_prefers_improving_the_weaker_bonus():
    items = [
        weapon(1, "slash"),
        armour(20, defence_magic=100, defence_ranged=10),
        armour(30, defence_magic=20, defence_ranged=20),
    ]
    result = run(
        items,
        (RoleConfig(id="a", style="slash"),),
        max_swaps=0,
        secondary_priority="magic_ranged_defence",
    )
    selected = result["selected_solution"]
    assert selected["loadouts"]["a"]["equipment"]["head"] == 30
    assert selected["secondary_value"] == 20


def test_magic_ranged_defence_uses_complete_loadout_bonuses():
    body = EquipmentDefinition(
        id=30,
        name="Complementary body",
        slot="body",
        requirements_complete=True,
        bonuses=EquipmentBonuses(defence_ranged=40),
    )
    result = run(
        [weapon(1, "slash"), armour(20, defence_magic=40), body],
        (RoleConfig(id="a", style="slash", locks={"head": 20, "body": 30}),),
        max_swaps=0,
        secondary_priority="magic_ranged_defence",
    )
    assert result["selected_solution"]["secondary_value"] == 40


def test_magic_ranged_defence_weights_each_roles_minimum():
    result = run(
        [
            weapon(1, "slash"),
            armour(20, defence_magic=100, defence_ranged=10),
            armour(30, defence_magic=20, defence_ranged=100),
        ],
        (
            RoleConfig(id="a", style="slash", weight=1, locks={"head": 20}),
            RoleConfig(id="b", style="slash", weight=3, locks={"head": 30}),
        ),
        max_swaps=1,
        secondary_priority="magic_ranged_defence",
    )
    assert result["selected_solution"]["secondary_value"] == 17.5


def test_active_time_weighting_excludes_utility_and_zero_weight_roles():
    items = [weapon(1, "slash"), armour(10, prayer=9), armour(20, prayer=3), armour(30, prayer=100)]
    roles = (
        RoleConfig(id="a", style="slash", weight=1, locks={"head": 10}),
        RoleConfig(id="b", style="slash", weight=3, locks={"head": 20}),
        RoleConfig(id="zero", style="slash", weight=0, locks={"head": 30}),
        RoleConfig(
            id="utility",
            style="special",
            weight=999,
            parent_role="a",
            locks={"weapon": 1, "head": 30},
        ),
    )
    result = run(items, roles, max_swaps=2, secondary_priority="prayer_bonus")
    assert result["selected_solution"]["secondary_value"] == 4.5
    assert result["active_time_shares"] == {"a": 0.25, "b": 0.75, "zero": 0}
    assert result["selected_solution"]["loadouts"]["utility"]["performance"]["dps"] is None


def test_accuracy_uses_evaluator_probability_with_normalized_weights():
    from tracker.gear.optimizer import _Search

    search = object.__new__(_Search)
    search.request = OptimizationRequest(
        roles=(
            RoleConfig(id="a", style="slash", weight=1),
            RoleConfig(id="b", style="magic", weight=3),
        ),
        secondary_priority="accuracy",
    )
    search.performance = lambda equipment, role: {"accuracy": {"a": 0.25, "b": 0.75}[role.id]}
    assert search.secondary({"a": {}, "b": {}}) == 0.625


def test_accuracy_breaks_real_equal_dps_tie_without_changing_primary_score():
    from tracker.gear.models import CombatTarget

    # Against this target both attack rolls are below defence: doubling the
    # attack roll and interval produces exactly equal ordinary-attack DPS.
    items = [
        weapon(1, "slash", attack_speed=2),
        EquipmentDefinition(
            id=2,
            name="More accurate slower weapon",
            slot="weapon",
            attack_styles=("slash",),
            attack_speed=4,
            requirements_complete=True,
            bonuses=EquipmentBonuses(slash=64),
        ),
    ]
    roles = (RoleConfig(id="a", style="slash", target=CombatTarget(defence_level=1000)),)
    ordinary = run(items, roles, max_swaps=0)["selected_solution"]
    accurate = run(items, roles, max_swaps=0, secondary_priority="accuracy")["selected_solution"]
    assert ordinary["loadouts"]["a"]["equipment"]["weapon"] == 1
    assert accurate["loadouts"]["a"]["equipment"]["weapon"] == 2
    assert ordinary["score"] == accurate["score"]
    assert accurate["secondary_value"] == accurate["loadouts"]["a"]["performance"]["accuracy"]


def test_secondary_candidates_survive_bounded_pool_and_beam_ties(monkeypatch):
    monkeypatch.setattr("tracker.gear.optimizer.CANDIDATES_PER_SLOT", 3)
    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", 1)
    items = [weapon(1, "slash"), *[armour(i, prayer=i) for i in range(10, 30)]]
    result = run(
        items, (RoleConfig(id="a", style="slash"),), max_swaps=0, secondary_priority="prayer_bonus"
    )
    assert result["search"]["candidate_truncation"]
    assert result["selected_solution"]["secondary_value"] == 29


def test_priority_preserves_exclusions_locks_and_directed_constraints():
    items = [weapon(1, "slash"), armour(10, prayer=9), armour(20, prayer=3), armour(30, prayer=100)]
    roles = (
        RoleConfig(id="a", style="slash", locks={"head": 20}),
        RoleConfig(id="b", style="slash"),
    )
    result = run(
        items,
        roles,
        max_swaps=0,
        secondary_priority="prayer_bonus",
        excluded_item_ids=(30,),
        transitions=(("a", "b"),),
        reserved_supply_slots=28,
    )
    selected = result["selected_solution"]
    assert selected["secondary_value"] == 3
    assert selected["loadouts"]["b"]["equipment"]["head"] == 20
    assert selected["maximum_actions"] == 0
    assert selected["max_gear_inventory_slots"] == 0


@pytest.mark.parametrize("count", [1, 2, 3, 4])
@pytest.mark.parametrize("priority", ["default", "prayer_bonus", "accuracy"])
def test_secondary_priority_survives_opt_in_refinement(monkeypatch, count, priority):
    from functools import partial

    from tracker.gear.optimizer import optimize

    items = [weapon(1, "slash"), armour(10, prayer=2), armour(20, prayer=8)]
    roles = tuple(RoleConfig(id=f"role-{i}", style="slash", weight=i + 1) for i in range(count))
    kwargs = {"max_swaps": 1, "secondary_priority": priority}
    baseline = run(items, roles, **kwargs)["selected_solution"]
    monkeypatch.setattr(
        "tests.gear.test_optimizer.optimize", partial(optimize, local_refinement=True)
    )
    result = run(items, roles, **kwargs)
    selected = result["selected_solution"]
    assert selected["secondary_priority"] == priority
    assert _solution_key(selected) <= _solution_key(baseline)
    assert len(selected["loadouts"]) == count
    assert result["search"]["local_refinement"]["work_budget"] == 2000
