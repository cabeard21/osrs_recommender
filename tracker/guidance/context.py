"""Assemble the task-scoped view of an account that §21.2 hands to the model.

The job is **relevance, not completeness**. An account has twenty-three skills, hundreds of
quest states and a whole corpus of training methods; a prompt containing all of it is both
expensive and worse, because the model has to guess which parts bear on the task. So the
requirement trees of the chosen candidate (§10.2) select the slice: the skills its leaves
name, the quests and unlocks its leaves name, and the training methods that cover the level
band §8 actually estimated.

Two rules are worth stating before the code, because both are easy to break and neither
breaks loudly:

**Three-valued facts stay three-valued.** §4.5 and D8 are not about capability state alone;
they are about what a fact means. ``account_type is None`` renders *unknown*, never *main* —
the docstring on :attr:`PlayerState.account_type` names the exact failure that follows from
getting this wrong, and a prompt is just a slower path to it. Same for ``members``, and for
``liquid_gp``, where ``None`` is *nobody has looked* and ``0`` is *someone looked and there
were none*.

**Everything is ordered.** §21.5 keys the cache on a hash of the rendered context, so a set
iteration or a dict insertion order leaking into the output would produce a cache that
misses at random and re-bills the user for advice they already have.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from tracker.content.loader import Content
from tracker.content.requirements import (
    AccountTypeLeaf,
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MembersLeaf,
    MilestoneLeaf,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
    iter_leaves,
)
from tracker.content.schema import Candidate, TrainingMethod
from tracker.domain.types import (
    BandEstimate,
    LeafRef,
    PlayerState,
    Recommendation,
    RoadmapSelection,
)

#: How many training methods reach the prompt. §21.2 bounds this because the corpus can hold
#: a dozen ways to train one skill in one band, and a model handed all of them writes about
#: the choice rather than about the task.
MAX_METHODS = 6

#: What an unobserved three-valued fact renders as. A single constant so the *unknown* in
#: ``account_type`` and the one in ``members`` cannot drift apart in the rendered text.
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SkillFact:
    """One skill the task actually depends on, with the target that makes it a task.

    ``target`` is the highest level any requirement leaf asks of this skill. Carrying it is
    the difference between telling the model *87* and telling it *87 → 94*: only the second
    is a piece of work, and only the second lets the model size the advice.

    ``level`` is ``None`` when the skill has never been observed at all. ``is_ranked`` is
    false when it has been observed but carries no XP — G5's "unranked is not zero", which
    matters here because *"you are level 1"* and *"we have never seen this skill"* lead to
    different first steps.
    """

    skill_id: str
    name: str
    level: int | None
    is_ranked: bool
    target: int | None


@dataclass(frozen=True, slots=True)
class MethodFact:
    """One authored training method, with the §10.5 detail that exists for exactly this.

    ``selected`` marks the method §8's estimator actually costed for one of the bands. The
    model is told which one that was so its advice and the app's hour figure describe the
    same plan — without it, the app can say *16 hours* while the model recommends a method
    that takes forty, and nothing in either statement is wrong.

    ``gate`` is the method's own ``requires``, rendered. A method the account cannot use is
    still worth showing when it is the obvious next step; hiding it would leave the model to
    invent an explanation for why the slow method is being recommended.
    """

    method_id: str
    name: str
    skill: str
    from_level: int
    to_level: int
    xp_per_hour: int
    cost_per_hour_gp: int
    selected: bool
    location: str | None = None
    target: str | None = None
    gear: tuple[str, ...] = ()
    inventory: tuple[str, ...] = ()
    notes: str | None = None
    wiki_url: str | None = None
    gate: str | None = None


@dataclass(frozen=True, slots=True)
class TaskContext:
    """Everything §21.3's prompt is allowed to know about one task on one account.

    Deliberately **not** carrying an observation timestamp or a clock reading. It would be a
    genuinely useful sentence — *"these levels are three weeks old"* — but §21.5 hashes this
    object's rendering to decide whether stored advice is still good, and a timestamp would
    invalidate every note on every sync regardless of whether anything the advice depended on
    moved. Staleness is the UI's job (§15) and it already does it.
    """

    # The account, as far as this task is concerned.
    account_type: str = UNKNOWN
    members: str = UNKNOWN
    combat_level: int | None = None
    quest_points: int | None = None
    liquid_gp: int | None = None
    """``None`` is *nobody has scanned a container*, and is not ``0`` (§6.5, G3)."""

    # The task.
    candidate_id: str = ""
    task_name: str = ""
    kind: str = ""
    reason: str = ""
    """§9.5's "Why" line, carried verbatim. The engine's sentence, not the model's."""

    estimated_hours: float | None = None
    estimated_gp: int | None = None
    estimate_confidence: str = UNKNOWN
    bands: tuple[BandEstimate, ...] = ()

    blocked: bool = False
    unknown_gate: bool = False
    blockers: tuple[LeafRef, ...] = ()

    # What it is for — §9.10's consequences, already computed and merely relayed.
    unblocks: tuple[str, ...] = ()
    needed_for: tuple[str, ...] = ()
    works_toward: tuple[str, ...] = ()
    speeds_up: tuple[str, ...] = ()
    roadmaps: tuple[tuple[str, float], ...] = ()

    # The relevant slice.
    relevant_skills: tuple[SkillFact, ...] = ()
    relevant_quests: tuple[tuple[str, str], ...] = ()
    relevant_unlocks: tuple[tuple[str, str], ...] = ()
    methods: tuple[MethodFact, ...] = field(default_factory=tuple)


