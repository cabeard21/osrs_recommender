"""Pure Quest Cape evaluation and isolated single-action counterfactuals."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from tracker.accounts.snapshot import AccountSnapshot
from tracker.domain.types import QuestStatus, Source, Tri
from tracker.quest_cape.catalog import QuestCatalog
from tracker.quest_cape.requirements import RequirementResult, evaluate_requirement


class CompleteQuest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["complete_quest"]
    quest: str


class AvailableQuestAction(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["complete_quest"]
    quest: str
    counts_for_cape: bool = Field(
        description="True if this quest independently counts toward Quest Cape completion; "
        "false for a goal-advancing prerequisite or subquest."
    )


class TrainSkill(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    type: Literal["train_skill"]
    skill: str
    target_level: int = Field(ge=1, le=99, strict=True)


Action = Annotated[CompleteQuest | TrainSkill, Field(discriminator="type")]
ActionType = Literal["complete_quest", "train_skill"]
ACTION_ADAPTER: TypeAdapter[Action] = TypeAdapter(Action)


class QuestView(BaseModel):
    id: str
    name: str
    counts_for_cape: bool
    completion: QuestStatus
    availability: Literal["complete", "available", "blocked", "unknown"]
    requirements: tuple[RequirementResult, ...]
    blockers: tuple[RequirementResult, ...]
    unknowns: tuple[RequirementResult, ...]
    notes: tuple[str, ...]
    wiki_url: str


class SkillBlocker(BaseModel):
    skill: str
    current: int | None
    thresholds: tuple[int, ...]
    quests: tuple[str, ...]


class GoalStatus(BaseModel):
    goal: Literal["quest_cape"] = "quest_cape"
    snapshot_id: str
    last_sync_at: datetime | None = Field(
        description="Last account sync time. Facts are observed as of this time, "
        "not guaranteed current."
    )
    catalog_id: str
    catalog_version: str
    total: int
    completed: int
    remaining: int
    available_now: int = Field(
        description="Incomplete Cape-counting quests currently available; excludes prerequisite "
        "quests that do not independently count toward the Cape total."
    )
    blocked: int
    unknown: int
    skill_blockers: tuple[SkillBlocker, ...]
    quests: tuple[QuestView, ...]
    quest_details_total: int
    next_quest_offset: int | None = None
    limitations: tuple[str, ...] = (
        "Availability uses observed facts and modeled completion requirements, without boosts.",
        "Combat execution, equipment, consumables, and quest guides are not evaluated.",
        "Remaining includes quests whose completion is unknown; prerequisite nodes do not count.",
    )


class AvailableActions(BaseModel):
    goal: Literal["quest_cape"] = "quest_cape"
    snapshot_id: str
    last_sync_at: datetime | None = Field(
        description="Last account sync time. Actions reflect observations as of this time, "
        "not guaranteed current."
    )
    catalog_id: str
    quest_actions: tuple[AvailableQuestAction, ...] = Field(
        description="Available goal-advancing quest actions on this page, including "
        "non-Cape-counting prerequisites; not a recommendation ranking."
    )
    skill_actions: tuple[TrainSkill, ...]
    actions_total: int = Field(
        description="Matching goal-advancing quest and skill actions after filters, before "
        "pagination; not the number of available Cape-counting quests."
    )
    next_action_offset: int | None = Field(
        description="Offset for the next page; null when all matching actions have been returned."
    )
    ordering: str = "Quest name; skill name and target level. No recommendation ranking."


class BlockerChange(BaseModel):
    quest: str
    before: tuple[RequirementResult, ...]
    after: tuple[RequirementResult, ...]


class ActionEvaluation(BaseModel):
    goal: Literal["quest_cape"] = "quest_cape"
    hypothetical: Literal[True] = True
    snapshot_id: str
    last_sync_at: datetime | None = Field(
        description="Last sync time of the observed account used for this hypothetical evaluation."
    )
    catalog_id: str
    action: Action
    completed_before: int
    completed_after: int
    completion_delta: int
    requirements_newly_satisfied: int
    quests_newly_available: tuple[str, ...]
    quests_helped_but_still_blocked: tuple[str, ...]
    downstream_quests: tuple[str, ...]
    preconditions: tuple[RequirementResult, ...]
    blocker_changes: tuple[BlockerChange, ...]
    limitations: tuple[str, ...] = Field(
        description="Simulation boundaries, including unmodeled XP rewards, item rewards, "
        "costs, and elapsed time."
    )


def _check_goal(goal: str) -> None:
    if goal != "quest_cape":
        raise ValueError("Only goal='quest_cape' is supported")


class QuestCapeService:
    def __init__(self, catalog: QuestCatalog) -> None:
        self.catalog = catalog
        self.index = catalog.index()
        self.relevant = catalog.relevant_ids()

    def _outstanding(self, snapshot: AccountSnapshot) -> set[str]:
        """Only unfinished goal nodes and still-needed prerequisite branches need actions."""
        outstanding: set[str] = set()

        def visit(key: str) -> None:
            if key in outstanding or snapshot.quests.get(key) is QuestStatus.COMPLETE:
                return
            outstanding.add(key)
            requirement = self.index[key].requires
            if requirement is not None:
                for leaf in evaluate_requirement(snapshot, requirement).unmet():
                    if leaf.kind == "quest":
                        visit(leaf.key)

        for quest in self.catalog.quests:
            if quest.counts_for_cape:
                visit(quest.id)
        return outstanding

    def get_goal_status(
        self,
        snapshot: AccountSnapshot,
        goal: str = "quest_cape",
        *,
        quest_offset: int = 0,
        quest_limit: int | None = None,
        quest_ids: list[str] | None = None,
    ) -> GoalStatus:
        _check_goal(goal)
        if quest_offset < 0 or (quest_limit is not None and not 1 <= quest_limit <= 100):
            raise ValueError("Quest offset must be nonnegative; limit must be between 1 and 100")
        if quest_ids is not None and not set(quest_ids) <= self.relevant:
            raise ValueError("Unknown Quest Cape quest identifier")
        views: list[QuestView] = []
        outstanding = self._outstanding(snapshot)
        levels: dict[str, set[int]] = {}
        affected: dict[str, set[str]] = {}
        for quest in sorted(self.catalog.quests, key=lambda q: (q.name.casefold(), q.id)):
            if quest.id not in self.relevant:
                continue
            completion = snapshot.quests.get(quest.id, QuestStatus.UNKNOWN)
            requirements = []
            if quest.requires is not None:
                requirements.append(evaluate_requirement(snapshot, quest.requires))
            gaps = quest.unmodeled
            if not quest.requirements_verified:
                gaps = (*gaps, "Quest requirements have not been verified")
            requirements.extend(
                RequirementResult(
                    kind="metadata",
                    key=f"{quest.id}:{i}",
                    status=Tri.UNKNOWN,
                    reason=gap,
                )
                for i, gap in enumerate(gaps)
            )
            unmet = tuple(n for r in requirements for n in r.unmet())
            blockers = tuple(r for r in unmet if r.status is Tri.UNSATISFIED)
            unknowns = tuple(r for r in unmet if r.status is Tri.UNKNOWN)
            availability: Literal["complete", "available", "blocked", "unknown"]
            if completion is QuestStatus.COMPLETE:
                availability = "complete"
            elif completion is QuestStatus.UNKNOWN:
                availability = "unknown"
            elif blockers:
                availability = "blocked"
            elif unknowns:
                availability = "unknown"
            else:
                availability = "available"
            views.append(
                QuestView(
                    id=quest.id,
                    name=quest.name,
                    counts_for_cape=quest.counts_for_cape,
                    completion=completion,
                    availability=availability,
                    requirements=tuple(requirements),
                    blockers=blockers,
                    unknowns=unknowns,
                    notes=quest.notes,
                    wiki_url=quest.wiki_url,
                )
            )
            if quest.id in outstanding:
                for result in unmet:
                    if result.kind == "skill" and isinstance(result.required, int):
                        levels.setdefault(result.key, set()).add(result.required)
                        affected.setdefault(result.key, set()).add(quest.id)
        counted = [q for q in views if q.counts_for_cape]
        completed = sum(q.completion is QuestStatus.COMPLETE for q in counted)
        selected = views if quest_ids is None else [q for q in views if q.id in quest_ids]
        end = len(selected) if quest_limit is None else quest_offset + quest_limit
        return GoalStatus(
            snapshot_id=snapshot.fingerprint,
            last_sync_at=snapshot.last_sync_at,
            catalog_id=self.catalog.fingerprint,
            catalog_version=self.catalog.version,
            total=len(counted),
            completed=completed,
            remaining=len(counted) - completed,
            available_now=sum(q.availability == "available" for q in counted),
            blocked=sum(q.availability == "blocked" for q in counted),
            unknown=sum(q.availability == "unknown" for q in counted),
            quests=tuple(selected[quest_offset:end]),
            quest_details_total=len(selected),
            next_quest_offset=end if end < len(selected) else None,
            skill_blockers=tuple(
                SkillBlocker(
                    skill=key,
                    current=snapshot.skills[key].level if key in snapshot.skills else None,
                    thresholds=tuple(sorted(values)),
                    quests=tuple(sorted(affected[key])),
                )
                for key, values in sorted(levels.items())
            ),
        )

    def get_available_actions(
        self,
        snapshot: AccountSnapshot,
        goal: str = "quest_cape",
        *,
        action_type: ActionType | None = None,
        skill: str | None = None,
        action_offset: int = 0,
        action_limit: int = 50,
    ) -> AvailableActions:
        if action_offset < 0 or not 1 <= action_limit <= 100:
            raise ValueError("Action offset must be nonnegative; limit must be between 1 and 100")
        if action_type not in (None, "complete_quest", "train_skill"):
            raise ValueError("Unknown action type")
        if skill is not None and action_type == "complete_quest":
            raise ValueError("Skill filter cannot be used with complete_quest actions")
        status = self.get_goal_status(snapshot, goal)
        outstanding = self._outstanding(snapshot)
        quest_actions = tuple(
            AvailableQuestAction(
                type="complete_quest", quest=q.id, counts_for_cape=q.counts_for_cape
            )
            for q in status.quests
            if q.availability == "available" and q.id in outstanding
        )
        skill_actions = tuple(
            TrainSkill(type="train_skill", skill=b.skill, target_level=level)
            for b in status.skill_blockers
            if b.current is not None
            for level in b.thresholds
            if level > b.current and (skill is None or b.skill == skill)
        )
        matching: tuple[AvailableQuestAction | TrainSkill, ...] = (
            *(quest_actions if action_type != "train_skill" and skill is None else ()),
            *(skill_actions if action_type != "complete_quest" else ()),
        )
        page = matching[action_offset : action_offset + action_limit]
        end = action_offset + len(page)
        return AvailableActions(
            snapshot_id=status.snapshot_id,
            last_sync_at=snapshot.last_sync_at,
            catalog_id=status.catalog_id,
            quest_actions=tuple(
                action for action in page if isinstance(action, AvailableQuestAction)
            ),
            skill_actions=tuple(action for action in page if isinstance(action, TrainSkill)),
            actions_total=len(matching),
            next_action_offset=end if end < len(matching) else None,
        )

    def evaluate_action(
        self,
        snapshot: AccountSnapshot,
        action: Action,
        goal: str = "quest_cape",
        expected_snapshot_id: str | None = None,
    ) -> ActionEvaluation:
        _check_goal(goal)
        if expected_snapshot_id is not None and expected_snapshot_id != snapshot.fingerprint:
            raise ValueError("snapshot_changed: retrieve current status and actions")
        before = self.get_goal_status(snapshot)
        preconditions: tuple[RequirementResult, ...] = ()
        limitations = ["No XP rewards, item rewards, costs, or elapsed time are simulated."]
        downstream: set[str] = set()
        if isinstance(action, TrainSkill):
            observed = snapshot.skills.get(action.skill)
            if observed is None:
                raise ValueError("Training requires an observed skill level")
            if action.target_level <= observed.level:
                raise ValueError("Training target must exceed the observed level")
            skills = dict(snapshot.skills)
            skills[action.skill] = replace(
                observed, level=action.target_level, xp=None, source=Source.DERIVED
            )
            hypothetical = replace(snapshot, skills=skills)
            if action.skill in _COMBAT_SKILLS:
                hypothetical = replace(hypothetical, combat_level=_combat_level(hypothetical))
                if hypothetical.combat_level is None:
                    limitations.append(
                        "Combat level is unknown: required skill observations missing."
                    )
        else:
            quest = self.index.get(action.quest)
            if quest is None or quest.id not in self.relevant:
                raise ValueError("Quest is not part of the Quest Cape prerequisite graph")
            completion = snapshot.quests.get(quest.id, QuestStatus.UNKNOWN)
            if completion is QuestStatus.COMPLETE:
                raise ValueError("Quest is already complete")
            if completion is QuestStatus.UNKNOWN:
                raise ValueError("Quest completion must be observed before evaluating completion")
            view = next(q for q in before.quests if q.id == quest.id)
            preconditions = (*view.blockers, *view.unknowns)
            if preconditions:
                limitations.append("Completion is assumed despite the listed unmet preconditions.")
            quests = dict(snapshot.quests)
            quests[quest.id] = QuestStatus.COMPLETE
            if quest.completes_parent:
                quests[quest.completes_parent] = QuestStatus.COMPLETE
            points = snapshot.quest_points
            if quest.quest_points is None or quest.staged_rewards or points is None:
                points = None
                limitations.append(
                    "Remaining quest-point reward is unknown; total is hypothetical unknown."
                )
            else:
                points += quest.quest_points
            hypothetical = replace(snapshot, quests=quests, quest_points=points)
            frontier = {quest.id}
            if quest.completes_parent:
                frontier.add(quest.completes_parent)
            while frontier:
                next_frontier = {
                    q.id
                    for q in self.catalog.quests
                    if q.id in self.relevant
                    and q.id not in downstream
                    and set(q.prerequisites) & frontier
                }
                downstream.update(next_frontier)
                frontier = next_frontier
        after = self.get_goal_status(hypothetical)
        previous = {q.id: q for q in before.quests}
        changes: list[BlockerChange] = []
        helped: list[str] = []
        newly: list[str] = []
        satisfied_count = 0
        for quest_view in after.quests:
            old = previous[quest_view.id]
            if old.completion is QuestStatus.COMPLETE:
                continue
            old_leaves = {
                (r.kind, r.key, str(r.required)): r.status
                for root in old.requirements
                for r in root.leaves()
            }
            satisfied = {
                (r.kind, r.key, str(r.required))
                for root in quest_view.requirements
                for r in root.leaves()
                if r.status is Tri.SATISFIED
            }
            gains = {key for key in satisfied if old_leaves.get(key) is not Tri.SATISFIED}
            satisfied_count += len(gains)
            if quest_view.availability == "available" and old.availability != "available":
                newly.append(quest_view.id)
            elif gains and quest_view.availability in ("blocked", "unknown"):
                helped.append(quest_view.id)
            old_blockers, new_blockers = (
                (*old.blockers, *old.unknowns),
                (*quest_view.blockers, *quest_view.unknowns),
            )
            if old_blockers != new_blockers:
                changes.append(
                    BlockerChange(quest=quest_view.id, before=old_blockers, after=new_blockers)
                )
        return ActionEvaluation(
            snapshot_id=before.snapshot_id,
            last_sync_at=snapshot.last_sync_at,
            catalog_id=before.catalog_id,
            action=action,
            completed_before=before.completed,
            completed_after=after.completed,
            completion_delta=after.completed - before.completed,
            requirements_newly_satisfied=satisfied_count,
            quests_newly_available=tuple(newly),
            quests_helped_but_still_blocked=tuple(helped),
            downstream_quests=tuple(sorted(downstream)),
            preconditions=preconditions,
            blocker_changes=tuple(changes),
            limitations=tuple(limitations),
        )


_COMBAT_SKILLS = frozenset(
    {"attack", "strength", "defence", "hitpoints", "prayer", "ranged", "magic"}
)


def _combat_level(snapshot: AccountSnapshot) -> int | None:
    if not _COMBAT_SKILLS <= snapshot.skills.keys():
        return None
    s = {key: snapshot.skills[key].level for key in _COMBAT_SKILLS}
    base = s["defence"] + s["hitpoints"] + s["prayer"] // 2
    offence = max(s["attack"] + s["strength"], s["ranged"] * 3 // 2, s["magic"] * 3 // 2)
    return (base * 10 + offence * 13) // 40
