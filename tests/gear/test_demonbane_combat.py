from types import SimpleNamespace

import pytest

from tracker.gear.combat import evaluate_loadout
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition

LEVELS = dict.fromkeys(("attack", "strength", "ranged", "magic", "defence", "slayer"), 99)


def role(style="slash", **kw):
    return SimpleNamespace(
        style=style,
        stance="accurate",
        spell="dark_demonbane",
        target=CombatTarget(traits=("demon",)),
        **kw,
    )


def sword(item_id):
    return EquipmentDefinition(
        id=item_id,
        name="Fixture",
        slot="weapon",
        attack_styles=("slash",),
        bonuses=EquipmentBonuses(slash=70, melee_strength=100),
    )


@pytest.mark.parametrize(
    "item_id,percent", [(2402, 60), (6746, 60), (30305, 60), (19675, 70), (29589, 70), (29577, 5)]
)
def test_swords(item_id, percent):
    item = sword(item_id)
    baseline = evaluate_loadout([item], "slash", LEVELS)
    actual = evaluate_loadout([item], role(), LEVELS)
    assert actual.max_hit == baseline.max_hit * (100 + percent) // 100
    assert actual.attack_roll == baseline.attack_roll * (100 + percent) // 100
    assert actual.demonbane_bonus.damage_percent == percent


