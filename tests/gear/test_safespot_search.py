"""Real catalog search parity, including passive synergies and resource frontiers."""

from dataclasses import replace

import pytest

from tools.gear_search_quality_fixture import load_case
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.models import CombatTarget
from tracker.gear.native import capture
from tracker.gear.optimizer import CombatOptionFilters, RoleConfig, optimize


def test_duration_changes_search_winner():
    """A synthetic ordinary competitor wins short fights but loses to ramped venom."""
    from tracker.gear.models import EquipmentBonuses

    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    ids = (1333, 29796)
    snapshot = replace(
        case.snapshot,
        members=True,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", case.at)
            for i in ids
        },
    )
    items = {i: catalog.items[i] for i in ids}
    items[1333] = items[1333].model_copy(
        update={
            "bonuses": EquipmentBonuses(slash=132, melee_strength=110),
            "attack_speed": 4,
        }
    )
    for duration, expected in [(1, 1333), (300, 29796)]:
        role = RoleConfig(
            id="r",
            style="slash",
            stance="aggressive",
            fight_duration_seconds=duration,
            target=CombatTarget(
                poison_susceptibility="susceptible", venom_susceptibility="susceptible"
            ),
        )
        request = case.request.model_copy(update={"roles": (role,), "mode": "owned"})
        result = optimize(snapshot, request, EquipmentCatalog(items), content, case.prices, case.at)
        assert result["selected_solution"]["loadouts"]["r"]["equipment"]["weapon"] == expected


@pytest.mark.parametrize("mode", ["fixed", "auto", "mixed"])
def test_complete_safespot_search_native_parity(mode):
    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    ids = (3202, 29796, 12931, 1333, 861, 892)
    snapshot = replace(
        case.snapshot,
        members=True,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1000, "test", case.at)
            for i in ids
        },
    )
    role = RoleConfig(
        id="safe",
        style="slash",
        stance="aggressive",
        safe_spotting=True,
        target=CombatTarget(
            poison_susceptibility="susceptible", venom_susceptibility="susceptible"
        ),
        allowed_disciplines=("melee", "ranged") if mode == "auto" else None,
        combat_options=CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "standard"),
            stances=("aggressive", "controlled", "defensive", "rapid", "accurate"),
            spells=(),
        ),
    )
    roles = (role, RoleConfig(id="ordinary", style="slash")) if mode == "mixed" else (role,)
    request = case.request.model_copy(update={"roles": roles, "mode": "owned"})
    args = (
        snapshot,
        request,
        EquipmentCatalog({i: catalog.items[i] for i in ids}, revision=catalog.revision),
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
    selected = actual["selected_solution"]
    assert selected is not None
    for rid, loadout in selected["loadouts"].items():
        expected = reference["selected_solution"]["loadouts"][rid]
        assert loadout["equipment"] == expected["equipment"]
        assert loadout["performance"]["dps"] == pytest.approx(
            expected["performance"]["dps"], rel=1e-13
        )
    assert selected["loadouts"]["safe"]["equipment"]["weapon"] in {3202, 29796, 861}
    assert evidence.snapshot()["native_requests"] > 0
    assert evidence.snapshot()["fallback_requests"] == 0
