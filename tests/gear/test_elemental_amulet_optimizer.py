"""Frozen prices exercise physical amulet selection and union purchase accounting."""

from types import SimpleNamespace

import pytest

from tests.gear.test_optimizer import NOW
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.domain.types import Container, SkillState, Source, UnlockState
from tracker.gear.combat import ELEMENTAL_SPELLS
from tracker.gear.models import ElementalSpellBonus, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize
from tracker.integrations.prices.client import PriceDTO, PriceSource


@pytest.mark.parametrize("swaps,budget,expected", [(1, 100, {10, 11}), (0, 150, {12})])
@pytest.mark.parametrize("thorough", [False, True])
def test_joint_amulets_respect_union_budget_and_swap_cap(
    make_content, make_item, swaps, budget, expected, thorough
):
    staff = EquipmentDefinition(
        id=1,
        name="Staff",
        slot="weapon",
        requirements_complete=True,
        spell_compatibility=tuple(ELEMENTAL_SPELLS),
    )
    amulets = {
        item_id: EquipmentDefinition(
            id=item_id,
            name=f"Amulet {item_id}",
            slot="neck",
            requirements_complete=True,
            tradeable=True,
            bonuses=EquipmentBonuses(magic=10),
            elemental_spell_bonus=ElementalSpellBonus(elements=elements, base_max_hit_bonus=2),
        )
        for item_id, elements in (
            (10, ("fire",)),
            (11, ("water",)),
            (12, ("air", "water", "earth", "fire")),
        )
    }
    snapshot = AccountSnapshot(
        1,
        "fixture",
        skills={"magic": SkillState(70, None, Source.MANUAL, NOW)},
        unlocks={"spellbook_standard": UnlockState.UNLOCKED},
        observed_items={(1, Container.BANK): ObservedItemFact(1, Container.BANK, 1, "test", NOW)},
    )
    content = make_content(
        items=[
            make_item(f"amulet_{item_id}", numeric_id=item_id, slot="neck") for item_id in amulets
        ]
    )
    prices = {
        item_id: PriceDTO(
            item_id=item_id,
            high_price_gp=price,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source=PriceSource.LIVE,
            provider="fixture",
        )
        for item_id, price in ((10, 50), (11, 50), (12, 150))
    }
    roles = tuple(
        RoleConfig(id=element, style="magic", spell=f"{element}_blast", locks={"weapon": 1})
        for element in ("fire", "water")
    )
    result = optimize(
        snapshot,
        OptimizationRequest(roles=roles, budget_gp=budget, max_swaps=swaps),
        SimpleNamespace(items={1: staff, **amulets}),
        content,
        prices,
        NOW,
        local_refinement=thorough,
    )
    selected = result["selected_solution"]
    assert selected is not None
    assert {row["equipment"]["neck"] for row in selected["loadouts"].values()} == expected
    assert selected["purchase_cost_gp"] == budget
    assert {row["item_id"] for row in selected["purchases"]} == expected
    assert all(row["performance"]["max_hit"] == 18 for row in selected["loadouts"].values())
