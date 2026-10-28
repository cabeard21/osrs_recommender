"""Combat-option selection through the existing complete-loadout search."""

from datetime import UTC, datetime
from types import SimpleNamespace

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _run(role: RoleConfig):
    weapon = EquipmentDefinition(
        id=101,
        name="Test blade",
        slot="weapon",
        attack_styles=("stab", "slash"),
        attack_profiles=(("stab", "accurate"), ("slash", "aggressive")),
        bonuses=EquipmentBonuses(stab=0, slash=80, melee_strength=40),
        requirements_complete=True,
    )
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (101, Container.BANK): ObservedItemFact(101, Container.BANK, 1, "test", NOW)
        },
    )
    return optimize(
        snapshot,
        OptimizationRequest(roles=(role,), mode="owned", max_swaps=0),
        SimpleNamespace(items={101: weapon}, version="test"),
        Content(),
        {},
        NOW,
    )


def _filters(attack_types=("stab", "slash"), stances=("accurate", "aggressive")):
    return CombatOptionFilters(attack_types=attack_types, stances=stances, spells=())


def test_optimizer_selects_best_legal_weapon_option():
    result = _run(RoleConfig(id="melee", style="stab", combat_options=_filters()))
    loadout = result["selected_solution"]["loadouts"]["melee"]
    assert loadout["combat_option"] == {
        "attack_type": "slash",
        "stance": "aggressive",
        "spell": None,
        "powered_attack": None,
    }
    assert loadout["performance"]["supported"]


def test_filter_excludes_better_option_and_empty_selection_remains_empty():
    filtered = _run(
        RoleConfig(id="melee", style="stab", combat_options=_filters(("stab",), ("accurate",)))
    )
    assert (
        filtered["selected_solution"]["loadouts"]["melee"]["combat_option"]["attack_type"] == "stab"
    )
    empty = _run(RoleConfig(id="melee", style="stab", combat_options=_filters(())))
    assert empty["selected_solution"] is None


def test_omitted_filters_keep_legacy_fixed_attack():
    result = _run(RoleConfig(id="melee", style="stab"))
    loadout = result["selected_solution"]["loadouts"]["melee"]
    assert loadout["combat_option"]["attack_type"] == "stab"
    assert loadout["combat_option"]["stance"] == "accurate"


def test_magic_option_is_selected_with_no_spellbook_unlock_row():
    result = _run(
        RoleConfig(
            id="magic",
            style="magic",
            combat_options=CombatOptionFilters(
                attack_types=("magic",), stances=("accurate",), spells=("wind_strike",)
            ),
        )
    )
    loadout = result["selected_solution"]["loadouts"]["magic"]
    assert loadout["combat_option"]["spell"] == "wind_strike"
    assert loadout["performance"]["supported"]