def build_task_context(
    *,
    state: PlayerState,
    recommendation: Recommendation,
    content: Content,
    roadmaps: RoadmapSelection,
) -> TaskContext:
    """Build the §21.2 context for one already-chosen recommendation.

    ``recommendation`` is the engine's output and is never second-guessed here — D14. Its
    ``reason``, ``estimate``, ``blockers`` and ``consequences`` are relayed as computed.

    A candidate absent from the corpus is not an error. Synthesized practice refreshers
    (§9.8) have ids no content file declares, and they are legitimate things to ask about;
    they simply contribute no requirement trees, so the slice comes out empty and the model
    works from the recommendation's own fields.
    """
    candidate = content.candidates.get(recommendation.candidate_id)
    trees = _requirement_trees(candidate)

    skill_targets = _skill_targets(trees)
    methods = _relevant_methods(
        content=content,
        skills=frozenset(skill_targets),
        bands=recommendation.estimate.bands if recommendation.estimate else (),
    )
    # A method's own skill belongs in the skill table even when no requirement leaf named it,
    # or the model is told to train something whose current level it was never shown.
    skill_ids = frozenset(skill_targets) | {method.skill for method in methods}

    return TaskContext(
        account_type=state.account_type.value if state.account_type is not None else UNKNOWN,
        members=_members_word(state.members),
        combat_level=state.combat_level,
        quest_points=state.quest_points,
        liquid_gp=state.liquid_gp,
        candidate_id=recommendation.candidate_id,
        task_name=recommendation.name,
        kind=recommendation.kind.value,
        reason=recommendation.reason,
        estimated_hours=recommendation.estimate.hours if recommendation.estimate else None,
        estimated_gp=recommendation.estimate.gp if recommendation.estimate else None,
        estimate_confidence=(
            recommendation.estimate.confidence.name.lower() if recommendation.estimate else UNKNOWN
        ),
        bands=recommendation.estimate.bands if recommendation.estimate else (),
        blocked=recommendation.blocked,
        unknown_gate=recommendation.unknown_gate,
        blockers=recommendation.blockers,
        unblocks=_unblocks(recommendation),
        needed_for=_needed_for(recommendation),
        works_toward=_works_toward(recommendation),
        speeds_up=_speeds_up(recommendation),
        roadmaps=_roadmaps(roadmaps, content),
        relevant_skills=_skill_facts(skill_ids, skill_targets, state, content),
        relevant_quests=_quest_facts(trees, recommendation, state, content),
        relevant_unlocks=_unlock_facts(trees, recommendation, state),
        methods=methods,
    )


# ---------------------------------------------------------------------------
# The relevant slice
# ---------------------------------------------------------------------------


def _requirement_trees(candidate: Candidate | None) -> tuple[Requirement, ...]:
    """The three trees §10.6 gives a candidate, minus the ones it left unset.

    All three, not just ``requires``: ``completion`` is what makes a skill band *a task about
    that skill*, and ``grants_facts`` names what the task hands the account afterwards, which
    is context for what to do with it.
    """
    if candidate is None:
        return ()
    trees = (candidate.requires, candidate.completion, candidate.grants_facts)
    return tuple(tree for tree in trees if tree is not None)


