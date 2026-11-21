"""Differential coverage for complete vampyre attacks inside the native scorer."""

import pytest

from tests.gear.test_native_scoring import context
from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.combat import evaluate_prepared_score
from tracker.gear.models import CombatTarget, EquipmentDefinition
from tracker.gear.npcs import npc_catalog
from tracker.gear.scoring import prepare_equipment


@pytest.mark.parametrize(
    "tier,style,weapon_id,ammo_id,ring,legal",
    [
        (1, "slash", 1, None, True, True),
        (2, "slash", 1, None, False, False),
        (2, "slash", 1, None, True, True),
        (2, "slash", 2402, None, False, True),
        (2, "slash", 2402, None, True, True),
        (2, "ranged", 9185, 9145, False, True),
        (2, "ranged", 9185, 9144, False, False),
        (2, "ranged", 9185, 21946, True, True),
        (2, "ranged", 1, 9145, False, False),
        (3, "ranged", 9185, 9145, True, False),
        (3, "ranged", 33716, None, True, True),
        (3, "slash", 33718, None, True, True),
        (3, "magic", 24699, None, True, False),
    ],
)
def test_compiled_evaluates_actual_attack(tier, style, weapon_id, ammo_id, ring, legal):
    from tracker.gear.native._scoring import ScoringContext

    search = context(style)
    weapon = search.items[1].model_copy(
        update={
            "id": weapon_id,
            "ammo_for": (f"bolt:{ammo_id}",) if weapon_id == 9185 else (),
            "attack_speed": 4,
        }
    )
    role = search.request.roles[0].model_copy(
        update={
            "target": CombatTarget(traits=(f"vampyre{tier}",), flat_armour=2),
            "on_slayer_task": True,
        }
    )
    head = search.items[2].model_copy(update={"slayer_bonus": "all"})
    gear = [weapon, head]
    if ring:
        gear.append(EquipmentDefinition(id=21140, name="Efaritay's aid", slot="ring"))
    if ammo_id:
        gear.append(
            EquipmentDefinition(
                id=ammo_id,
                name="Bolts",
                slot="ammunition",
                ammo_type=f"bolt:{ammo_id}",
                bolt_effect="diamond" if ammo_id == 21946 else None,
            )
        )
    search.items = {item.id: item for item in gear}
    search.eligible = search.items
    search.request.roles = (role,)
    actual = ScoringContext(search).score({item.slot: item.id for item in gear}, 0)
    assert actual["supported"] is legal
    expected = evaluate_prepared_score(prepare_equipment(gear), role, search.levels)
    assert expected.supported is legal
    if legal:
        assert actual["dps"] == expected.dps
        assert actual["accuracy"] == expected.accuracy
        assert actual["ring_charge_probability"] == expected.ring_charge_probability


def test_compiled_vanstrom_allows_only_the_blisterwood_flail():
    from tracker.gear.native._scoring import ScoringContext

    entry = next(row for row in npc_catalog().entries.values() if row["npc_id"] == 9567)
    search = context("crush")
    catalog = load_catalog(load_content())
    search.items = search.eligible = {i: catalog.items[i] for i in (24699, 22398, 21140)}
    role = search.request.roles[0].model_copy(
        update={
            "target": CombatTarget.model_validate(entry["target"]),
        }
    )
    search.request.roles = (role,)
    scorer = ScoringContext(search)
    for weapon_id in (24699, 22398):
        gear = {"weapon": weapon_id, "ring": 21140}
        actual = scorer.score(gear, 0)
        expected = evaluate_prepared_score(
            prepare_equipment([search.items[i] for i in gear.values()]), role, search.levels
        )
        assert actual["supported"] == expected.supported == (weapon_id == 24699)
        if expected.supported:
            assert actual["dps"] == expected.dps > 0


@pytest.mark.parametrize("full_set", [True, False])
@pytest.mark.parametrize("tier", [1, 3])
def test_native_elite_void_stakes(tier, full_set):
    from tracker.gear.native._scoring import ScoringContext

    search = context("ranged", "rapid")
    weapon = search.items[1].model_copy(update={"id": 33716, "attack_speed": 3})
    items = [weapon]
    for slot, item_id in (("head", 11664), ("body", 13072), ("legs", 13073), ("hands", 8842)):
        if full_set or slot != "hands":
            items.append(EquipmentDefinition(id=item_id, name=slot, slot=slot))
    gear = {item.slot: item.id for item in items}
    search.items = {item.id: item for item in items}
    search.eligible = search.items
    role = search.request.roles[0].model_copy(
        update={"target": CombatTarget(traits=(f"vampyre{tier}",))}
    )
    search.request.roles = (role,)
    scorer = ScoringContext(search)
    result = scorer.score(gear, 0)
    expected = evaluate_prepared_score(prepare_equipment(items), role, search.levels)
    assert result["supported"] and expected.supported
    assert result["dps"] == expected.dps and result["accuracy"] == expected.accuracy
    bare = scorer.score({"weapon": weapon.id}, 0)
    if full_set:
        assert result["dps"] > bare["dps"]
    else:
        assert result["dps"] == bare["dps"]


