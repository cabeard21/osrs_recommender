"""Equal physical equipment competes using its own ownership and purchase cost."""

from types import SimpleNamespace

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, snapshot
from tracker.content.loader import load_content
from tracker.gear.catalog import EquipmentCatalog, load_catalog
from tracker.gear.execution_profile import execution_context
from tracker.gear.facts import equipment_fact
from tracker.gear.native import capture
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, _Search, optimize


@pytest.fixture(scope="module")
def equivalent_capes():
    content = load_content()
    full = load_catalog(content)
    # A third, synthetic equivalent makes joint top-two candidate truncation
    # observable while the real reviewed cape rows remain unchanged.
    ordinary = full.items[6568]
    items = {item_id: full.items[item_id] for item_id in (1333, 6568, 20050)}
    items[6000] = ordinary.model_copy(update={"id": 6000, "name": "Synthetic equivalent cape"})
    return content, EquipmentCatalog(items)


def _prices():
    return {
        item_id: SimpleNamespace(
            item_id=item_id,
            high_price_gp=amount,
            high_trade_at=NOW,
            low_price_gp=amount,
            low_trade_at=NOW,
            fetched_at=NOW,
            source="live",
        )
        for item_id, amount in ((6000, 900), (6568, 1000), (20050, 100))
    }


def _request(*, vector=False, roles=1, **kwargs):
    objective = (
        {"objectives": [{"kind": "defence_roll", "styles": ["stab"]}]}
        if vector
        else {"secondary_priority": "stab_defence_roll"}
    )
    return OptimizationRequest(
        roles=tuple(
            RoleConfig(id=str(index), style="slash", locks={"weapon": 1333})
            for index in range(roles)
        ),
        mode="usable",
        budget_gp=10000,
        max_swaps=0,
        **objective,
        **kwargs,
    )


@pytest.fixture(params=[False, True], ids=["python", "native"])
def solve(equivalent_capes, request):
    content, catalog = equivalent_capes

    def run(account, scenario):
        native = request.param
        with (
            capture() as evidence,
            execution_context(
                "combined" if native else "baseline",
                scenario,
                fixed_reporting=native,
                factored_evaluation=native,
                compact_states=native,
                native_search=native,
            ),
        ):
            result = optimize(account, scenario, catalog, content, _prices(), NOW)
        archives = {group["points"].archive for group in result.get("objective_frontiers", ())}
        for archive in archives:
            request.addfinalizer(archive.close)
        if native:
            assert evidence.snapshot()["native_requests"] > 0
            assert evidence.snapshot()["fallback_requests"] == 0
        return result

    return run


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("include_untradeables", [False, True])
def test_joint_candidates_keep_owned_or_cheaper_equivalent(
    equivalent_capes, owned, include_untradeables
):
    content, catalog = equivalent_capes
    account = snapshot(owned=(1333, 20050) if owned else (1333,))
    request = _request(roles=2, include_untradeables=include_untradeables)
    facts = {
        item_id: equipment_fact(account, item, content, _prices(), NOW)
        for item_id, item in catalog.items.items()
    }
    search = _Search(account, request, catalog.items, facts, None)
    assignments = search.joint_loadouts(0)
    assert any(all(row.get("cape") == 20050 for row in setup.values()) for setup in assignments)
    assert search.acquisition_tie({20050}) == (0 if owned else 100, 0)


@pytest.mark.parametrize("vector", [False, True])
@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("roles", [1, 2])
def test_optimizer_uses_owned_or_cheaper_actual_cape(solve, vector, owned, roles):
    account = snapshot(owned=(1333, 20050) if owned else (1333,))
    result = solve(account, _request(vector=vector, roles=roles))
    selected = result["selected_solution"]
    assert all(row["equipment"].get("cape") == 20050 for row in selected["loadouts"].values())
    assert selected["purchase_cost_gp"] == (0 if owned else 100)
    assert [row["item_id"] for row in selected["purchases"]] == ([] if owned else [20050])
    if vector:
        for group in result["objective_frontiers"]:
            for point in group["points"]:
                solution = point["solution"]
                assert 6568 not in solution["carried_item_ids"]
                assert 6000 not in solution["carried_item_ids"]


@pytest.mark.parametrize("vector", [False, True])
@pytest.mark.parametrize("boundary", ["lock", "exclusion"])
def test_equivalent_form_selection_respects_physical_boundaries(solve, vector, boundary):
    constraints = (
        {"locks": {"cape": 6568}} if boundary == "lock" else {"excluded_item_ids": (20050, 6000)}
    )
    result = solve(
        snapshot(owned=(1333, 20050)),
        _request(vector=vector, **constraints),
    )
    selected = result["selected_solution"]
    assert selected["loadouts"]["0"]["equipment"]["cape"] == 6568
    assert selected["purchase_cost_gp"] == 1000
    assert [row["item_id"] for row in selected["purchases"]] == [6568]
