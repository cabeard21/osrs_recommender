from dataclasses import replace
from pathlib import Path

import pytest

from tests.gear.test_optimizer import NOW
from tests.gear.test_scoring_options import context
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, QuestStatus
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import RoleConfig


@pytest.fixture(scope="module")
def items():
    return load_catalog(load_content(Path("content"))).items


def test_reviewed_equipment_is_available_with_its_exact_identity(items):
    from tracker.gear.vampyres import FORMS

    for item_id, form in FORMS.items():
        item = items[item_id]
        assert (item.name, item.slot) == form
        assert item.requirements_complete and not item.unsupported_effects, item_id
        assert item.tradeable is (item_id in {2961, 21140, 9145, 9292, 9299, 9306})


def test_direct_attack_profiles_and_wear_requirements(items):
    assert items[33718].attack_profiles == (
        ("slash", "accurate"),
        ("slash", "aggressive"),
        ("slash", "defensive"),
    )
    assert items[33718].attack_speed == 4 and not items[33718].two_handed
    assert items[33722].two_handed and items[33722].attack_speed == 5
    assert ("stab", "controlled") in items[33722].attack_profiles
    assert ("crush", "aggressive") not in items[33722].attack_profiles
    assert items[33716].stackable and not items[33716].ammo_for and items[33716].attack_speed == 3
    assert items[33716].requires.to_yaml() == {"skill": {"ranged": 50}}
    assert items[33718].requires.to_yaml() == {"skill": {"attack": 50}}
    assert items[33722].requires.to_yaml() == {"skill": {"attack": 50}}
    assert items[24697].requires.to_yaml() == {"skill": {"attack": 50}}
    assert items[19675].requires.to_yaml() == {"skill": {"attack": 75}}
    assert items[2402].requires is None
    for item_id in (7639, 7648, 22398, 24699):
        assert "fire_wave" in items[item_id].spell_compatibility
        assert "ice_barrage" not in items[item_id].spell_compatibility
        assert ("magic", "aggressive") not in items[item_id].attack_profiles


@pytest.mark.parametrize("bolt", (9145, 9292, 9299, 9306))
def test_silver_bolts_require_compatible_crossbow(items, bolt):
    key = f"bolt:{bolt}"
    assert items[bolt].ammo_type == key
    assert items[bolt].requires.to_yaml() == {"skill": {"ranged": 26}}
    for supported in (9177, 9179, 9185, 25916, 26374):
        assert key in items[supported].ammo_for
    for unsupported in (9176, 8880, 861, 4734, 33716):
        assert key not in items[unsupported].ammo_for


def test_only_reviewed_form_is_changed(items):
    from tracker.gear.vampyres import apply_review

    row = items[33718].model_dump()
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "name": "Blisterwood flail"})
    assert apply_review({**row, "unsupported_effects": ["Other"]})["unsupported_effects"] == [
        "Other"
    ]
    assert items[33800].unsupported_effects  # Quest-only Silvthrill ballista


def test_quest_progress_for_planning_and_exact_observed_ownership(items):
    snapshot, _, _, _ = context(RoleConfig(id="vampyre", style="crush"))
    content = load_content(Path("content"))
    state = replace(snapshot, quests={"the_blood_moon_rises": QuestStatus.IN_PROGRESS})
    assert (
        equipment_fact(state, items[33718], content, {}, NOW)["acquisition_requirement"]["status"]
        == "satisfied"
    )
    assert (
        equipment_fact(state, items[33722], content, {}, NOW)["acquisition_requirement"]["status"]
        == "unsatisfied"
    )
    state = replace(
        snapshot,
        observed_items={
            (7639, Container.BANK): ObservedItemFact(7639, Container.BANK, 1, "test", NOW)
        },
        quests={},
    )
    assert "acquisition_requirement" not in equipment_fact(state, items[7639], content, {}, NOW)
    partial = equipment_fact(state, items[7648], content, {}, NOW)
    assert partial["planning_ownership"]["status"] != "owned"
    assert partial["acquisition_requirement"]["status"] == "unknown"


def test_poisoned_bolt_severity_changes_damage_and_respects_immunity():
    from tracker.gear.status_damage import expected_damage, poison_ammo_kind
    from tracker.gear.vampyres import SILVER_POISON_SEVERITY

    assert dict(SILVER_POISON_SEVERITY) == {9292: 6, 9299: 11, 9306: 16}
    for severity, expected in ((6, 2), (11, 3), (16, 4)):
        assert expected_damage(1, 5, 18, "poison", severity) == expected
    assert poison_ammo_kind("susceptible") == "poison"
    assert poison_ammo_kind("immune") is None
    assert poison_ammo_kind("unknown") == "unknown"
