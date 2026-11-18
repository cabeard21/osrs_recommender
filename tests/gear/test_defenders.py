"""Defender wear, exact ownership, and optimizer coverage."""

from dataclasses import replace

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tracker.content.loader import load_content
from tracker.domain.types import UnlockState
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

DEFENDERS = [
    ((8844, 24136), {}, None),
    ((8845, 24137), {}, None),
    ((8846, 24138), {"attack": 5, "defence": 5}, None),
    ((8847, 24139), {"attack": 10, "defence": 10}, None),
    ((8848, 24140), {"attack": 20, "defence": 20}, None),
    ((8849, 24141), {"attack": 30, "defence": 30}, None),
    ((8850, 24142, 23230, 27009), {"attack": 40, "defence": 40}, None),
    ((12954, 24143, 19722, 27008), {"defence": 60}, None),
    ((22322, 24186), {"attack": 70, "defence": 70}, None),
    ((27550, 27551), {"attack": 70, "defence": 70}, "ca_master"),
    ((27552, 27553), {"attack": 70, "defence": 70}, "ca_grandmaster"),
    ((33101,), {}, None),
]


@pytest.fixture(scope="module")
def catalog_context():
    content = load_content()
    return content, load_catalog(content)


@pytest.mark.parametrize("ids,levels,unlock", DEFENDERS)
def test_defender_stats_and_wear(catalog_context, ids, levels, unlock):
    content, catalog = catalog_context
    player = snapshot(levels=levels, quests={})
    if unlock:
        player = replace(player, unlocks={unlock: UnlockState.UNLOCKED})
    for item_id in ids:
        item = catalog.items[item_id]
        assert item.slot == "shield"
        assert item.bonuses == catalog.items[ids[0]].bonuses
        assert not item.unsupported_effects
        assert equipment_fact(player, item, content, {}, NOW)["acquisition"] == "untradeable"
        assert equipment_fact(player, item, content, {}, NOW)["wear"]["status"] == "satisfied"
        for skill, level in levels.items():
            weaker = replace(
                player,
                skills={**player.skills, skill: replace(player.skills[skill], level=level - 1)},
            )
            assert equipment_fact(weaker, item, content, {}, NOW)["wear"]["status"] == "unsatisfied"
        if unlock:
            for unlocks, status in [
                ({}, "unknown"),
                ({unlock: UnlockState.LOCKED}, "unsatisfied"),
            ]:
                blocked = replace(player, unlocks=unlocks)
                assert equipment_fact(blocked, item, content, {}, NOW)["wear"]["status"] == status


@pytest.mark.parametrize(
    "shield,owned,mode,include,expected",
    [
        *[
            (item_id, (item_id,), "owned", False, True)
            for ids, _, _ in DEFENDERS
            for item_id in ids
        ],
        (8850, (24142,), "owned", False, False),
        (8850, (20461,), "owned", False, False),
        (8850, (), "usable", True, True),
        (8850, (), "usable", False, False),
        *[
            (broken, (broken,), "owned", False, False)
            for broken in (20449, 20451, 20453, 20455, 20457, 20459, 20461, 20463, 22441)
        ],
    ],
)
def test_defenders_in_optimizer(catalog_context, shield, owned, mode, include, expected):
    content, catalog = catalog_context
    player = replace(
        snapshot(owned=(1323, *owned)),
        unlocks={"ca_master": UnlockState.UNLOCKED, "ca_grandmaster": UnlockState.UNLOCKED},
    )
    result = optimize(
        player,
        OptimizationRequest(
            roles=(RoleConfig(id="melee", style="slash"),),
            mode=mode,
            include_untradeables=include,
            locks={"weapon": 1323, "shield": shield},
            max_swaps=0,
        ),
        catalog,
        content,
        {},
        NOW,
    )
    solution = result["selected_solution"]
    assert (solution is not None) is expected
    if solution:
        loadout = solution["loadouts"]["melee"]
        assert loadout["equipment"]["shield"] == shield
        assert loadout["performance"]["dps"] > 0
        assert solution["purchase_cost_gp"] == 0
        assert solution["purchases"] == []
        assert (shield in solution["unowned_untradeable_item_ids"]) is include
