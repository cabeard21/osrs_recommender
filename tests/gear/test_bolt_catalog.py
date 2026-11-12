"""Reviewed enchanted ammunition compatibility and independent wear boundaries."""

import json
from pathlib import Path

import pytest

from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(load_content())


@pytest.mark.parametrize(
    "weapon,allowed,rejected",
    [
        (9174, (9236,), (9238, 9242)),
        (9176, (9236,), (9238,)),
        (8880, (9236, 8882), (9238,)),
        (9177, (9236, 9238), (9242,)),
        (9179, (9236, 9238), (9243,)),
        (9181, (9236, 9238), (9242,)),
        (9183, (9242, 9243), (9244, 21944)),
        (9185, (9244, 9245), (21944,)),
        (21902, (9242, 21944), ()),
        (11785, (9243, 21946), ()),
        (26374, (9245, 21950), ()),
    ],
)
def test_reviewed_crossbow_boundaries(catalog, weapon, allowed, rejected):
    item = catalog.items[weapon]
    assert item.requirements_complete
    assert not item.unsupported_effects
    for bolt in allowed:
        assert catalog.items[bolt].ammo_type in item.ammo_for
    for bolt in rejected:
        assert f"bolt:{bolt}" not in item.ammo_for


@pytest.mark.parametrize(
    "normal,dragon,effect,level",
    [
        (9236, 21932, "opal", 1),
        (9238, 21936, "pearl", 26),
        (9242, 21944, "ruby", 46),
        (9243, 21946, "diamond", 46),
        (9244, 21948, "dragonstone", 61),
        (9245, 21950, "onyx", 61),
    ],
)
def test_bolt_review_exact_forms(catalog, normal, dragon, effect, level):
    for item_id, required in ((normal, level), (dragon, 64)):
        item = catalog.items[item_id]
        assert item.bolt_effect == effect
        assert item.ammo_type == f"bolt:{item_id}"
        assert item.requires.to_yaml() == {"skill": {"ranged": required}}
        assert item.requirements_complete and item.tradeable
        assert not item.unsupported_effects


def test_review_does_not_enable_utility_ammunition_or_special_weapons(catalog):
    for item_id in (9237, 9239, 9240, 9241, 21934, 21012):
        assert catalog.items[item_id].unsupported_effects


def test_overlay_preserves_unrelated_blockers_and_source_rows():
    from tracker.gear.bolts_catalog import apply_review

    rows = json.loads(Path("content/equipment/catalog.json").read_text())
    row = next(row for row in rows if row["id"] == 9236)
    original = {**row, "unsupported_effects": [*row["unsupported_effects"], "Unreviewed rule"]}
    reviewed = apply_review(original)
    assert reviewed["unsupported_effects"] == ["Unreviewed rule"]
    assert original["unsupported_effects"] != reviewed["unsupported_effects"]
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**row, "slot": "weapon"})


def test_crossbow_gates_do_not_inherit_creation_requirements(catalog):
    for item_id, level in ((9177, 26), (9183, 46), (26374, 80)):
        assert catalog.items[item_id].requires.to_yaml() == {"skill": {"ranged": level}}


def test_phoenix_tradeable_and_blurite_owned_form_preserved(catalog):
    assert catalog.items[767].tradeable is True
    assert catalog.items[9176].tradeable is False
    assert catalog.items[9176].requires.to_yaml() == {"skill": {"ranged": 16}}
