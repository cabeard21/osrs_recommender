"""Equally scored shared ammunition must survive irrelevant-slot beam pruning."""

from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW, run, weapon
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.facts import equipment_fact
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search, _solution_key, optimize
from tracker.gear.refinement import refine_ammunition, refine_magic_staves, refine_shared_slots
from tracker.integrations.prices.client import PriceDTO, PriceSource


def ammunition_case():
    # The unused crossbow wins marginal scaffolding. Combined with neutral slot
    # choices it evicts the bow's strongest arrow from the melee role's beam.
    items = [
        weapon(100, "slash", 30),
        weapon(200, "ranged", 30, ammo_for=("arrow",), two_handed=True),
        weapon(300, "ranged", 100, ammo_for=("bolt",)),
    ]
    items.extend(
        EquipmentDefinition(
            id=item_id,
            name=name,
            slot="ammunition",
            ammo_type="arrow",
            requirements_complete=True,
            tradeable=True,
            bonuses=EquipmentBonuses(ranged_strength=strength),
        )
        for item_id, name, strength in (
            (884, "Iron arrow", 10),
            (886, "Steel arrow", 16),
            (888, "Mithril arrow", 22),
            (890, "Adamant arrow", 31),
        )
    )
    items.append(
        EquipmentDefinition(
            id=900,
            name="Unused strong bolt",
            slot="ammunition",
            ammo_type="bolt",
            requirements_complete=True,
            bonuses=EquipmentBonuses(ranged_strength=100),
        )
    )
    for index, slot in enumerate(("head", "cape", "neck")):
        items.extend(
            EquipmentDefinition(
                id=1000 + index * 10 + variant,
                name=f"Neutral {slot} {variant}",
                slot=slot,
                requirements_complete=True,
            )
            for variant in range(5)
        )
    roles = (
        RoleConfig(id="melee", style="slash", locks={"weapon": 100}),
        RoleConfig(id="ranged", style="ranged", locks={"weapon": 200}),
    )
    return items, roles


def assert_shared_adamant(solution):
    assert solution is not None
    assert {row["equipment"].get("ammunition") for row in solution["loadouts"].values()} == {890}
    assert solution["maximum_actions"] == 1
    assert all(t["action_count"] == 1 for t in solution["transitions"])
    assert all(a["slot"] != "ammunition" for t in solution["transitions"] for a in t["actions"])


@pytest.mark.parametrize("max_swaps", [1, 4])
def test_shared_arrows_remove_a_redundant_switch_and_fill_the_one_action_curve(max_swaps):
    items, roles = ammunition_case()
    result = run(items, roles, max_swaps=max_swaps)
    # Exact witness: sharing the ranged role's arrow is legal and equally strong.
    shared_roles = tuple(
        RoleConfig(**{**role.model_dump(), "locks": {**role.locks, "ammunition": 890}})
        for role in roles
    )
    witness = run(items, shared_roles, max_swaps=1)["selected_solution"]
    assert witness is not None
    assert_shared_adamant(result["curve"][1]["solution"])
    for point in result["curve"][1:]:
        assert_shared_adamant(point["solution"])
        assert point["solution"]["score"] >= witness["score"]
    assert_shared_adamant(result["unrestricted"])
    assert result["curve"][0]["solution"] is None


def test_explicit_different_arrow_locks_are_preserved():
    items, roles = ammunition_case()
    locked = tuple(
        RoleConfig(**{**r.model_dump(), "locks": {**r.locks, "ammunition": ammo}})
        for r, ammo in zip(roles, (884, 890), strict=True)
    )
    result = run(items, locked, max_swaps=4)
    assert result["curve"][1]["solution"] is None
    solution = result["selected_solution"]
    assert solution["loadouts"]["melee"]["equipment"]["ammunition"] == 884
    assert solution["loadouts"]["ranged"]["equipment"]["ammunition"] == 890
    assert solution["maximum_actions"] == 2


def test_purchased_shared_arrow_remains_one_union_purchase_at_exact_budget():
    items, roles = ammunition_case()
    snapshot = AccountSnapshot(
        1,
        "arrows",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i.id, Container.BANK): ObservedItemFact(i.id, Container.BANK, 1, "test", NOW)
            for i in items
            if i.id != 890
        },
    )
    price = PriceDTO(
        item_id=890,
        high_price_gp=500,
        high_trade_at=NOW,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=NOW,
        source=PriceSource.LIVE,
        provider="shared-arrow-test",
    )
    result = optimize(
        snapshot,
        OptimizationRequest(roles=roles, mode="usable", budget_gp=500, max_swaps=4),
        SimpleNamespace(items={i.id: i for i in items}, revision="arrow-regression"),
        Content(),
        {890: price},
        NOW,
    )
    solution = result["selected_solution"]
    assert_shared_adamant(solution)
    assert solution["purchase_cost_gp"] == 500
    assert len(solution["purchases"]) == 1
    assert solution["purchases"][0]["item_id"] == 890
    assert solution["purchases"][0]["cost_gp"] == 500


