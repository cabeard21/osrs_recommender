from types import SimpleNamespace

import pytest

from tests.gear.test_native_effect_costs import NOW, cost_scorer, prices
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.halberd_charging import cost_context
from tracker.gear.models import CombatTarget, EquipmentDefinition
from tracker.gear.running_costs import evaluate_running_cost


def item(item_id, name, slot):
    return EquipmentDefinition(id=item_id, name=name, slot=slot)


RING = item(21140, "Efaritay's aid", "ring")
STAKE = item(33716, "Blisterwood stake", "weapon")
CAPE = item(22109, "Ava's assembler", "cape")
OPTION = {"attack_type": "light", "stance": "rapid"}


def test_ring_upkeep_with_stake_recovery_reconciles_to_report_and_compact_score():
    gear = {"ring": RING, "weapon": STAKE, "cape": CAPE}
    quotes = prices(RING.id, STAKE.id)
    values = {
        "attack_interval": 1.2,
        "accuracy": 0.4,
        "dps": 3,
        "vampyre_bonus": {"ring_active": True, "ring_charge_probability": 0.4},
    }
    result = evaluate_running_cost(gear, OPTION, values, quotes, NOW)
    assert result["status"] == "known"
    resources = {row["item_id"]: row for row in result["resources"]}
    assert resources[STAKE.id]["consumed_quantity"] == pytest.approx(0.2)
    assert resources[RING.id]["consumed_quantity"] == pytest.approx(0.4 / 200)
    assert result["gp_per_attack"] == pytest.approx(7 * (0.2 + 0.4 / 200))
    assert "remaining charges are unknown" in result["charging_assumption"]
    prepared = CostEvaluator(quotes, NOW).prepare(gear, OPTION, vampyre_target=True)
    numeric = prepared.score(1.2, 3, 0.4, ring_charge_probability=0.4)
    assert numeric.gp_per_damage == result["gp_per_damage"]
    assert prepared.report(numeric, 0.4, ring_charge_probability=0.4) == result


def test_target_and_ring_are_both_required_and_cache_identity_is_shared_for_inactive_ring():
    role = SimpleNamespace(id="r", target=CombatTarget(traits=("vampyre2",)))
    opts = cost_context(SimpleNamespace(roles=(role,)), "r")
    e = CostEvaluator(prices(RING.id), NOW)
    off = e.prepare({}, {"attack_type": "crush"})
    gear = {"ring": RING}
    assert e.prepare(gear, {"attack_type": "crush"}) is off
    assert e.prepare({}, {"attack_type": "crush"}, **opts) is off
    active = e.prepare(gear, {"attack_type": "crush"}, **opts)
    assert active is not off
    assert active.score(2.4, 5, 0.4, ring_charge_probability=0.64).gp_per_attack == pytest.approx(
        7 * 0.64 / 200
    )


def test_ring_replacement_distinguishes_zero_chance_from_unknown_chance():
    engine = CostEvaluator(prices(RING.id), NOW)
    prepared = engine.prepare({"ring": RING}, {"attack_type": "crush"}, vampyre_target=True)
    assert prepared.score(2.4, 5, 0.1, ring_charge_probability=0.0).gp_per_attack == 0
    unknown = prepared.score(2.4, 5, 0.1)
    assert unknown.gp_per_attack is None
    assert "probability" in prepared.report(unknown, 0.1)["reasons"][0]


@pytest.mark.parametrize("missing", [21140, 33716])
def test_missing_ring_or_stake_price_does_not_make_attack_free(missing):
    gear = {"ring": RING, "weapon": STAKE}
    prepared = CostEvaluator(prices(*(i for i in (21140, 33716) if i != missing)), NOW).prepare(
        gear, OPTION, vampyre_target=True
    )
    result = prepared.score(1.2, 3, 0.5, ring_charge_probability=0.5)
    assert result.status == "unavailable"
    assert result.gp_per_attack is None
    assert (RING if missing == 21140 else STAKE).name in prepared.missing_prices


@pytest.mark.parametrize("has_quote", [True, False])
def test_native_ring_cost_uses_probability_of_one_or_more_landed_hits(has_quote):
    from tests.gear.test_native_stages import stage_search
    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.models import EquipmentBonuses
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.scoring import prepare_equipment

    weapon = EquipmentDefinition(
        id=29084,
        name="Sulphur blades",
        slot="weapon",
        attack_pattern="independent_double",
        attack_styles=("slash",),
        attack_profiles=(("slash", "aggressive"),),
        bonuses=EquipmentBonuses(melee_strength=50, slash=40),
    )
    equipment = {"weapon": weapon.id, "ring": RING.id}
    definitions = {"weapon": weapon, "ring": RING}
    with stage_search() as search:
        search.items = {v.id: v for v in definitions.values()}
        search.eligible = search.items
        search.facts = dict.fromkeys(search.items, search.facts[2])
        role = RoleConfig(
            id="z", style="slash", stance="aggressive", target=CombatTarget(traits=("vampyre2",))
        )
        search.request = search.request.model_copy(update={"roles": (role,)})
        search.running_at, search.running_prices = NOW, prices(RING.id) if has_quote else {}
        compiled = cost_scorer(search)
        (row,) = compiled.score_variants(equipment, 0)
        direct = evaluate_prepared_score(prepare_equipment(definitions), role, search.levels)
        chance = 1 - (1 - direct.accuracy) ** 2
        assert direct.ring_charge_probability == pytest.approx(chance)
        assert row["ring_charge_probability"] == direct.ring_charge_probability
        value = row["objective_values"]["gp_per_damage"]
        if has_quote:
            assert value == pytest.approx(7 / 200 * chance / row["interval"] / row["dps"])
        else:
            assert value is None


@pytest.mark.parametrize("armour_id, slot", [(29022, "body"), (29025, "legs"), (29028, "head")])
def test_blood_moon_armour_keeps_dps_eligible_with_unavailable_repair_cost(armour_id, slot):
    from tests.gear.test_native_stages import stage_search
    from tracker.gear.optimizer import RoleConfig

    gear = {slot: item(armour_id, "Blood Moon armour", slot)}
    option = {"attack_type": "slash"}
    perf = {"attack_interval": 2.4, "accuracy": 0.5, "dps": 3}
    direct = evaluate_running_cost(gear, option, perf, {}, NOW)
    prepared = CostEvaluator({}, NOW).prepare(gear, option)
    assert direct["status"] == prepared.score(2.4, 3).status == "unavailable"
    assert direct["gp_per_attack"] is None
    assert direct["reasons"] == list(prepared.limitations)
    assert "Blood Moon armour" in direct["reasons"][0]
    with stage_search() as search:
        search.items = {2: search.items[2], armour_id: gear[slot]}
        search.eligible = search.items
        search.facts = dict.fromkeys(search.items, search.facts[2])
        search.request = search.request.model_copy(
            update={"roles": (RoleConfig(id="z", style="slash", stance="accurate"),)}
        )
        search.running_at, search.running_prices = NOW, {}
        (row,) = cost_scorer(search).score_variants({"weapon": 2, slot: armour_id}, 0)
        assert row["dps"] > 0
        assert row["objective_values"]["gp_per_damage"] is None