@pytest.mark.parametrize("tier", [1, 2])
@pytest.mark.parametrize(
    "family", ["opal", "pearl", "ruby", "diamond", "dragonstone", "onyx", "poison"]
)
def test_compiled_ring_and_secondary_bolt_hits(tier, family):
    from tracker.gear.native._scoring import ScoringContext

    search = context("ranged", "rapid")
    ammo_id = 9306 if family == "poison" else 21946
    weapon = search.items[1].model_copy(update={"id": 9185, "ammo_for": (f"bolt:{ammo_id}",)})
    ammo = EquipmentDefinition(
        id=ammo_id,
        name="Bolts",
        slot="ammunition",
        ammo_type=f"bolt:{ammo_id}",
        bolt_effect=None if family == "poison" else family,
    )
    items = [
        weapon,
        ammo,
        EquipmentDefinition(id=21140, name="Efaritay's aid", slot="ring"),
        EquipmentDefinition(id=32879, name="Aquanite hopper", slot="shield"),
    ]
    role = search.request.roles[0].model_copy(
        update={
            "target": CombatTarget(
                traits=(f"vampyre{tier}",),
                poison_susceptibility="susceptible",
                hitpoints=90,
                flat_armour=1,
            ),
        }
    )
    search.items = {item.id: item for item in items}
    search.eligible = search.items
    search.request.roles = (role,)
    actual = ScoringContext(search).score({item.slot: item.id for item in items}, 0)
    expected = evaluate_prepared_score(prepare_equipment(items), role, search.levels)
    assert actual["supported"] and expected.supported
    assert actual["dps"] == expected.dps
    assert actual["ring_charge_probability"] == expected.ring_charge_probability


@pytest.mark.parametrize("mode", ["tier2-ring", "sentinel-ranged", "auto", "mixed"])
def test_complete_compiled_search_keeps_legal_vampyre_setups(mode, monkeypatch):
    from dataclasses import replace

    from tools.benchmark_gear_desktop import result_digest
    from tools.gear_search_quality_fixture import load_case
    from tracker.accounts.snapshot import ObservedItemFact
    from tracker.content.loader import load_content
    from tracker.domain.types import Container, QuestStatus, SkillState, Source
    from tracker.gear import optimizer
    from tracker.gear.catalog import EquipmentCatalog, load_catalog
    from tracker.gear.native import capture
    from tracker.gear.objectives import ObjectiveDescriptor
    from tracker.gear.optimizer import CombatOptionFilters, RoleConfig, optimize
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    case = load_case("melee_1m")
    content = load_content()
    catalog = load_catalog(content)
    tier2 = mode in {"tier2-ring", "mixed"}
    ids = (4151, 21140, 6585) if tier2 else (33716, 33718, 24699, 33722, 21140, 4151)
    items = {i: catalog.items[i] for i in ids}
    snapshot = replace(
        case.snapshot,
        skills={k: SkillState(99, None, Source.MANUAL, case.at) for k in content.skills},
        quests=dict.fromkeys(content.quests, QuestStatus.COMPLETE),
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1000, "vampyre", case.at)
            for i in ids
        },
    )
    role = RoleConfig(
        id="vyre",
        style="slash" if tier2 else "ranged",
        allowed_disciplines=("melee", "ranged", "magic") if mode == "auto" else None,
        target=CombatTarget(traits=("vampyre2" if tier2 else "vampyre3",)),
        combat_options=CombatOptionFilters(
            attack_types=("stab", "slash", "crush", "light", "magic"),
            stances=("accurate", "aggressive", "rapid"),
            spells=("fire_wave",),
        ),
    )
    roles = (role, RoleConfig(id="ordinary", style="slash")) if mode == "mixed" else (role,)
    request = case.request.model_copy(
        update={
            "roles": roles,
            "mode": "owned",
            "objectives": (
                ObjectiveDescriptor(kind="prayer_bonus"),
                ObjectiveDescriptor(kind="gp_per_damage"),
            ),
            "max_dps_loss_pct": 100,
        }
    )
    monkeypatch.setattr(optimizer, "CANDIDATES_PER_SLOT", 2)
    args = (
        snapshot,
        request,
        EquipmentCatalog(items, revision=catalog.revision),
        content,
        {
            **case.prices,
            **{
                i: PriceDTO(
                    item_id=i,
                    high_price_gp=3100 if i == 21140 else 55,
                    high_trade_at=case.at,
                    low_price_gp=None,
                    low_trade_at=None,
                    fetched_at=case.at,
                    source=PriceSource.LIVE,
                    provider="vampyre-native-fixture",
                )
                for i in (21140, 33716)
            },
        },
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
    assert actual["selected_solution"]["loadouts"]["vyre"]["performance"]["supported"]
    assert result_digest(actual) == result_digest(reference)
    diagnostics = evidence.snapshot()
    assert diagnostics["native_requests"] > 0 and diagnostics["fallback_requests"] == 0
    assert any(row["event"] == "stage" for row in diagnostics["events"])
    if mode == "mixed":
        assert any(
            row["event"] == "completed_candidate_admission" and row["screened"] > 0
            for row in diagnostics["events"]
        )