def _leaves(trees: Iterable[Requirement]) -> tuple[Requirement, ...]:
    return tuple(leaf for tree in trees for leaf in iter_leaves(tree))


def _skill_targets(trees: Iterable[Requirement]) -> Mapping[str, int]:
    """Highest level asked of each skill named anywhere in the trees.

    Maximum rather than the first hit: a candidate may name a skill in both ``requires`` and
    ``completion`` at different levels, and the target that describes the work is the higher.
    """
    targets: dict[str, int] = {}
    for leaf in _leaves(trees):
        if isinstance(leaf, SkillLeaf):
            targets[leaf.skill] = max(targets.get(leaf.skill, 0), leaf.level)
    return targets


def _skill_facts(
    skill_ids: frozenset[str],
    targets: Mapping[str, int],
    state: PlayerState,
    content: Content,
) -> tuple[SkillFact, ...]:
    facts = []
    for skill_id in sorted(skill_ids):
        observed = state.skills.get(skill_id)
        declared = content.skills.get(skill_id)
        facts.append(
            SkillFact(
                skill_id=skill_id,
                name=declared.name if declared is not None else skill_id,
                level=observed.level if observed is not None else None,
                is_ranked=observed is not None and observed.xp is not None,
                target=targets.get(skill_id),
            )
        )
    return tuple(facts)


def _quest_facts(
    trees: Iterable[Requirement],
    recommendation: Recommendation,
    state: PlayerState,
    content: Content,
) -> tuple[tuple[str, str], ...]:
    quest_ids = {leaf.quest_id for leaf in _leaves(trees) if isinstance(leaf, QuestLeaf)}
    quest_ids |= {
        blocker.key for blocker in recommendation.blockers if blocker.leaf_type == "quest"
    }
    facts = []
    for quest_id in sorted(quest_ids):
        declared = content.quests.get(quest_id)
        status = state.quests.get(quest_id)
        facts.append(
            (
                declared.name if declared is not None else quest_id,
                status.value if status is not None else UNKNOWN,
            )
        )
    return tuple(facts)


def _unlock_facts(
    trees: Iterable[Requirement],
    recommendation: Recommendation,
    state: PlayerState,
) -> tuple[tuple[str, str], ...]:
    keys = {leaf.key for leaf in _leaves(trees) if isinstance(leaf, UnlockLeaf)}
    keys |= {blocker.key for blocker in recommendation.blockers if blocker.leaf_type == "unlock"}
    facts = []
    for key in sorted(keys):
        observed = state.unlocks.get(key)
        facts.append((key, observed.value if observed is not None else UNKNOWN))
    return tuple(facts)


def _relevant_methods(
    *,
    content: Content,
    skills: frozenset[str],
    bands: tuple[BandEstimate, ...],
) -> tuple[MethodFact, ...]:
    """Authored methods for the trained skills, covering the levels §8 actually costed.

    Filtering by band rather than by skill alone is what keeps this a slice: the corpus has
    methods for level 1 and methods for level 92, and on a 70 → 75 task neither is an answer.
    When there are no bands — an acquisition, a quest, a refresher — every method for the
    skill is in range, which is the right default because nothing narrower has been said.
    """
    if not skills:
        return ()

    selected_ids = {band.method_id for band in bands if band.method_id is not None}
    ranges = tuple((band.from_level, band.to_level) for band in bands)

    matches: list[MethodFact] = []
    for method in content.training_methods.values():
        if method.skill not in skills:
            continue
        if ranges and not _overlaps_any(method, ranges):
            continue
        matches.append(_method_fact(method, selected=method.id in selected_ids))

    # Selected first — it is the one the app's own hour figure describes — then fastest, then
    # by id so a corpus reordering cannot move the cache.
    matches.sort(key=lambda fact: (not fact.selected, -fact.xp_per_hour, fact.method_id))
    return tuple(matches[:MAX_METHODS])


def _overlaps_any(method: TrainingMethod, ranges: Iterable[tuple[int, int]]) -> bool:
    return any(
        method.level_range.min <= to_level and method.level_range.max >= from_level
        for from_level, to_level in ranges
    )


