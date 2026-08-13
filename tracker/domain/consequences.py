"""§9.10's *"what is this actually for?"* — a candidate's consequences, derived not authored.

The six factors of §9.4 say how a candidate scored. They do not say what it *does*, and for
a large part of the corpus they cannot: ``tools/generate_candidates.py`` emits every skill
band with ``advances: {}``, because §10.6 reserves the judgment of which capability a level
advances for a human. So *"Train Slayer to 10"* carries no goal in any field it owns, scores
its ``pvp_value`` at the ε floor, and reaches the top of a list on ``effort_decay`` alone.

The chain that explains it exists, one hop away and in nobody's hands: Slayer 10 is a
``requires`` leaf of ``complete_desert_treasure_i``, which advances ``ice_barrage_nh``. This
module walks that hop and reports it.

What this is not
----------------

**It is not a scoring input.** Nothing here is read by §9.4, and the engine derives it
*after* the ranking is fixed (see :func:`tracker.recommendations.engine.recommend_run`). A
consequence is a description of a decision already made; letting one back into the decision
would make the explanation self-justifying.

**It does not invent a reason.** Every field can be empty, and for a candidate that unblocks
nothing, dents no goal and accelerates nothing, all of them are. That silence is the honest
output and is deliberately not back-filled: an entry with nothing to say ranked on cheapness
alone, and saying so plainly is more use to a player than generic prose would be.

Two kinds of "not yet"
----------------------

Every count here is over **blockers** — leaves §9.1 evaluates to *unsatisfied*. Unknown
leaves are excluded, and the distinction is the difference between a true sentence and a
false one. Desert Treasure I names eleven leaves; against a freshly-synced account four are
skills observed to be too low and seven are quests nobody has been asked about. *"1 of 4
remaining"* is a claim about the corpus and the account. *"1 of 11"* would be a claim about
how much has been looked at, dressed up as progress — and G3 is explicit that the remedy for
an unknown is a sync, not a grind.

The injected seams
------------------

Like :mod:`tracker.domain.candidates`, this module declares the shape of the evaluation it
needs and takes the implementation as an argument, rather than importing
``tracker.progression`` and closing a cycle. The engine passes
:class:`~tracker.recommendations.facts.GateOracle`, which answers both from counterfactual
worlds the sizing pass had already built.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence

from tracker.content.loader import Content
from tracker.content.requirements import (
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MilestoneLeaf,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
    iter_leaves,
)
from tracker.content.schema import Candidate
from tracker.domain.candidates import MethodUnlockWinner
from tracker.domain.types import (
    Acceleration,
    Consequences,
    GateProgress,
    GoalLink,
    GoalProgress,
    LeafRef,
    UnblockedCapability,
)

#: *"Which of this candidate's gate leaves are still unsatisfied, in the world where
#: ``grants`` is true?"* ``None`` means *as things actually stand*.
OutstandingGate = Callable[[Candidate, Requirement | None], tuple[LeafRef, ...]]

#: The same question asked of a capability's own ``requires`` tree, resolved transitively
#: through ``capability:`` leaves so a roadmap rung answers for the chain beneath it (§4.1).
OutstandingCapabilityGate = Callable[[str, Requirement | None], tuple[LeafRef, ...]]

#: How many candidates one entry may report being needed for. Three fits a card, and the
#: fourth-most-nearly-unblocked thing has yet to be what changes anyone's mind.
_GATE_LIMIT = 3

#: How many goals one entry may report moving, direct or indirect. Two, because the second
#: is usually the rung above the first and the third is always ``raid_ready``.
_GOAL_LIMIT = 2


def unblocked_capabilities(
    capability_ids: Sequence[str], content: Content
) -> tuple[UnblockedCapability, ...]:
    """Name the capabilities :func:`~tracker.domain.candidates.unlock_flips` identified.

    A capability the corpus no longer declares is dropped rather than rendered as its id:
    this list is the one the *"Why"* line quotes, and a raw id there reads as a bug in the
    sentence rather than as a gap in the content.
    """
    return tuple(
        UnblockedCapability(
            capability_id=capability_id, name=content.capabilities[capability_id].name
        )
        for capability_id in capability_ids
        if capability_id in content.capabilities
    )


def granted_facts(grants: Requirement) -> frozenset[tuple[str, str]]:
    """The ``(type, key)`` pairs a ``grants_facts`` tree makes true.

    Half of :func:`gate_progress`'s pre-filter. Deliberately coarse — a level is reduced to
    its skill name, so *"grants Magic 94"* and *"needs Magic 50"* both read as
    ``("skill", "magic")``. The filter only has to be **safe**, never exact: it decides
    which gates are worth evaluating properly, and the evaluation is what decides the answer.

    Two pairs are synthetic, because two leaf types are moved by facts that do not name them:
    a skill grant can raise a combat level, and a quest grant always raises quest points.
    Omitting either would make the filter unsafe in the one direction that matters, silently
    dropping a real consequence rather than merely doing extra work.
    """
    facts: set[tuple[str, str]] = set()
    for leaf in iter_leaves(grants):
        match leaf:
            case SkillLeaf():
                facts.add(("skill", leaf.skill))
                facts.add(("combat_level", ""))
            case UnlockLeaf() | MilestoneLeaf():
                facts.add((leaf.type, leaf.key))
            case QuestLeaf():
                facts.add(("quest", leaf.quest_id))
                facts.add(("quest_points", ""))
            case ItemLeaf():
                facts.add(("item", leaf.item_id))
    return frozenset(facts)


def gate_facts(requirement: Requirement, content: Content) -> frozenset[tuple[str, str]]:
    """The ``(type, key)`` pairs a gate's satisfaction could depend on.

    The other half of the pre-filter, and the half with a subtlety: a ``capability:`` leaf
    names no fact of its own, so the walk has to descend into that capability's own
    ``requires`` and keep descending. A gate reading ``capability: ice_barrage_nh`` really
    depends on Magic 94, Ancient Magicks and Desert Treasure I, and a filter that stopped at
    the leaf would decide those facts could not affect it.

    ``seen`` guards the descent. §10.7 validates the capability graph as acyclic, so a cycle
    here means the corpus was never validated — and recursing forever would be a worse way to
    report that than quietly terminating.
    """
    facts: set[tuple[str, str]] = set()
    seen: set[str] = set()

    def walk(node: Requirement) -> None:
        for leaf in iter_leaves(node):
            match leaf:
                case SkillLeaf():
                    facts.add(("skill", leaf.skill))
                case UnlockLeaf() | MilestoneLeaf():
                    facts.add((leaf.type, leaf.key))
                case QuestLeaf():
                    facts.add(("quest", leaf.quest_id))
                case ItemLeaf():
                    facts.add(("item", leaf.item_id))
                case CombatLevelLeaf():
                    facts.add(("combat_level", ""))
                case QuestPointsLeaf():
                    facts.add(("quest_points", ""))
                case CapabilityLeaf():
                    if leaf.capability_id in seen:
                        continue
                    seen.add(leaf.capability_id)
                    capability = content.capabilities.get(leaf.capability_id)
                    if capability is not None and capability.requires is not None:
                        walk(capability.requires)

    walk(requirement)
    return frozenset(facts)


def gate_progress(
    candidate: Candidate,
    others: Iterable[Candidate],
    content: Content,
    outstanding_gate: OutstandingGate,
    *,
    limit: int = _GATE_LIMIT,
) -> tuple[GateProgress, ...]:
    """Which other candidates this one's facts unblock or move closer to.

    A candidate whose gate is already clear is skipped: nothing was unblocked by making true
    something that was not standing in the way. So is one whose outstanding count is
    unchanged, which is the common case and the reason the list stays short.

    Ordered by ``(remaining_after, -cleared, candidate_id)`` — what this most nearly unblocks
    first, then what it clears most of, then the id. **Never by name**, so a content rename
    cannot reorder a card.
    """
    grants = candidate.grants_facts
    if grants is None:
        return ()

    granted = granted_facts(grants)
    progress: list[GateProgress] = []
    for other in others:
        if other.id == candidate.id:
            continue
        if other.requires is None:
            continue
        if not (granted & gate_facts(other.requires, content)):
            # Nothing this grant provides appears anywhere in that gate, so its outstanding
            # count cannot move and the counterfactual need never be evaluated. Skipping is
            # what keeps the pass proportional to the corpus's *connectivity* rather than to
            # its size: without it, explaining a dozen entries means re-evaluating all 365
            # gates a dozen times to discover that almost none of them changed.
            continue
        before = outstanding_gate(other, None)
        if not before:
            continue  # not gated, or gated by nothing outstanding — nothing to unblock
        after = outstanding_gate(other, grants)
        if len(after) >= len(before):
            continue
        progress.append(
            GateProgress(
                candidate_id=other.id,
                name=other.name,
                remaining_before=len(before),
                remaining_after=len(after),
                satisfied=tuple(leaf for leaf in before if leaf not in after),
            )
        )

    progress.sort(
        key=lambda entry: (
            entry.remaining_after,
            -(entry.remaining_before - entry.remaining_after),
            entry.candidate_id,
        )
    )
    return tuple(progress[:limit])


def goal_progress(
    candidate: Candidate,
    content: Content,
    weights: Mapping[str, float],
    outstanding_capability_gate: OutstandingCapabilityGate,
    *,
    limit: int = _GOAL_LIMIT,
) -> tuple[GoalProgress, ...]:
    """Which capabilities' own requirements this candidate's facts directly reduce.

    Every declared capability is asked, not only the weighted ones, so an entry serving a
    goal outside the active roadmaps is reported and flagged rather than silently dropped.
    The ordering is what keeps that honest: on-roadmap goals come first, so a flagged one can
    only appear where there was no unflagged one to show.

    A capability already fully satisfied is skipped for :func:`gate_progress`'s reason —
    nothing was advanced by satisfying what was not outstanding.
    """
    grants = candidate.grants_facts
    if grants is None:
        return ()

    granted = granted_facts(grants)
    progress: list[GoalProgress] = []
    for capability_id, capability in content.capabilities.items():
        if capability.requires is None:
            continue
        if not (granted & gate_facts(capability.requires, content)):
            continue  # see :func:`gate_progress` — the same safe pre-filter, same reason
        before = outstanding_capability_gate(capability_id, None)
        if not before:
            continue
        after = outstanding_capability_gate(capability_id, grants)
        if len(after) >= len(before):
            continue
        weight = weights.get(capability_id, 0.0)
        progress.append(
            GoalProgress(
                capability_id=capability_id,
                name=capability.name,
                weight=weight,
                remaining_before=len(before),
                remaining_after=len(after),
                on_roadmap=weight > 0.0,
                satisfied=tuple(leaf for leaf in before if leaf not in after),
            )
        )

    progress.sort(key=_goal_order)
    return tuple(progress[:limit])


def goal_links(
    progress: Sequence[GateProgress],
    content: Content,
    weights: Mapping[str, float],
    *,
    limit: int = _GOAL_LIMIT,
) -> tuple[GoalLink, ...]:
    """The one-hop indirect goal: what the candidates in ``progress`` are themselves for.

    This is the sentence *"Train Slayer to 10"* needed all along. The band advances nothing
    of its own, but it gates Desert Treasure I, and Desert Treasure I's ``advances`` map
    names ``ice_barrage_nh``.

    One hop, and the cap applies to the result rather than to the walk: see :class:`GoalLink`
    on why a transitive closure would say ``raid_ready`` about everything.
    """
    links: list[GoalLink] = []
    seen: set[str] = set()
    for entry in progress:
        via = content.candidates.get(entry.candidate_id)
        if via is None:
            continue
        advances = via.advances
        for capability_id in sorted(advances, key=lambda key: (-advances[key], key)):
            capability = content.capabilities.get(capability_id)
            if capability is None or capability_id in seen:
                continue
            seen.add(capability_id)
            weight = weights.get(capability_id, 0.0)
            links.append(
                GoalLink(
                    capability_id=capability_id,
                    name=capability.name,
                    weight=weight,
                    on_roadmap=weight > 0.0,
                    via_candidate_id=entry.candidate_id,
                    via_name=entry.name,
                    contribution=advances[capability_id],
                )
            )

    # Not :func:`_goal_order`: ``contribution`` has to outrank the id, or a unique id would
    # decide every comparison before the editorial weight was ever consulted.
    links.sort(
        key=lambda link: (
            not link.on_roadmap,
            -link.weight,
            -link.contribution,
            link.capability_id,
        )
    )
    return tuple(links[:limit])


def acceleration(winner: MethodUnlockWinner | None, content: Content) -> tuple[Acceleration, ...]:
    """Name the grind A30's argmax landed on, if there was one.

    A tuple of at most one, because ``method_unlock`` is a maximum and never a sum — the
    shape says so at the type level, where a bare optional would leave the door open for a
    later edit to start listing every grind a candidate shortens and quietly turn breadth
    into a substitute for depth.
    """
    if winner is None:
        return ()
    other = content.candidates.get(winner.other_id)
    if other is None:
        return ()
    return (
        Acceleration(
            candidate_id=winner.other_id,
            name=other.name,
            hours_before=winner.hours_before,
            hours_after=winner.hours_after,
        ),
    )


def consequences_for(
    candidate: Candidate,
    *,
    content: Content,
    weights: Mapping[str, float],
    unlocked_capability_ids: Sequence[str],
    accelerated: MethodUnlockWinner | None,
    others: Iterable[Candidate],
    outstanding_gate: OutstandingGate,
    outstanding_capability_gate: OutstandingCapabilityGate,
) -> Consequences:
    """Everything §9.10 can say about one candidate, assembled.

    ``others`` must be **the same pool ``method_unlock`` measured against** — every candidate
    still open, blocked ones included. Handing this a narrower set is how *"unblocks Y"* and
    *"speeds up Y"* come to disagree about which candidates exist.

    ``unlocked_capability_ids`` and ``accelerated`` are passed in rather than recomputed
    because the engine already has them: they are the identities
    :func:`~tracker.domain.candidates.unlock_flips` and
    :func:`~tracker.domain.candidates.method_unlock_detail` retained during scoring, and
    asking for them again would run A30's O(n²) pass a second time.
    """
    gates = gate_progress(candidate, others, content, outstanding_gate)
    goals = goal_progress(candidate, content, weights, outstanding_capability_gate)
    return Consequences(
        unblocks_capabilities=unblocked_capabilities(unlocked_capability_ids, content),
        gate_progress=gates,
        goal_progress=goals,
        speeds_up=acceleration(accelerated, content),
        # Only when nothing direct was found. A candidate that measurably dents a goal has no
        # need of an inference about one, and showing both would rank a guess beside a
        # measurement as though they were the same kind of claim.
        goal_links=() if goals else goal_links(gates, content, weights),
    )


def _goal_order(entry: GoalProgress) -> tuple[bool, float, str]:
    """On-roadmap first, then by blended weight, then by id.

    ``not on_roadmap`` sorts ``False`` before ``True``, which is what puts a goal the player
    actually chose above one merely reachable from here. Weight breaks the tie within each
    group and the id breaks it after that, so the order is total and reproducible; **name is
    never a key**, so renaming a capability cannot reorder a card.
    """
    return (not entry.on_roadmap, -entry.weight, entry.capability_id)
