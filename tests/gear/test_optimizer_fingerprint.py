"""Memoized snapshot identity preserves optimizer cancellation and exact results."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot, ObservedItemFact
from tracker.content.loader import Content
from tracker.domain.types import Container, SkillState, Source
from tracker.gear.models import EquipmentBonuses, EquipmentDefinition
from tracker.gear.optimizer import OptimizationRequest, RoleConfig, optimize

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def context():
    item = EquipmentDefinition(
        id=1333,
        name="Rune scimitar",
        slot="weapon",
        attack_styles=("slash",),
        requirements_complete=True,
        bonuses=EquipmentBonuses(slash=45, melee_strength=44),
    )
    snapshot = AccountSnapshot(
        1,
        "fixture",
        skills={key: SkillState(59, None, Source.RUNELITE, NOW) for key in ("attack", "strength")},
        observed_items={
            (1333, Container.BANK): ObservedItemFact(1333, Container.BANK, 1, "runelite", NOW)
        },
    )
    request = OptimizationRequest(
        roles=(RoleConfig(id="melee", style="slash"),),
        mode="owned",
        max_swaps=0,
        expected_snapshot_id=snapshot.fingerprint,
    )
    return snapshot, request, SimpleNamespace(items={1333: item}, revision="fixture")


def test_cancellation_checks_still_observe_changes_during_search():
    snapshot, request, catalog = context()
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        assert snapshot.fingerprint == request.expected_snapshot_id
        return calls >= 10

    with pytest.raises(ValueError, match="optimization_cancelled"):
        optimize(snapshot, request, catalog, Content(), {}, NOW, cancelled=cancelled)
    assert calls == 10


def test_repeated_fingerprint_callback_preserves_exact_deterministic_output():
    snapshot, request, catalog = context()
    without_callback = optimize(snapshot, request, catalog, Content(), {}, NOW)
    with_callback = optimize(
        snapshot,
        request,
        catalog,
        Content(),
        {},
        NOW,
        cancelled=lambda: snapshot.fingerprint != request.expected_snapshot_id,
    )
    assert with_callback == without_callback


def test_cached_identity_of_original_cannot_accept_a_new_account_observation():
    snapshot, request, catalog = context()
    changed = replace(snapshot, last_sync_at=NOW)
    assert changed.fingerprint != snapshot.fingerprint
    with pytest.raises(ValueError, match="snapshot_changed"):
        optimize(changed, request, catalog, Content(), {}, NOW)
