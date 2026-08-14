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
from tracker.content.schema import Candidate, Item, TrainingMethod
from tracker.domain.types import (
    COINS_ITEM_ID,
    BandEstimate,
    Container,
    ItemObservation,
    LeafRef,
    PlayerState,
    Recommendation,
    RoadmapSelection,
)

#: How many training methods reach the prompt. §21.2 bounds this because the corpus can hold
#: a dozen ways to train one skill in one band, and a model handed all of them writes about
#: the choice rather than about the task.
MAX_METHODS = 6

#: How many items reach the prompt. Generous against today's corpus — every declared item
#: fits — and a real bound once §10.5's item list grows past what is worth spending tokens on.
MAX_ITEMS = 40

#: Every container an item could be sitting in. An item unobserved after only a bank scan is
#: *unknown*, not *absent* — the same rule :meth:`Evaluator._item` applies, and the reason
#: this module cannot simply test membership of ``observed_items``.
_ALL_CONTAINERS: frozenset[Container] = frozenset(Container)

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
class ItemFact:
    """One item §10.5 declares, and whether this account has been seen holding it.

    ``state`` is §4.5's three, and the middle one is the whole reason this type exists. An
    item missing from ``observed_items`` after a bank scan alone is **unknown**, not absent:
    the equipment slot the player is wearing it in has never been looked at. Only once every
    container has been scanned does absence become evidence — the same rule
    :meth:`tracker.progression.evaluate.Evaluator._item` applies, deliberately duplicated
    rather than shared because that one returns a ``Tri`` for the engine and this one returns
    prose for a reader.

    ``required`` marks an item this task's own requirement trees name. Those are listed even
    when not held, because *"you need this and do not have it"* is the point; an unrequired
    item is only worth its tokens when the player actually has it.
    """

    item_id: str
    name: str
    state: str
    quantity: int | None = None
    containers: tuple[str, ...] = ()
    required: bool = False


@dataclass(frozen=True, slots=True)
class GearRung:
    """Where the account stands on one authored ladder — one style, one slot (§10.5).

    Two hundred items collapse to a handful of these. ``best_held`` is the highest rung the
    account has been seen wearing or banking, ``next_name`` is the rung above it, and
    ``ladder_size`` gives both a scale: *"rung 5 of 12"* says far more than *"Rune scimitar"*.

    ``certain`` is false when nothing on this ladder has been seen **and** some container has
    never been scanned. That combination is the one §4.5 cares about: it looks identical to
    owning nothing, and telling a player to go and buy their first scimitar when they are
    wearing a whip is the failure this whole section exists to prevent.
    """

    style: str
    slot: str
    ladder_size: int
    best_held: str | None = None
    best_tier: int | None = None
    next_name: str | None = None
    next_tier: int | None = None
    certain: bool = False


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

    scanned_containers: tuple[str, ...] = ()
    """Which of bank, inventory and equipment have been seen in full — **not when**.

    The *when* is deliberately absent for the reason this class's docstring gives: §21.5
    hashes this object's rendering, and a timestamp would invalidate every stored note on
    every sync. Which containers were looked in is what changes the advice; how long ago
    they were looked in is §15's job and it already does it.
    """

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
    items: tuple[ItemFact, ...] = ()
    """What the account is known to own, as far as §10.5's corpus can name it.

    Not a slice of the bank — the tracker has no view of one. ``observed_items`` is keyed by
    numeric id and carries no names, and §8.3 forbids pulling the price API's full catalogue
    at runtime to supply them, so the only items that can be *named* to a model are the ones
    the corpus declares. That makes this list narrow by construction, and the rendering says
    so: a model that reads "not held" against eight items and infers an empty bank has been
    misled by the omission rather than by anything stated.
    """

    gear: tuple[GearRung, ...] = ()
    """Where the account stands on each authored gear ladder (§10.5).

    Separate from :attr:`items`, which answers *"does this task's requirement hold?"*. This
    answers *"what are they actually using, and what is the next upgrade?"* — the question
    no requirement leaf asks and the one a player asks first.
    """

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
        scanned_containers=_scanned_containers(state),
        relevant_skills=_skill_facts(skill_ids, skill_targets, state, content),
        relevant_quests=_quest_facts(trees, recommendation, state, content),
        relevant_unlocks=_unlock_facts(trees, recommendation, state),
        items=_item_facts(trees, recommendation, state, content),
        gear=_gear_rungs(state, content),
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


def _scanned_containers(state: PlayerState) -> tuple[str, ...]:
    """Which containers have been seen in full, in the enum's own order.

    Enum order rather than alphabetical: bank, inventory, equipment is how a player thinks
    about where their things are, and the order is fixed by the enum so it cannot drift and
    move §21.5's hash.
    """
    return tuple(container.value for container in Container if container in state.container_scans)


