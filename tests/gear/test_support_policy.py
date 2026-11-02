"""Request-local community assumptions never rewrite the verified catalog."""

from datetime import UTC, datetime

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.requirements import SkillLeaf
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.facts import equipment_fact
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize
from tracker.gear.support import project_catalog

NOW = datetime(2026, 10, 28, tzinfo=UTC)
GENERIC = "Offensive effects have not been validated."


def context(level=70, owned=True):
    item = EquipmentDefinition(
        id=123,
        name="Ordinary test sword",
        slot="weapon",
        attack_styles=("slash",),
        bonuses=EquipmentBonuses(slash=30, melee_strength=30),
        requires=SkillLeaf(skill="attack", level=40),
        unsupported_effects=(GENERIC,),
    )
    catalog = EquipmentCatalog(
        {123: item},
        "physical",
        community_items={123: {"classification": "ordinary", "tradeable": True}},
        community_provenance="source-sha:policy-v1",
    )
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={key: SkillState(level, None, Source.MANUAL, NOW) for key in ("attack", "strength")},
        observed_items={
            (123, Container.BANK): ObservedItemFact(123, Container.BANK, 1, "test", NOW)
        }
        if owned
        else {},
    )
    return snapshot, catalog


def request(policy="verified_only", **kwargs):
    return OptimizationRequest(
        roles=(RoleConfig(id="melee", style="slash"),), support_policy=policy, max_swaps=0, **kwargs
    )


def test_strict_default_and_community_projection_are_immutable():
    _, catalog = context()
    assert request().support_policy == "verified_only"
    assert project_catalog(catalog, "verified_only") is catalog
    projected = project_catalog(catalog, "community_best_effort")
    assert projected.items[123].requires == catalog.items[123].requires
    assert not projected.items[123].requirements_complete
    assert not projected.items[123].unsupported_effects
    assert catalog.items[123].unsupported_effects == (GENERIC,)
    assert projected.community_assumptions[123]
    assert projected.revision == catalog.revision
    assert project_catalog(projected, "verified_only") is catalog
    assert project_catalog(projected, "community_best_effort").items == projected.items


@pytest.mark.parametrize("level,expected", [(70, "satisfied"), (20, "unsatisfied")])
def test_community_known_requirements_remain_distinct(level, expected, make_content):
    snapshot, catalog = context(level)
    catalog = project_catalog(catalog, "community_best_effort")
    fact = equipment_fact(
        snapshot,
        catalog.items[123],
        make_content(),
        {},
        NOW,
        support_assumptions=catalog.community_assumptions[123],
    )
    assert fact["wear"]["status"] == expected
    assert fact["wear"]["known_status"] == expected
    assert not fact["wear"]["requirements_complete"]
    assert fact["support_status"] == "community_assumed"


def test_community_unknown_skill_is_not_satisfied(make_content):
    _, catalog = context()
    catalog = project_catalog(catalog, "community_best_effort")
    fact = equipment_fact(
        AccountSnapshot(1, "test"),
        catalog.items[123],
        make_content(),
        {},
        NOW,
        support_assumptions=catalog.community_assumptions[123],
    )
    assert fact["wear"]["status"] == "unknown"


@pytest.mark.parametrize(
    "update",
    [
        {"content_ids": ("reviewed_unknown",)},
        {"requires": None},
        {"unsupported_effects": (GENERIC, "Charged damage is unsupported.")},
    ],
)
def test_never_relax_authored_unknown_missing_gates_or_explicit_mechanics(update):
    _, catalog = context()
    original = catalog.items[123].model_copy(update=update)
    catalog = EquipmentCatalog({123: original}, community_items=catalog.community_items)
    projected = project_catalog(catalog, "community_best_effort")
    assert projected.items[123] == original
    assert not projected.community_assumptions


def test_optimizer_and_exact_evaluation_share_policy_and_identity(make_content):
    snapshot, catalog = context()
    content = make_content()
    strict = optimize(snapshot, request(mode="owned"), catalog, content, {}, NOW)
    best = optimize(
        snapshot, request("community_best_effort", mode="owned"), catalog, content, {}, NOW
    )
    assert strict["selected_solution"] is None
    assert best["selected_solution"]["loadouts"]["melee"]["equipment"] == {"weapon": 123}
    exact = evaluate_configurations(
        snapshot,
        request("community_best_effort", mode="owned"),
        {},
        {"weapon": 123},
        catalog,
        content,
        {},
        NOW,
    )
    assert exact["proposed"]["status"] == "valid"
    assert (
        exact["proposed"]["performance"]
        == best["selected_solution"]["loadouts"]["melee"]["performance"]
    )
    assert best["assumptions_fingerprint"] != strict["assumptions_fingerprint"]
    assert best["support_policy"] == "community_best_effort"
    assert best["items"][0]["support_status"] == "community_assumed"


