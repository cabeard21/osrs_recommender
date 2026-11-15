"""Finite-window status damage uses deterministic NPC timer phases."""

import pytest

from tracker.gear.status_damage import expected_damage


def test_zero_application_and_short_window():
    assert expected_damage(0, 5, 60, "venom") == 0
    assert expected_damage(1, 5, 1, "venom") == pytest.approx(6 / 30)


def test_certain_venom_uniform_phase_and_ramp():
    assert expected_damage(1, 5, 18, "venom") == 6
    assert expected_damage(1, 5, 36, "venom") == 14
    assert expected_damage(1, 5, 144, "venom") == 104
    assert expected_damage(1, 5, 162, "venom") == 124


def test_poison_reapplication_refreshes_severity():
    assert expected_damage(1, 5, 180, "poison") == 60
    assert 0 < expected_damage(0.1, 5, 60, "venom") < expected_damage(1, 5, 60, "venom")


def test_single_poison_application_matches_documented_81_damage():
    assert expected_damage(1, 10000, 468, "poison") == 81


def test_real_catalog_charged_serpentine_is_reviewed():
    from tracker.content.loader import load_content
    from tracker.gear.catalog import load_catalog

    catalog = load_catalog(load_content())
    head = catalog.items[12931]
    assert head.bonuses.melee_strength == 5
    assert not head.unsupported_effects
    assert head.requirements_complete
    assert head.tradeable is False


def test_npc_status_sidecar_and_canonical_protection():
    from tracker.gear.models import CombatTarget, TargetSelection
    from tracker.gear.npcs import npc_catalog, resolve_target
    from tracker.gear.optimizer import RoleConfig

    catalog = npc_catalog()
    cow = next(e for e in catalog.entries.values() if e["name"] == "Cow")
    assert cow["target"]["poison_susceptibility"] == "immune"
    assert cow["target"]["venom_susceptibility"] == "immune"
    role = RoleConfig(
        id="r",
        style="slash",
        target_selection=TargetSelection(key=cow["key"], catalog_revision=catalog.revision),
        target=CombatTarget.model_validate(
            {**cow["target"], "venom_susceptibility": "susceptible"}
        ),
    )
    with pytest.raises(ValueError, match="cannot be overridden"):
        resolve_target(role)


def test_araxxors_spawn_profiles_stay_blocked_until_encounter_review():
    from tracker.gear.npcs import npc_catalog

    for npc_id in (13675, 13671, 13673):
        rows = [e for e in npc_catalog().entries.values() if e["npc_id"] == npc_id]
        assert rows
        for row in rows:
            assert row["support_status"] == "unsupported"
            assert any("guaranteed-maximum-hit" in reason for reason in row["reasons"])


def test_first_venom_tick_matches_geometric_application_probability():
    chance = 0.2
    geometric = sum(6 * (1 - (1 - chance) ** (tick // 5 + 1)) for tick in range(1, 31)) / 30
    assert expected_damage(chance, 5, 18, "venom") == pytest.approx(geometric)


@pytest.mark.parametrize("style", ["slash", "ranged", "magic"])
def test_charged_serpentine_unreviewed_combinations_rejected(style):
    from tests.gear.test_native_leafy import context, weapon
    from tracker.gear.combat import evaluate_loadout
    from tracker.gear.models import EquipmentDefinition
    from tracker.gear.optimizer import RoleConfig

    item = weapon(1333, style)
    head = EquipmentDefinition(id=12931, name="Charged serp", slot="head")
    role = RoleConfig(id="r", style=style)
    native, search = context([item, head], role)
    assert not native.score({"weapon": item.id, "head": head.id}, 0)["supported"]
    assert not evaluate_loadout([item, head], role, search.levels).supported


@pytest.mark.parametrize(
    "chance,speed,duration,kind",
    [(2, 5, 60, "venom"), (1, 0, 60, "venom"), (1, 5, 0, "venom"), (1, 5, 60, "other")],
)
def test_invalid_numerical_context(chance, speed, duration, kind):
    with pytest.raises(ValueError):
        expected_damage(chance, speed, duration, kind)


@pytest.mark.parametrize(
    "poison,venom",
    [
        ("susceptible", "susceptible"),
        ("susceptible", "immune"),
        ("immune", "immune"),
        ("unknown", "unknown"),
    ],
)
@pytest.mark.parametrize("head", [None, 12931])
@pytest.mark.parametrize("armour", [-2, 0, 25, 100])
def test_python_native_status_parity(poison, venom, head, armour):
    from tests.gear.test_native_leafy import context
    from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
    from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.scoring import prepare_equipment

    weapon = EquipmentDefinition(
        id=29796,
        name="Noxious halberd",
        slot="weapon",
        attack_speed=5,
        attack_styles=("slash",),
        bonuses=EquipmentBonuses(slash=132, melee_strength=142),
    )
    items = [weapon]
    if head:
        items.append(EquipmentDefinition(id=head, name="Serpentine helm", slot="head"))
    role = RoleConfig(
        id="r",
        style="slash",
        stance="aggressive",
        target=CombatTarget(
            poison_susceptibility=poison, venom_susceptibility=venom, flat_armour=armour
        ),
    )
    native, search = context(items, role)
    actual = native.score({i.slot: i.id for i in items}, 0)
    report = evaluate_loadout(items, role, search.levels)
    score = evaluate_prepared_score(prepare_equipment(items), role, search.levels)
    assert report.supported and score.supported and actual["supported"]
    assert actual["dps"] == pytest.approx(report.dps, rel=1e-14)
    assert score.dps == report.dps
    if venom == "unknown":
        assert report.status_damage.kind == "unknown"
        assert "unknown" in report.status_damage.limitations[0]
