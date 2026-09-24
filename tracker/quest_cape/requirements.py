"""Explanations over the existing requirement AST, independent of engine state."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from tracker.accounts.requirements import level_status, quest_status
from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.requirements import (
    AllOf,
    AnyOf,
    AtLeast,
    CombatLevelLeaf,
    MembersLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
)
from tracker.domain.types import QuestStatus, Tri, UnlockState
from tracker.progression.tri import and_all, at_least, negate, or_any


class RequirementResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: str
    key: str
    status: Tri
    current: int | str | bool | None = None
    required: int | str | bool | None = None
    reason: str
    children: tuple[RequirementResult, ...] = ()

    def leaves(self) -> tuple[RequirementResult, ...]:
        return tuple(n for c in self.children for n in c.leaves()) if self.children else (self,)

    def unmet(self) -> tuple[RequirementResult, ...]:
        if self.status is Tri.SATISFIED:
            return ()
        # Preserve negation as a condition: its satisfied child is not a blocker.
        if self.kind == "not":
            return (self,)
        return tuple(n for c in self.children for n in c.unmet()) if self.children else (self,)


def evaluate_requirement(snapshot: AccountSnapshot, requirement: Requirement) -> RequirementResult:
    if isinstance(requirement, AllOf | AnyOf | AtLeast | Not):
        if isinstance(requirement, AllOf | AnyOf):
            children = tuple(evaluate_requirement(snapshot, n) for n in requirement.children)
            status = (and_all if isinstance(requirement, AllOf) else or_any)(
                c.status for c in children
            )
        elif isinstance(requirement, AtLeast):
            children = tuple(evaluate_requirement(snapshot, n) for n in requirement.of)
            status = at_least((c.status for c in children), requirement.n)
        else:
            children = (evaluate_requirement(snapshot, requirement.child),)
            status = negate(children[0].status)
        return RequirementResult(
            kind=requirement.type,
            key=requirement.type,
            status=status,
            reason=requirement.type,
            children=children,
        )

    current: int | str | bool | None = None
    required: int | str | bool | None = None
    key: str = requirement.type
    status = Tri.UNKNOWN
    if isinstance(requirement, SkillLeaf):
        key, required = requirement.skill, requirement.level
        skill = snapshot.skills.get(key)
        current = skill.level if skill else None
        status = level_status(current, requirement.level)
    elif isinstance(requirement, QuestLeaf):
        key, required = requirement.quest_id, "complete"
        observed = snapshot.quests.get(key, QuestStatus.UNKNOWN)
        current = observed.value
        status = quest_status(observed)
    elif isinstance(requirement, QuestPointsLeaf | CombatLevelLeaf):
        required = (
            requirement.points if isinstance(requirement, QuestPointsLeaf) else requirement.level
        )
        current = (
            snapshot.quest_points
            if isinstance(requirement, QuestPointsLeaf)
            else snapshot.combat_level
        )
        if snapshot.last_sync_at is None:
            current = None
        status = level_status(current, required)
    elif isinstance(requirement, MembersLeaf):
        current, required = snapshot.members, requirement.members
        status = Tri.UNKNOWN if current is None else Tri.from_bool(current == required)
    elif isinstance(requirement, UnlockLeaf):
        key, required = requirement.key, "unlocked"
        value = snapshot.unlocks.get(key, UnlockState.UNKNOWN)
        current = value.value
        status = (
            Tri.UNKNOWN
            if value is UnlockState.UNKNOWN
            else Tri.from_bool(value is UnlockState.UNLOCKED)
        )
    return RequirementResult(
        kind=requirement.type,
        key=key,
        status=status,
        current=current,
        required=required,
        reason=f"{key}: {current if current is not None else 'unknown'} / {required}",
    )
