import pytest
from pydantic import ValidationError

from tracker.gear.combat import evaluate_loadout
from tracker.gear.models import EquipmentDefinition
from tracker.gear.optimizer import RoleConfig

LEVELS = {"attack": 90, "strength": 90, "magic": 90, "ranged": 90}


def test_request_defaults_and_strict_validation():
    role = RoleConfig(id="r", style="slash")
    assert role.safe_spotting is False
    assert role.fight_duration_seconds == 60
    for patch in (
        {"safe_spotting": 1},
        {"fight_duration_seconds": True},
        {"fight_duration_seconds": 0},
        {"fight_duration_seconds": 3601},
        {"style": "special", "safe_spotting": True},
    ):
        with pytest.raises(ValidationError):
            RoleConfig(**{"id": "r", "style": "slash", **patch})


@pytest.mark.parametrize(
    "item_id,valid",
    [(1333, False), (3190, True), (3204, True), (23987, True), (29796, True), (4158, False)],
)
def test_actual_melee_reach(item_id, valid):
    weapon = EquipmentDefinition(
        id=item_id, name=str(item_id), slot="weapon", attack_styles=("slash",)
    )
    role = RoleConfig(id="r", style="slash", safe_spotting=True)
    result = evaluate_loadout([weapon], role, LEVELS)
    assert result.supported == valid
    assert evaluate_loadout(
        [weapon], role.model_copy(update={"safe_spotting": False}), LEVELS
    ).supported


def test_casting_and_staff_melee_are_separate():
    staff = EquipmentDefinition(
        id=1381, name="Staff of air", slot="weapon", attack_styles=("crush",)
    )
    assert evaluate_loadout(
        [staff], RoleConfig(id="r", style="magic", safe_spotting=True), LEVELS
    ).supported
    assert not evaluate_loadout(
        [staff], RoleConfig(id="r", style="crush", safe_spotting=True), LEVELS
    ).supported
    assert not evaluate_loadout(
        [], RoleConfig(id="r", style="crush", safe_spotting=True), LEVELS
    ).supported


def test_reviewed_catalog_halberd_profiles_and_gates(make_content):
    from tracker.gear.catalog import load_catalog

    catalog = load_catalog(make_content())
    for item_id in (3190, 3192, 3194, 3196, 3198, 3200, 3202, 3204, 6599, 28049, 23987, 29796):
        weapon = catalog.items[item_id]
        assert weapon.requirements_complete
        assert weapon.attack_profiles == (
            ("stab", "controlled"),
            ("slash", "aggressive"),
            ("stab", "defensive"),
        )
        assert not weapon.unsupported_effects
    assert catalog.items[3204].requires.to_yaml()["all_of"][-1] == {"quest": "regicide"}
    assert catalog.items[23987].requires.to_yaml()["all_of"][-1] == {"unlock": "diary_western_hard"}
    assert catalog.items[23895].unsupported_effects


@pytest.mark.parametrize("item_id,valid", [(861, True), (10148, False), (99999, False)])
def test_ranged_reach_requires_reviewed_form(item_id, valid):
    weapon = EquipmentDefinition(
        id=item_id,
        name="bow",
        slot="weapon",
        attack_styles=("ranged",),
        attack_profiles=(("ranged", "rapid"),),
    )
    role = RoleConfig(id="r", style="ranged", stance="rapid", safe_spotting=True)
    assert evaluate_loadout([weapon], role, LEVELS).supported == valid


@pytest.mark.parametrize("item_id,valid", [(3202, True), (1333, False)])
def test_native_fixed_attacks_enforce_reach(item_id, valid):
    from tests.gear.test_native_leafy import context

    weapon = EquipmentDefinition(
        id=item_id, name="fixture", slot="weapon", attack_styles=("slash",)
    )
    role = RoleConfig(id="r", style="slash", safe_spotting=True)
    scorer, _ = context([weapon], role)
    actual = scorer.score({"weapon": item_id}, 0)
    assert actual["supported"] == valid


def test_complete_synergy_seeds_respect_locks_and_budget():
    from tracker.gear.optimizer import OptimizationRequest, _Search

    search = object.__new__(_Search)
    role = RoleConfig(id="r", style="slash")
    search.request = OptimizationRequest(roles=(role,))
    search.eligible = {3202: None, 29796: None, 12931: None}
    search.cost = lambda _: 0
    assert search.synergy_seeds((role,)) == [
        {},
        {"weapon": 3202, "head": 12931},
        {"weapon": 29796, "head": 12931},
    ]
    for locks in ({"head": None}, {"weapon": 1333}, {"shield": 1540}):
        assert search.synergy_seeds((role.model_copy(update={"locks": locks}),)) == [{}]
    search.cost = lambda _: 1
    assert search.synergy_seeds((role,)) == [{}]
