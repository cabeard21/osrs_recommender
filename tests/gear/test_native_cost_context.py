from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.gear.combat_options import CombatOption
from tracker.gear.compact_costs import CostEvaluator
from tracker.gear.models import EquipmentDefinition
from tracker.gear.native.cost_context import pack_costs


def test_native_cost_tables_preserve_missing_quotes_and_cape_unknowns():
    items = {
        2: EquipmentDefinition(id=2, name="Bow", slot="weapon", ammo_for=("arrow:test",)),
        3: EquipmentDefinition(id=3, name="Arrow", slot="ammunition", ammo_type="arrow:test"),
        9756: EquipmentDefinition(id=9756, name="Cape", slot="cape"),
    }
    search = SimpleNamespace(items=items, running_prices={}, running_at=datetime.now(UTC))
    scoring = SimpleNamespace(
        dense_ids=(0, 2, 3, 9756),
        option_weapons=(2,),
        option_records=((None, CombatOption(attack_type="standard", stance="accurate")),),
    )
    packed = pack_costs(search, scoring)
    assert list(packed.option_kind) == [1]
    assert list(packed.ranged_kind) == [0, 1, 0, 0]
    assert packed.ammo_valid[2] == 1
    assert packed.unit_prices[2] == -1
    assert packed.recovery[0] == 0
    assert packed.recovery[3] == -1


def test_native_melee_resource_cost_is_known_zero():
    weapon = EquipmentDefinition(id=2, name="Sword", slot="weapon")
    search = SimpleNamespace(items={2: weapon}, running_prices={}, running_at=datetime.now(UTC))
    scoring = SimpleNamespace(
        dense_ids=(0, 2),
        option_weapons=(2,),
        option_records=((None, CombatOption(attack_type="slash", stance="accurate")),),
    )
    assert pack_costs(search, scoring).option_cost[0] == 0


@pytest.mark.parametrize(
    "weapon_id,powered,spell",
    [
        (1381, None, "fire_strike"),
        (11905, "trident", None),
        (2, None, "unreviewed_spell"),
    ],
)
def test_native_option_cost_uses_authoritative_recipes(weapon_id, powered, spell):
    now = datetime.now(UTC)
    weapon = EquipmentDefinition(id=weapon_id, name="Staff", slot="weapon")
    option = CombatOption(
        attack_type="magic", stance="accurate", spell=spell, powered_attack=powered
    )
    prices = {
        item: SimpleNamespace(
            high_price_gp=7,
            high_trade_at=now,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=now,
            source="live",
        )
        for item in (556, 554, 558, 562, 560, 995)
    }
    search = SimpleNamespace(items={weapon_id: weapon}, running_prices=prices, running_at=now)
    scoring = SimpleNamespace(
        dense_ids=(0, weapon_id), option_weapons=(weapon_id,), option_records=((None, option),)
    )
    expected = CostEvaluator(prices, now).prepare({"weapon": weapon}, option.model_dump())
    packed = pack_costs(search, scoring)
    assert packed.option_cost[0] == (
        expected.gp_per_attack if expected.gp_per_attack is not None else -1
    )


def test_native_cost_table_records_thrown_repair_and_interference_flags():
    items = {
        806: EquipmentDefinition(id=806, name="Dart", slot="weapon"),
        4747: EquipmentDefinition(id=4747, name="Hammers", slot="weapon"),
    }
    search = SimpleNamespace(items=items, running_prices={}, running_at=datetime.now(UTC))
    scoring = SimpleNamespace(dense_ids=(0, 806, 4747), option_weapons=(), option_records=())
    packed = pack_costs(search, scoring)
    assert packed.ranged_kind[1] == 2
    assert packed.torag[2] == 1


def test_native_interference_uses_reviewed_body_identity():
    from tracker.gear.models import EquipmentBonuses

    items = {
        1127: EquipmentDefinition(id=1127, name="Rune platebody", slot="body"),
        2503: EquipmentDefinition(
            id=2503,
            name="Black dragonhide",
            slot="body",
            bonuses=EquipmentBonuses(ranged=-1),
        ),
    }
    search = SimpleNamespace(items=items, running_prices={}, running_at=datetime.now(UTC))
    scoring = SimpleNamespace(dense_ids=(0, 1127, 2503), option_weapons=(), option_records=())
    assert list(pack_costs(search, scoring).interference) == [0, 1, 0]
