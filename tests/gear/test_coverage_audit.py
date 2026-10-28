"""The coverage audit describes gates and retention without changing the search."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import Content
from tracker.content.requirements import SkillLeaf
from tracker.db.gear_prices import CachedPriceRecord
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.coverage_audit import audit_snapshot
from tracker.gear.evaluation import evaluate_equipment
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

AT = datetime(2026, 10, 19, tzinfo=UTC)


def item(numeric_id, slot="head", **changes):
    return EquipmentDefinition(
        id=numeric_id,
        name=f"Item {numeric_id}",
        slot=slot,
        **{"requirements_complete": True, **changes},
    )


def account(ids, *, scans=True):
    return AccountSnapshot(
        1,
        "private-user",
        skills={
            k: SkillState(70, None, Source.RUNELITE, AT)
            for k in ("attack", "strength", "defence", "ranged", "magic")
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", AT) for i in ids
        },
        container_scans={c: ContainerScanFact(c, AT, "test") for c in Container} if scans else {},
    )


def slash(**changes):
    return OptimizationRequest(
        roles=(RoleConfig(id="slash", style="slash"),), mode="owned", **changes
    )


def audit(snapshot, definitions, *, prices=None, requests=None):
    return audit_snapshot(
        snapshot,
        Content(),
        EquipmentCatalog({i.id: i for i in definitions}),
        prices or {},
        AT,
        requests,
    )


def by_id(result):
    return {i["item_id"]: i for i in result["items"]}


def test_missing_ids_and_missing_scans_stay_unknown_not_missing_equipment():
    snapshot = account([1, 999], scans=False)
    snapshot = replace(
        snapshot,
        observed_items={
            **snapshot.observed_items,
            (998, Container.EQUIPMENT): ObservedItemFact(998, Container.EQUIPMENT, 1, "test", AT),
        },
    )
    result = audit(snapshot, [item(1)])
    rows = by_id(result)
    assert rows[999]["classification"] == "unclassified"
    assert rows[998]["classification"] == "equipment"
    assert rows[998]["name"] == "Unknown physical item 998"
    assert rows[1]["fact"]["ownership"]["status"] == "owned"
    assert rows[1]["observations"][0]["scan_status"] == "missing_scan"
    assert result["current_account_summary"]["accepted_observed_ids"] == 0
    assert "private-user" not in str(result)


def test_stale_rows_remain_visible_but_not_current_or_owned():
    snapshot = account([1])
    snapshot = replace(
        snapshot,
        container_scans={
            c: ContainerScanFact(c, AT + timedelta(seconds=1), "test") for c in Container
        },
    )
    row = by_id(audit(snapshot, [item(1)]))[1]
    assert not row["accepted_observation"]
    assert row["observations"][0]["scan_status"] == "stale"
    assert row["fact"]["ownership"]["status"] == "unowned"


def test_requirements_effects_and_role_support_are_independent():
    weapon = item(100, "weapon", attack_styles=("slash",))
    definitions = [
        weapon,
        item(1, requirements_complete=False),
        item(2, requires=SkillLeaf(type="skill", skill="attack", level=99)),
        item(3, unsupported_effects=("Unreviewed proc",)),
        item(4),
    ]
    # helper's explicit default must be replaced to create incomplete metadata.
    result = audit(account([i.id for i in definitions]), definitions, requests=[slash()])
    rows = by_id(result)
    assert rows[1]["primary_blocker"] == "incomplete_requirements"
    assert rows[2]["primary_blocker"] == "unmet_requirements"
    assert rows[3]["scenario_results"][0]["access_eligible"]
    assert rows[3]["scenario_results"][0]["role_support"] == "unsupported"
    assert rows[3]["primary_blocker"] == "unsupported_effects"
    assert rows[4]["primary_blocker"] == "none"
    assert result["current_account_summary"]["fully_supported"] == 2


def test_unknown_requirement_is_not_a_failed_requirement():
    definition = item(1, requires=SkillLeaf(type="skill", skill="hunter", level=1))
    row = by_id(audit(account([1]), [definition]))[1]
    assert row["primary_blocker"] == "unknown_requirements"
    assert row["fact"]["wear"]["unmet"][0]["status"] == "unknown"


def test_future_prices_are_unavailable_as_of_and_raw_cache_is_separate():
    definition = item(1, tradeable=True)
    price = CachedPriceRecord(1, 100, AT, 90, AT, AT + timedelta(days=1), "live", "test")
    row = by_id(audit(account([1]), [definition], prices={1: price}))[1]
    assert row["fact"]["price"]["amount_gp"] is None
    assert row["pricing"]["current_cache"]["amount_gp"] == 100
    assert "fetched_after_evaluation" in row["pricing"]["flags"]
    assert row["pricing"]["required_for_observed_item"] is False
    price = replace(price, fetched_at=AT, high_trade_at=AT + timedelta(seconds=1))
    row = by_id(audit(account([1]), [definition], prices={1: price}))[1]
    assert row["fact"]["price"]["amount_gp"] == 90
    assert "high_trade_after_evaluation" in row["pricing"]["flags"]


def test_scenario_restrictions_do_not_relabel_supported_items():
    definitions = [item(100, "weapon", attack_styles=("slash",)), item(1), item(2)]
    result = audit(
        account([100, 1, 2]),
        definitions,
        requests=[slash(excluded_item_ids=(1,), locks={"head": 2})],
    )
    rows = by_id(result)
    assert not rows[1]["scenario_results"][0]["access_eligible"]
    assert rows[1]["primary_blocker"] == "scenario_restriction"
    assert rows[2]["scenario_results"][0]["initial_eligible"]
    assert rows[2]["scenario_results"][0]["candidate_retention"] == "retained"


def test_deterministic_order_duplicate_containers_and_five_roles():
    definitions = [item(100, "weapon", attack_styles=("slash",)), item(1)]
    snapshot = account([100, 1])
    snapshot = replace(
        snapshot,
        observed_items={
            **snapshot.observed_items,
            (1, Container.INVENTORY): ObservedItemFact(1, Container.INVENTORY, 4, "test", AT),
        },
    )
    first = audit(snapshot, definitions)
    second = audit(
        replace(snapshot, observed_items=dict(reversed(snapshot.observed_items.items()))),
        list(reversed(definitions)),
    )
    assert first == second
    assert [s["request"]["roles"][0]["style"] for s in first["scenarios"]] == [
        "stab",
        "slash",
        "crush",
        "ranged",
        "magic",
    ]
    assert by_id(first)[1]["fact"]["ownership"]["quantity"] == 4


def test_default_limit_breakpoint_omission_is_measured_not_inferred():
    definitions = [
        item(100, "weapon", attack_styles=("slash",)),
        *[
            item(i, bonuses=EquipmentBonuses(melee_strength=3 if i == 12 else 0))
            for i in range(1, 13)
        ],
        item(20, "cape", bonuses=EquipmentBonuses(melee_strength=3)),
    ]
    snapshot = account([i.id for i in definitions])
    result = audit(snapshot, definitions, requests=[slash(max_swaps=0)])
    row = by_id(result)[12]
    assert row["scenario_results"][0]["initial_eligible"]
    assert row["scenario_results"][0]["candidate_retention"] == "omitted"
    assert row["primary_blocker"] == "candidate_retention"
    assert row["fully_supported"]
    assert row["scenario_results"][0]["later_search"] == "not_measured"
    assert result["scenarios"][0]["pools"]["head"] == [None, *range(1, 12)]
    catalog = EquipmentCatalog({i.id: i for i in definitions})
    request = slash(max_swaps=0)
    answer = optimize(snapshot, request, catalog, Content(), {}, AT)
    exact = evaluate_equipment(
        {"weapon": 100, "head": 12, "cape": 20},
        catalog.items,
        request.roles[0],
        {k: v.level for k, v in snapshot.skills.items()},
    )
    assert exact.max_hit == 9
    assert answer["selected_solution"]["loadouts"]["slash"]["performance"]["max_hit"] == 8


def test_exclusion_is_primary_before_incomplete_metadata():
    definitions = [item(1, requirements_complete=False)]
    row = by_id(audit(account([1]), definitions, requests=[slash(excluded_item_ids=(1,))]))[1]
    assert row["primary_blocker"] == "scenario_restriction"
    assert "Incomplete requirement metadata." in row["secondary_limitations"]


def test_locked_weapon_requires_compatible_ammunition_scaffold():
    definitions = [
        item(100, "weapon", attack_styles=("ranged",), ammo_for=("arrow",)),
        item(101, "weapon", attack_styles=("ranged",), ammo_for=("bolt",)),
        item(1, "ammunition", ammo_type="arrow"),
        item(2, "ammunition", ammo_type="bolt"),
    ]
    request = OptimizationRequest(
        roles=(RoleConfig(id="range", style="ranged"),), mode="owned", locks={"weapon": 100}
    )
    row = by_id(audit(account([i.id for i in definitions]), definitions, requests=[request]))[2]
    result = row["scenario_results"][0]
    assert result["role_support"] == "supported"
    assert not result["initial_eligible"]
    assert result["scenario_problems"]


def test_variant_membership_is_not_review_approval(make_content, make_item):
    content = make_content(items=[make_item("primary", numeric_id=1, variant_item_ids=(2,))])
    definition = item(2, requirements_complete=False)
    result = audit_snapshot(account([2]), content, EquipmentCatalog({2: definition}), {}, AT)
    row = by_id(result)[2]
    assert row["variant_review"]["review_needed"]
    assert row["variant_review"]["reviewed_primary_id"] is None
    assert row["fact"]["wear"]["status"] == "unknown"


def test_acquisition_unknown_ownership_and_price_gates_are_not_free_items():
    snapshot = account([1])
    snapshot = replace(
        snapshot,
        container_scans={
            Container.BANK: ContainerScanFact(Container.BANK, AT + timedelta(seconds=1), "test")
        },
    )
    request = OptimizationRequest(roles=(RoleConfig(id="magic", style="magic"),), mode="usable")
    row = by_id(audit(snapshot, [item(1, tradeable=True)], requests=[request]))[1]
    assert row["ownership"]["status"] == "unknown"
    assert row["primary_blocker"] == "missing_purchase_price"
    assert row["scenario_results"][0]["access_problems"] == [
        "Physical item 1 has no usable purchase price."
    ]
    row = by_id(audit(snapshot, [item(1, tradeable=False)], requests=[request]))[1]
    assert row["primary_blocker"] == "unsupported_acquisition"


def test_hypothetical_requirements_stay_distinct_from_actual_account_facts():
    definition = item(1, requires=SkillLeaf(type="skill", skill="attack", level=99))
    request = OptimizationRequest(
        roles=(RoleConfig(id="magic", style="magic"),),
        mode="future",
        skill_overrides={"attack": 99},
    )
    from tracker.content.schema import Skill

    content = Content(skills={"attack": Skill(id="attack", name="Attack")})
    result = audit_snapshot(
        account([1]), content, EquipmentCatalog({1: definition}), {}, AT, [request]
    )
    row = by_id(result)[1]
    assert row["fact"]["wear"]["status"] == "unsatisfied"
    assert row["scenario_results"][0]["initial_eligible"]
    assert not row["fully_supported"]


def test_utility_roles_remain_unscored_and_naive_time_is_rejected():
    definitions = [item(100, "weapon", attack_styles=("slash",)), item(1)]
    request = OptimizationRequest(
        roles=(
            RoleConfig(id="slash", style="slash"),
            RoleConfig(id="utility", style="special", parent_role="slash", locks={"weapon": 100}),
        ),
        mode="owned",
    )
    row = by_id(audit(account([100, 1]), definitions, requests=[request]))[1]
    assert row["scenario_results"][1]["role_support"] == "unavailable"
    with pytest.raises(ValueError, match="timezone"):
        audit_snapshot(account([1]), Content(), EquipmentCatalog({}), {}, AT.replace(tzinfo=None))


def test_exact_authored_ids_establish_missing_equipment_but_variants_do_not(
    make_content, make_item
):
    content = make_content(
        items=[
            make_item(
                "exact", name="Authored helm", numeric_id=999, slot="head", variant_item_ids=(1000,)
            ),
            make_item("ambiguous_head", numeric_id=1001, slot="head"),
            make_item("ambiguous_cape", numeric_id=1001, slot="cape"),
        ]
    )
    result = audit_snapshot(account([999, 1000, 1001]), content, EquipmentCatalog({}), {}, AT)
    rows = by_id(result)
    assert rows[999]["classification"] == "equipment"
    assert rows[999]["primary_blocker"] == "missing_physical_catalog"
    assert rows[999]["name"] == "Authored helm"
    assert rows[999]["canonical_name_source"] == "authored_exact_id"
    assert rows[999]["authored_slot"] == "head"
    assert rows[999]["slot"] is None
    assert rows[999]["compatibility_metadata"] is None
    assert len(rows[999]["scenario_results"]) == 5
    assert all(
        s["access_eligible"] is None
        and s["initial_eligible"] is None
        and s["role_support"] == "unavailable"
        and s["candidate_retention"] == "not_measured"
        for s in rows[999]["scenario_results"]
    )
    assert rows[1000]["classification"] == "unclassified"
    assert rows[1000]["name"] == "Unknown physical item 1000"
    assert rows[1000]["authored_slot"] is None
    assert rows[1000]["scenario_results"] == []
    assert rows[1001]["classification"] == "equipment"
    assert rows[1001]["authored_identity_ambiguous"]
    assert rows[1001]["name"] == "Unknown physical item 1001"
    assert rows[1001]["authored_slot"] is None
    assert len(rows[1001]["authored_exact_matches"]) == 2


def test_known_physical_compatibility_metadata_remains_concrete():
    definition = item(
        1,
        "weapon",
        attack_styles=("ranged",),
        attack_profiles=(("ranged", "rapid"),),
        two_handed=True,
        ammo_for=("arrow",),
    )
    row = by_id(audit(account([1]), [definition]))[1]
    assert row["canonical_name_source"] == "physical_catalog"
    assert row["compatibility_metadata"] == {
        "attack_styles": ["ranged"],
        "attack_profiles": [["ranged", "rapid"]],
        "two_handed": True,
        "ammo_type": None,
        "ammo_for": ["arrow"],
    }


def test_exact_authored_non_equipment_does_not_establish_bank_equipment(make_content, make_item):
    consumable = make_item("consumable", name="Known supply", numeric_id=999).model_copy(
        update={"slot": None}
    )
    content = make_content(items=[consumable])
    result = audit_snapshot(account([999]), content, EquipmentCatalog({}), {}, AT)
    row = by_id(result)[999]
    assert row["name"] == "Known supply"
    assert row["canonical_name_source"] == "authored_exact_id"
    assert row["classification"] == "unclassified"
    assert row["primary_blocker"] == "unclassified_observation"
    assert result["current_account_summary"]["confirmed_equipment_ids"] == 0
