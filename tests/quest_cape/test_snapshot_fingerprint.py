"""Snapshot identity is calculated once per immutable, fully detached observation."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tracker.accounts.snapshot import (
    AccountSnapshot,
    ContainerScanFact,
    Observation,
    ObservedItemFact,
)
from tracker.domain.types import Container, QuestStatus, SkillState, Source, UnlockState
from tracker.gear.facts import hypothetical_snapshot

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def snapshot() -> AccountSnapshot:
    return AccountSnapshot(
        1,
        "fixture",
        skills={"attack": SkillState(59, 273739, Source.RUNELITE, NOW)},
        quests={"dragon_slayer_i": QuestStatus.COMPLETE},
        quest_observations={"dragon_slayer_i": Observation("runelite", NOW)},
        unlocks={"example": UnlockState.UNLOCKED},
        observed_items={
            (1333, Container.BANK): ObservedItemFact(1333, Container.BANK, 1, "runelite", NOW)
        },
        container_scans={Container.BANK: ContainerScanFact(Container.BANK, NOW, "runelite")},
        quest_points=240,
        combat_level=72,
        members=True,
        last_sync_at=NOW,
    )


def legacy_fingerprint(account: AccountSnapshot) -> str:
    """Original content serialization remains the public snapshot identity contract."""
    identity = account.summary() | {
        "observed_items": [
            (item_id, container.value, item.quantity, item.source, item.observed_at.isoformat())
            for (item_id, container), item in sorted(
                account.observed_items.items(), key=lambda pair: (pair[0][0], pair[0][1].value)
            )
        ],
        "container_scans": [
            (container.value, scan.scanned_at.isoformat(), scan.source)
            for container, scan in sorted(
                account.container_scans.items(), key=lambda pair: pair[0].value
            )
        ],
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def test_repeated_fingerprint_reads_serialize_only_once(monkeypatch):
    account = snapshot()
    expected = legacy_fingerprint(account)
    original = AccountSnapshot.summary
    calls = []

    def summary(self):
        calls.append(self)
        return original(self)

    monkeypatch.setattr(AccountSnapshot, "summary", summary)
    for _ in range(100):
        assert account.fingerprint == expected
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"player_id": 2},
        {"username": "different"},
        {"skills": {"attack": SkillState(60, 273739, Source.RUNELITE, NOW)}},
        {"skills": {"attack": SkillState(59, 273740, Source.RUNELITE, NOW)}},
        {"skills": {"attack": SkillState(59, 273739, Source.MANUAL, NOW)}},
        {"skills": {"attack": SkillState(59, 273739, Source.RUNELITE, NOW + timedelta(seconds=1))}},
        {"quests": {"dragon_slayer_i": QuestStatus.IN_PROGRESS}},
        {"quest_observations": {"dragon_slayer_i": Observation("manual", NOW)}},
        {
            "quest_observations": {
                "dragon_slayer_i": Observation("runelite", NOW + timedelta(seconds=1))
            }
        },
        {"unlocks": {"example": UnlockState.LOCKED}},
        {
            "observed_items": {
                (1333, Container.BANK): ObservedItemFact(1333, Container.BANK, 2, "runelite", NOW)
            }
        },
        {
            "observed_items": {
                (1333, Container.BANK): ObservedItemFact(1333, Container.BANK, 1, "manual", NOW)
            }
        },
        {
            "observed_items": {
                (1333, Container.BANK): ObservedItemFact(
                    1333, Container.BANK, 1, "runelite", NOW + timedelta(seconds=1)
                )
            }
        },
        {"observed_items": {}},
        {
            "container_scans": {
                Container.BANK: ContainerScanFact(
                    Container.BANK, NOW + timedelta(seconds=1), "runelite"
                )
            }
        },
        {"container_scans": {Container.BANK: ContainerScanFact(Container.BANK, NOW, "manual")}},
        {"container_scans": {}},
        {"quest_points": 241},
        {"combat_level": 73},
        {"members": False},
        {"last_sync_at": NOW + timedelta(seconds=1)},
    ],
)
def test_replacement_recalculates_every_freshness_component(changes):
    account = snapshot()
    before = account.fingerprint
    changed = replace(account, **changes)
    assert changed.fingerprint == legacy_fingerprint(changed)
    assert changed.fingerprint != before
    assert account.fingerprint == before


def test_hypothetical_snapshot_does_not_inherit_observation_fingerprint():
    account = snapshot()
    before = account.fingerprint
    projected = hypothetical_snapshot(account, {"attack": 60}, {}, NOW)
    assert projected.fingerprint == legacy_fingerprint(projected)
    assert projected.fingerprint != before
    assert account.fingerprint == before


def test_cache_does_not_change_value_equality_or_expose_identity_in_repr():
    original = snapshot()
    equivalent = snapshot()
    before = repr(original)
    assert original.fingerprint == legacy_fingerprint(equivalent)
    assert original == equivalent
    assert repr(original) == before


def test_caller_mutation_and_returned_summary_cannot_invalidate_fingerprint():
    items = dict(snapshot().observed_items)
    skills = dict(snapshot().skills)
    account = AccountSnapshot(1, "fixture", skills=skills, observed_items=items)
    before = account.fingerprint
    items.clear()
    skills.clear()
    account.summary()["skills"].clear()
    assert account.fingerprint == before == legacy_fingerprint(account)
