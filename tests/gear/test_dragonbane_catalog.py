from dataclasses import replace
from pathlib import Path

import pytest

from tests.gear.test_scoring_options import context
from tracker.accounts.requirements import evaluate_requirement
from tracker.content.loader import load_content
from tracker.domain.types import SkillState, Source, UnlockState
from tracker.gear.catalog import load_catalog
from tracker.gear.optimizer import RoleConfig


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content(Path("content")))


@pytest.mark.parametrize("item_id", [22978, 21012, 25916, 25918, 30070])
def test_exact_reviewed_forms(catalog, item_id):
    item = catalog.items[item_id]
    assert item.requirements_complete
    assert not item.unsupported_effects
    assert item.tradeable is (item_id not in {25916, 25918})


def test_profiles_spells_and_bolts(catalog):
    assert catalog.items[22978].attack_profiles == (
        ("stab", "controlled"),
        ("slash", "controlled"),
        ("crush", "controlled"),
        ("stab", "defensive"),
    )
    for item_id in (21012, 25916, 25918):
        assert {"bolt:21905", "bolt:21944", "bolt:21946", "bolt:11875", "bolt:21316"} <= set(
            catalog.items[item_id].ammo_for
        )
        assert "arrow:892" not in catalog.items[item_id].ammo_for
        assert "bolt:8882" not in catalog.items[item_id].ammo_for
    wand = catalog.items[30070]
    assert {"fire_surge", "ice_barrage"} <= set(wand.spell_compatibility)
    assert "dark_demonbane" not in wand.spell_compatibility
    assert wand.attack_speed == 4


@pytest.mark.parametrize(
    "state,expected",
    [(None, "unknown"), (UnlockState.LOCKED, "unsatisfied"), (UnlockState.UNLOCKED, "satisfied")],
)
def test_lance_requires_training_observation(catalog, state, expected):
    snapshot, _, _, _ = context(RoleConfig(id="melee", style="stab"))
    snapshot = replace(
        snapshot,
        skills={
            **snapshot.skills,
            "attack": SkillState(78, None, Source.MANUAL, snapshot.last_sync_at),
        },
        unlocks={} if state is None else {"barbarian_hasta_training": state},
    )
    assert evaluate_requirement(snapshot, catalog.items[22978].requires).status.value == expected
    insufficient = replace(
        snapshot,
        skills={
            **snapshot.skills,
            "attack": SkillState(77, None, Source.MANUAL, snapshot.last_sync_at),
        },
    )
    assert (
        evaluate_requirement(insufficient, catalog.items[22978].requires).status.value
        == "unsatisfied"
    )


def test_exact_identity_and_blockers(catalog):
    from tracker.gear.dragonbane import apply_review

    row = catalog.items[22978].model_dump()
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "name": "Wrong"})
    assert apply_review(
        {**row, "unsupported_effects": ["Offensive effects have not been validated.", "Other"]}
    )["unsupported_effects"] == ["Other"]
    assert apply_review({**row, "id": 1})["id"] == 1


@pytest.mark.parametrize(
    "item_id,skill,level",
    [(21012, "ranged", 70), (25916, "ranged", 70), (25918, "ranged", 70), (30070, "magic", 65)],
)
def test_other_forms_have_only_reviewed_wear_levels(catalog, item_id, skill, level):
    assert catalog.items[item_id].requires.to_yaml() == {"skill": {skill: level}}
