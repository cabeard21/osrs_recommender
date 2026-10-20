from tracker.gear.catalog import load_catalog


def test_reviewed_catalog_has_stats_and_preserves_dragon_gate(make_content, make_item):
    content = make_content(
        items=[
            make_item(
                "dragon_scimitar",
                numeric_id=4587,
                requires={"all_of": [{"skill": {"attack": 60}}, {"quest": "monkey_madness_i"}]},
            )
        ],
        quests={"monkey_madness_i": "Monkey Madness I"},
    )
    catalog = load_catalog(content)
    item = catalog.items[4587]
    assert item.bonuses.slash == 67
    assert item.bonuses.melee_strength == 66
    assert item.requires == content.items["dragon_scimitar"].requires
    assert item.requirements_complete
    assert item.attack_styles == ("stab", "slash")


def test_missing_requirement_overlay_never_means_unrestricted(make_content):
    catalog = load_catalog(make_content())
    assert not catalog.items[4587].requirements_complete
    assert catalog.items[20997].unsupported_effects
    assert catalog.items[20997].two_handed


def test_magic_damage_source_tenths_are_converted_to_percent(make_content):
    catalog = load_catalog(make_content())
    assert catalog.items[12002].bonuses.magic_damage == 5
    assert catalog.items[21018].bonuses.magic_damage == 3
    assert 7800 not in catalog.items
