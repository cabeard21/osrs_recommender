"""Frozen equipment-effect cases retain exact complete native/Python results."""

from dataclasses import replace

import pytest

from tools.benchmark_gear_desktop import case_provenance, result_digest
from tools.gear_search_quality_fixture import load_case
from tools.native_effect_cases import EFFECT_CASES, derive_effect_case
from tracker.content.loader import load_content
from tracker.gear.catalog import load_catalog
from tracker.gear.native import capture
from tracker.gear.optimizer import optimize


@pytest.fixture(scope="module")
def effect_base():
    content = load_content()
    return replace(load_case("melee_1m"), content=content, catalog=load_catalog(content))


@pytest.mark.parametrize("name", EFFECT_CASES)
def test_effect_cases_are_frozen_deterministic_and_detached(effect_base, name):
    before = effect_base.snapshot.fingerprint
    first, metadata = derive_effect_case(effect_base, case_provenance(effect_base), name)
    second, repeated = derive_effect_case(effect_base, case_provenance(effect_base), name)
    assert case_provenance(first) == case_provenance(second)
    assert metadata == repeated
    assert metadata["original_account_replayed"] is False
    assert metadata["effect_case"] == name
    assert effect_base.snapshot.fingerprint == before


@pytest.mark.parametrize("name", EFFECT_CASES)
@pytest.mark.parametrize("thorough", [False, True])
def test_effect_complete_archives_match_python_and_use_native(effect_base, name, thorough):
    pytest.importorskip("tracker.gear.native._stages")
    case, _ = derive_effect_case(effect_base, case_provenance(effect_base), name)
    args = (case.snapshot, case.request, case.catalog, case.content, case.prices, case.at)
    flags = {
        "_execution_profile": "combined",
        "_fixed_reporting": True,
        "_factored_evaluation": True,
        "_compact_states": True,
        "_complete_frontiers": True,
        "_running_frontier": True,
        "local_refinement": thorough,
    }
    reference = optimize(*args, **flags)
    with capture() as evidence:
        actual = optimize(*args, **flags, _native_search=True)
    assert result_digest(actual) == result_digest(reference)
    assert actual["selected_solution"] is not None
    diagnostics = evidence.snapshot()
    assert diagnostics["fallback_requests"] == 0
    assert diagnostics["native_requests"] > 0
    assert any(row["event"] == "stage" for row in diagnostics["events"])
