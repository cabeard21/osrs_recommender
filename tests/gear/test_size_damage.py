from math import floor

import pytest
from pydantic import ValidationError

from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout, evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentDefinition
from tracker.gear.optimizer import RoleConfig
from tracker.gear.prepared_combat import prepared_combat
from tracker.gear.scoring import prepare_equipment

LEVELS = {"attack": 60, "strength": 60, "ranged": 60, "magic": 60, "defence": 60}


@pytest.fixture
def blade(make_content):
    return load_catalog(make_content()).items[27021]


def test_colossal_review_and_profiles(blade):
    assert not blade.unsupported_effects
    assert blade.requirements_complete and blade.tradeable is False
    assert blade.requires.to_yaml() == {"skill": {"attack": 60}}
    assert blade.size_damage_bonus.model_dump() == {"damage_per_size": 2, "max_size": 5}
    assert blade.attack_profiles == (
        ("slash", "accurate"),
        ("slash", "aggressive"),
        ("crush", "aggressive"),
        ("slash", "defensive"),
    )


@pytest.mark.parametrize("style", ["slash", "crush"])
@pytest.mark.parametrize("size", [0, 1, 2, 3, 4, 5, 6, 64])
@pytest.mark.parametrize("task", [False, True])
def test_colossal_maximum_and_exact_damage_distribution(blade, style, size, task):
    mask = EquipmentDefinition(id=8921, name="Black mask", slot="head", slayer_bonus="melee")
    role = RoleConfig(
        id="melee",
        style=style,
        stance="aggressive",
        on_slayer_task=task,
        target=CombatTarget(size=size),
    )
    result = evaluate_loadout([blade, mask], role, LEVELS)
    base = floor(0.5 + 71 * 164 / 640)
    maximum = (base * 7 // 6 if task else base) + 2 * min(size, 5)
    assert result.supported and result.max_hit == maximum
    assert result.size_damage_bonus.model_dump() == {
        "item_id": 27021,
        "target_size": size,
        "max_hit_bonus": 2 * min(size, 5),
    }
    mean = sum(max(1, d) for d in range(maximum + 1)) / (maximum + 1)
    assert result.dps == pytest.approx(result.accuracy * mean / 3.6)
    plain = blade.model_copy(update={"size_damage_bonus": None})
    baseline = evaluate_loadout([plain, mask], role, LEVELS)
    assert result.attack_roll == baseline.attack_roll
    with prepared_combat():
        for target_size in (1, size, 5, 1):
            changed = role.model_copy(update={"target": CombatTarget(size=target_size)})
            expected = evaluate_loadout([blade, mask], changed, LEVELS)
            score = evaluate_prepared_score(prepare_equipment([blade, mask]), changed, LEVELS)
            assert score.supported and score.dps == expected.dps


@pytest.mark.parametrize("armour", [-5, 0, 5, 100])
def test_size_bonus_is_rolled_before_flat_armour(blade, armour):
    role = RoleConfig(id="melee", style="slash", target=CombatTarget(size=5, flat_armour=armour))
    result = evaluate_loadout([blade], role, LEVELS)
    maximum = floor(0.5 + 68 * 164 / 640) + 10
    expected = sum(max(0, max(1, d) - armour) for d in range(maximum + 1)) / (maximum + 1)
    assert result.supported
    assert result.max_hit == max(0, maximum - armour)
    assert result.dps == pytest.approx(result.accuracy * expected / 3.6)


def test_size_bonus_respects_damage_cap(blade):
    role = RoleConfig(id="melee", style="slash", target=CombatTarget(size=5, damage_cap=20))
    assert not evaluate_loadout([blade], role, LEVELS).supported


@pytest.mark.parametrize("style", ["ranged", "magic"])
def test_size_effect_is_only_for_melee_weapon(style):
    effect = {"damage_per_size": 2, "max_size": 5}
    weapon = EquipmentDefinition(
        id=1,
        name="Fixture",
        slot="weapon",
        attack_styles=(style,),
        size_damage_bonus=effect,
    )
    role = RoleConfig(id="other", style=style, target=CombatTarget(size=5))
    plain = weapon.model_copy(update={"size_damage_bonus": None})
    assert evaluate_loadout([weapon], role, LEVELS) == evaluate_loadout([plain], role, LEVELS)


@pytest.mark.parametrize("size", [65, -1, True, 1.5, "5"])
def test_target_size_rejects_invalid_values(size):
    with pytest.raises(ValidationError):
        CombatTarget(size=size)


def test_old_targets_default_to_one_tile():
    assert CombatTarget().size == 1


def test_size_review_keeps_unrelated_blockers_and_checks_identity(blade):
    from tracker.gear.size_damage import apply_review

    row = blade.model_dump()
    result = apply_review(
        {
            **row,
            "unsupported_effects": [
                "Offensive effects have not been validated.",
                "Other mechanic",
            ],
        }
    )
    assert result["unsupported_effects"] == ["Other mechanic"]
    assert apply_review({**row, "id": 1})["id"] == 1
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "name": "Wrong weapon"})


def test_optimizer_changes_weapon_choice_with_target_size(blade):
    from tests.gear.test_optimizer import run
    from tracker.gear.models import EquipmentBonuses

    # Equal accuracy and speed isolate the two weapons' damage tradeoff.
    rival = blade.model_copy(
        update={
            "id": 1,
            "name": "Stronger ordinary weapon",
            "size_damage_bonus": None,
            "bonuses": EquipmentBonuses(slash=98, melee_strength=130),
        }
    )
    selected = []
    for size in (1, 5):
        result = run(
            [blade, rival],
            (
                RoleConfig(
                    id="melee",
                    style="slash",
                    target=CombatTarget(size=size),
                ),
            ),
        )
        loadout = result["selected_solution"]["loadouts"]["melee"]
        selected.append(loadout["equipment"]["weapon"])
        if size == 5:
            assert loadout["performance"]["size_damage_bonus"]["max_hit_bonus"] == 10
        assert result["assumptions"]["size_damage_model_version"] == "target-size-max-hit-v1"
    assert selected == [1, 27021]


def test_size_weapon_survives_bounded_candidate_retention(blade, monkeypatch):
    from dataclasses import replace

    from tests.gear.test_optimizer import NOW, weapon
    from tests.gear.test_scoring_options import context
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.content.loader import Content
    from tracker.domain.types import Container
    from tracker.gear import optimizer
    from tracker.gear.facts import equipment_fact

    role = RoleConfig(id="melee", style="slash", target=CombatTarget(size=5))
    snapshot, items, _, request = context(role)
    items = {**items, 27021: blade, **{i: weapon(i, "slash", 500) for i in range(100, 110)}}
    snapshot = replace(
        snapshot,
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in items
        },
    )
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    pools = optimizer._Search(snapshot, request, items, facts, None).candidate_pools()
    assert 27021 in pools["weapon"]
