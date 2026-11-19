"""Equipment-dependent native costs retain authoritative recipe semantics."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.gear.combat_options import CombatOption
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.models import EquipmentDefinition, TomeEffect
from tracker.gear.native.cost_context import pack_costs

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def prices(*ids):
    return {
        item: SimpleNamespace(
            high_price_gp=7,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source="live",
        )
        for item in ids
    }


def cost_scorer(search):
    from tracker.gear.native._scoring import ScoringContext

    from tracker.gear.objectives import ObjectiveDescriptor

    search.request = search.request.model_copy(
        update={
            "objectives": (ObjectiveDescriptor(kind="gp_per_damage"),),
            "secondary_priority": "default",
        }
    )
    return ScoringContext(search)


def assert_cost_projection(search, scoring, equipment):
    from tracker.gear.halberd_charging import cost_context

    engine = CostEvaluator(search.running_prices, search.running_at)
    rows = scoring.score_variants(equipment, 0)
    assert rows
    expected = []
    for row in rows:
        configured, option = scoring.option_records[row["option_index"]]
        recipe = engine.prepare(
            {slot: search.items[item] for slot, item in equipment.items()},
            option.model_dump(),
            **cost_context(search.request, configured),
        )
        cost = recipe.score(row["interval"], row["dps"], row["accuracy"]).gp_per_damage
        assert row["objective_values"]["gp_per_damage"] == cost
        expected.append(-cost if cost is not None else -1e100)
    assert scoring.score_projection(equipment, 0) == (
        max(row["dps"] for row in rows),
        max(expected),
    )


@pytest.mark.parametrize("weapon_id", [23987, 29796])
@pytest.mark.parametrize("duration", [30, 54, 60, 180])
def test_native_halberd_head_costs_match_python(weapon_id, duration):
    from tests.gear.test_native_stages import stage_search
    from tracker.gear.halberd_charging import CrystalChargingPolicy
    from tracker.gear.models import EquipmentBonuses
    from tracker.gear.optimizer import RoleConfig

    with stage_search() as search:
        weapon = EquipmentDefinition(
            id=weapon_id,
            name="Halberd",
            slot="weapon",
            attack_styles=("slash",),
            attack_profiles=(("slash", "aggressive"),),
            attack_speed=5 if weapon_id == 29796 else 7,
            bonuses=EquipmentBonuses(slash=100, melee_strength=100),
        )
        head = EquipmentDefinition(
            id=12931,
            name="Serpentine helm",
            slot="head",
            bonuses=EquipmentBonuses(melee_strength=5),
        )
        search.items = {weapon.id: weapon, head.id: head}
        search.facts = dict.fromkeys(search.items, search.facts[2])
        search.eligible = search.items
        policy = CrystalChargingPolicy(coin_recharge_cost_gp=150000)
        search.request = search.request.model_copy(
            update={
                "crystal_halberd_charging": policy,
                "roles": (
                    RoleConfig(
                        id="z", style="slash", stance="aggressive", fight_duration_seconds=duration
                    ),
                ),
            }
        )
        search.running_at, search.running_prices = NOW, prices(12934)
        scoring = cost_scorer(search)
        for equipment in ({"weapon": weapon.id}, {"weapon": weapon.id, "head": head.id}):
            assert_cost_projection(search, scoring, equipment)


@pytest.mark.parametrize("spell", ["fire_strike", "earth_wave", "iban_blast", "ice_barrage"])
@pytest.mark.parametrize("missing", [554, 555, 557, 560])
def test_tome_cost_table_uses_actual_supply_classes(spell, missing):
    items = {
        1381: EquipmentDefinition(id=1381, name="Air staff", slot="weapon"),
        **{
            item: EquipmentDefinition(
                id=item,
                name=element,
                slot="shield",
                tome_effect=TomeEffect(element=element, rune_id=rune),
            )
            for item, element, rune in [
                (20714, "fire", 554),
                (25574, "water", 555),
                (30064, "earth", 557),
            ]
        },
        999: EquipmentDefinition(
            id=999,
            name="Duplicate Fire",
            slot="shield",
            tome_effect=TomeEffect(element="fire", rune_id=554),
        ),
    }
    option = CombatOption(attack_type="magic", stance="accurate", spell=spell)
    quotes = prices(*(i for i in (554, 555, 556, 557, 558, 560, 565) if i != missing))
    search = SimpleNamespace(items=items, running_prices=quotes, running_at=NOW)
    scoring = SimpleNamespace(
        dense_ids=(0, *sorted(items)), option_weapons=(1381,), option_records=((None, option),)
    )
    packed = pack_costs(search, scoring)
    assert packed.supply_count == 4
    assert (
        packed.supply_class[scoring.dense_ids.index(999)]
        == packed.supply_class[scoring.dense_ids.index(20714)]
    )
    engine = CostEvaluator(quotes, NOW)
    for shield in (None, 20714, 25574, 30064):
        equipment = {"weapon": items[1381], **({"shield": items[shield]} if shield else {})}
        recipe = engine.prepare(equipment, option.model_dump())
        dense = scoring.dense_ids.index(shield) if shield else 0
        value = packed.option_cost[packed.supply_class[dense]]
        assert value == (recipe.gp_per_attack if recipe.gp_per_attack is not None else -1)


@pytest.mark.parametrize("cape", [None, 10499, 9756])
@pytest.mark.parametrize(
    "interference,missing_price", [(False, False), (True, False), (False, True)]
)
def test_native_hopper_cost_stage_matches_python_recovery(cape, interference, missing_price):
    from tests.gear.test_native_stages import stage_search
    from tracker.gear.models import CombatTarget, EquipmentBonuses
    from tracker.gear.optimizer import RoleConfig

    with stage_search() as search:
        items = [
            EquipmentDefinition(
                id=9185,
                name="Crossbow",
                slot="weapon",
                attack_styles=("ranged",),
                ammo_for=("bolt:test",),
                bonuses=EquipmentBonuses(ranged=40),
            ),
            EquipmentDefinition(
                id=9144,
                name="Bolts",
                slot="ammunition",
                ammo_type="bolt:test",
                bonuses=EquipmentBonuses(ranged_strength=50),
            ),
            EquipmentDefinition(id=32879, name="Hopper", slot="shield"),
            EquipmentDefinition(id=300, name="Plain", slot="shield"),
            EquipmentDefinition(id=10499, name="Accumulator", slot="cape"),
            EquipmentDefinition(id=9756, name="Unobserved upgrade", slot="cape"),
            EquipmentDefinition(id=1127, name="Interfering body", slot="body"),
        ]
        search.items = {item.id: item for item in items}
        search.facts = dict.fromkeys(search.items, search.facts[2])
        search.eligible = search.items
        search.request = search.request.model_copy(
            update={
                "roles": (
                    RoleConfig(
                        id="z", style="ranged", stance="rapid", target=CombatTarget(hitpoints=500)
                    ),
                )
            }
        )
        search.running_at, search.running_prices = NOW, prices(*(() if missing_price else (9144,)))
        scoring = cost_scorer(search)
        base = {
            "weapon": 9185,
            "ammunition": 9144,
            **({"cape": cape} if cape else {}),
            **({"body": 1127} if interference else {}),
        }
        choices = [None, 300, 32879]
        for shield in choices:
            assert_cost_projection(
                search, scoring, {**base, **({"shield": shield} if shield else {})}
            )
