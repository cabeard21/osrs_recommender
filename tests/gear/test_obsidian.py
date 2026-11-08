"""Exact obsidian forms use ordinary stats, with no synergy multiplier."""

import json
from pathlib import Path

import pytest

from tests.gear.test_catalog_coverage_phase2 import LEVELS, NOW, snapshot
from tests.gear.test_high_impact_coverage import quote
from tracker.content.loader import load_content
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.combat import evaluate_loadout
from tracker.gear.evaluation import item_problems
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

RULES = {
    21298: {"defence": 60},
    21301: {"defence": 60},
    21304: {"defence": 60},
    6524: {"defence": 60},
    6568: {},
    20050: {},
    6523: {"attack": 60},
    6525: {"attack": 60},
    6527: {"attack": 60},
    6528: {"strength": 60},
    23235: {"strength": 60},
    6526: {"attack": 60, "magic": 60},
    6522: {"ranged": 60},
}
RAW = {r["id"]: r for r in json.loads(Path("content/equipment/catalog.json").read_text())}


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


@pytest.mark.parametrize("item_id", RULES)
def test_all_forms_keep_physical_stats_and_are_eligible(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    assert item.requirements_complete
    assert not item.unsupported_effects
    assert item.bonuses.model_dump() == RAW[item_id]["bonuses"]
    assert item.attack_speed == RAW[item_id]["attack_speed"]
    assert item.two_handed == RAW[item_id]["two_handed"]
    assert item.tradeable is (item_id != 23235)
    owned = equipment_fact(snapshot(owned=(item_id,)), item, content, {}, NOW)
    request = OptimizationRequest(roles=(RoleConfig(id="one", style="crush"),), mode="owned")
    assert not item_problems(item_id, owned, request)
    assert bool(item.omitted_set_effects) is (item_id not in (6568, 20050, 6524))


@pytest.mark.parametrize("item_id", RULES)
def test_exact_wear_boundaries_and_missing_skills(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    rules = RULES[item_id]
    assert (
        equipment_fact(snapshot(levels=rules), item, content, {}, NOW)["wear"]["status"]
        == "satisfied"
    )
    for skill, level in rules.items():
        below = snapshot(levels={**rules, skill: level - 1})
        missing = snapshot(levels={k: v for k, v in rules.items() if k != skill})
        assert equipment_fact(below, item, content, {}, NOW)["wear"]["status"] == "unsatisfied"
        assert equipment_fact(missing, item, content, {}, NOW)["wear"]["status"] == "unknown"


@pytest.mark.parametrize("item_id", RULES)
def test_exact_purchase_quotes_and_no_form_aliases(reviewed, item_id):
    content, catalog = reviewed
    item = catalog.items[item_id]
    player = snapshot(owned=(6528,) if item_id == 23235 else ())
    request = OptimizationRequest(
        roles=(RoleConfig(id="one", style="crush"),), mode="usable", budget_gp=100
    )
    unquoted = equipment_fact(player, item, content, {}, NOW)
    assert item_problems(item_id, unquoted, request)
    priced = equipment_fact(player, item, content, {item_id: quote(item_id)}, NOW)
    assert bool(item_problems(item_id, priced, request)) is (item_id == 23235)
    assert priced["ownership"]["status"] == "unknown"


@pytest.mark.parametrize(
    "item_id,style",
    [
        (6523, "stab"),
        (6525, "slash"),
        (6527, "crush"),
        (6528, "crush"),
        (23235, "crush"),
        (6526, "crush"),
        (6526, "magic"),
        (6522, "ranged"),
    ],
)
def test_locked_optimizer_accepts_every_weapon_and_reports_omissions(reviewed, item_id, style):
    content, full = reviewed
    catalog = EquipmentCatalog({item_id: full.items[item_id]}, full.revision)
    result = optimize(
        snapshot(owned=(item_id,)),
        OptimizationRequest(
            roles=(RoleConfig(id="one", style=style, locks={"weapon": item_id}),),
            mode="owned",
            max_swaps=0,
        ),
        catalog,
        content,
        {},
        NOW,
    )
    assert result["selected_solution"] is not None
    loadout = result["selected_solution"]["loadouts"]["one"]
    assert loadout["equipment"]["weapon"] == item_id
    assert loadout["performance"]["supported"]
    assert any("not applied" in warning for warning in loadout["performance"]["limitations"])


def test_full_set_scores_identically_to_plain_base_stats(reviewed):
    _, catalog = reviewed
    gear = {catalog.items[i].slot: catalog.items[i] for i in (21298, 21301, 21304, 6523, 6524)}
    plain = {
        slot: item.model_copy(
            update={"id": item.id + 100000, "name": "Plain", "omitted_set_effects": ()}
        )
        for slot, item in gear.items()
    }
    actual = evaluate_loadout(gear, "stab", LEVELS)
    expected = evaluate_loadout(plain, "stab", LEVELS)
    assert actual.supported and expected.supported
    for field in ("attack_roll", "max_hit", "dps", "bonuses"):
        assert getattr(actual, field) == getattr(expected, field)
    assert actual.limitations
    assert catalog.items[11128].unsupported_effects  # Necklace review is separate.


def test_staff_casting_profiles_and_two_handed_legality(reviewed):
    _, catalog = reviewed
    staff = catalog.items[6526]
    assert "fire_strike" in staff.spell_compatibility
    assert ("magic", "aggressive") not in staff.attack_profiles
    cast = evaluate_loadout({"weapon": staff}, "magic", LEVELS)
    assert cast.supported and cast.attack_interval == 3
    blocked = evaluate_loadout({"weapon": staff, "shield": catalog.items[6524]}, "crush", LEVELS)
    assert not blocked.supported


def test_review_preserves_unrelated_explicit_blockers():
    from tracker.gear.obsidian import apply_review

    row = {
        **RAW[21304],
        "unsupported_effects": ["Offensive effects have not been validated.", "Unknown proc."],
    }
    reviewed = apply_review(row)
    assert reviewed["unsupported_effects"] == ["Unknown proc."]
    assert row["unsupported_effects"][0] == "Offensive effects have not been validated."
    with pytest.raises(ValueError, match="physical form"):
        apply_review({**RAW[21304], "name": "Wrong form"})


def test_review_changes_catalog_revision(make_content, monkeypatch):
    import tracker.gear.catalog as module

    before = load_catalog(make_content()).revision
    monkeypatch.setattr(module, "OBSIDIAN_REVISION", b"changed review")
    assert load_catalog(make_content()).revision != before
