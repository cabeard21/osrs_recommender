"""Presets must preserve custom-request semantics and never hide unsupported mechanics."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tools.benchmark_gear_desktop import without_observations
from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.combat import evaluate_loadout
from tracker.gear.encounters import encounter_presets, get_encounter_preset
from tracker.gear.models import (
    CombatTarget,
    EquipmentBonuses,
    EquipmentDefinition,
    TargetDefenceBonuses,
)
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize


def test_presets_are_versioned_and_source_pinned() -> None:
    presets = encounter_presets()
    assert [preset.id for preset in presets] == ["dagannoth_kings", "zulrah_forms"]
    for preset in presets:
        assert preset.version == 2
        assert "89c3e25b344aea90d0189746e4b5f73dde0f0383" in preset.source_url
        assert preset.limitations
        assert preset.scoring_supported


def test_kings_custom_request_preserves_only_declared_cycle() -> None:
    preset = get_encounter_preset("dagannoth_kings")
    request = preset.to_request(budget_gp=123, max_swaps=3, reserved_supply_slots=14)
    assert request.budget_gp == 123
    assert request.max_swaps == 3
    assert request.reserved_supply_slots == 14
    assert request.ordered_roles == ("supreme", "prime", "rex")
    assert request.loop
    assert request.base_role == "supreme"
    assert len(request.roles) == 3
    assert tuple(role.style for role in request.roles) == ("slash", "ranged", "magic")
    assert request.roles[2].target is not None
    assert request.roles[2].target.magic_level == 0
    assert all(role.target and role.target.weakness_percent == 35 for role in request.roles)
    assert all(role.target and role.target.size == 3 for role in request.roles)


def test_zulrah_is_explicit_form_template_not_claimed_rotation() -> None:
    preset = get_encounter_preset("zulrah_forms")
    request = preset.to_request()
    assert request.ordered_roles == ("serpentine", "magma", "tanzanite")
    assert not request.loop
    assert tuple(role.style for role in request.roles) == ("magic", "magic", "ranged")
    assert "rotation" in " ".join(preset.limitations).lower()
    assert all(role.target and role.target.damage_cap == 50 for role in request.roles)
    assert all(role.target and role.target.size == 5 for role in request.roles)


def test_preset_conversion_is_immutable_and_cannot_override_safety_markers() -> None:
    preset = get_encounter_preset("zulrah_forms")
    first = preset.to_request(budget_gp=10)
    second = preset.to_request(budget_gp=20)
    assert first.budget_gp == 10
    assert second.budget_gp == 20
    assert first.roles == second.roles
    with pytest.raises(TypeError):
        preset.to_request(roles=())


def test_unknown_preset_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown encounter preset"):
        get_encounter_preset("made_up_boss")


def test_rex_earth_spell_matches_independent_roll_calculation() -> None:
    role = get_encounter_preset("dagannoth_kings").roles[2]
    assert role.spell == "earth_strike"
    result = evaluate_loadout((), role, {"magic": 99})
    assert result.supported
    # Accurate casting: (99 + 9 + 2) * 64 = 7040; earth weakness adds floor(35%).
    assert result.attack_roll == 9504
    assert result.defence_roll == 9 * 74
    # All strike elements scale to 8 at Magic 99; weakness adds floor(8 * .35).
    assert result.max_hit == 10


def test_zulrah_normal_hit_is_supported_but_above_cap_is_not_approximated() -> None:
    role = get_encounter_preset("zulrah_forms").roles[0]
    result = evaluate_loadout((), role, {"magic": 99})
    assert result.supported
    assert result.attack_roll == 10560
    assert result.max_hit == 12
    assert result.defence_roll == 309 * 19
    boosted = role.model_copy(update={"spell": "fire_surge"})
    item = EquipmentDefinition(
        id=1,
        name="Synthetic magic damage",
        slot="neck",
        bonuses=EquipmentBonuses(magic_damage=100),
    )
    unsupported = evaluate_loadout((item,), boosted, {"magic": 99})
    assert not unsupported.supported
    assert unsupported.dps is None
    assert any("cap" in limitation.lower() for limitation in unsupported.limitations)


def test_zulrah_preset_has_exact_custom_request_and_combat_parity() -> None:
    preset = get_encounter_preset("zulrah_forms")
    expected_roles = tuple(
        RoleConfig(
            id=role_id,
            style=style,
            target=CombatTarget(
                name=f"Zulrah ({role_id})",
                size=5,
                defence_level=300,
                magic_level=300,
                bonuses=TargetDefenceBonuses(magic=magic_bonus, ranged=ranged_bonus),
                weakness_element="fire",
                weakness_percent=50,
                damage_cap=50,
            ),
        )
        for role_id, style, magic_bonus, ranged_bonus in (
            ("serpentine", "magic", -45, 50),
            ("magma", "magic", 0, 300),
            ("tanzanite", "ranged", 300, 0),
        )
    )
    custom = OptimizationRequest(
        roles=expected_roles,
        ordered_roles=("serpentine", "magma", "tanzanite"),
        base_role="serpentine",
    )
    assert preset.to_request() == custom
    assert evaluate_loadout((), preset.roles[0], {"magic": 99}) == evaluate_loadout(
        (), expected_roles[0], {"magic": 99}
    )


@pytest.mark.parametrize("preset_id", ["dagannoth_kings", "zulrah_forms"])
def test_preset_optimization_matches_round_tripped_custom_request(preset_id: str) -> None:
    now = datetime(2026, 10, 19, tzinfo=UTC)
    items = (
        EquipmentDefinition(
            id=1,
            name="Synthetic sword",
            slot="weapon",
            attack_styles=("slash",),
            requirements_complete=True,
        ),
        EquipmentDefinition(
            id=2,
            name="Synthetic thrown weapon",
            slot="weapon",
            attack_styles=("ranged",),
            requirements_complete=True,
        ),
    )
    snapshot = AccountSnapshot(
        1,
        "preset_test",
        skills={
            name: SkillState(99, None, Source.MANUAL, now)
            for name in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (item.id, Container.BANK): ObservedItemFact(item.id, Container.BANK, 1, "test", now)
            for item in items
        },
    )
    request = get_encounter_preset(preset_id).to_request(mode="owned", max_swaps=2)
    custom = OptimizationRequest.model_validate(request.model_dump(mode="json"))
    catalog = SimpleNamespace(items={item.id: item for item in items}, version="preset-test")
    preset_result = optimize(snapshot, request, catalog, Content(), {}, now)
    custom_result = optimize(snapshot, custom, catalog, Content(), {}, now)
    assert without_observations(preset_result) == without_observations(custom_result)
    assert preset_result["selected_solution"] is not None
    assert all(
        loadout["performance"]["supported"]
        for loadout in preset_result["selected_solution"]["loadouts"].values()
    )
