"""Exact evaluation shares the search's physical legality and combat formulas."""

import pytest

from tracker.gear.combat import evaluate_loadout
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig


def test_exact_evaluation_matches_existing_validated_combat_function():
    weapon = EquipmentDefinition(
        id=1,
        name="Sword",
        slot="weapon",
        attack_styles=("slash",),
        bonuses=EquipmentBonuses(slash=30, melee_strength=45),
    )
    role = RoleConfig(id="single", style="slash")
    levels = {"attack": 70, "strength": 75}
    actual = evaluate_equipment({"weapon": 1}, {1: weapon}, role, levels)
    assert actual == evaluate_loadout({"weapon": weapon}, role, levels)
    assert actual.supported


@pytest.mark.parametrize(
    "equipment,reason",
    [
        ({"weapon": 999}, "Unknown physical item"),
        ({"head": 1}, "does not occupy head"),
        ({"weapon": 1, "shield": 2}, "Two-handed"),
    ],
)
def test_exact_evaluation_rejects_invalid_physical_loadouts(equipment, reason):
    items = {
        1: EquipmentDefinition(id=1, name="Bow", slot="weapon", two_handed=True),
        2: EquipmentDefinition(id=2, name="Shield", slot="shield"),
    }
    result = evaluate_equipment(
        equipment, items, RoleConfig(id="single", style="slash"), {"attack": 99, "strength": 99}
    )
    assert not result.supported
    assert result.dps is result.max_hit is result.accuracy is result.attack_interval is None
    assert any(reason in limitation for limitation in result.limitations)


def fixed_context(make_content, *, observed=(1, 2, 3), **item_changes):
    from datetime import UTC, datetime

    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.service import GearService

    now = datetime(2026, 10, 27, tzinfo=UTC)
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(70, None, Source.MANUAL, now)
            for key in ("attack", "strength", "defence", "magic", "ranged")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", now)
            for i in observed
        },
    )
    service = GearService(make_content())
    service._equipment = EquipmentCatalog(
        {
            1: EquipmentDefinition(
                id=1,
                name="Bow",
                slot="weapon",
                attack_styles=("ranged",),
                ammo_for=("arrow",),
                requirements_complete=True,
            ),
            2: EquipmentDefinition(
                id=2, name="Arrow", slot="ammunition", ammo_type="arrow", requirements_complete=True
            ),
            3: EquipmentDefinition(
                id=3, name="Bolt", slot="ammunition", ammo_type="bolt", requirements_complete=True
            ),
            **item_changes,
        }
    )
    return service, snapshot, now


def test_fixed_ammunition_matches_optimizer_and_no_search_runs(make_content, monkeypatch):
    from tracker.gear.optimizer import OptimizationRequest

    service, snapshot, now = fixed_context(make_content)
    request = OptimizationRequest(roles=(RoleConfig(id="single", style="ranged"),), mode="owned")
    optimized = service.optimize(snapshot, request, now=now)
    baseline = optimized["selected_solution"]["loadouts"]["single"]
    monkeypatch.setattr(
        "tracker.gear.optimizer._Search.__init__", lambda *a, **k: pytest.fail("search ran")
    )
    result = service.evaluate(
        snapshot, request, baseline["equipment"], {"weapon": 1, "ammunition": 3}, now=now
    )
    assert result["baseline"]["performance"] == baseline["performance"]
    assert result["proposed"]["status"] == "unsupported"
    assert result["proposed"]["performance"] is None
    assert result["deltas"] is None
    assert "ammunition" in result["proposed"]["reasons"][0]["message"]


def test_future_skill_and_acquisition_assumptions_remain_request_local(make_content):
    from tracker.content.requirements import SkillLeaf
    from tracker.gear.optimizer import OptimizationRequest

    service, snapshot, now = fixed_context(make_content, observed=(2,))
    bow = (
        service.equipment_catalog()
        .items[1]
        .model_copy(update={"requires": SkillLeaf(skill="ranged", level=90)})
    )
    service._equipment = type(service.equipment_catalog())(
        {**service.equipment_catalog().items, 1: bow}
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="single", style="ranged"),), mode="future", assumed_item_ids=(1,)
    )
    equipment = {"weapon": 1, "ammunition": 2}
    unavailable = service.evaluate(snapshot, request, equipment, equipment, now=now)
    assert unavailable["proposed"]["status"] == "invalid"
    assumed = request.model_copy(update={"skill_overrides": {"ranged": 90}})
    available = service.evaluate(snapshot, assumed, equipment, equipment, now=now)
    assert available["proposed"]["status"] == "valid"
    assert available["proposed"]["purchase_cost_gp"] == 0
    assert available["proposed"]["assumed_item_ids"] == [1]
    assert snapshot.skills["ranged"].level == 70
    assert not any(i == 1 for i, _ in snapshot.observed_items)


def test_unknown_requirements_unsupported_effects_and_unpriced_purchase(make_content):
    from tracker.gear.optimizer import OptimizationRequest

    service, snapshot, now = fixed_context(make_content)
    equipment = {"weapon": 1, "ammunition": 2}
    request = OptimizationRequest(
        roles=(RoleConfig(id="single", style="ranged"),), mode="usable", budget_gp=1000
    )
    original = service.equipment_catalog()
    for changes, status, reason in (
        ({"requirements_complete": False}, "invalid", "requirements"),
        ({"unsupported_effects": ("Unsupported set effect",)}, "unsupported", "set effect"),
    ):
        service._equipment = type(original)(
            {**original.items, 1: original.items[1].model_copy(update=changes)}
        )
        result = service.evaluate(snapshot, request, equipment, equipment, now=now)
        assert result["proposed"]["status"] == status
        assert result["proposed"]["performance"] is None
        assert any(reason in r["message"] for r in result["proposed"]["reasons"])
    service, unowned, now = fixed_context(make_content, observed=(2,))
    catalog = service.equipment_catalog()
    service._equipment = type(catalog)(
        {**catalog.items, 1: catalog.items[1].model_copy(update={"tradeable": True})}
    )
    result = service.evaluate(unowned, request, equipment, equipment, now=now)
    assert result["proposed"]["status"] == "invalid"
    assert result["proposed"]["purchase_cost_gp"] is None
    assert any("price" in r["message"] for r in result["proposed"]["reasons"])


def test_fixed_evaluator_rejects_multiple_roles_and_cancels_without_leaking_lock(make_content):
    from tracker.gear.optimizer import OptimizationRequest

    service, snapshot, now = fixed_context(make_content)
    request = OptimizationRequest(
        roles=(RoleConfig(id="a", style="ranged"), RoleConfig(id="b", style="ranged"))
    )
    with pytest.raises(ValueError, match="one ordinary"):
        service.evaluate(snapshot, request, {}, {}, now=now)
    request = OptimizationRequest(roles=(RoleConfig(id="single", style="ranged"),))
    with pytest.raises(ValueError, match="evaluation_cancelled"):
        service.evaluate(snapshot, request, {}, {}, now=now, cancelled=lambda: True)
    assert service._optimization_lock.acquire(blocking=False)
    service._optimization_lock.release()


def test_fixed_evaluator_rejects_unknown_and_noninteger_direct_ids(make_content):
    from tracker.gear.optimizer import OptimizationRequest

    service, snapshot, now = fixed_context(make_content)
    request = OptimizationRequest(roles=(RoleConfig(id="single", style="ranged"),))
    for equipment in ({"weapon": 999}, {"weapon": True}):
        with pytest.raises(ValueError):
            service.evaluate(snapshot, request, equipment, {}, now=now)
