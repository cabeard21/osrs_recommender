"""Charged glories share combat review, never physical ownership or prices."""

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest

from tests.gear.test_catalog_coverage_phase2 import NOW, quote, snapshot
from tracker.accounts.snapshot import ContainerScanFact
from tracker.content.loader import load_content
from tracker.domain.types import Container
from tracker.gear import catalog as catalog_module
from tracker.gear.catalog import EquipmentCatalog, _reviewed_equivalent, load_catalog
from tracker.gear.execution_profile import execution_context
from tracker.gear.facts import equipment_fact
from tracker.gear.native import capture
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

CHARGED = (1706, 1708, 1710, 1712, 11976, 11978)


@pytest.fixture(scope="module")
def glories():
    content = load_content()
    full = load_catalog(content)
    return content, EquipmentCatalog({i: full.items[i] for i in (1333, 1704, *CHARGED)})


def account(owned):
    return replace(
        snapshot(owned=(1333, owned)),
        container_scans={c: ContainerScanFact(c, NOW, "test") for c in Container},
    )


@pytest.mark.parametrize("item_id", CHARGED)
def test_charged_glory_is_reviewed_with_exact_ownership(glories, item_id):
    content, catalog = glories
    item = catalog.items[item_id]
    assert item.bonuses == catalog.items[1704].bonuses
    assert item.requirements_complete
    assert item.requires is None
    assert item.tradeable is True
    assert item.unsupported_effects == ()
    facts = {
        i: equipment_fact(account(item_id), catalog.items[i], content, {}, NOW)
        for i in (1704, *CHARGED)
    }
    assert facts[item_id]["ownership"]["status"] == "owned"
    assert facts[item_id]["preparation"] is None
    assert all(facts[i]["ownership"]["status"] == "unowned" for i in facts if i != item_id)


@pytest.mark.parametrize("native", (False, True), ids=("python", "native"))
@pytest.mark.parametrize("mode", ("owned", "usable"))
@pytest.mark.parametrize("item_id", CHARGED)
def test_optimizer_uses_owned_charged_glory_without_purchase(glories, item_id, mode, native):
    content, catalog = glories
    request = OptimizationRequest(
        roles=(RoleConfig(id="one", style="slash", locks={"weapon": 1333}),),
        mode=mode,
        budget_gp=1000,
        max_swaps=0,
        secondary_priority="crush_defence_roll",
    )
    with (
        capture() as evidence,
        execution_context(
            "combined" if native else "baseline",
            request,
            fixed_reporting=native,
            factored_evaluation=native,
            compact_states=native,
            native_search=native,
        ),
    ):
        result = optimize(account(item_id), request, catalog, content, {1704: quote(1704)}, NOW)
    selected = result["selected_solution"]
    assert selected["loadouts"]["one"]["equipment"]["neck"] == item_id
    assert selected["purchases"] == []
    assert selected["purchase_cost_gp"] == 0
    if native:
        assert evidence.snapshot()["native_requests"] > 0
        assert evidence.snapshot()["fallback_requests"] == 0


def test_locking_unowned_base_glory_still_requires_its_purchase(glories):
    content, catalog = glories
    request = OptimizationRequest(
        roles=(RoleConfig(id="one", style="slash", locks={"weapon": 1333, "neck": 1704}),),
        mode="usable",
        budget_gp=1000,
        max_swaps=0,
    )
    result = optimize(account(1706), request, catalog, content, {1704: quote(1704)}, NOW)
    selected = result["selected_solution"]
    assert selected["loadouts"]["one"]["equipment"]["neck"] == 1704
    assert selected["purchases"] == [{"item_id": 1704, "cost_gp": 100, "conditional": False}]
    assert selected["purchase_cost_gp"] == 100


@pytest.mark.parametrize("field", ("name", "bonuses"))
def test_charged_glory_review_rejects_changed_physical_data(field):
    rows = json.loads(Path("content/equipment/catalog.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in rows}
    variant = by_id[1706]
    value = "Different amulet" if field == "name" else {**variant["bonuses"], "prayer": 99}
    with pytest.raises(ValueError, match="Reviewed equipment form differs"):
        _reviewed_equivalent({**variant, field: value}, by_id)


@pytest.mark.parametrize("with_sidecars", (False, True))
def test_equivalent_reviews_affect_catalog_revision(monkeypatch, tmp_path, with_sidecars):
    content = load_content()
    root = Path("content/equipment") if with_sidecars else tmp_path
    if not with_sidecars:
        for name in ("catalog.json", "manifest.json"):
            shutil.copyfile(Path("content/equipment") / name, root / name)
    before = load_catalog(content, root)
    monkeypatch.setattr(
        catalog_module,
        "REVIEWED_EQUIVALENT_FORMS",
        MappingProxyType({25264: 11773, 26770: 11773}),
    )
    after = load_catalog(content, root)
    assert before.revision != after.revision


@pytest.mark.parametrize("gate_unknown", (False, True))
def test_glory_equivalence_requires_reviewed_authored_membership(
    make_content, make_item, gate_unknown
):
    content = make_content(
        items=[
            make_item(
                "glory",
                numeric_id=1704,
                variant_item_ids=CHARGED if gate_unknown else (),
                gate_unknown=gate_unknown,
            )
        ]
    )
    catalog = load_catalog(content)
    assert all(not catalog.items[i].requirements_complete for i in CHARGED)


@pytest.mark.parametrize("roles", (1, 2))
def test_vector_frontier_keeps_owned_charged_glory(glories, roles):
    content, catalog = glories
    request = OptimizationRequest(
        roles=tuple(
            RoleConfig(id=str(i), style="slash", locks={"weapon": 1333}) for i in range(roles)
        ),
        mode="usable",
        budget_gp=1000,
        max_swaps=0,
        objectives=[{"kind": "defence_roll", "styles": ["crush"]}],
        max_dps_loss_pct=100,
    )
    result = optimize(account(1706), request, catalog, content, {1704: quote(1704)}, NOW)
    archives = {group["points"].archive for group in result["objective_frontiers"]}
    try:
        assert result["objective_frontiers"]
        for group in result["objective_frontiers"]:
            points = tuple(group["points"])
            assert points
            for point in points:
                selected = point["solution"]
                assert all(
                    row["equipment"]["neck"] == 1706 for row in selected["loadouts"].values()
                )
                assert selected["purchases"] == []
                assert selected["purchase_cost_gp"] == 0
    finally:
        for archive in archives:
            archive.close()
