"""Demonbane context survives complete optimizer entry points."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.gear.test_optimizer import NOW, weapon
from tests.gear.test_scoring_options import context
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import Content, load_content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear import optimizer
from tracker.gear.catalog import load_catalog
from tracker.gear.facts import equipment_fact
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import RoleConfig


def test_mark_is_explicit_strict_and_serialized():
    assert RoleConfig(id="mage", style="magic").mark_of_darkness is False
    enabled = RoleConfig(id="mage", style="magic", mark_of_darkness=True)
    assert enabled.model_dump(mode="json")["mark_of_darkness"] is True
    with pytest.raises(ValidationError):
        RoleConfig(id="mage", style="magic", mark_of_darkness="true")


def test_demonbane_candidates_survive_small_mixed_target_slot_cap(monkeypatch):
    catalog = load_catalog(load_content(Path("content")))
    role = RoleConfig(id="demon", style="slash", target=CombatTarget(traits=("demon",)))
    snapshot, items, _, request = context(role)
    contextual = {2402, 6745, 6746, 19675, 30305, 29589, 29577, 29591, 29594, 732}
    items = {
        **items,
        **{i: catalog.items[i].model_copy(update={"requires": None}) for i in contextual},
        **{i: weapon(i, "slash", 200) for i in range(100, 110)},
    }
    snapshot = replace(
        snapshot,
        skills={
            key: SkillState(99, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "magic", "ranged", "slayer")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in items
        },
    )
    request = request.model_copy(update={"roles": (role, RoleConfig(id="ordinary", style="slash"))})
    facts = {i: equipment_fact(snapshot, item, Content(), {}, NOW) for i, item in items.items()}
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    pools = optimizer._Search(snapshot, request, items, facts, None).candidate_pools()
    # Only styles eligible for these roles need survive; ranged/magic are separate roles.
    assert {2402, 6745, 6746, 19675, 30305, 29589, 29577} <= set(pools["weapon"])


@pytest.mark.parametrize("style", ["slash", "ranged", "magic", "multi", "auto"])
def test_complete_demonbane_search_matches_python_without_fallback(style):
    from tools.benchmark_gear_desktop import result_digest
    from tools.gear_search_quality_fixture import load_case
    from tracker.domain.types import QuestStatus
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.native import capture
    from tracker.gear.optimizer import CombatOptionFilters, optimize

    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    ids = (19675, 30305, 29589, 29577, 29591, 29594, 732, 4151, 892, 11865, 4170)
    items = {i: catalog.items[i] for i in ids}
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        quests={**case.snapshot.quests, "a_kingdom_divided": QuestStatus.COMPLETE},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1000, "demonbane", case.at)
            for i in ids
        },
    )
    role = RoleConfig(
        id="demon",
        style="magic" if style in {"multi", "auto"} else style,
        allowed_disciplines=("melee", "ranged", "magic") if style == "auto" else None,
        target=CombatTarget(traits=("demon",), demonbane_vulnerability_percent=70),
        on_slayer_task=True,
        mark_of_darkness=True,
        combat_options=CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "light", "standard", "magic"),
            stances=("accurate", "aggressive", "controlled", "rapid"),
            spells=("inferior_demonbane", "superior_demonbane", "dark_demonbane", "fire_wave"),
        ),
    )
    roles = (role, RoleConfig(id="ordinary", style="slash")) if style == "multi" else (role,)
    request = case.request.model_copy(update={"roles": roles, "mode": "owned"})
    args = (
        snapshot,
        request,
        EquipmentCatalog(items, revision=catalog.revision),
        content,
        case.prices,
        case.at,
    )
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
    }
    reference = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert actual["selected_solution"] is not None
    assert result_digest(actual) == result_digest(reference)
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0
    assert any(row["event"] == "stage" for row in evidence.snapshot()["events"])