def test_unknown_community_price_never_becomes_free(make_content):
    snapshot, catalog = context(owned=False)
    result = evaluate_configurations(
        snapshot,
        request("community_best_effort", budget_gp=100000),
        {},
        {"weapon": 123},
        catalog,
        make_content(),
        {},
        NOW,
    )
    assert result["proposed"]["status"] == "invalid"
    assert result["proposed"]["purchase_cost_gp"] is None
    assert any("no usable purchase price" in r["message"] for r in result["proposed"]["reasons"])


def test_malformed_tradeability_and_policy_fail_closed():
    _, catalog = context()
    malformed = EquipmentCatalog(
        catalog.items, community_items={123: {"classification": "ordinary", "tradeable": "false"}}
    )
    assert not project_catalog(malformed, "community_best_effort").community_assumptions
    with pytest.raises(ValueError, match="support policy"):
        project_catalog(catalog, "invented")


def test_positive_community_price_budget_exclusion_and_lock(make_content):
    from tracker.integrations.prices.client import PriceDTO, PriceSource

    snapshot, catalog = context(owned=False)
    prices = {
        123: PriceDTO(
            item_id=123,
            high_price_gp=100,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source=PriceSource.LIVE,
            provider="test",
        )
    }

    def exact(**changes):
        return evaluate_configurations(
            snapshot,
            request("community_best_effort", **changes),
            {},
            {"weapon": 123},
            catalog,
            make_content(),
            prices,
            NOW,
        )["proposed"]

    assert exact(budget_gp=100)["status"] == "valid"
    assert exact(budget_gp=100)["purchase_cost_gp"] == 100
    assert exact(budget_gp=99)["status"] == "invalid"
    assert exact(budget_gp=100, excluded_item_ids=(123,))["status"] == "invalid"
    assert exact(budget_gp=100, locks={"weapon": None})["status"] == "invalid"


def test_stale_ordinary_sidecar_does_not_relax_new_catalog(tmp_path, make_content):
    import hashlib
    import json

    from tracker.gear.catalog import load_catalog

    _, catalog = context()
    physical = catalog.items[123].model_dump(
        mode="json", exclude={"requires", "requirements_complete", "tradeable", "content_ids"}
    )
    payload = json.dumps([physical]).encode()
    requirements = json.dumps({"items": {"123": {"attack": 40}}}).encode()
    (tmp_path / "catalog.json").write_bytes(payload)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"catalog_sha256": hashlib.sha256(payload).hexdigest()})
    )
    (tmp_path / "requirements.json").write_bytes(requirements)
    community = {
        "provenance": {
            "catalog_sha256": hashlib.sha256(payload).hexdigest(),
            "requirements_sha256": hashlib.sha256(requirements).hexdigest(),
        },
        "items": {"123": {"classification": "ordinary", "tradeable": True}},
    }
    (tmp_path / "community.json").write_text(json.dumps(community))
    loaded = load_catalog(make_content(), tmp_path)
    assert project_catalog(loaded, "community_best_effort").community_assumptions
    community["provenance"]["catalog_sha256"] = "stale"
    (tmp_path / "community.json").write_text(json.dumps(community))
    loaded = load_catalog(make_content(), tmp_path)
    assert not loaded.community_items
    assert not loaded.community_provenance
    assert project_catalog(loaded, "community_best_effort").items[123].unsupported_effects


@pytest.mark.parametrize("tradeable", [True, False])
def test_missing_gates_only_assumed_for_tradeable_ordinary_items(tradeable, make_content):
    snapshot, catalog = context()
    item = catalog.items[123].model_copy(update={"requires": None})
    catalog = EquipmentCatalog(
        {123: item},
        community_items={
            123: {
                "classification": "ordinary",
                "tradeable": tradeable,
                "requirements_assumed_absent": True,
            }
        },
    )
    projected = project_catalog(catalog, "community_best_effort")
    assert bool(projected.community_assumptions) is tradeable
    if tradeable:
        fact = equipment_fact(
            snapshot,
            projected.items[123],
            make_content(),
            {},
            NOW,
            support_assumptions=projected.community_assumptions[123],
        )
        assert fact["wear"]["status"] == "satisfied"
        assert fact["wear"]["known_status"] == "unknown"
        assert (
            "No equip requirement data; tradeable item is assumed ungated."
            in fact["support_assumptions"]
        )
