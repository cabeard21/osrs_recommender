"""Completed tradeoffs must not retain avoidably empty equipment slots."""

from copy import deepcopy

import pytest

from tests.gear.test_optimizer import NOW, weapon
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.facts import equipment_fact
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search


def scenario(*, locks=None, reserved=12, owned=True, powered=False):
    items = [
        weapon(
            1,
            "magic",
            spell_compatibility=("earth_blast",),
            attack_profiles=(("magic", "accurate"),),
        ),
        weapon(
            2,
            "ranged",
            50,
            attack_profiles=(("ranged", "accurate"), ("ranged", "rapid"), ("ranged", "longrange")),
        ),
        EquipmentDefinition(
            id=3,
            name="Wizard boots",
            slot="feet",
            requirements_complete=True,
            bonuses=EquipmentBonuses(magic=4, defence_magic=4),
        ),
        EquipmentDefinition(
            id=4,
            name="Seers ring",
            slot="ring",
            requirements_complete=True,
            bonuses=EquipmentBonuses(magic=6, defence_magic=6),
        ),
        EquipmentDefinition(
            id=5,
            name="Granite boots",
            slot="feet",
            requirements_complete=True,
            bonuses=EquipmentBonuses(magic=-3, defence_ranged=8),
        ),
    ]
    if powered:
        items = [
            items[0].model_copy(
                update={
                    "powered_attack": "fixture",
                    "powered_attack_base_max_hit": 18,
                    "powered_attack_stances": ("accurate",),
                    "spell_compatibility": (),
                }
            ),
            *items[1:],
        ]
    snapshot = AccountSnapshot(
        1,
        "fixture",
        skills={
            k: SkillState(60, None, Source.MANUAL, NOW)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "fixture", NOW)
            for i in items
            if owned or i.id != 3
        },
    )
    request = OptimizationRequest(
        roles=(
            RoleConfig(id="mage", style="magic", spell="earth_blast", locks=locks or {}),
            RoleConfig(id="ranged", style="ranged", stance="rapid", weight=0.2),
        ),
        mode="owned",
        max_swaps=8,
        reserved_supply_slots=reserved,
        secondary_priority="magic_ranged_defence",
    )
    facts = {i.id: equipment_fact(snapshot, i, Content(), {}, NOW) for i in items}
    search = _Search(snapshot, request, {i.id: i for i in items}, facts, None)
    if powered:
        equipment = {"weapon": 1, "ring": 4}
        key = ("mage", tuple(sorted(equipment.items())))
        configured = request.roles[0].model_copy(update={"powered_attack": "fixture"})
        search.performance_cache[key] = search.evaluate(equipment, configured).model_dump(
            mode="json"
        )
        search.option_cache[key] = {
            "attack_type": "magic",
            "stance": "accurate",
            "spell": None,
            "powered_attack": "fixture",
        }
    seed = search.solution(
        {"mage": {"weapon": 1, "ring": 4}, "ranged": {"weapon": 2, "feet": 5}}, None
    )
    assert seed is not None
    return search, seed


def refine(search, seed, **kwargs):
    from tracker.gear.finalist_refinement import refine_finalist

    return refine_finalist(search, seed, **kwargs)


def test_fills_mage_boots_and_keeps_ring_on_ranged_without_mutating_seed():
    search, seed = scenario()
    before = deepcopy(seed)
    refined, diagnostics = refine(search, seed)
    assert refined["loadouts"]["mage"]["equipment"]["feet"] == 3
    assert refined["loadouts"]["ranged"]["equipment"]["ring"] == 4
    assert refined["score"] > seed["score"]
    assert refined["secondary_value"] > seed["secondary_value"]
    assert refined["maximum_actions"] <= seed["maximum_actions"]
    assert refined["max_gear_inventory_slots"] <= seed["max_gear_inventory_slots"]
    assert diagnostics["improvements"] >= 2
    assert seed == before


def test_respects_explicit_empty_lock_and_account_access():
    for search, seed in [scenario(locks={"feet": None}), scenario(owned=False)]:
        refined, _ = refine(search, seed)
        assert "feet" not in refined["loadouts"]["mage"]["equipment"]


def test_preserves_chosen_combat_options_and_cache():
    search, seed = scenario()
    cache = dict(search.performance_cache)
    refined, _ = refine(search, seed)
    for rid, row in seed["loadouts"].items():
        assert refined["loadouts"][rid]["combat_option"] == row["combat_option"]
    assert dict(search.performance_cache) == cache


def test_bounded_and_cancellable():
    search, seed = scenario()
    refined, diagnostics = refine(search, seed, limit=0)
    assert refined == seed
    assert diagnostics["evaluated_assignments"] == 0
    assert diagnostics["work_budget_exhausted"]
    search.cancelled = lambda: True
    with pytest.raises(ValueError, match="optimization_cancelled"):
        refine(search, seed)


