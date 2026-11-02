"""The fixed anchor supports ordinary attacks with exact wear and ownership gates."""

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tools.import_equipment import REVIEWED, normalize
from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize


@pytest.fixture(scope="module")
def reviewed():
    content = load_content()
    return content, load_catalog(content)


def test_fixed_anchor_profiles_and_import_review(reviewed):
    _, catalog = reviewed
    item = catalog.items[10887]
    assert item.requirements_complete and item.tradeable is False
    assert not item.unsupported_effects
    assert item.id in REVIEWED
    assert set(item.attack_profiles) == {
        ("crush", "accurate"),
        ("crush", "aggressive"),
        ("stab", "controlled"),
        ("crush", "defensive"),
    }
    row = normalize(
        {
            "id": 10887,
            "name": item.name,
            "slot": "weapon",
            "category": "Spiked",
            "offensive": {
                k: getattr(item.bonuses, k) for k in ("stab", "slash", "crush", "magic", "ranged")
            },
            "defensive": dict.fromkeys(("stab", "slash", "crush", "magic", "ranged"), 0),
            "bonuses": {"str": 100, "ranged_str": 0, "magic_str": 0, "prayer": 0},
            "speed": 6,
            "isTwoHanded": True,
        }
    )
    assert set(row["attack_profiles"]) == set(item.attack_profiles)
    assert set(row["attack_styles"]) == {"crush", "stab"}
    assert not row["unsupported_effects"]


@pytest.mark.parametrize(
    "levels,expected",
    [
        ({"attack": 60, "strength": 40}, "satisfied"),
        ({"attack": 59, "strength": 40}, "unsatisfied"),
        ({"attack": 60, "strength": 39}, "unsatisfied"),
        ({"attack": 60}, "unknown"),
        ({"strength": 40}, "unknown"),
    ],
)
def test_fixed_anchor_wear_without_quest_completion(reviewed, levels, expected):
    content, catalog = reviewed
    fact = equipment_fact(
        snapshot(levels=levels, quests={}), catalog.items[10887], content, {}, NOW
    )
    assert fact["wear"]["status"] == expected


@pytest.mark.parametrize(
    "item_id,owned,eligible",
    [
        (10887, (10887,), True),
        (10887, (), False),
        (10887, (10888,), False),
        (10888, (10888,), False),
        (27855, (27855,), False),
    ],
)
def test_exact_owned_anchor_search(reviewed, item_id, owned, eligible):
    content, catalog = reviewed
    player = snapshot(levels={"attack": 60, "strength": 40}, owned=owned, quests={})
    role = RoleConfig(id="melee", style="crush", stance="aggressive")
    result = optimize(
        player,
        OptimizationRequest(
            roles=(role,),
            mode="owned",
            locks={"weapon": item_id},
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
        loadout = solution["loadouts"]["melee"]
        assert loadout["equipment"]["weapon"] == 10887
        assert loadout["performance"]["dps"] > 0
        assert loadout["performance"]["attack_interval"] == pytest.approx(3.6)


def test_broken_and_bounty_hunter_forms_remain_unreviewed(reviewed):
    _, catalog = reviewed
    for item_id in (10888, 27855):
        assert catalog.items[item_id].unsupported_effects
        assert not catalog.items[item_id].requirements_complete
