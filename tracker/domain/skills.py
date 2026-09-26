"""Canonical OSRS skill identity at provider and read boundaries."""

from __future__ import annotations

from collections.abc import Mapping

from tracker.domain.types import SOURCE_PRECEDENCE, SkillState

SKILL_ALIASES = {"runecrafting": "runecraft"}


def canonical_skill_name(skill: str) -> str:
    """Use RuneLite/OSRS's ``runecraft`` id for WOM's ``runecrafting`` metric."""
    return SKILL_ALIASES.get(skill, skill)


def canonical_skill_states(skills: Mapping[str, SkillState]) -> dict[str, SkillState]:
    """Resolve a direct snapshot's aliases by time, source, then canonical key."""
    selected: dict[str, tuple[str, SkillState]] = {}
    for raw_name, state in skills.items():
        name = canonical_skill_name(raw_name)
        previous = selected.get(name)
        rank = (
            state.observed_at,
            -_source_rank(state),
            raw_name == name,
        )
        if previous is None or rank > (
            previous[1].observed_at,
            -_source_rank(previous[1]),
            previous[0] == name,
        ):
            selected[name] = (raw_name, state)
    return {name: state for name, (_, state) in selected.items()}


def _source_rank(state: SkillState) -> int:
    try:
        return SOURCE_PRECEDENCE.index(state.source)
    except ValueError:
        return len(SOURCE_PRECEDENCE)
