from datetime import UTC, datetime

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatPerformance, CombatTarget
from tracker.gear.optimizer import RoleConfig
from tracker.gear.running_costs import evaluate_running_cost
from tracker.gear.scoring import prepare_equipment


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content())


def test_hopper_catalog(catalog):
    item = catalog.items[32879]
    assert not item.unsupported_effects
    assert item.requirements_complete and item.tradeable
    assert item.requires.to_yaml() == {"skill": {"ranged": 60}}


@pytest.mark.parametrize("ammo", [9144, 9236, 9238, 9242, 9243, 9244, 9245])
@pytest.mark.parametrize("weapon", [9185, 26374])
@pytest.mark.parametrize("armour", [-4, 0, 3])
def test_shared_scoring_and_report(catalog, ammo, weapon, armour):
    equipment = {
        slot: catalog.items[i]
        for slot, i in [("weapon", weapon), ("ammunition", ammo), ("shield", 32879)]
    }
    role = RoleConfig(
        id="r",
        style="ranged",
        stance="rapid",
        target=CombatTarget(hitpoints=500, flat_armour=armour),
    )
    result = evaluate_loadout(equipment, role, {"ranged": 99})
    assert result.supported
    report = result.aquanite_hopper
    assert report.approximate and report.assumptions
    assert report.proc_chance == 0.11
    assert report.expected_ammunition_per_attack == 1.11
    score = evaluate_prepared_score(prepare_equipment(equipment), role, {"ranged": 99})
    assert score.dps == result.dps
    ordinary = evaluate_loadout(
        {k: v for k, v in equipment.items() if k != "shield"}, role, {"ranged": 99}
    )
    assert result.attack_interval == ordinary.attack_interval
    assert CombatPerformance.model_validate_json(result.model_dump_json()) == result
    if result.bolt_effect:
        assert result.dps * result.attack_interval == pytest.approx(
            result.bolt_effect.expected_damage_per_attack + report.expected_damage_delta
        )


@pytest.mark.parametrize("cape,recovery", [(None, 0), (22109, 0.8)])
def test_extra_ammunition_cost(catalog, cape, recovery):
    from tests.gear.test_running_costs import prices

    equipment = {
        k: catalog.items[i] for k, i in [("weapon", 9185), ("ammunition", 9144), ("shield", 32879)]
    }
    if cape:
        equipment["cape"] = catalog.items[cape]
    result = evaluate_running_cost(
        equipment,
        {"attack_type": "heavy"},
        {"attack_interval": 3, "dps": 2},
        prices(**{"9144": 10}),
        datetime(2026, 11, 2, tzinfo=UTC),
    )
    assert result["resources"][0]["required_quantity"] == 1.11
    assert result["resources"][0]["supplied_quantity"] == pytest.approx(1.11 * recovery)
    assert result["gp_per_attack"] == pytest.approx(11.1 * (1 - recovery))


def test_review_preserves_other_blockers():
    from tracker.gear.hopper_catalog import apply_review

    row = {
        "id": 32879,
        "name": "Aquanite hopper",
        "slot": "shield",
        "unsupported_effects": ["Offensive effects have not been validated.", "Other"],
    }
    assert apply_review(row)["unsupported_effects"] == ["Other"]
    assert len(row["unsupported_effects"]) == 2
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "slot": "body"})
    assert apply_review({"id": 1}) == {"id": 1}


@pytest.mark.parametrize("level,status", [(59, "unsatisfied"), (60, "satisfied")])
def test_wear_boundary(catalog, level, status):
    from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
    from tracker.gear.facts import equipment_fact

    fact = equipment_fact(
        snapshot(levels={"ranged": level}), catalog.items[32879], load_content(), {}, NOW
    )
    assert fact["wear"]["status"] == status


def optimization_context(catalog):
    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.domain.types import Container, SkillState, Source
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest

    now = datetime(2026, 11, 2, tzinfo=UTC)
    plain = catalog.items[32879].model_copy(
        update={
            "id": 999999,
            "name": "Plain shield",
            "bonuses": catalog.items[32879].bonuses.model_copy(update={"ranged": 13}),
        }
    )
    items = {i: catalog.items[i] for i in (9185, 9243, 32879)}
    items[plain.id] = plain
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            k: SkillState(99, None, Source.MANUAL, now)
            for k in ("ranged", "attack", "strength", "magic", "defence", "hitpoints")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "test", now)
            for i in items
        },
    )
    request = OptimizationRequest(
        mode="owned",
        max_swaps=0,
        roles=(
            RoleConfig(
                id="r",
                style="ranged",
                combat_options=CombatOptionFilters(
                    attack_types=("heavy",), stances=("rapid", "accurate"), spells=()
                ),
            ),
        ),
    )
    return (
        snapshot,
        request,
        EquipmentCatalog(items, revision=catalog.revision),
        load_content(),
        {},
        now,
    )


def test_optimizer_prefers_hopper_for_passive(catalog, monkeypatch):
    from tracker.gear import hopper
    from tracker.gear.optimizer import optimize

    context = optimization_context(catalog)
    result = optimize(*context)
    loadout = result["selected_solution"]["loadouts"]["r"]
    assert loadout["equipment"]["shield"] == 32879
    assert loadout["performance"]["aquanite_hopper"]["approximate"]
    assert result["selected_solution"]["purchase_cost_gp"] == 0
    assert "aquanite_hopper_model_version" in result["assumptions"]
    monkeypatch.setattr(hopper, "active", lambda *args: False)
    without_passive = optimize(*context)
    assert without_passive["selected_solution"]["loadouts"]["r"]["equipment"]["shield"] == 999999


def test_inactive_for_non_crossbow_and_melee(catalog):
    result = evaluate_loadout([catalog.items[32879]], "crush", {"attack": 99, "strength": 99})
    assert result.supported and result.aquanite_hopper is None
    result = evaluate_loadout([catalog.items[32879]], "magic", {"magic": 99})
    assert result.supported and result.aquanite_hopper is None


def test_purchase_budget_for_unowned_hopper(catalog):
    from dataclasses import replace

    from tests.gear.test_running_costs import prices
    from tracker.gear.optimizer import optimize

    snapshot, request, reduced, content, _, now = optimization_context(catalog)
    snapshot = replace(
        snapshot,
        observed_items={
            key: fact for key, fact in snapshot.observed_items.items() if key[0] != 32879
        },
    )
    records = prices(**{"32879": 100, "9243": 10})
    for budget, expected in [(99, 999999), (100, 32879)]:
        result = optimize(
            snapshot,
            request.model_copy(update={"mode": "usable", "budget_gp": budget}),
            reduced,
            content,
            records,
            now,
        )
        solution = result["selected_solution"]
        assert solution["loadouts"]["r"]["equipment"]["shield"] == expected
        assert solution["purchase_cost_gp"] == (100 if budget == 100 else 0)


def test_worker_serialization_matches_serial(catalog):
    from tracker.gear.optimizer import optimize
    from tracker.gear.parallel import AutoProcessPool
    from tracker.gear.potions import PotionPolicy

    snapshot, request, reduced, content, prices, now = optimization_context(catalog)
    branch = request.model_copy(update={"potions": PotionPolicy(mode="fixed")})
    expected = optimize(snapshot, branch, reduced, content, prices, now, _complete_frontiers=True)
    pool = AutoProcessPool(1)
    try:
        pool.start(content, reduced)
        results = pool.run_potions(
            snapshot, request, reduced, content, prices, now, branches=[branch]
        )
    finally:
        pool.close()
    assert results[0]["selected_solution"] == expected["selected_solution"]