def test_mark_uses_rolled_distribution():
    staff = EquipmentDefinition(
        id=29594, name="Fixture", slot="weapon", spell_compatibility=("dark_demonbane",)
    )
    actual = evaluate_loadout([staff], role("magic", mark_of_darkness=True), LEVELS)
    mean = sum(max(1, x) + (max(1, x) * 50 // 100) for x in range(31)) / 31
    assert actual.supported
    assert actual.max_hit == 45
    assert actual.dps == actual.accuracy * mean / 3


def test_demon_spell_cannot_attack_non_demon():
    staff = EquipmentDefinition(
        id=29594, name="Fixture", slot="weapon", spell_compatibility=("dark_demonbane",)
    )
    assert not evaluate_loadout([staff], "magic", LEVELS, spell="dark_demonbane").supported


@pytest.mark.parametrize("vulnerability", [0, 1, 25, 70, 80, 100, 120, 200, 1000])
@pytest.mark.parametrize("percent", [25, 50])
def test_mark_total_exact(vulnerability, percent):
    from tracker.gear.combat import _marked_damage_total

    for maximum in range(100):
        expected = sum(
            max(1, x) + (max(1, x) * percent // 100) * vulnerability // 100
            for x in range(maximum + 1)
        )
        assert _marked_damage_total(maximum, percent, vulnerability) == expected


@pytest.mark.parametrize(
    "item_id,style,spell",
    [
        (2402, "slash", None),
        (6745, "slash", None),
        (6746, "slash", None),
        (30305, "slash", None),
        (19675, "slash", None),
        (29589, "slash", None),
        (29577, "slash", None),
        (29591, "ranged", None),
        (732, "ranged", None),
        (4170, "magic", "inferior_demonbane"),
        (29594, "magic", "dark_demonbane"),
    ],
)
@pytest.mark.parametrize("vulnerability", [0, 25, 70, 80, 100, 120, 200])
@pytest.mark.parametrize("task", [False, True])
def test_native_demonbane_parity(item_id, style, spell, vulnerability, task):
    from tracker.gear.native._scoring import ScoringContext

    from tracker.gear.combat import evaluate_prepared_score
    from tracker.gear.optimizer import RoleConfig
    from tracker.gear.scoring import prepare_equipment

    item = EquipmentDefinition(
        id=item_id,
        name="Fixture",
        slot="weapon",
        attack_styles=(style,),
        spell_compatibility=(spell,) if spell else (),
        bonuses=EquipmentBonuses(
            slash=70, melee_strength=100, ranged=124, ranged_strength=40, magic=37, magic_damage=10
        ),
    )
    mask = EquipmentDefinition(id=11865, name="Mask", slot="head", slayer_bonus="all")
    configured = RoleConfig(
        id="d",
        style=style,
        spell=spell or "fire_strike",
        on_slayer_task=task,
        mark_of_darkness=True,
        target=CombatTarget(traits=("demon",), demonbane_vulnerability_percent=vulnerability),
    )
    search = SimpleNamespace(
        items={item.id: item, mask.id: mask},
        eligible={item.id, mask.id},
        request=SimpleNamespace(roles=(configured,), secondary_priority="default"),
        levels=LEVELS,
    )
    actual = ScoringContext(search).score({"weapon": item.id, "head": mask.id}, 0)
    reference = evaluate_prepared_score(prepare_equipment([item, mask]), configured, LEVELS)
    assert actual["supported"] == reference.supported
    assert actual["dps"] == reference.dps
    assert actual["accuracy"] == reference.accuracy


def test_mark_damage_cap_checked_after_transform():
    from tracker.gear.native._scoring import ScoringContext

    from tracker.gear.optimizer import RoleConfig

    staff = EquipmentDefinition(
        id=29594, name="Fixture", slot="weapon", spell_compatibility=("dark_demonbane",)
    )
    configured = RoleConfig(
        id="d",
        style="magic",
        spell="dark_demonbane",
        mark_of_darkness=True,
        target=CombatTarget(traits=("demon",), damage_cap=35),
    )
    search = SimpleNamespace(
        items={staff.id: staff},
        eligible={staff.id},
        request=SimpleNamespace(roles=(configured,), secondary_priority="default"),
        levels=LEVELS,
    )
    assert not evaluate_loadout([staff], configured, LEVELS).supported
    assert not ScoringContext(search).score({"weapon": staff.id}, 0)["supported"]


def test_holy_water_damage_ignores_task_and_equipment_strength():
    from tracker.gear.optimizer import RoleConfig

    water = EquipmentDefinition(
        id=732,
        name="Holy water",
        slot="weapon",
        attack_styles=("ranged",),
        bonuses=EquipmentBonuses(ranged_strength=12),
    )
    armour = EquipmentDefinition(
        id=1, name="Armour", slot="body", bonuses=EquipmentBonuses(ranged_strength=1000)
    )
    mask = EquipmentDefinition(id=11865, name="Mask", slot="head", slayer_bonus="all")
    configured = RoleConfig(
        id="d", style="ranged", on_slayer_task=True, target=CombatTarget(traits=("demon",))
    )
    result = evaluate_loadout([water, armour, mask], configured, LEVELS)
    assert result.supported
    assert result.max_hit == 20
    assert any("Defence drain" in limitation for limitation in result.limitations)


def test_scorching_task_damage_is_additive():
    from tracker.gear.optimizer import RoleConfig

    bow = EquipmentDefinition(
        id=29591,
        name="Scorching bow",
        slot="weapon",
        attack_styles=("ranged",),
        bonuses=EquipmentBonuses(ranged=124, ranged_strength=100),
    )
    mask = EquipmentDefinition(id=11865, name="Mask", slot="head", slayer_bonus="all")
    configured = RoleConfig(
        id="d", style="ranged", on_slayer_task=True, target=CombatTarget(traits=("demon",))
    )
    baseline = evaluate_loadout([bow], "ranged", LEVELS)
    result = evaluate_loadout([bow, mask], configured, LEVELS)
    assert result.max_hit == baseline.max_hit * 145 // 100
    assert result.attack_roll == (baseline.attack_roll * 23 // 20) * 130 // 100


def test_holy_water_special_target_is_rejected():
    from tracker.gear.optimizer import RoleConfig

    water = EquipmentDefinition(id=732, name="Holy water", slot="weapon", attack_styles=("ranged",))
    configured = RoleConfig(
        id="d", style="ranged", target=CombatTarget(traits=("demon", "holy_water_special"))
    )
    assert not evaluate_loadout([water], configured, LEVELS).supported


@pytest.mark.parametrize("staff_id", [4170, 29594])
@pytest.mark.parametrize("marked", [False, True])
def test_native_spell_accuracy_and_damage_without_mark(staff_id, marked):
    from tracker.gear.native._scoring import ScoringContext

    from tracker.gear.optimizer import RoleConfig

    staff = EquipmentDefinition(
        id=staff_id, name="Staff", slot="weapon", spell_compatibility=("dark_demonbane",)
    )
    configured = RoleConfig(
        id="d",
        style="magic",
        spell="dark_demonbane",
        mark_of_darkness=marked,
        target=CombatTarget(traits=("demon",)),
    )
    search = SimpleNamespace(
        items={staff.id: staff},
        eligible={staff.id},
        request=SimpleNamespace(roles=(configured,), secondary_priority="default"),
        levels=LEVELS,
    )
    actual = ScoringContext(search).score({"weapon": staff.id}, 0)
    reference = evaluate_loadout([staff], configured, LEVELS)
    assert reference.demonbane_bonus.accuracy_percent == (40 if marked else 20) * (
        2 if staff_id == 29594 else 1
    )
    assert reference.demonbane_bonus.damage_percent == (
        (50 if staff_id == 29594 else 25) if marked else 0
    )
    assert actual["dps"] == reference.dps
    assert actual["accuracy"] == reference.accuracy