def test_ranged_strength_of_shared_arrow_does_not_change_melee_performance():
    items, roles = ammunition_case()
    catalog = {i.id: i for i in items}
    levels = {"attack": 70, "strength": 70}
    iron = evaluate_equipment({"weapon": 100, "ammunition": 884}, catalog, roles[0], levels)
    adamant = evaluate_equipment({"weapon": 100, "ammunition": 890}, catalog, roles[0], levels)
    empty = evaluate_equipment({"weapon": 100}, catalog, roles[0], levels)
    assert iron.supported and adamant.supported and empty.supported
    assert iron.dps == adamant.dps == empty.dps
    assert iron.max_hit == adamant.max_hit == empty.max_hit
    assert iron.bonuses.melee_strength == adamant.bonuses.melee_strength
    assert iron.bonuses.ranged_strength != adamant.bonuses.ranged_strength


def finalist_case(*, bonuses=None, roles=None, **request_changes):
    items, default_roles = ammunition_case()
    items = [item for item in items if item.slot in ("weapon", "ammunition")]
    if bonuses:
        items = [
            item.model_copy(update={"bonuses": EquipmentBonuses(ranged_strength=10, **bonuses)})
            if item.id == 884
            else item
            for item in items
        ]
    catalog = {item.id: item for item in items}
    snapshot = AccountSnapshot(
        1,
        "refinement",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (item.id, Container.BANK): ObservedItemFact(item.id, Container.BANK, 1, "test", NOW)
            for item in items
        },
    )
    request = OptimizationRequest(roles=roles or default_roles, mode="owned", **request_changes)
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in catalog.items()}
    return _Search(snapshot, request, catalog, facts, None)


def refine_finalist(search, loadouts):
    original = search.solution(loadouts, None)
    assert original is not None
    diagnostics = {"evaluated_assignments": 0, "improved_finalists": 0}
    return original, refine_ammunition(search, original, _solution_key, diagnostics), diagnostics


def test_shared_neutral_slots_can_improve_a_one_action_finalist():
    items = [
        weapon(100, "slash", 30),
        weapon(200, "ranged", 30),
        EquipmentDefinition(
            id=300, name="Shared cloak", slot="cape", requirements_complete=True,
            bonuses=EquipmentBonuses(defence_slash=5),
        ),
        EquipmentDefinition(
            id=400, name="Shared blessing", slot="ammunition", requirements_complete=True,
            bonuses=EquipmentBonuses(prayer=2),
        ),
    ]
    roles = (
        RoleConfig(id="melee", style="slash", locks={"weapon": 100}),
        RoleConfig(id="ranged", style="ranged", locks={"weapon": 200}),
    )
    catalog = {item.id: item for item in items}
    snapshot = AccountSnapshot(
        1, "shared", skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (item.id, Container.BANK): ObservedItemFact(item.id, Container.BANK, 1, "test", NOW)
            for item in items
        },
    )
    request = OptimizationRequest(roles=roles, mode="owned", max_swaps=1,
                                  secondary_priority="balanced_defence")
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in catalog.items()}
    search = _Search(snapshot, request, catalog, facts, None)
    original = search.solution({"melee": {"weapon": 100}, "ranged": {"weapon": 200}}, None)
    assert original is not None and original["maximum_actions"] == 1

    improved = refine_shared_slots(search, original, _solution_key)

    assert improved["maximum_actions"] == 1
    assert all(row["equipment"].get("cape") == 300 for row in improved["loadouts"].values())
    assert all(row["equipment"].get("ammunition") == 400 for row in improved["loadouts"].values())
    assert _solution_key(improved) < _solution_key(original)

    result = run(items, roles, max_swaps=1, secondary_priority="balanced_defence")
    selected = result["curve"][1]["solution"]
    assert selected is not None
    assert all(row["equipment"].get("cape") == 300 for row in selected["loadouts"].values())
    assert all(
        row["equipment"].get("ammunition") == 400 for row in selected["loadouts"].values()
    )


def test_missing_magic_staff_can_improve_a_one_action_finalist(monkeypatch):
    items = [
        weapon(100, "slash", 30),
        weapon(200, "ranged", 30),
        EquipmentDefinition(
            id=300, name="Staff of air", slot="weapon", attack_styles=("magic",),
            requirements_complete=True, bonuses=EquipmentBonuses(magic=10),
        ),
    ]
    roles = (
        RoleConfig(id="melee", style="slash"),
        RoleConfig(id="ranged", style="ranged"),
        RoleConfig(id="mage", style="magic", spell="wind_blast"),
    )
    catalog = {item.id: item for item in items}
    snapshot = AccountSnapshot(
        1, "staff", skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (item.id, Container.BANK): ObservedItemFact(item.id, Container.BANK, 1, "test", NOW)
            for item in items
        },
    )
    request = OptimizationRequest(roles=roles, mode="owned", max_swaps=1, base_role="melee")
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in catalog.items()}
    search = _Search(snapshot, request, catalog, facts, None)
    original = search.solution(
        {"melee": {"weapon": 100}, "ranged": {"weapon": 200}, "mage": {}}, None
    )
    assert original is not None and original["maximum_actions"] == 1

    improved = refine_magic_staves(search, original, _solution_key)

    assert improved["loadouts"]["mage"]["equipment"]["weapon"] == 300
    assert improved["maximum_actions"] == 1
    assert improved["score"] > original["score"]

    candidate_pools = _Search.candidate_pools

    def pools_without_staff(current):
        pools = candidate_pools(current)
        return {**pools, "weapon": [item for item in pools["weapon"] if item != 300]}

    monkeypatch.setattr(_Search, "candidate_pools", pools_without_staff)
    result = run(items, roles, max_swaps=1, base_role="melee")
    selected = result["curve"][1]["solution"]
    assert selected is not None
    assert selected["loadouts"]["mage"]["equipment"]["weapon"] == 300
    assert selected["maximum_actions"] == 1
    zero_action = result["curve"][0]["solution"]
    assert zero_action is None or zero_action["maximum_actions"] == 0


