"""Prayer configuration participates in complete-loadout optimization."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.loader import Content
from tracker.domain.types import SkillState, Source
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize
from tracker.gear.prayers import PrayerPolicy

NOW = datetime(2026, 11, 4, tzinfo=UTC)


def run(policy):
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "magic", "prayer")
        },
    )
    return optimize(
        snapshot,
        OptimizationRequest(
            roles=(RoleConfig(id="melee", style="crush", prayers=policy),),
            mode="owned",
            max_swaps=0,
        ),
        SimpleNamespace(items={}, version="test"),
        Content(),
        {},
        NOW,
    )


def test_fixed_prayers_increase_dps_and_are_serialized():
    baseline = run(PrayerPolicy())["selected_solution"]
    fixed = run(PrayerPolicy(mode="fixed", selected_ids=("ultimate_strength",)))[
        "selected_solution"
    ]
    assert fixed["score"] > baseline["score"]
    assert fixed["loadouts"]["melee"]["selected_prayer_ids"] == ["ultimate_strength"]


def test_optimize_obeys_allowlist_and_empty_allowlist():
    policy = PrayerPolicy(mode="optimize", allowed_ids=("ultimate_strength",))
    result = run(policy)["selected_solution"]
    assert result["loadouts"]["melee"]["selected_prayer_ids"] == ["ultimate_strength"]
    empty = run(PrayerPolicy(mode="optimize"))["selected_solution"]
    assert empty["loadouts"]["melee"]["selected_prayer_ids"] == []


def test_missing_observed_unlock_rejects_fixed_prayer():
    with pytest.raises(ValueError):
        run(PrayerPolicy(mode="fixed", selected_ids=("piety",)))


def test_prayers_do_not_bypass_ancient_spell_access():
    from tests.gear.test_combat_option_optimizer import _magic_context
    from tracker.gear.models import CombatTarget

    snapshot, request, catalog, content, prices, now = _magic_context(
        CombatTarget(), fixed=True, magic_level=99, staff_spells=("ice_barrage",)
    )
    snapshot = replace(
        snapshot,
        skills={
            **snapshot.skills,
            "prayer": SkillState(70, None, Source.MANUAL, now),
        },
    )
    role = request.roles[0].model_copy(
        update={
            "spell": "ice_barrage",
            "prayers": PrayerPolicy(mode="fixed", selected_ids=("mystic_might",)),
        }
    )
    result = optimize(
        snapshot, request.model_copy(update={"roles": (role,)}), catalog, content, prices, now
    )
    assert result["selected_solution"] is None


def test_finalist_refinement_keeps_prayers_and_finds_improvements():
    from tests.gear.test_finalist_refinement import refine, scenario
    from tracker.gear.optimizer import _Search

    original, seed = scenario()
    snapshot = replace(
        original.snapshot,
        skills={
            **original.snapshot.skills,
            "prayer": SkillState(70, None, Source.MANUAL, NOW),
        },
    )
    request = original.request.model_copy(
        update={
            "roles": tuple(
                role.model_copy(
                    update={
                        "prayers": PrayerPolicy(
                            mode="fixed",
                            selected_ids=("mystic_might" if role.id == "mage" else "eagle_eye",),
                        )
                    }
                )
                for role in original.request.roles
            )
        }
    )
    search = _Search(snapshot, request, original.items, original.facts, None)
    seed = search.solution({rid: row["equipment"] for rid, row in seed["loadouts"].items()}, None)
    refined, diagnostics = refine(search, seed)
    assert diagnostics["improvements"] > 0
    assert refined["score"] > seed["score"]
    for rid in seed["loadouts"]:
        assert (
            refined["loadouts"][rid]["selected_prayer_ids"]
            == seed["loadouts"][rid]["selected_prayer_ids"]
        )
