import pytest
from pydantic import ValidationError

from tracker.gear.optimizer import RoleConfig


def test_mark_is_explicit_and_serialized():
    assert RoleConfig(id="a", style="magic").mark_of_darkness is False
    role = RoleConfig(id="a", style="magic", mark_of_darkness=True)
    assert role.model_dump()["mark_of_darkness"] is True


@pytest.mark.parametrize("value", [1, "true", None])
def test_mark_rejects_non_boolean(value):
    with pytest.raises(ValidationError):
        RoleConfig(id="a", style="magic", mark_of_darkness=value)


def test_fixed_auto_cannot_bypass_mark_quest_access():
    from tools.gear_search_quality_fixture import load_case
    from tracker.gear.auto import resolve_auto_role
    from tracker.gear.models import CombatTarget, EquipmentDefinition
    from tracker.gear.optimizer import CombatOptionFilters

    case = load_case("melee_1m")
    weapon = EquipmentDefinition(
        id=4170,
        name="Slayer's staff",
        slot="weapon",
        spell_compatibility=("inferior_demonbane",),
    )
    role = RoleConfig(
        id="a",
        style="magic",
        mark_of_darkness=True,
        allowed_disciplines=("magic",),
        target=CombatTarget(traits=("demon",)),
        combat_options=CombatOptionFilters(
            attack_types=("magic",),
            stances=("accurate",),
            spells=("inferior_demonbane",),
        ),
    )
    assert (
        resolve_auto_role(
            role,
            {"weapon": 4170},
            {4170: weapon},
            case.snapshot,
            {"magic": 99},
        )
        is None
    )


def test_melee_only_auto_demon_keeps_cost_frontier():
    from types import SimpleNamespace

    from tracker.gear.models import CombatTarget
    from tracker.gear.running_frontier import needs_running_cost_frontier

    role = SimpleNamespace(
        style="slash",
        allowed_disciplines=("melee",),
        target=CombatTarget(traits=("demon",)),
    )
    assert needs_running_cost_frontier(SimpleNamespace(roles=(role,)))
