"""Known equipment totals, independent of optimizer search and account ownership.

Reference: weirdgloop/osrs-dps-calc at
89c3e25b344aea90d0189746e4b5f73dde0f0383, cdn/json/equipment.json.
"""

import pytest

from tools.import_equipment import normalize
from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout
from tracker.gear.models import EquipmentDefinition

LOADOUT_IDS = (1333, 12610, 884, 10828, 1019, 1725, 577, 1033, 11126, 4131, 13125)


@pytest.mark.parametrize(
    ("item_id", "strength"),
    ((1333, 44), (10828, 3), (1725, 10), (11126, 6), (4131, 2), (10551, 4), (7462, 12)),
)
def test_known_melee_strength_survives_catalog_serialization(item_id, strength):
    item = load_catalog(load_content()).items[item_id]
    assert item.bonuses.melee_strength == strength
    assert EquipmentDefinition.model_validate_json(item.model_dump_json()) == item


def test_import_preserves_distinct_attack_strength_and_defence_bonuses():
    # Independent source-shaped fixture: do not derive expected values from catalog.json.
    item = EquipmentDefinition.model_validate(
        normalize(
            {
                "id": 1333,
                "name": "Rune scimitar",
                "slot": "weapon",
                "category": "Slash Sword",
                "speed": 4,
                "isTwoHanded": False,
                "offensive": {"stab": 7, "slash": 45, "crush": -2, "magic": 0, "ranged": 0},
                "defensive": {"stab": 0, "slash": 1, "crush": 0, "magic": 0, "ranged": 0},
                "bonuses": {"str": 44, "ranged_str": 0, "magic_str": 0, "prayer": 0},
            }
        )
    )
    assert item.bonuses.slash == 45
    assert item.bonuses.melee_strength == 44
    assert item.bonuses.defence_slash == 1
    assert item.attack_speed == 4


def test_ownership_alias_does_not_replace_physical_equipment_statistics(make_content, make_item):
    content = make_content(items=[make_item("alias", numeric_id=4587, variant_item_ids=(1333,))])
    catalog = load_catalog(content)
    assert catalog.items[1333].bonuses.melee_strength == 44
    assert catalog.items[4587].bonuses.melee_strength == 66
    assert not catalog.items[1333].requirements_complete


def test_complete_loadout_totals_and_independent_ordinary_melee_reference():
    catalog = load_catalog(load_content())
    items = [catalog.items[item_id] for item_id in LOADOUT_IDS]
    result = evaluate_loadout(items, "slash", {"attack": 59, "strength": 59})
    assert result.supported
    assert result.bonuses.model_dump() == {
        "stab": 14,
        "slash": 52,
        "crush": 5,
        "ranged": 16,
        "magic": 5,
        "melee_strength": 65,
        "ranged_strength": 10,
        "magic_damage": 0,
        "defence_stab": 48,
        "defence_slash": 49,
        "defence_crush": 54,
        "defence_ranged": 37,
        "defence_magic": 12,
        "prayer": 12,
    }
    # Pinned Wiki ordinary-attack rules, calculated independently of _calculate.
    effective_strength = 59 + 8  # Accurate gives +3 Attack, no Strength stance bonus.
    strength_bonus = 44 + 3 + 10 + 6 + 2
    assert effective_strength * (strength_bonus + 64) == 8643
    assert result.max_hit == (320 + effective_strength * (strength_bonus + 64)) // 640 == 14
    assert result.attack_roll == (59 + 8 + 3) * (45 + 7 + 64) == 8120
    assert result.defence_roll == (1 + 9) * 64 == 640
    accuracy = 1 - 642 / 16242
    assert result.accuracy == pytest.approx(accuracy)
    # On an accurate hit, uniform 0..14 transforms zero to one (total damage 106).
    assert result.dps == pytest.approx(accuracy * (106 / 15) / 2.4)
    assert result.attack_interval == 2.4


def test_mapping_and_sequence_aggregate_identically():
    catalog = load_catalog(load_content())
    items = [catalog.items[item_id] for item_id in LOADOUT_IDS]
    levels = {"attack": 59, "strength": 59}
    assert evaluate_loadout(
        {item.slot: item for item in items}, "slash", levels
    ) == evaluate_loadout(items, "slash", levels)


def test_torso_strength_increase_is_a_dps_tie_at_this_hit_breakpoint():
    catalog = load_catalog(load_content())
    items = [catalog.items[item_id] for item_id in LOADOUT_IDS]
    baseline = evaluate_loadout(items, "slash", {"attack": 59, "strength": 59})
    torso = evaluate_loadout(
        [catalog.items[10551] if item.slot == "body" else item for item in items],
        "slash",
        {"attack": 59, "strength": 59},
    )
    assert torso.bonuses.melee_strength == baseline.bonuses.melee_strength + 4
    assert torso.max_hit == baseline.max_hit == 14
    assert torso.attack_roll == baseline.attack_roll
    assert torso.dps == baseline.dps
    assert torso.bonuses.defence_slash > baseline.bonuses.defence_slash


