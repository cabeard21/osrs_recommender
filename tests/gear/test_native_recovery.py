"""Unknown Ava/body recovery is a candidate cost, never a branch fallback."""

from types import SimpleNamespace

import pytest

from tests.gear.test_native_effect_costs import NOW, assert_cost_projection, cost_scorer, prices
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.native.cost_context import pack_costs
from tracker.gear.native.packing import support_reason
from tracker.gear.optimizer import RoleConfig


def recovery_items():
    return {
        item.id: item
        for item in (
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
            EquipmentDefinition(
                id=806,
                name="Thrown dart",
                slot="weapon",
                attack_styles=("ranged",),
                bonuses=EquipmentBonuses(ranged=40, ranged_strength=50),
            ),
            EquipmentDefinition(id=32879, name="Hopper", slot="shield"),
            EquipmentDefinition(id=10499, name="Accumulator", slot="cape"),
            EquipmentDefinition(id=9756, name="Unknown upgrade", slot="cape"),
            EquipmentDefinition(id=999998, name="Ordinary cape", slot="cape"),
            EquipmentDefinition(
                id=1127, name="Interfering body", slot="body", bonuses=EquipmentBonuses(ranged=-1)
            ),
            EquipmentDefinition(id=2503, name="Compatible body", slot="body"),
            EquipmentDefinition(
                id=999999, name="Unreviewed body", slot="body", bonuses=EquipmentBonuses(ranged=15)
            ),
        )
    }


def test_native_cost_tables_distinguish_all_body_recovery_states():
    items = recovery_items()
    packed = pack_costs(
        SimpleNamespace(items=items, running_prices=prices(9144), running_at=NOW),
        SimpleNamespace(dense_ids=(0, *items), option_records=(), option_weapons=()),
    )
    classes = dict(zip((0, *items), packed.body_recovery, strict=True))
    assert classes[0] == classes[10499] == 0
    assert classes[2503] == 1
    assert classes[1127] == 2
    assert classes[999999] == 3


def test_mixed_body_catalog_does_not_disable_native_ranged_search():
    items = recovery_items()
    search = SimpleNamespace(
        request=SimpleNamespace(
            roles=(RoleConfig(id="r", style="ranged"),), secondary_priority="prayer_bonus"
        ),
        items=items,
        eligible=items,
        levels={"ranged": 70},
    )
    assert support_reason(search) is None


@pytest.mark.parametrize("weapon", [9185, 806])
@pytest.mark.parametrize("cape", [None, 999998, 10499, 9756])
@pytest.mark.parametrize("hopper", [False, True])
def test_unknown_recovery_affects_cost_ranking_without_rejecting_dps(weapon, cape, hopper):
    from tests.gear.test_native_stages import stage_search

    with stage_search() as search:
        search.items = recovery_items()
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
        search.running_at, search.running_prices = NOW, prices(9144, 806)
        scorer = cost_scorer(search)
        base = {
            "weapon": weapon,
            **({"ammunition": 9144} if weapon == 9185 else {}),
            **({"cape": cape} if cape else {}),
            **({"shield": 32879} if hopper else {}),
        }
        choices = [None, 1127, 2503, 999999]
        for body in choices:
            assert_cost_projection(search, scorer, {**base, **({"body": body} if body else {})})