def test_publication_refines_even_when_exploration_produces_no_new_candidates(monkeypatch):
    import hashlib

    import tracker.gear.frontier as frontier

    search, seed = scenario()
    monkeypatch.setattr(_Search, "loadouts", lambda *args: [])
    monkeypatch.setattr(_Search, "joint_loadouts", lambda *args: [])
    monkeypatch.setattr(frontier, "_shared_assignments", lambda *args: [])
    monkeypatch.setattr(frontier, "_combat_variants", lambda *args: [])
    groups, diagnostics, _, _ = frontier.explore(search, [seed] * 9, seed, False)
    points = groups[8]["points"]
    assert len(points) == 1
    row = points[0]["solution"]
    assert row["loadouts"]["mage"]["equipment"]["feet"] == 3
    assert row["loadouts"]["ranged"]["equipment"]["ring"] == 4
    identity = hashlib.sha256(frontier._identity(row["loadouts"]).encode()).hexdigest()[:24]
    assert points[0]["id"] == f"frontier-8-{identity}"
    assert points[0]["dps_loss_pct"] == 0
    assert diagnostics["finalist_refinement"]["improved_finalists"] == 1


def test_each_finalist_receives_its_own_budget_and_results_are_deterministic():
    search, seed = scenario()
    first, work = refine(search, seed, limit=4)
    second, again = refine(search, seed, limit=4)
    assert first == second
    assert work == again
    assert work["evaluated_assignments"] == 4


def test_rejects_changes_that_increase_cost_inventory_or_directional_actions():
    from tracker.gear.finalist_refinement import _dominates

    _, seed = scenario()
    better = {**seed, "score": seed["score"] + 1}
    assert _dominates(better, seed)
    for field in (
        "purchase_cost_gp",
        "max_gear_inventory_slots",
        "gear_inventory_slots",
        "maximum_actions",
    ):
        assert not _dominates({**better, field: seed[field] + 1}, seed)
    transitions = [{**t, "action_count": t["action_count"] + 1} for t in seed["transitions"]]
    assert not _dominates({**better, "transitions": transitions}, seed)


def test_recorded_slow_attack_remains_slow_with_explicit_combat_filters():
    from tracker.gear.optimizer import CombatOptionFilters

    search, seed = scenario()
    roles = tuple(
        role.model_copy(
            update={
                "combat_options": CombatOptionFilters(
                    attack_types=("magic",) if role.id == "mage" else ("light",),
                    stances=("accurate", "rapid", "longrange"),
                    spells=("earth_blast",) if role.id == "mage" else (),
                )
            }
        )
        for role in search.request.roles
    )
    search.request = search.request.model_copy(update={"roles": roles})
    # Select an intentionally slower ranged stance, rather than its DPS winner.
    ranged = seed["loadouts"]["ranged"]
    configured = roles[1].model_copy(update={"stance": "longrange"})
    equipment = ranged["equipment"]
    key = ("ranged", tuple(sorted(equipment.items())))
    search.performance_cache[key] = search.evaluate(equipment, configured).model_dump(mode="json")
    search.option_cache[key] = {
        "attack_type": "light",
        "stance": "longrange",
        "spell": None,
        "powered_attack": None,
    }
    seed = search.solution({rid: row["equipment"] for rid, row in seed["loadouts"].items()}, None)
    refined, _ = refine(search, seed)
    assert refined["loadouts"]["ranged"]["combat_option"]["stance"] == "longrange"
    assert (
        refined["loadouts"]["ranged"]["performance"]["attack_interval"]
        == seed["loadouts"]["ranged"]["performance"]["attack_interval"]
    )
    assert refined["loadouts"]["mage"]["equipment"]["feet"] == 3


def test_uses_search_objective_instead_of_request_priority():
    search, seed = scenario()
    # Cost frontiers reuse the search with a custom secondary objective.
    search.secondary = lambda assignments: (
        -sum(10 for equipment in assignments.values() if equipment.get("feet") == 3)
    )
    assignment = {rid: row["equipment"] for rid, row in seed["loadouts"].items()}
    seed = search.solution(assignment, None)
    refined, _ = refine(search, seed)
    assert "feet" not in refined["loadouts"]["mage"]["equipment"]
    assert refined["secondary_value"] == 0


def test_keeps_powered_attack_when_filling_mage_boots():
    search, seed = scenario(powered=True)
    refined, _ = refine(search, seed)
    mage = refined["loadouts"]["mage"]
    assert mage["equipment"]["feet"] == 3
    assert mage["combat_option"]["powered_attack"] == "fixture"
    assert mage["performance"]["supported"]


@pytest.mark.parametrize("limit", [-1, 2049, True, 1.5])
def test_invalid_finalist_budget(limit):
    search, seed = scenario()
    with pytest.raises(ValueError, match="finalist limit"):
        refine(search, seed, limit=limit)
