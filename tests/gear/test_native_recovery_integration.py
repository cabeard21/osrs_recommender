"""Unknown Ava interference limits cost knowledge, never combat eligibility."""

from dataclasses import replace

import pytest

from tools.benchmark_gear_desktop import case_provenance, result_digest
from tools.gear_search_quality_fixture import load_case
from tools.native_effect_cases import derive_effect_case
from tracker.accounts.snapshot import ObservedItemFact
from tracker.content.loader import load_content
from tracker.domain.types import Container
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.native import capture
from tracker.gear.objectives import ObjectiveDescriptor
from tracker.gear.optimizer import optimize
from tracker.gear.prayers import PrayerPolicy

UNKNOWN_BODY = 999999


@pytest.fixture(scope="module")
def recovery_base():
    content = load_content()
    return replace(load_case("melee_1m"), content=content, catalog=load_catalog(content))


def recovery_case(base, *, hopper=False, auto=False):
    case, _ = derive_effect_case(
        base, case_provenance(base), "effect_hopper" if hopper else "effect_ranged"
    )
    unknown = EquipmentDefinition(
        id=UNKNOWN_BODY,
        name="Unreviewed recovery body",
        slot="body",
        requirements_complete=True,
        bonuses=EquipmentBonuses(ranged=300, ranged_strength=20),
    )
    ids = (9185, 9243, 10499, 2503, *((32879,) if hopper else ()))
    items = {i: base.catalog.items[i] for i in ids}
    items[UNKNOWN_BODY] = unknown
    owned = {
        (i, Container.BANK): ObservedItemFact(i, Container.BANK, 100, "recovery-fixture", case.at)
        for i in items
    }
    role = case.request.roles[0].model_copy(
        update={
            "combat_options": None,
            "prayers": PrayerPolicy(),
            "allowed_disciplines": ("ranged",) if auto else None,
        }
    )
    request = case.request.model_copy(
        update={
            "roles": (role,),
            "max_swaps": 0,
            "locks": {"weapon": 9185, "ammunition": 9243, "cape": 10499},
        }
    )
    return replace(
        case,
        snapshot=replace(case.snapshot, observed_items=owned),
        catalog=EquipmentCatalog(items),
        request=request,
    )


@pytest.mark.parametrize("hopper", [False, True])
@pytest.mark.parametrize("thorough", [False, True])
def test_unknown_recovery_body_keeps_dps_winner_and_exact_archives(recovery_base, hopper, thorough):
    case = recovery_case(recovery_base, hopper=hopper)
    _assert_recovery_parity(case, thorough)


def test_auto_unknown_recovery_body_retains_native_ranged_branch(recovery_base):
    _assert_recovery_parity(recovery_case(recovery_base, hopper=True, auto=True), False)


def _assert_recovery_parity(case, thorough):
    pytest.importorskip("tracker.gear.native._stages")
    request = case.request.model_copy(
        update={
            "objectives": (ObjectiveDescriptor(kind="gp_per_damage"),),
            "secondary_priority": "default",
        }
    )
    args = (case.snapshot, request, case.catalog, case.content, case.prices, case.at)
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
        "local_refinement": thorough,
    }
    reference = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert result_digest(actual) == result_digest(reference)
    selected = actual["selected_solution"]
    assert selected is not None
    assert selected["loadouts"]["effect"]["equipment"]["body"] == UNKNOWN_BODY
    assert selected["running_cost"]["status"] == "unavailable"
    points = [p for group in actual["objective_frontiers"] for p in group["points"]]
    assert points
    assert any(p["solution"]["loadouts"]["effect"]["equipment"].get("body") == 2503 for p in points)
    assert all(
        p["solution"]["loadouts"]["effect"]["equipment"].get("body") != UNKNOWN_BODY for p in points
    )
    diagnostics = evidence.snapshot()
    assert diagnostics["fallback_requests"] == 0
    assert diagnostics["native_requests"] > 0
    assert any(row["event"] == "stage" and row.get("cost") for row in diagnostics["events"])
