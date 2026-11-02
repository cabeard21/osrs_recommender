"""Ancient staff participates in account-aware Standard magic search."""

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tools.import_equipment import REVIEWED
from tracker.content.loader import load_content
from tracker.domain.types import QuestStatus
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import ANCIENT_SPELLS, ELEMENTAL_SPELLS
from tracker.gear.combat_options import eligible_combat_options
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


def test_ancient_staff_reviewed_standard_spell_compatibility(reviewed):
    _, catalog = reviewed
    staff = catalog.items[4675]
    assert staff.requirements_complete and staff.tradeable
    assert not staff.unsupported_effects
    assert staff.id in REVIEWED
    assert set(staff.spell_compatibility) == set(ELEMENTAL_SPELLS) | set(ANCIENT_SPELLS)
    player = snapshot(levels={"attack": 50, "magic": 99})
    assert {
        option.spell
        for option in eligible_combat_options(staff, player, discipline="magic", levels={})
    } == set(ELEMENTAL_SPELLS)


@pytest.mark.parametrize("automatic", [True, False])
@pytest.mark.parametrize(
    ("levels", "quests", "owned", "eligible"),
    [
        ({"attack": 50, "magic": 50}, {"desert_treasure_i": QuestStatus.COMPLETE}, (4675,), True),
        ({"attack": 49, "magic": 50}, {"desert_treasure_i": QuestStatus.COMPLETE}, (4675,), False),
        ({"attack": 50, "magic": 49}, {"desert_treasure_i": QuestStatus.COMPLETE}, (4675,), False),
        ({"magic": 50}, {"desert_treasure_i": QuestStatus.COMPLETE}, (4675,), False),
        ({"attack": 50, "magic": 50}, {}, (4675,), False),
        (
            {"attack": 50, "magic": 50},
            {"desert_treasure_i": QuestStatus.NOT_STARTED},
            (4675,),
            False,
        ),
        ({"attack": 50, "magic": 50}, {"desert_treasure_i": QuestStatus.COMPLETE}, (), False),
    ],
)
def test_owned_ancient_staff_magic_search(reviewed, levels, quests, owned, eligible, automatic):
    content, catalog = reviewed
    player = snapshot(levels=levels, quests=quests, owned=owned)
    role = RoleConfig(
        id="mage",
        style="magic",
        spell="fire_bolt",
        combat_options=CombatOptionFilters(
            attack_types=("magic",), stances=("accurate",), spells=("fire_bolt",)
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
    assert (solution is not None) is eligible
    if eligible:
        loadout = solution["loadouts"]["mage"]
        assert loadout["equipment"]["weapon"] == 4675
        if automatic:
            assert loadout["combat_option"]["spell"] == "fire_bolt"
        assert loadout["performance"]["dps"] > 0
        # Its four-tick melee attack must not speed up five-tick spellcasting.
        assert loadout["performance"]["attack_interval"] == 3.0
