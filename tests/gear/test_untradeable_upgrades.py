"""Optional untradeable acquisition never rewrites account ownership or GE cost."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from tracker.accounts.snapshot import AccountSnapshot, ContainerScanFact, ObservedItemFact
from tracker.content.loader import Content
from tracker.content.requirements import QuestLeaf, SkillLeaf
from tracker.db.gear_prices import CachedPriceRecord
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.evaluation import evaluate_configurations
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig, optimize
from tracker.gear.parallel_payload import decode_job, job_payload
from tracker.gear.potions import PotionPolicy

NOW = datetime(2026, 11, 5, tzinfo=UTC)


def weapon(item_id, strength=0, **kwargs):
    return EquipmentDefinition(
        id=item_id,
        name=str(item_id),
        slot="weapon",
        attack_styles=("slash",),
        requirements_complete=True,
        bonuses=EquipmentBonuses(melee_strength=strength),
        **kwargs,
    )


def context(*, complete=True, extra=()):
    snapshot = AccountSnapshot(
        1,
        "test",
        skills={
            key: SkillState(70, None, Source.MANUAL, NOW)
            for key in ("attack", "strength", "defence", "ranged", "magic", "prayer")
        },
        observed_items={(1, Container.BANK): ObservedItemFact(1, Container.BANK, 1, "test", NOW)},
        container_scans={c: ContainerScanFact(c, NOW, "test") for c in Container}
        if complete
        else {},
    )
    items = [weapon(1), weapon(2, 80, tradeable=False), *extra]
    return snapshot, EquipmentCatalog({i.id: i for i in items}, revision="test"), Content()


def body(**kwargs):
    return OptimizationRequest(
        roles=(RoleConfig(id="melee", style="slash"),), max_swaps=0, **kwargs
    )


def run(request, *, complete=True, extra=(), prices=None):
    snapshot, catalog, content = context(complete=complete, extra=extra)
    return optimize(snapshot, request, catalog, content, prices or {}, NOW)


def test_toggle_enables_eligible_untradeable_without_purchase_or_ownership_change():
    snapshot, catalog, content = context()
    fingerprint = snapshot.fingerprint
    disabled = optimize(snapshot, body(), catalog, content, {}, NOW)
    enabled = optimize(snapshot, body(include_untradeables=True), catalog, content, {}, NOW)
    assert disabled["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 1
    solution = enabled["selected_solution"]
    assert solution["loadouts"]["melee"]["equipment"]["weapon"] == 2
    assert solution["purchase_cost_gp"] == 0
    assert solution["purchases"] == []
    assert solution["unowned_untradeable_item_ids"] == [2]
    assert disabled["selected_solution"]["unowned_untradeable_item_ids"] == []
    assert enabled["assumptions"]["include_untradeables"] is True
    assert enabled["assumptions_fingerprint"] != disabled["assumptions_fingerprint"]
    assert (
        next(i for i in enabled["items"] if i["item_id"] == 2)["ownership"]["status"] == "unowned"
    )
    assert snapshot.fingerprint == fingerprint


def test_owned_mode_still_requires_observed_ownership():
    result = run(body(mode="owned", include_untradeables=True))
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 1
    assert result["selected_solution"]["unowned_untradeable_item_ids"] == []


def test_unknown_ownership_stays_unknown():
    result = run(body(include_untradeables=True), complete=False)
    assert result["selected_solution"]["unowned_untradeable_item_ids"] == [2]
    assert next(i for i in result["items"] if i["item_id"] == 2)["ownership"]["status"] == "unknown"


@pytest.mark.parametrize(
    "requirements",
    [
        {"requires": SkillLeaf(skill="attack", level=99)},
        {"requirements_complete": False},
        {"requires": QuestLeaf(quest_id="unknown_quest")},
    ],
)
def test_requirements_and_unknown_gates_stay_enforced(requirements):
    blocked = weapon(3, 150, tradeable=False).model_copy(update=requirements)
    result = run(body(include_untradeables=True), extra=(blocked,))
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 2


def test_tradeable_purchase_budget_remains_required_with_untradeable():
    head = EquipmentDefinition(
        id=3,
        name="Head",
        slot="head",
        requirements_complete=True,
        tradeable=True,
        bonuses=EquipmentBonuses(melee_strength=40),
    )
    unknown = weapon(4, 200, tradeable=True)
    price = CachedPriceRecord(3, 100, NOW, None, None, NOW, "live", "test")
    cheap = run(
        body(include_untradeables=True, budget_gp=99), extra=(head, unknown), prices={3: price}
    )
    funded = run(
        body(include_untradeables=True, budget_gp=100), extra=(head, unknown), prices={3: price}
    )
    assert cheap["selected_solution"]["purchase_cost_gp"] == 0
    solution = funded["selected_solution"]
    assert solution["loadouts"]["melee"]["equipment"] == {"weapon": 2, "head": 3}
    assert solution["purchase_cost_gp"] == 100
    assert solution["purchases"] == [{"item_id": 3, "cost_gp": 100, "conditional": False}]
    assert solution["unowned_untradeable_item_ids"] == [2]


def test_fixed_evaluation_applies_same_policy():
    snapshot, catalog, content = context()
    enabled = evaluate_configurations(
        snapshot,
        body(include_untradeables=True),
        {"weapon": 1},
        {"weapon": 2},
        catalog,
        content,
        {},
        NOW,
    )
    assert enabled["proposed"]["status"] == "valid"
    assert enabled["proposed"]["purchase_cost_gp"] == 0
    assert enabled["proposed"]["purchases"] == []
    assert enabled["proposed"]["unowned_untradeable_item_ids"] == [2]
    disabled = evaluate_configurations(
        snapshot, body(), {"weapon": 1}, {"weapon": 2}, catalog, content, {}, NOW
    )
    assert disabled["proposed"]["status"] == "invalid"
    assert disabled["proposed"]["unowned_untradeable_item_ids"] == []


def test_toggle_is_strict_boolean():
    with pytest.raises(ValidationError):
        body(include_untradeables="true")


def test_worker_round_trip_preserves_policy():
    snapshot, _, _ = context()
    request = body(include_untradeables=True)
    restored, parsed, prices, at = decode_job(
        job_payload(snapshot, request, {}, NOW, "test"), "test"
    )
    assert parsed.include_untradeables is True
    assert parsed == request
    assert restored.fingerprint == snapshot.fingerprint
    assert prices == {}
    assert at == NOW


def test_auto_and_potion_search_preserve_policy_and_acquisitions():
    snapshot, catalog, content = context()
    catalog = EquipmentCatalog(
        {
            i: item.model_copy(update={"attack_profiles": (("slash", "accurate"),)})
            for i, item in catalog.items.items()
        },
        revision="test",
    )
    request = OptimizationRequest(
        include_untradeables=True,
        max_swaps=0,
        roles=(
            RoleConfig(
                id="melee",
                style="slash",
                allowed_disciplines=("melee",),
                combat_options=CombatOptionFilters(
                    attack_types=("slash",), stances=("accurate",), spells=()
                ),
            ),
        ),
        potions=PotionPolicy(mode="optimize", allowed_ids=("super_strength",)),
    )
    result = optimize(snapshot, request, catalog, content, {}, NOW)
    assert result["assumptions"]["include_untradeables"] is True
    assert result["selected_solution"]["unowned_untradeable_item_ids"] == [2]
    assert result["selected_solution"]["purchases"] == []


def test_exclusions_unknown_acquisition_and_unsupported_effects_stay_enforced():
    unknown = weapon(3, 150)
    unsupported = weapon(
        4, 200, tradeable=False, unsupported_effects=("Unsupported special effect",)
    )
    result = run(
        body(include_untradeables=True, excluded_item_ids=(2,)), extra=(unknown, unsupported)
    )
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 1


def test_owned_untradeables_are_not_reported_as_acquisitions():
    from dataclasses import replace

    snapshot, catalog, content = context()
    snapshot = replace(
        snapshot,
        observed_items={
            **snapshot.observed_items,
            (2, Container.BANK): ObservedItemFact(2, Container.BANK, 1, "test", NOW),
        },
    )
    result = optimize(snapshot, body(include_untradeables=True), catalog, content, {}, NOW)
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 2
    assert result["selected_solution"]["unowned_untradeable_item_ids"] == []


@pytest.mark.parametrize("beam_width", [1, 64])
def test_identical_owned_gear_wins_ties_before_physical_id(monkeypatch, beam_width):
    from dataclasses import replace

    monkeypatch.setattr("tracker.gear.optimizer.BEAM_WIDTH", beam_width)
    snapshot, _, content = context()
    snapshot = replace(
        snapshot,
        observed_items={
            (2, Container.BANK): ObservedItemFact(2, Container.BANK, 1, "test", NOW),
        },
    )
    catalog = EquipmentCatalog({i: weapon(i, 80, tradeable=False) for i in (1, 2)}, revision="test")
    result = optimize(snapshot, body(include_untradeables=True), catalog, content, {}, NOW)
    assert result["selected_solution"]["loadouts"]["melee"]["equipment"]["weapon"] == 2
    assert result["selected_solution"]["unowned_untradeable_item_ids"] == []


def test_untradeable_acquisition_tie_break_keeps_real_metric_gain():
    from tracker.gear.frontier import pareto
    from tracker.gear.optimizer import _solution_key

    base = run(body(include_untradeables=True))["selected_solution"]
    owned = {**base, "secondary_value": 5, "unowned_untradeable_item_ids": []}
    unowned = {**base, "secondary_value": 6, "unowned_untradeable_item_ids": [2]}
    assert _solution_key(unowned) < _solution_key(owned)
    assert pareto([owned, unowned]) == [unowned]
    tradeoff = {**unowned, "score": owned["score"] - 0.1}
    assert len(pareto([owned, tradeoff])) == 2