@pytest.mark.parametrize("ammunition", [884, None])
def test_global_ammunition_locks_include_explicit_empty(ammunition):
    items, _ = ammunition_case()
    roles = (
        RoleConfig(id="a", style="slash", locks={"weapon": 100}),
        RoleConfig(id="b", style="magic", spell="fire_strike", locks={"weapon": 200}),
    )
    result = run(items, roles, max_swaps=2, locks={"ammunition": ammunition})
    for point in result["curve"]:
        if point["solution"]:
            assert all(
                row["equipment"].get("ammunition") == ammunition
                for row in point["solution"]["loadouts"].values()
            )
    assert result["selected_solution"] is not None


def test_role_empty_lock_is_not_filled_from_ranged_ammunition():
    search = finalist_case(
        roles=(
            RoleConfig(id="melee", style="slash", locks={"weapon": 100, "ammunition": None}),
            RoleConfig(id="ranged", style="ranged", locks={"weapon": 200}),
        )
    )
    original, refined, _ = refine_finalist(
        search,
        {
            "melee": {"weapon": 100},
            "ranged": {"weapon": 200, "ammunition": 890},
        },
    )
    assert refined == original
    assert "ammunition" not in refined["loadouts"]["melee"]["equipment"]


@pytest.mark.parametrize(
    "protected",
    [
        "melee_strength",
        "prayer",
        "defence_stab",
        "defence_slash",
        "defence_crush",
        "defence_ranged",
        "defence_magic",
    ],
)
def test_refinement_retains_ammunition_with_real_combat_or_unscored_benefits(protected):
    search = finalist_case(bonuses={protected: 30})
    original, refined, diagnostics = refine_finalist(
        search,
        {
            "melee": {"weapon": 100, "ammunition": 884},
            "ranged": {"weapon": 200, "ammunition": 890},
        },
    )
    assert refined == original
    assert refined["loadouts"]["melee"]["equipment"]["ammunition"] == 884
    assert diagnostics["improved_finalists"] == 0


def test_unscored_utility_destination_is_fixed_while_other_roles_can_share():
    search = finalist_case(
        roles=(
            RoleConfig(id="melee", style="slash", locks={"weapon": 100}),
            RoleConfig(id="ranged", style="ranged", locks={"weapon": 200}),
            RoleConfig(id="utility", style="special", parent_role="melee", locks={"weapon": 100}),
        ),
        ordered_roles=("utility", "ranged", "melee"),
        reserved_supply_slots=26,
    )
    original, refined, _ = refine_finalist(
        search,
        {
            "melee": {"weapon": 100, "ammunition": 884},
            "ranged": {"weapon": 200, "ammunition": 890},
            "utility": {"weapon": 100, "ammunition": 884},
        },
    )
    assert refined["loadouts"]["utility"] == original["loadouts"]["utility"]
    assert refined["loadouts"]["utility"]["performance"]["dps"] is None
    assert refined["loadouts"]["melee"]["equipment"]["ammunition"] == 890
    assert refined["max_gear_inventory_slots"] <= original["max_gear_inventory_slots"] == 2
    assert refined["remaining_inventory_slots"] >= 0
    for before, after in zip(original["transitions"], refined["transitions"], strict=True):
        assert after["action_count"] <= before["action_count"]
        assert after["max_gear_inventory_slots"] <= before["max_gear_inventory_slots"]


def test_refinement_observes_cooperative_cancellation_between_assignments():
    search = finalist_case()
    original = search.solution(
        {"melee": {"weapon": 100, "ammunition": 884}, "ranged": {"weapon": 200, "ammunition": 890}},
        None,
    )
    assert original is not None
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 1

    search.cancelled = cancelled
    diagnostics = {"evaluated_assignments": 0, "improved_finalists": 0}
    with pytest.raises(ValueError, match="optimization_cancelled"):
        refine_ammunition(search, original, _solution_key, diagnostics)
    assert calls == 2


def test_ammunition_refinement_and_curve_output_are_deterministic():
    items, roles = ammunition_case()
    first = run(items, roles, max_swaps=1)
    second = run(items, roles, max_swaps=1)
    for key in ("curve", "unrestricted", "selected_solution", "search"):
        assert first[key] == second[key]