def _item_facts(
    trees: Iterable[Requirement],
    recommendation: Recommendation,
    state: PlayerState,
    content: Content,
) -> tuple[ItemFact, ...]:
    """The items worth naming: what this task needs, and what the account is known to hold.

    Both halves are needed and neither is sufficient. The requirement trees name what would
    block the task, which is the existing slice principle applied to :class:`ItemLeaf`. But
    the question a player actually asks — *"do I already have something better than this?"* —
    is not answered by any leaf, and answering it is what stops the model prefacing its advice
    with a guess about gear it was never shown. So every declared item the account is observed
    to hold is listed too, task-relevant or not.

    Coins are skipped: §6.5 already renders them as ``liquid_gp`` in the account block, and a
    second line saying the same number in different words is a line the model has to reconcile.
    """
    required_ids = {leaf.item_id for leaf in _leaves(trees) if isinstance(leaf, ItemLeaf)}
    required_ids |= {
        blocker.key for blocker in recommendation.blockers if blocker.leaf_type == "item"
    }
    fully_scanned = _ALL_CONTAINERS <= state.container_scans.keys()

    facts: list[ItemFact] = []
    for item in content.items.values():
        if item.item_id is None or item.item_id == COINS_ITEM_ID:
            continue
        required = item.id in required_ids
        observation = _observation(item, state)
        held = observation is not None and observation.quantity > 0
        # An unrequired item nobody has been seen holding earns nothing but tokens.
        if not held and not required:
            continue
        # Nor does one the ladder summary already reported: `gear` names the best rung held
        # in every slot, so repeating it here spends tokens to say the same thing twice and
        # invites the model to treat two mentions as two items.
        if held and not required and item.tier is not None:
            continue
        facts.append(
            ItemFact(
                item_id=item.id,
                name=item.name,
                state=_item_state(held=held, fully_scanned=fully_scanned),
                quantity=observation.quantity if held and observation is not None else None,
                containers=(
                    tuple(
                        container.value
                        for container in Container
                        if container in observation.containers
                    )
                    if held and observation is not None
                    else ()
                ),
                required=required,
            )
        )

    # Required first — those are the ones that gate the task — then by name, so a corpus
    # reordering cannot move the cache.
    facts.sort(key=lambda fact: (not fact.required, fact.name))
    return tuple(facts[:MAX_ITEMS])


def _observation(item: Item, state: PlayerState) -> ItemObservation | None:
    """The observation for any id that counts as owning ``item`` (§10.5).

    One piece of gear wears several numeric ids — charged and uncharged, broken and locked —
    and matching only ``item_id`` is how a player holding a *charged* blowpipe is told they
    have no blowpipe. Ties break on the largest stack, then the lowest id, so two variants in
    the bank cannot make the rendering depend on set iteration order.
    """
    found = [
        observation
        for item_id in sorted(item.owned_item_ids)
        if (observation := state.observed_items.get(item_id)) is not None
        and observation.quantity > 0
    ]
    if not found:
        return None
    return max(found, key=lambda observation: (observation.quantity, -observation.item_id))


def _gear_rungs(state: PlayerState, content: Content) -> tuple[GearRung, ...]:
    """Where this account stands on each authored ladder: best held, and the next rung up.

    This is the section that answers the question a player actually asks, and it exists
    because listing two hundred items cannot. A ladder collapses to two names — what they
    have and what comes next — which is both far cheaper and far more useful than the corpus
    dumped out in full.

    A ladder with nothing held is still worth a line: *"no ranged weapon on the ladder has
    been seen"* is exactly the state that produces bad advice when left unsaid, and it is
    reported as unknown rather than absent until every container has been scanned.
    """
    fully_scanned = _ALL_CONTAINERS <= state.container_scans.keys()
    ladders: dict[tuple[str, str], list[Item]] = {}
    for item in content.items.values():
        if item.tier is None or item.slot is None or item.style is None:
            continue
        ladders.setdefault((item.style, item.slot), []).append(item)

    rungs: list[GearRung] = []
    for (style, slot), items in sorted(ladders.items()):
        # By tier, then id: validation forbids two items sharing a rung, so the id is a
        # tie-break that can never fire — it is here so a corpus bug degrades to a stable
        # ordering rather than to a cache that misses at random.
        items.sort(key=lambda item: (item.tier or 0, item.id))
        held = [item for item in items if _observation(item, state) is not None]
        best = held[-1] if held else None
        following = [item for item in items if best is None or (item.tier or 0) > (best.tier or 0)]
        rungs.append(
            GearRung(
                style=style,
                slot=slot,
                ladder_size=len(items),
                best_held=best.name if best is not None else None,
                best_tier=best.tier if best is not None else None,
                next_name=following[0].name if following else None,
                next_tier=following[0].tier if following else None,
                certain=bool(held) or fully_scanned,
            )
        )
    return tuple(rungs)


def _item_state(*, held: bool, fully_scanned: bool) -> str:
    """§4.5's three states. Absence is only evidence once every container has been looked in."""
    if held:
        return "held"
    return "not held" if fully_scanned else UNKNOWN


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
