"""Anti-dragon shield requires Dragon Slayer I started, including completion."""

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tools.import_equipment import REVIEWED
from tracker.accounts.requirements import evaluate_requirement
from tracker.content.loader import load_content
from tracker.content.requirements import QuestLeaf, parse
from tracker.domain.types import QuestStatus
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


@pytest.mark.parametrize(
    "status,expected",
    [
        (QuestStatus.NOT_STARTED, "unsatisfied"),
        (QuestStatus.IN_PROGRESS, "satisfied"),
        (QuestStatus.COMPLETE, "satisfied"),
        (QuestStatus.UNKNOWN, "unknown"),
    ],
)
def test_started_quest_gate_round_trip(status, expected):
    raw = {"quest": {"id": "dragon_slayer_i", "status": "in_progress"}}
    gate = parse(raw)
    assert gate.to_yaml() == raw
    player = snapshot(quests={"dragon_slayer_i": status})
    result = evaluate_requirement(player, gate)
    assert result.status.value == expected
    assert result.required == "in_progress"
    # Ordinary quest requirements still require completion.
    ordinary = evaluate_requirement(player, QuestLeaf(quest_id="dragon_slayer_i"))
    assert ordinary.status.value == (
        "satisfied"
        if status is QuestStatus.COMPLETE
        else "unknown"
        if status is QuestStatus.UNKNOWN
        else "unsatisfied"
    )


@pytest.mark.parametrize(
    "status,eligible",
    [
        (QuestStatus.NOT_STARTED, False),
        (QuestStatus.IN_PROGRESS, True),
        (QuestStatus.COMPLETE, True),
        (QuestStatus.UNKNOWN, False),
        (None, False),
    ],
)
@pytest.mark.parametrize("style,weapon", [("slash", 1323), ("ranged", 8880), ("magic", 1383)])
def test_locked_shield_search(reviewed, status, eligible, style, weapon):
    content, full_catalog = reviewed
    item = full_catalog.items[1540]
    assert item.requirements_complete and item.tradeable
    assert not item.unsupported_effects
    assert item.id in REVIEWED
    catalog = EquipmentCatalog({i: full_catalog.items[i] for i in (1540, weapon, 8882)})
    player = snapshot(
        owned=(1540, weapon, 8882), quests={} if status is None else {"dragon_slayer_i": status}
    )
    fact = equipment_fact(player, item, content, {}, NOW)
    assert (fact["wear"]["status"] == "satisfied") is eligible
    result = optimize(
        player,
        OptimizationRequest(
            roles=(
                RoleConfig(id="role", style=style, spell="water_strike", locks={"shield": 1540}),
            ),
            mode="owned",
            max_swaps=0,
        ),
        catalog,
        content,
        {},
        NOW,
    )
    solution = result["selected_solution"]
    assert (solution is not None) is eligible
    if eligible:
        assert solution["loadouts"]["role"]["equipment"]["shield"] == 1540
        assert solution["score"] > 0


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "dragon_slayer_i", "status": "not_started"},
        {"id": "dragon_slayer_i", "status": "unknown"},
        {"id": "dragon_slayer_i", "status": True},
        {"id": "", "status": "in_progress"},
        {"id": "dragon_slayer_i"},
        {"id": "dragon_slayer_i", "status": "in_progress", "extra": True},
    ],
)
def test_invalid_quest_status_mapping(raw):
    from tracker.content.errors import RequirementSyntaxError

    with pytest.raises(RequirementSyntaxError):
        parse({"quest": raw})


def test_shield_review_preserves_community_classifications(reviewed):
    _, catalog = reviewed
    assert catalog.community_items
    assert catalog.community_provenance
    assert catalog.items[11710].unsupported_effects  # Nightmare Zone form is separate.


def test_locked_shield_still_rejects_two_handed_weapon(reviewed):
    content, full_catalog = reviewed
    catalog = EquipmentCatalog({i: full_catalog.items[i] for i in (1540, 861, 892)})
    player = snapshot(owned=(1540, 861, 892), quests={"dragon_slayer_i": QuestStatus.COMPLETE})
    result = optimize(
        player,
        OptimizationRequest(
            roles=(RoleConfig(id="role", style="ranged", locks={"weapon": 861, "shield": 1540}),),
            mode="owned",
            max_swaps=0,
        ),
        catalog,
        content,
        {},
        NOW,
    )
    assert result["selected_solution"] is None


@pytest.mark.parametrize("status", [QuestStatus.IN_PROGRESS, QuestStatus.COMPLETE])
def test_auto_search_includes_locked_shield_in_every_discipline(reviewed, status):
    from tracker.gear.auto import optimize_auto

    content, full_catalog = reviewed
    ids = (1540, 1323, 8880, 8882, 1383)
    catalog = EquipmentCatalog({i: full_catalog.items[i] for i in ids})
    player = snapshot(owned=ids, quests={"dragon_slayer_i": status})
    result = optimize_auto(
        player,
        OptimizationRequest(
            roles=(
                RoleConfig(
                    id="role",
                    style="slash",
                    spell="water_strike",
                    allowed_disciplines=("melee", "ranged", "magic"),
                    combat_options=CombatOptionFilters(
                        attack_types=(
                            "stab",
                            "slash",
                            "crush",
                            "light",
                            "standard",
                            "heavy",
                            "magic",
                        ),
                        stances=(
                            "accurate",
                            "aggressive",
                            "defensive",
                            "controlled",
                            "rapid",
                            "longrange",
                        ),
                        spells=("water_strike",),
                    ),
                    locks={"shield": 1540},
                ),
            ),
            mode="owned",
            max_swaps=0,
        ),
        catalog,
        content,
        {},
        NOW,
    )
    assert len(result["discipline_results"]) == 3
    for branch in result["discipline_results"]:
        assert branch["status"] == "best_found"
        assert branch["selected_solution"]["loadouts"]["role"]["equipment"]["shield"] == 1540