def _method_fact(method: TrainingMethod, *, selected: bool) -> MethodFact:
    detail = method.detail
    return MethodFact(
        method_id=method.id,
        name=method.name,
        skill=method.skill,
        from_level=method.level_range.min,
        to_level=method.level_range.max,
        xp_per_hour=method.xp_per_hour,
        cost_per_hour_gp=method.cost_per_hour_gp,
        selected=selected,
        location=detail.location,
        target=detail.target,
        gear=detail.gear,
        inventory=detail.inventory,
        notes=detail.notes,
        wiki_url=detail.wiki_url,
        gate=describe_requirement(method.requires),
    )


# ---------------------------------------------------------------------------
# Relaying the engine's own output (§9.10)
# ---------------------------------------------------------------------------


def _unblocks(recommendation: Recommendation) -> tuple[str, ...]:
    return tuple(
        capability.name for capability in recommendation.consequences.unblocks_capabilities
    )


def _needed_for(recommendation: Recommendation) -> tuple[str, ...]:
    lines = []
    for gate in recommendation.consequences.gate_progress:
        if gate.unblocks:
            lines.append(f"{gate.name} (this clears the last requirement)")
        else:
            lines.append(
                f"{gate.name} ({gate.remaining_after} of {gate.remaining_before} "
                "requirements would remain)"
            )
    return tuple(lines)


def _works_toward(recommendation: Recommendation) -> tuple[str, ...]:
    lines = [
        f"{goal.name}{'' if goal.on_roadmap else ' (not on a chosen roadmap)'}"
        for goal in recommendation.consequences.goal_progress
    ]
    lines += [
        f"{link.name} via {link.via_name}{'' if link.on_roadmap else ' (not on a chosen roadmap)'}"
        for link in recommendation.consequences.goal_links
    ]
    return tuple(lines)


def _speeds_up(recommendation: Recommendation) -> tuple[str, ...]:
    return tuple(
        f"{acceleration.name}: {acceleration.hours_before:.0f}h -> {acceleration.hours_after:.0f}h"
        for acceleration in recommendation.consequences.speeds_up
    )


def _roadmaps(roadmaps: RoadmapSelection, content: Content) -> tuple[tuple[str, float], ...]:
    normalized = roadmaps.normalized()
    named = [
        (
            content.roadmaps[roadmap_id].name if roadmap_id in content.roadmaps else roadmap_id,
            weight,
        )
        for roadmap_id, weight in normalized.items()
    ]
    named.sort(key=lambda entry: (-entry[1], entry[0]))
    return tuple(named)


# ---------------------------------------------------------------------------
# Rendering requirement nodes
# ---------------------------------------------------------------------------


def describe_requirement(requirement: Requirement | None) -> str | None:
    """A one-line, human-readable summary of a requirement's leaves.

    Flattened to a comma-joined list rather than reproducing the boolean structure. The
    grammar's combinators matter to the evaluator (§9.1) and would only be noise here: the
    model is being told what a method needs, not asked to evaluate it — that already happened
    upstream, and its verdict arrives separately as ``blocked``.
    """
    if requirement is None:
        return None
    described = sorted({describe_leaf(leaf) for leaf in iter_leaves(requirement)})
    return ", ".join(described) if described else None


def describe_leaf(leaf: Requirement) -> str:
    """Render one leaf. Unknown node types fall back to their ``type``, never to a crash."""
    if isinstance(leaf, SkillLeaf):
        return f"{leaf.skill} {leaf.level}"
    if isinstance(leaf, QuestLeaf):
        return f"quest {leaf.quest_id}"
    if isinstance(leaf, UnlockLeaf):
        return f"unlock {leaf.key}"
    if isinstance(leaf, ItemLeaf):
        return f"item {leaf.item_id}"
    if isinstance(leaf, MilestoneLeaf):
        return f"milestone {leaf.key}"
    if isinstance(leaf, CapabilityLeaf):
        return f"capability {leaf.capability_id}"
    if isinstance(leaf, CombatLevelLeaf):
        return f"combat level {leaf.level}"
    if isinstance(leaf, QuestPointsLeaf):
        return f"{leaf.points} quest points"
    if isinstance(leaf, AccountTypeLeaf):
        return f"account type {leaf.account_type}"
    if isinstance(leaf, MembersLeaf):
        return "members" if leaf.members else "free-to-play"
    return str(leaf.type)  # pragma: no cover — every §10.2 leaf is covered above


def _members_word(members: bool | None) -> str:
    """``None`` is *nobody has said*, and is not *no* (§4.5)."""
    if members is None:
        return UNKNOWN
    return "yes" if members else "no"
