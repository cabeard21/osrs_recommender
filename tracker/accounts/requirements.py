"""Shared factual leaf semantics, used by both account paths."""

from tracker.domain.types import QuestStatus, Tri


def level_status(current: int | None, required: int) -> Tri:
    return Tri.UNKNOWN if current is None else Tri.from_bool(current >= required)


def quest_status(current: QuestStatus) -> Tri:
    if current is QuestStatus.UNKNOWN:
        return Tri.UNKNOWN
    return Tri.from_bool(current is QuestStatus.COMPLETE)
