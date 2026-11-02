"""Ancient direct damage, account eligibility and optimizer integration."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tracker.api.gear_evaluations import FixedEvaluation
from tracker.api.gear_ui import combat_option_capabilities
from tracker.content.loader import load_content
from tracker.domain.types import QuestStatus, UnlockState
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_loadout
from tracker.gear.combat_options import eligible_combat_options, enumerate_combat_options
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize

CASES = [
    ("smoke_rush", 50, 13),
    ("shadow_rush", 52, 14),
    ("blood_rush", 56, 15),
    ("ice_rush", 58, 16),
    ("smoke_burst", 62, 17),
    ("shadow_burst", 64, 18),
    ("blood_burst", 68, 21),
    ("ice_burst", 70, 22),
    ("smoke_blitz", 74, 23),
    ("shadow_blitz", 76, 24),
    ("blood_blitz", 80, 25),
    ("ice_blitz", 82, 26),
    ("smoke_barrage", 86, 27),
    ("shadow_barrage", 88, 28),
    ("blood_barrage", 92, 29),
    ("ice_barrage", 94, 30),
]


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


@pytest.mark.parametrize(("spell", "level", "hit"), CASES)
def test_ancient_direct_damage_and_level_boundary(reviewed, spell, level, hit):
    _, catalog = reviewed
    staff = catalog.items[4675]
    for magic in (level, 99):
        result = evaluate_loadout([staff], "magic", {"magic": magic}, spell=spell)
        assert result.supported
        assert result.max_hit == hit
        assert result.attack_interval == 3
        assert any("Single-target" in note for note in result.limitations)
    assert not evaluate_loadout([staff], "magic", {"magic": level - 1}, spell=spell).supported
    weakness = evaluate_loadout(
        [staff],
        "magic",
        {"magic": 99},
        CombatTarget(weakness_element="water", weakness_percent=100),
        spell=spell,
    )
    assert weakness.max_hit == hit
    assert not weakness.elemental_weakness.applied


@pytest.mark.parametrize("staff_id", [None, 1387, 1409])
def test_ancient_autocast_requires_reviewed_compatible_staff(reviewed, staff_id):
    _, catalog = reviewed
    items = [catalog.items[staff_id]] if staff_id else []
    assert not evaluate_loadout(items, "magic", {"magic": 99}, spell="ice_barrage").supported


@pytest.mark.parametrize("quest", [None, QuestStatus.NOT_STARTED, QuestStatus.COMPLETE])
@pytest.mark.parametrize(
    "unlock", [None, UnlockState.LOCKED, UnlockState.UNKNOWN, UnlockState.UNLOCKED]
)
def test_ancient_access_and_capabilities(reviewed, quest, unlock):
    _, catalog = reviewed
    player = replace(
        snapshot(levels={"magic": 94}),
        quests={} if quest is None else {"desert_treasure_i": quest},
        unlocks={
            "spellbook_standard": UnlockState.LOCKED,
            **({"spellbook_ancient": unlock} if unlock is not None else {}),
        },
    )
    expected = quest == QuestStatus.COMPLETE and unlock in (None, UnlockState.UNLOCKED)
    options = enumerate_combat_options(catalog.items[4675], player, discipline="magic", levels={})
    barrage = next(row for row in options if row.spell == "ice_barrage")
    assert barrage.available is expected
    assert all(not row.available for row in options if row.spell == "fire_strike")
    spells = combat_option_capabilities(player, SimpleNamespace(equipment_catalog=lambda: catalog))[
        "spells"
    ]
    assert next(row for row in spells if row["id"] == "ice_barrage")["available"] is expected
    assert not eligible_combat_options(None, player, discipline="magic", levels={})


@pytest.mark.parametrize("automatic", [True, False])
def test_ancient_staff_optimized_with_ancient_spell(reviewed, automatic):
    content, catalog = reviewed
    player = snapshot(
        levels={"attack": 50, "magic": 70},
        owned=(4675,),
        quests={"desert_treasure_i": QuestStatus.COMPLETE},
    )
    role = RoleConfig(
        id="mage",
        style="magic",
        spell="ice_burst",
        combat_options=CombatOptionFilters(
            attack_types=("magic",), stances=("accurate",), spells=("ice_burst",)
        )
        if automatic
        else None,
    )
    result = optimize(
        player,
        OptimizationRequest(roles=(role,), mode="owned", locks={"weapon": 4675}),
        catalog,
        content,
        {},
        NOW,
    )
    solution = result["selected_solution"]
    assert solution is not None
    assert solution["loadouts"]["mage"]["performance"]["max_hit"] == 22


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize("unlock_key", ["spellbook_ancient", "ancient_magicks"])
def test_explicit_ancient_lock_blocks_search_and_fixed_evaluation(reviewed, automatic, unlock_key):
    content, catalog = reviewed
    player = replace(
        snapshot(
            levels={"attack": 50, "magic": 70},
            owned=(4675,),
            quests={"desert_treasure_i": QuestStatus.COMPLETE},
        ),
        unlocks={unlock_key: UnlockState.LOCKED},
    )
    role = RoleConfig(
        id="mage",
        style="magic",
        spell="ice_burst",
        combat_options=CombatOptionFilters(
            attack_types=("magic",), stances=("accurate",), spells=("ice_burst",)
        )
        if automatic
        else None,
    )
    request = OptimizationRequest(roles=(role,), mode="owned", locks={"weapon": 4675})
    assert optimize(player, request, catalog, content, {}, NOW)["selected_solution"] is None
    if not automatic:
        result = evaluate_configurations(
            player, request, {"weapon": 4675}, {"weapon": 4675}, catalog, content, {}, NOW
        )
        assert result["baseline"]["status"] == "invalid"
        assert result["baseline"]["performance"] is None
        assert any(row["path"] == "spell" for row in result["baseline"]["reasons"])
        FixedEvaluation.model_validate(result["baseline"])


def test_ancient_magic_damage_bonus(reviewed):
    _, catalog = reviewed
    staff = catalog.items[4675]
    boosted = staff.model_copy(
        update={"bonuses": staff.bonuses.model_copy(update={"magic_damage": 15.0})}
    )
    result = evaluate_loadout([boosted], "magic", {"magic": 94}, spell="ice_barrage")
    assert result.supported and result.max_hit == 34
