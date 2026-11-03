"""Consumable ammunition does not spend the equipment acquisition budget."""

from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize
from tracker.integrations.prices.client import PriceDTO, PriceSource


@pytest.mark.parametrize(
    "item_id,slot,ammo_type",
    [
        (882, "ammunition", "arrow:882"),
        (9140, "ammunition", "bolt:9140"),
        (806, "weapon", None),
        (25849, "weapon", None),
    ],
)
@pytest.mark.parametrize("priced", [False, True])
def test_ammunition_ignores_budget_in_search_and_fixed_evaluation(
    make_content, item_id, slot, ammo_type, priced
):
    bow = EquipmentDefinition(
        id=1,
        name="Bow",
        slot="weapon",
        attack_styles=("ranged",),
        ammo_for=(ammo_type,) if ammo_type else (),
        requirements_complete=True,
    )
    ammo = EquipmentDefinition(
        id=item_id,
        name="Consumable",
        slot=slot,
        ammo_type=ammo_type,
        attack_styles=("ranged",) if slot == "weapon" else (),
        stackable=True,
        tradeable=True,
        requirements_complete=True,
    )
    equipment = (
        {"weapon": 1, "ammunition": item_id} if slot == "ammunition" else {"weapon": item_id}
    )
    catalog = SimpleNamespace(items={1: bow, item_id: ammo}, version="test")
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={"ranged": SkillState(70, None, Source.MANUAL, NOW)},
        observed_items={(1, Container.BANK): ObservedItemFact(1, Container.BANK, 1, "test", NOW)},
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="r", style="ranged", locks=equipment),),
        budget_gp=0,
        max_swaps=0,
    )
    prices = (
        {
            item_id: PriceDTO(
                item_id=item_id,
                high_price_gp=1000,
                high_trade_at=NOW,
                low_price_gp=None,
                low_trade_at=None,
                fetched_at=NOW,
                source=PriceSource.LIVE,
                provider="test",
            )
        }
        if priced
        else {}
    )
    content = make_content()
    result = optimize(snapshot, request, catalog, content, prices, NOW)
    solution = result["selected_solution"]
    assert solution is not None
    assert solution["purchase_cost_gp"] == 0
    assert solution["purchases"] == []
    evaluated = evaluate_configurations(
        snapshot, request, equipment, equipment, catalog, content, prices, NOW
    )
    assert evaluated["proposed"]["status"] == "valid"
    assert evaluated["proposed"]["purchase_cost_gp"] == 0
    owned = request.model_copy(update={"mode": "owned"})
    assert optimize(snapshot, owned, catalog, content, prices, NOW)["selected_solution"] is None


@pytest.mark.parametrize(
    "item_id,slot,ammo_type",
    [(20220, "ammunition", None), (20226, "ammunition", "bolt:20226"), (12926, "weapon", None)],
)
def test_non_consumable_equipment_still_counts_toward_budget(
    make_content, item_id, slot, ammo_type
):
    from tracker.gear.evaluation import item_problems, purchase_cost, purchases
    from tracker.gear.facts import equipment_fact

    item = EquipmentDefinition(
        id=item_id,
        name="Equipment",
        slot=slot,
        ammo_type=ammo_type,
        stackable=True,
        attack_styles=("ranged",) if slot == "weapon" else (),
        tradeable=True,
        requirements_complete=True,
    )
    price = PriceDTO(
        item_id=item_id,
        high_price_gp=1000,
        high_trade_at=NOW,
        low_price_gp=None,
        low_trade_at=None,
        fetched_at=NOW,
        source=PriceSource.LIVE,
        provider="test",
    )
    fact = equipment_fact(AccountSnapshot(1, "test"), item, make_content(), {item_id: price}, NOW)
    request = OptimizationRequest(roles=(RoleConfig(id="r", style="ranged"),))
    assert purchase_cost({item_id}, {item_id: fact}, request) == 1000
    assert purchases({item_id}, {item_id: fact}, request)[0]["cost_gp"] == 1000
    unpriced = {**fact, "price": {"amount_gp": None}}
    assert "no usable purchase price" in item_problems(item_id, unpriced, request)[0]
