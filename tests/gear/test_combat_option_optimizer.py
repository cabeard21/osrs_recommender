"""Combat-option selection through the existing complete-loadout search."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.models import CombatTarget, EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 28, tzinfo=UTC)


def _run(role: RoleConfig):
    weapon = EquipmentDefinition(
        id=101,
        name="Test blade",
        slot="weapon",
        attack_styles=("stab", "slash"),
        attack_profiles=(("stab", "accurate"), ("slash", "aggressive")),
        bonuses=EquipmentBonuses(stab=0, slash=80, melee_strength=40),
        requirements_complete=True,
    )
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (101, Container.BANK): ObservedItemFact(101, Container.BANK, 1, "test", NOW)
        },
    )
    return optimize(
        snapshot,
        OptimizationRequest(roles=(role,), mode="owned", max_swaps=0),
        SimpleNamespace(items={101: weapon}, version="test"),
        Content(),
        {},
        NOW,
    )


def _filters(attack_types=("stab", "slash"), stances=("accurate", "aggressive")):
    return CombatOptionFilters(attack_types=attack_types, stances=stances, spells=())


def test_optimizer_selects_best_legal_weapon_option():
    result = _run(RoleConfig(id="melee", style="stab", combat_options=_filters()))
    loadout = result["selected_solution"]["loadouts"]["melee"]
    assert loadout["combat_option"] == {
        "attack_type": "slash",
        "stance": "aggressive",
        "spell": None,
        "powered_attack": None,
    }
    assert loadout["performance"]["supported"]


def test_filter_excludes_better_option_and_empty_selection_remains_empty():
    filtered = _run(
        RoleConfig(id="melee", style="stab", combat_options=_filters(("stab",), ("accurate",)))
    )
    assert (
        filtered["selected_solution"]["loadouts"]["melee"]["combat_option"]["attack_type"] == "stab"
    )
    empty = _run(RoleConfig(id="melee", style="stab", combat_options=_filters(())))
    assert empty["selected_solution"] is None


def test_omitted_filters_keep_legacy_fixed_attack():
    result = _run(RoleConfig(id="melee", style="stab"))
    loadout = result["selected_solution"]["loadouts"]["melee"]
    assert loadout["combat_option"]["attack_type"] == "stab"
    assert loadout["combat_option"]["stance"] == "accurate"


def test_magic_option_is_selected_with_no_spellbook_unlock_row():
    result = _run(
        RoleConfig(
            id="magic",
            style="magic",
            combat_options=CombatOptionFilters(
                attack_types=("magic",), stances=("accurate",), spells=("wind_strike",)
            ),
        )
    )
    loadout = result["selected_solution"]["loadouts"]["magic"]
    assert loadout["combat_option"]["spell"] == "wind_strike"
    assert loadout["performance"]["supported"]


MAGIC_SPELLS = ("wind_bolt", "water_bolt", "earth_bolt", "fire_bolt")


def _magic_context(
    target,
    spells=MAGIC_SPELLS,
    *,
    fixed=False,
    powered_base=None,
    magic_level=35,
    staff_spells=MAGIC_SPELLS,
):
    staff = EquipmentDefinition(
        id=201,
        name="Standard staff",
        slot="weapon",
        attack_styles=("magic",),
        spell_compatibility=staff_spells,
        bonuses=EquipmentBonuses(magic=20),
        requirements_complete=True,
    )
    items = {staff.id: staff}
    if powered_base is not None:
        powered = EquipmentDefinition(
            id=202,
            name="Powered staff",
            slot="weapon",
            attack_styles=("magic",),
            powered_attack="fixture",
            powered_attack_base_max_hit=powered_base,
            powered_attack_stances=("accurate",),
            bonuses=EquipmentBonuses(magic=20),
            requirements_complete=True,
        )
        items = {**items, powered.id: powered}
        spells = (*spells, "powered:202")
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={"magic": SkillState(magic_level, None, Source.MANUAL, NOW)},
        observed_items={
            (item_id, Container.BANK): ObservedItemFact(item_id, Container.BANK, 1, "test", NOW)
            for item_id in items
        },
    )
    role = RoleConfig(
        id="mage",
        style="magic",
        spell="fire_bolt",
        target=target,
        combat_options=None
        if fixed
        else CombatOptionFilters(attack_types=("magic",), stances=("accurate",), spells=spells),
    )
    return (
        snapshot,
        OptimizationRequest(roles=(role,), mode="owned", max_swaps=0),
        SimpleNamespace(items=items, version="test"),
        Content(),
        {},
        NOW,
    )


def _magic_loadout(target, spells=MAGIC_SPELLS, *, fixed=False, powered_base=None):
    args = _magic_context(target, spells, fixed=fixed, powered_base=powered_base)
    return optimize(*args)["selected_solution"]["loadouts"]["mage"]


@pytest.mark.parametrize(
    ("element", "spell"),
    [("air", "wind_bolt"), ("water", "water_bolt"), ("earth", "earth_bolt"), ("fire", "fire_bolt")],
)
def test_magic_optimizer_selects_matching_element_and_applies_bonus(element, spell):
    neutral = _magic_loadout(CombatTarget())
    weak = _magic_loadout(CombatTarget(weakness_element=element, weakness_percent=50))
    assert weak["equipment"]["weapon"] == 201
    assert weak["combat_option"]["spell"] == spell
    assert weak["performance"]["max_hit"] == 18
    assert weak["performance"]["attack_roll"] == (35 + 11) * 84 * 3 // 2
    assert weak["performance"]["dps"] > neutral["performance"]["dps"]


def test_magic_weakness_respects_spell_exclusion_and_fixed_mode():
    target = CombatTarget(weakness_element="water", weakness_percent=50)
    excluded = _magic_loadout(target, spells=("fire_bolt",))
    fixed = _magic_loadout(target, fixed=True)
    for loadout in (excluded, fixed):
        assert loadout["combat_option"]["spell"] == "fire_bolt"
        assert loadout["performance"]["max_hit"] == 12
        assert loadout["performance"]["attack_roll"] == (35 + 11) * 84


@pytest.mark.parametrize(("powered_base", "weapon_id"), [(10, 201), (30, 202)])
def test_magic_weakness_competes_with_powered_dps(powered_base, weapon_id):
    target = CombatTarget(weakness_element="water", weakness_percent=50)
    loadout = _magic_loadout(target, powered_base=powered_base)
    assert loadout["equipment"]["weapon"] == weapon_id
    if weapon_id == 201:
        assert loadout["combat_option"]["spell"] == "water_bolt"
        assert loadout["performance"]["max_hit"] == 18
    else:
        assert loadout["combat_option"]["powered_attack"] == "fixture"
        assert loadout["performance"]["max_hit"] == powered_base
        assert loadout["performance"]["attack_roll"] == (35 + 11) * 84


@pytest.mark.parametrize("auto", [False, True])
def test_weakness_metadata_survives_exact_and_frontier_evaluation(auto):
    from tracker.gear.evaluation import evaluate_configurations

    snapshot, request, catalog, content, _, now = _magic_context(
        CombatTarget(weakness_element="water", weakness_percent=50)
    )
    role = request.roles[0]
    if auto:
        role = role.model_copy(update={"allowed_disciplines": ("melee", "ranged", "magic")})
    request = request.model_copy(
        update={"roles": (role,), "secondary_priority": "accuracy", "max_dps_loss_pct": 100.0}
    )
    prices = {
        item_id: SimpleNamespace(
            high_price_gp=price,
            low_price_gp=price,
            high_trade_at=now,
            low_trade_at=now,
            fetched_at=now,
            source="live",
        )
        for item_id, price in [(556, 2), (555, 5), (557, 5), (554, 5), (562, 100)]
    }
    result = optimize(snapshot, request, catalog, content, prices, now)
    selected = result["selected_solution"]["loadouts"]["mage"]
    assert selected["combat_option"]["spell"] == "water_bolt"
    assert selected["performance"]["elemental_weakness"]["applied"]
    assert result["secondary_frontiers"] and result["running_cost_frontiers"]
    for groups in (result["secondary_frontiers"], result["running_cost_frontiers"]):
        points = [point for group in groups for point in group["points"]]
        assert points
        for point in points:
            loadout = point["solution"]["loadouts"]["mage"]
            equipment, option = loadout["equipment"], loadout["combat_option"]
            exact = evaluate_configurations(
                snapshot,
                request,
                equipment,
                equipment,
                catalog,
                content,
                prices,
                now,
                baseline_combat_option=option,
                proposed_combat_option=option,
            )
            assert exact["baseline"]["status"] == "valid"
            assert exact["proposed"]["status"] == "valid"
            assert exact["baseline"]["performance"] == loadout["performance"]
            assert exact["proposed"]["performance"] == loadout["performance"]
            weakness = loadout["performance"]["elemental_weakness"]
            assert weakness["element"] == "water"
            assert weakness["percent"] == 50
            assert weakness["applied"] == (option["spell"] == "water_bolt")


def test_catalog_npc_weakness_survives_service_optimize_and_exact_evaluation(monkeypatch):
    from tracker.gear.npcs import npc_catalog
    from tracker.gear.service import GearService

    npc = npc_catalog()
    entry = npc.detail(npc.search("Dagannoth Rex")["items"][0]["key"])
    snapshot, request, catalog, content, prices, now = _magic_context(None)
    # Validate the selection object just as a transport request would.
    request = OptimizationRequest.model_validate(
        {
            **request.model_dump(mode="json"),
            "roles": [
                {
                    **request.roles[0].model_dump(mode="json"),
                    "target_selection": {"key": entry["key"], "catalog_revision": npc.revision},
                }
            ],
        }
    )
    service = GearService(content)
    monkeypatch.setattr(service, "equipment_catalog", lambda: catalog)
    result = service.optimize(snapshot, request, price_records=prices, now=now)
    loadout = result["selected_solution"]["loadouts"]["mage"]
    assert loadout["combat_option"]["spell"] == "earth_bolt"
    assert loadout["performance"]["elemental_weakness"]["element"] == "earth"
    assert loadout["performance"]["elemental_weakness"]["percent"] == 35
    exact = service.evaluate(
        snapshot,
        request,
        loadout["equipment"],
        loadout["equipment"],
        price_records=prices,
        now=now,
        baseline_combat_option=loadout["combat_option"],
        proposed_combat_option=loadout["combat_option"],
    )
    assert exact["baseline"]["status"] == "valid"
    assert exact["baseline"]["performance"] == loadout["performance"]


def test_multi_magic_roles_keep_independent_weakness_and_spell_choices():
    args = _magic_context(CombatTarget(weakness_element="air", weakness_percent=35))
    request = args[1]
    first = request.roles[0]
    second = first.model_copy(
        update={
            "id": "fire-mage",
            "target": CombatTarget(weakness_element="fire", weakness_percent=50),
        }
    )
    request = request.model_copy(update={"roles": (first, second)})
    result = optimize(args[0], request, *args[2:])
    loadouts = result["selected_solution"]["loadouts"]
    for role_id, spell, element, percent, bonus in (
        ("mage", "wind_bolt", "air", 35, 4),
        ("fire-mage", "fire_bolt", "fire", 50, 6),
    ):
        loadout = loadouts[role_id]
        assert loadout["combat_option"]["spell"] == spell
        weakness = loadout["performance"]["elemental_weakness"]
        assert weakness["applied"]
        assert (weakness["element"], weakness["percent"]) == (element, percent)
        assert weakness["max_hit_bonus"] == bonus
        assert loadout["performance"]["max_hit"] == 12 + bonus


@pytest.mark.parametrize("restriction", ["level", "autocast"])
def test_matching_weakness_does_not_bypass_spell_eligibility(restriction):
    args = _magic_context(
        CombatTarget(weakness_element="water", weakness_percent=50),
        spells=("wind_bolt", "water_bolt"),
        magic_level=22 if restriction == "level" else 35,
        staff_spells=("wind_bolt",) if restriction == "autocast" else MAGIC_SPELLS,
    )
    request = args[1].model_copy(update={"locks": {"weapon": 201}})
    result = optimize(args[0], request, *args[2:])
    loadout = result["selected_solution"]["loadouts"]["mage"]
    assert loadout["combat_option"]["spell"] == "wind_bolt"
    assert not loadout["performance"]["elemental_weakness"]["applied"]
    assert loadout["performance"]["elemental_weakness"]["max_hit_bonus"] == 0
