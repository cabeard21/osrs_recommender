"""Account-facing spell capabilities distinguish Arceuus access from Standard."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tracker.accounts.snapshot import AccountSnapshot
from tracker.api.gear_ui import combat_option_capabilities, mark_of_darkness_capability
from tracker.domain.types import QuestStatus, SkillState, Source, UnlockState


def capabilities(level):
    account = AccountSnapshot(
        1,
        "demonbane",
        skills={
            "magic": SkillState(level, None, Source.RUNELITE, datetime(2026, 11, 14, tzinfo=UTC))
        },
    )
    gear = SimpleNamespace(equipment_catalog=lambda: SimpleNamespace(items={}))
    return {row["id"]: row for row in combat_option_capabilities(account, gear)["spells"]}


def test_inferior_demonbane_available_without_quest_observation():
    spells = capabilities(44)
    assert spells["inferior_demonbane"]["available"]
    assert not spells["superior_demonbane"]["available"]
    assert not spells["dark_demonbane"]["available"]


def test_advanced_demonbane_requires_confirmed_quest_even_at_99_magic():
    spells = capabilities(99)
    assert spells["inferior_demonbane"]["available"]
    for name in ("superior_demonbane", "dark_demonbane"):
        assert not spells[name]["available"]
        assert "Kingdom" in spells[name]["reason"]


@pytest.mark.parametrize("level", [None, 58, 59, 99])
@pytest.mark.parametrize("quest", [None, QuestStatus.NOT_STARTED, QuestStatus.COMPLETE])
def test_mark_capability_requires_magic_and_quest(level, quest):
    snapshot = AccountSnapshot(
        1,
        "mark",
        skills={}
        if level is None
        else {"magic": SkillState(level, None, Source.MANUAL, datetime(2026, 11, 14, tzinfo=UTC))},
        quests={} if quest is None else {"a_kingdom_divided": quest},
    )
    capability = mark_of_darkness_capability(snapshot)
    assert capability["available"] is (
        level is not None and level >= 59 and quest is QuestStatus.COMPLETE
    )
    assert capability["level"] == 59
    assert bool(capability["reason"]) is not capability["available"]


@pytest.mark.parametrize("unlock", [UnlockState.LOCKED, UnlockState.UNKNOWN])
def test_mark_capability_respects_explicit_arceuus_veto(unlock):
    snapshot = AccountSnapshot(
        1,
        "mark",
        skills={"magic": SkillState(99, None, Source.MANUAL, datetime(2026, 11, 14, tzinfo=UTC))},
        quests={"a_kingdom_divided": QuestStatus.COMPLETE},
    )
    assert mark_of_darkness_capability(snapshot)["available"]
    vetoed = replace(snapshot, unlocks={"spellbook_arceuus": unlock})
    capability = mark_of_darkness_capability(vetoed)
    assert not capability["available"]
    assert "Arceuus" in capability["reason"]


def test_mark_capability_without_account_explains_missing_access():
    capability = mark_of_darkness_capability(None)
    assert not capability["available"]
    assert "59" in capability["reason"] and "Kingdom" in capability["reason"]
