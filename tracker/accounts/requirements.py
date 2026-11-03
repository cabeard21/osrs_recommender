"""Shared factual requirement evaluation over an immutable account snapshot."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from tracker.accounts.snapshot import AccountSnapshot
from tracker.content.requirements import (
    AllOf,
    AnyOf,
    AtLeast,
    CombatLevelLeaf,
    ItemLeaf,
    MembersLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
)
from tracker.domain.tri import and_all, at_least, negate, or_any
from tracker.domain.types import Container, QuestStatus, Tri, UnlockState


def level_status(current: int | None, required: int) -> Tri:
    return Tri.UNKNOWN if current is None else Tri.from_bool(current >= required)


def quest_status(current: QuestStatus) -> Tri:
    if current is QuestStatus.UNKNOWN:
        return Tri.UNKNOWN
    return Tri.from_bool(current is QuestStatus.COMPLETE)


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


def _item_status(snapshot: AccountSnapshot, item_ids: frozenset[int]) -> Tri:
    for (item_id, container), sighting in snapshot.observed_items.items():
        if item_id not in item_ids or sighting.quantity <= 0:
            continue
        scan = snapshot.container_scans.get(container)
        if scan is None or sighting.observed_at >= scan.scanned_at:
            return Tri.SATISFIED
    return Tri.UNSATISFIED if set(Container) <= snapshot.container_scans.keys() else Tri.UNKNOWN


def evaluate_requirement(
    snapshot: AccountSnapshot,
    requirement: Requirement,
    *,
    item_ids_by_key: Mapping[str, frozenset[int]] | None = None,
) -> RequirementResult:
    if isinstance(requirement, AllOf | AnyOf | AtLeast | Not):
        if isinstance(requirement, AllOf | AnyOf):
            children = tuple(
                evaluate_requirement(snapshot, n, item_ids_by_key=item_ids_by_key)
                for n in requirement.children
            )
            status = (and_all if isinstance(requirement, AllOf) else or_any)(
                c.status for c in children
            )
        elif isinstance(requirement, AtLeast):
            children = tuple(
                evaluate_requirement(snapshot, n, item_ids_by_key=item_ids_by_key)
                for n in requirement.of
            )
            status = at_least((c.status for c in children), requirement.n)
        else:
            children = (
                evaluate_requirement(snapshot, requirement.child, item_ids_by_key=item_ids_by_key),
            )
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
        key, required = requirement.quest_id, requirement.status
        observed = snapshot.quests.get(key, QuestStatus.UNKNOWN)
        current = observed.value
        if requirement.status == "in_progress" and observed is not QuestStatus.UNKNOWN:
            status = Tri.from_bool(observed in {QuestStatus.IN_PROGRESS, QuestStatus.COMPLETE})
        else:
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
    elif isinstance(requirement, ItemLeaf):
        key, required = requirement.item_id, "owned"
        ids = item_ids_by_key.get(key) if item_ids_by_key is not None else None
        if not ids:
            return RequirementResult(
                kind="item",
                key=key,
                status=Tri.UNKNOWN,
                required=required,
                reason=f"unsupported item requirement: {key} has no catalog identity",
            )
        status = _item_status(snapshot, ids)
        current = {
            Tri.SATISFIED: "owned",
            Tri.UNSATISFIED: "not observed in latest accepted scans",
            Tri.UNKNOWN: "unknown",
        }[status]
    else:
        return RequirementResult(
            kind=requirement.type,
            key=requirement.type,
            status=Tri.UNKNOWN,
            reason=f"unsupported requirement kind: {requirement.type}",
        )
    return RequirementResult(
        kind=requirement.type,
        key=key,
        status=status,
        current=current,
        required=required,
        reason=f"{key}: {current if current is not None else 'unknown'} / {required}",
    )