def test_corrected_complete_loadout_matches_pinned_wiki_execution():
    catalog = load_catalog(load_content())
    replacements = {1725: 6585, 577: 10551, 13125: 26770}
    result = evaluate_loadout(
        [catalog.items[replacements.get(item_id, item_id)] for item_id in LOADOUT_IDS],
        "slash",
        {"attack": 59, "strength": 59},
    )
    assert result.supported
    assert result.bonuses.melee_strength == 44 + 3 + 8 + 4 + 6 + 2 + 8 == 75
    assert result.bonuses.slash == 45 + 7 + 10 == 62
    assert result.attack_roll == 70 * 126 == 8820
    assert result.defence_roll == 640
    assert result.max_hit == (320 + 67 * 139) // 640 == 15
    assert result.accuracy == pytest.approx(1 - 642 / 17642)
    assert result.dps == pytest.approx(3.0363738994067186)
    assert result.attack_interval == 2.4


@pytest.mark.parametrize("variant_id", (25264, 26770))
def test_reviewed_imbued_ring_forms_retain_their_own_physical_identity(variant_id):
    catalog = load_catalog(load_content())
    primary = catalog.items[11773]
    variant = catalog.items[variant_id]
    assert variant.id == variant_id
    assert variant.bonuses == primary.bonuses
    assert variant.requirements_complete
    assert variant.requires == primary.requires
    assert variant.tradeable is False
    assert not variant.unsupported_effects


def test_owned_ring_variant_and_torso_jointly_improve_optimized_max_hit():
    from datetime import UTC, datetime

    from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
    from tracker.domain.types import Container, QuestStatus, SkillState, Source
    from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

    content = load_content()
    catalog = load_catalog(content)
    now = datetime(2026, 10, 19, tzinfo=UTC)
    snapshot = AccountSnapshot(
        1,
        "bonus-regression",
        skills={
            skill: SkillState(level, None, Source.MANUAL, now)
            for skill, level in {"attack": 59, "strength": 59, "defence": 56}.items()
        },
        quests=dict.fromkeys(
            ("the_fremennik_trials", "the_fremennik_isles", "horror_from_the_deep"),
            QuestStatus.COMPLETE,
        ),
        observed_items={
            (item_id, Container.BANK): ObservedItemFact(item_id, Container.BANK, 1, "test", now)
            for item_id in (*LOADOUT_IDS, 26770, 10551)
        },
    )
    result = optimize(
        snapshot,
        OptimizationRequest(roles=(RoleConfig(id="melee", style="slash"),), mode="owned"),
        catalog,
        content,
        {},
        now,
    )
    loadout = result["selected_solution"]["loadouts"]["melee"]
    assert loadout["equipment"]["ring"] == 26770
    assert loadout["equipment"]["body"] == 10551
    assert 11773 not in loadout["equipment"].values()
    assert loadout["performance"]["bonuses"]["melee_strength"] == 77
    assert loadout["performance"]["max_hit"] == 15
    assert loadout["performance"]["dps"] == pytest.approx(3.026489964290112)
    assert result["selected_solution"]["purchase_cost_gp"] == 0


def test_reviewed_form_still_needs_authored_gate_completeness(make_content, make_item):
    content = make_content(
        items=[
            make_item(
                "ring",
                numeric_id=11773,
                variant_item_ids=(26770,),
                gate_unknown=True,
            )
        ]
    )
    assert not load_catalog(content).items[26770].requirements_complete
    # Physical equivalence is insufficient to invent missing authored wear gates.
    assert not load_catalog(make_content()).items[26770].requirements_complete


@pytest.mark.parametrize("changed_field", ("strength", "slot", "speed", "missing_primary"))
def test_reviewed_equivalence_rejects_source_drift(tmp_path, changed_field):
    import hashlib
    import json
    from pathlib import Path

    rows = json.loads(Path("content/equipment/catalog.json").read_text(encoding="utf-8"))
    primary = next(row for row in rows if row["id"] == 11773)
    variant = next(row for row in rows if row["id"] == 26770)
    if changed_field == "strength":
        variant = {**variant, "bonuses": {**variant["bonuses"], "melee_strength": 9}}
    elif changed_field == "slot":
        variant = {**variant, "slot": "head"}
    elif changed_field == "speed":
        variant = {**variant, "attack_speed": 2}
    payload = json.dumps([variant] if changed_field == "missing_primary" else [primary, variant])
    (tmp_path / "catalog.json").write_bytes(payload.encode())
    (tmp_path / "manifest.json").write_text(
        json.dumps({"catalog_sha256": hashlib.sha256(payload.encode()).hexdigest()})
    )
    with pytest.raises(ValueError, match="Reviewed equipment form differs"):
        load_catalog(load_content(), tmp_path)


def test_ambiguous_source_form_remains_unsupported(tmp_path):
    import hashlib
    import json
    from pathlib import Path

    rows = json.loads(Path("content/equipment/catalog.json").read_text(encoding="utf-8"))
    selected = [
        {**row, "unsupported_effects": ["Ambiguous source equipment variant."]}
        if row["id"] == 26770
        else row
        for row in rows
        if row["id"] in {11773, 26770}
    ]
    payload = json.dumps(selected).encode()
    (tmp_path / "catalog.json").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"catalog_sha256": hashlib.sha256(payload).hexdigest()})
    )
    variant = load_catalog(load_content(), tmp_path).items[26770]
    assert variant.unsupported_effects == ("Ambiguous source equipment variant.",)
