from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import load_catalog
from tracker.gear.evaluation import item_problems, purchases
from tracker.gear.facts import equipment_fact
from tracker.gear.optimizer import OptimizationRequest, RoleConfig

NOW = datetime(2026, 11, 23, tzinfo=UTC)


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(Content())


def snapshot(*owned, members=True, **levels):
    return AccountSnapshot(
        1,
        "weight",
        members=members,
        skills={k: SkillState(level, None, Source.MANUAL, NOW) for k, level in levels.items()},
        observed_items={
            (i, Container.BANK): ObservedItemFact(i, Container.BANK, 1, "test", NOW) for i in owned
        },
    )


def fact(catalog, item_id, account, prices=None):
    return equipment_fact(account, catalog.items[item_id], Content(), prices or {}, NOW)


def request(mode="owned", **fields):
    return OptimizationRequest(roles=(RoleConfig(id="main", style="slash"),), mode=mode, **fields)


def test_banked_graceful_counts_only_for_its_exact_variant(catalog):
    account = snapshot(13579)
    row = fact(catalog, 13580, account)
    assert row["wear"]["status"] == "satisfied"
    assert row["planning_ownership"]["status"] == "owned"
    assert row["ownership"]["status"] == "unknown"
    assert row["preparation"]["source_item_id"] == 13579
    assert row["preparation"]["charges"] == "not_applicable"
    assert not item_problems(13580, row, request())
    for sibling in (11851, 13592):
        assert item_problems(sibling, fact(catalog, sibling, account), request())


@pytest.mark.parametrize(
    "item_id,skill,minimum",
    [
        (10073, "hunter", 40),
        (10074, "hunter", 66),
        (10554, "defence", 40),
    ],
)
def test_reducer_wear_threshold(catalog, item_id, skill, minimum):
    assert not catalog.items[item_id].unsupported_effects
    for level, expected in [(minimum - 1, "unsatisfied"), (minimum, "satisfied")]:
        assert fact(catalog, item_id, snapshot(**{skill: level}))["wear"]["status"] == expected


def test_common_reducers_are_members_only_and_other_capes_keep_blockers(catalog):
    assert fact(catalog, 89, snapshot(88, members=False))["wear"]["status"] == "unsatisfied"
    assert fact(catalog, 89, snapshot(88))["wear"]["status"] == "satisfied"
    assert catalog.items[13340].unsupported_effects and catalog.items[13342].unsupported_effects


def test_cape_purchase_uses_inventory_market_and_observation_avoids_purchase(catalog):
    prices = {
        10071: SimpleNamespace(
            high_price_gp=54,
            high_trade_at=NOW,
            low_price_gp=None,
            low_trade_at=None,
            fetched_at=NOW,
            source="live",
        )
    }
    for owned in ((), (10071,), (10074,)):
        row = fact(catalog, 10074, snapshot(*owned, hunter=66), prices)
        assert row["price"]["amount_gp"] == 54
        assert row["acquisition"] == "tradeable"
        needed = purchases({10074}, {10074: row}, request("usable"))
        assert [p["item_id"] for p in needed] == ([] if owned else [10071])


def test_execution_resolves_bag_locks_assumptions_and_exclusions(catalog):
    from tracker.gear.weight_reducers import normalize_reducer_request

    original = request(
        "future", locks={"head": 11850}, assumed_item_ids=(11850,), excluded_item_ids=(13579,)
    )
    effective = normalize_reducer_request(original, catalog.items)
    assert effective.locks == {"head": 11851} and original.locks == {"head": 11850}
    assert effective.assumed_item_ids == (11851,) and effective.excluded_item_ids == (13580,)
    with pytest.raises(ValueError, match="excluded"):
        normalize_reducer_request(
            request(locks={"head": 11851}, excluded_item_ids=(11850,)), catalog.items
        )


def test_reviewed_set_and_acquisition_gates(catalog):
    from tracker.gear.weight_reducers import REVIEWED_FORMS

    assert len(REVIEWED_FORMS) == 76
    assert all(
        catalog.items[i].requirements_complete and not catalog.items[i].unsupported_effects
        for i in REVIEWED_FORMS
    )
    recolour = fact(catalog, 13580, snapshot())
    assert recolour["acquisition_requirement"]["status"] == "unknown"
    assert item_problems(13580, recolour, request("usable", include_untradeables=True))
    assert not item_problems(
        11851, fact(catalog, 11851, snapshot()), request("usable", include_untradeables=True)
    )


def test_exact_configuration_accepts_banked_lock_and_reports_observed_source(catalog):
    from tracker.gear.catalog import EquipmentCatalog
    from tracker.gear.evaluation import evaluate_configurations
    from tracker.gear.models import EquipmentDefinition

    sword = EquipmentDefinition(
        id=1,
        name="Sword",
        slot="weapon",
        requirements_complete=True,
        attack_styles=("slash",),
        attack_profiles=(("slash", "accurate"),),
    )
    account = snapshot(88, 1, attack=70, strength=70, defence=70)
    result = evaluate_configurations(
        account,
        request(locks={"feet": 88}),
        {"weapon": 1, "feet": 89},
        {"weapon": 1, "feet": 89},
        EquipmentCatalog({1: sword, 89: catalog.items[89]}),
        Content(),
        {},
        NOW,
    )
    side = result["baseline"]
    assert side["status"] == "valid"
    assert side["purchases"] == []
    assert side["preparations"][0]["source_item_id"] == 88


def test_review_preserves_additional_blockers_and_checks_physical_form(catalog):
    from tracker.gear.weight_reducers import review_reducer

    item = catalog.items[89]
    flagged = item.model_copy(update={"unsupported_effects": ("Unreviewed transformation",)})
    assert review_reducer(flagged).unsupported_effects == flagged.unsupported_effects
    with pytest.raises(ValueError, match="physical form changed"):
        review_reducer(item.model_copy(update={"name": "Other boots"}))


def test_global_and_role_locks_can_name_the_same_physical_reducer(catalog):
    from tracker.api.gear_optimizations import BrowserOptimizationRequest
    from tracker.gear.weight_reducers import normalize_reducer_request

    payload = {
        "roles": [{"id": "a", "style": "slash", "locks": {"head": 11851}}],
        "locks": {"head": 11850},
        "expected_snapshot_id": "test",
    }
    browser = BrowserOptimizationRequest.model_validate(payload)
    effective = normalize_reducer_request(browser, catalog.items)
    assert effective.roles[0].locks == effective.locks == {"head": 11851}
    with pytest.raises(ValueError, match=r"[Cc]onflicting global and role"):
        BrowserOptimizationRequest.model_validate({**payload, "locks": {"head": 13579}})
