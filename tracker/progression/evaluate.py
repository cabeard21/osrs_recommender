"""Three-valued requirement evaluation (§9.1).

This module answers one question — *does this requirement tree hold for this account?* —
and it answers it in three values, because §6.9's ``status`` is three-valued and the
whole point of D8 is that "we have never looked" is not "no".

What it produces alongside the answer matters as much as the answer. :class:`EvalResult`
carries the leaves that came back ``unsatisfied`` (**blockers** — things to *do*), the
leaves that came back ``unknown`` (**unknowns** — things to *sync*), and the counts
behind ``unlock_fraction``. §6.9 keeps those two lists separate precisely because they
demand different user actions.

Three rules here are easy to get wrong and expensive to get wrong:

* **``unlock: available`` and ``quest: in_progress`` are ``unsatisfied``** (§9.1, A5).
  Both read as positive. "Available" means purchasable, not held; the grammar has no
  partial-credit leaf, so an in-progress quest is progress expressed through
  ``unlock_fraction``, never through a softened leaf.
* **Unknown leaves sit in the denominator of ``unlock_fraction`` and are never credited**
  (§6.9, A3). One satisfied, one unsatisfied and one unknown leaf is ``0.33``.
* **Nothing branches on the truthiness of a ``Tri``.** ``Tri.__bool__`` raises, and every
  dispatch here is an explicit match on all three members (§9.1).

Prose lives in :mod:`tracker.progression.engine`, not here. This module renders each leaf
to a short noun phrase (*"94 Magic"*, *"Voidwaker"*) and stops; the sentences of §6.9 —
reasons and warnings — need :class:`~tracker.domain.types.PlayerState` context this layer
deliberately does not interpret.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

from tracker.accounts.requirements import level_status, quest_status
from tracker.content.loader import Content
from tracker.content.requirements import (
    AccountTypeLeaf,
    AllOf,
    AnyOf,
    AtLeast,
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MembersLeaf,
    MilestoneLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
)
from tracker.domain.types import (
    AccountType,
    Container,
    LeafRef,
    MilestoneKind,
    PlayerState,
    QuestStatus,
    Tri,
    UnlockState,
)
from tracker.progression.tri import and_all, at_least, negate, or_any

#: Every container an ``item:`` leaf could be satisfied from. An item is only *absent*
#: once all three have been scanned — see :meth:`Evaluator._item`.
_ALL_CONTAINERS: frozenset[Container] = frozenset(Container)


class RequirementCycleError(RuntimeError):
    """A ``capability:`` leaf reached a capability already being evaluated.

    :func:`tracker.content.validate.validate_content` proves the capability graph acyclic
    before anything runs, so this is a backstop, not a control-flow tool. It exists
    because the alternative failure mode is a ``RecursionError`` several hundred frames
    deep with no indication of which capabilities formed the loop.
    """


@dataclass(frozen=True, slots=True)
class EvalResult:
    """The outcome of evaluating one requirement tree (§6.9, §9.1).

    ``blockers`` and ``unknowns`` are **pruned at satisfied nodes**: a subtree that came
    back ``satisfied`` blocks nothing, so the losing alternative of a satisfied ``any_of``
    never reaches the user as *"requires Armadyl godsword"* when they are holding a
    Voidwaker. The leaf *counts* are never pruned — §9.1 defines them over every leaf in
    the tree, and A3 is explicit that unknowns stay in the denominator.

    Both lists are deduplicated while preserving first-seen order; the counts are not,
    because a leaf mentioned twice is two leaves to §9.1 but one thing to fix.
    """

    value: Tri
    blockers: tuple[LeafRef, ...] = ()
    unknowns: tuple[LeafRef, ...] = ()
    satisfied_leaves: int = 0
    total_leaves: int = 0
    contributing: tuple[LeafRef, ...] = field(default=())
    """Satisfied leaves that *justify* this result — §6.9's "contributing" leaves.

    Empty unless ``value is Tri.SATISFIED``, and empty below any node that is not itself
    satisfied. §6.9: *"A leaf that played no part in unlocking the capability — a losing
    branch of an ``any_of``, or a leaf under an unsatisfied sibling — never affects
    readiness."* This is the input to ``readiness_confidence``, and it reaches through
    ``capability:`` leaves because §6.9 calls the walk *transitive*.
    """

    @property
    def unlock_fraction(self) -> float:
        """``satisfied_leaves / total_leaves`` (§6.9, A3); ``0.0`` with no leaves.

        A requirement-free capability is unlocked with a fraction of ``0.0``. That reads
        oddly in isolation but is the honest answer: there is no progress to report on a
        capability that asks for nothing, and inventing ``1.0`` would let it dominate any
        ranking that treats the fraction as proximity.
        """
        if self.total_leaves == 0:
            return 0.0
        return self.satisfied_leaves / self.total_leaves


def evaluate(requirement: Requirement, state: PlayerState, content: Content) -> EvalResult:
    """Evaluate one requirement tree (§9.1). Pure — no I/O, no database, no clock.

    Each call gets a fresh memo table. To evaluate many capabilities against the same
    account — what :mod:`tracker.progression.engine` does — construct one
    :class:`Evaluator` and reuse it, so a shared ``capability:`` prerequisite is evaluated
    once rather than once per dependant.
    """
    return Evaluator(state, content).evaluate(requirement)


class Evaluator:
    """A memoized evaluation session over one ``(state, content)`` pair.

    Capability results are cached because the capability graph is a DAG, not a tree
    (§4.1): ``deep_wildy_nh`` requires ``ice_barrage_nh``, and so will everything else
    downstream of barraging. Without the cache the shared prefix is re-walked once per
    dependant; with it, each capability is evaluated exactly once per session.

    An instance is single-account and single-corpus by construction. There is no
    invalidation because both inputs are frozen.
    """

    __slots__ = ("_capabilities", "_content", "_evaluating", "_state")

    def __init__(self, state: PlayerState, content: Content) -> None:
        self._state = state
        self._content = content
        self._capabilities: dict[str, EvalResult] = {}
        self._evaluating: list[str] = []

    # -- entry points -------------------------------------------------------

    def evaluate(self, requirement: Requirement) -> EvalResult:
        """Evaluate an arbitrary requirement tree."""
        return self._node(requirement)

    def capability(self, capability_id: str) -> EvalResult:
        """Evaluate a capability's own ``requires`` tree, memoized.

        A capability that is not declared resolves ``unknown`` rather than raising.
        §10.7 makes a dangling ``capability:`` reference a content error caught at load,
        so this path means the corpus was never validated — and answering *"we cannot
        know"* keeps a validated corpus's evaluation total while still surfacing the
        problem in ``unknowns`` rather than swallowing it.
        """
        cached = self._capabilities.get(capability_id)
        if cached is not None:
            return cached

        if capability_id in self._evaluating:
            cycle = " → ".join([*self._evaluating, capability_id])
            raise RequirementCycleError(
                f"capability requirement cycle: {cycle}. §10.7 validates the capability "
                "graph as acyclic, so this corpus was not validated before evaluation"
            )

        capability = self._content.capabilities.get(capability_id)
        if capability is None:
            return EvalResult(value=Tri.UNKNOWN)

        self._evaluating.append(capability_id)
        try:
            if capability.requires is None:
                result = EvalResult(value=Tri.SATISFIED)
            else:
                result = self._node(capability.requires)
        finally:
            self._evaluating.pop()

        self._capabilities[capability_id] = result
        return result

    # -- dispatch -----------------------------------------------------------

    def _node(self, requirement: Requirement) -> EvalResult:
        match requirement:
            case SkillLeaf():
                return self._skill(requirement)
            case UnlockLeaf():
                return self._unlock(requirement)
            case QuestLeaf():
                return self._quest(requirement)
            case ItemLeaf():
                return self._item(requirement)
            case MilestoneLeaf():
                return self._milestone(requirement)
            case CapabilityLeaf():
                return self._capability_leaf(requirement)
            case CombatLevelLeaf():
                return self._combat_level(requirement)
            case QuestPointsLeaf():
                return self._quest_points(requirement)
            case AccountTypeLeaf():
                return self._account_type(requirement)
            case MembersLeaf():
                return self._members(requirement)
            case AllOf():
                children = self._children(requirement.children)
                return _combine(children, and_all(child.value for child in children))
            case AnyOf():
                children = self._children(requirement.children)
                return _combine(children, or_any(child.value for child in children))
            case AtLeast():
                children = self._children(requirement.of)
                value = at_least((child.value for child in children), requirement.n)
                return _combine(children, value)
            case Not():
                return self._not(requirement)

    def _children(self, children: Iterable[Requirement]) -> tuple[EvalResult, ...]:
        return tuple(self._node(child) for child in children)

    def _not(self, requirement: Not) -> EvalResult:
        """``not`` (§9.1) — value negates, accounting does not.

        Leaf counts pass through because §9.1 counts *"leaves evaluating to satisfied"*
        over *"all leaves"*, and a leaf under a negation still evaluates to whatever it
        evaluates to. Blockers and unknowns are dropped: the thing standing between the
        player and a satisfied ``not`` is the *presence* of something, and ``LeafRef``
        has no vocabulary for "get rid of this". No authored content uses ``not`` today;
        if it ever does, the negated blocker deserves its own representation rather than
        a misleading entry in a list the UI renders as a to-do.
        """
        child = self._node(requirement.child)
        return EvalResult(
            value=negate(child.value),
            satisfied_leaves=child.satisfied_leaves,
            total_leaves=child.total_leaves,
        )

    # -- leaves (§9.1's resolution table, one method per row) ---------------

    def _skill(self, leaf: SkillLeaf) -> EvalResult:
        """satisfied: level ≥ target · unsatisfied: level < target · unknown: no snapshot."""
        skill = self._content.skills.get(leaf.skill)
        name = skill.name if skill is not None else leaf.skill
        ref = LeafRef("skill", leaf.skill, f"{leaf.level} {name}", leaf.level)

        snapshot = self._state.skills.get(leaf.skill)
        return _leaf(ref, level_status(snapshot.level if snapshot else None, leaf.level))

    def _unlock(self, leaf: UnlockLeaf) -> EvalResult:
        """satisfied: ``unlocked`` · unsatisfied: ``available`` or ``locked`` · unknown: ditto.

        ``available`` is the trap (A5). Rigour visible in the Prayer book is not Rigour
        unlocked, and an absent entry is ``unknown`` for the same reason §6.5 makes an
        unscanned container unknown: we have not looked.
        """
        ref = LeafRef("unlock", leaf.key, _titleize(leaf.key))
        state = self._state.unlocks.get(leaf.key, UnlockState.UNKNOWN)
        match state:
            case UnlockState.UNLOCKED:
                return _leaf(ref, Tri.SATISFIED)
            case UnlockState.AVAILABLE | UnlockState.LOCKED:
                return _leaf(ref, Tri.UNSATISFIED)
            case UnlockState.UNKNOWN:
                return _leaf(ref, Tri.UNKNOWN)

    def _quest(self, leaf: QuestLeaf) -> EvalResult:
        """satisfied: ``complete`` · unsatisfied: ``not_started`` **or** ``in_progress``."""
        quest = self._content.quests.get(leaf.quest_id)
        name = quest.name if quest is not None else leaf.quest_id
        ref = LeafRef("quest", leaf.quest_id, name)

        status = self._state.quests.get(leaf.quest_id, QuestStatus.UNKNOWN)
        return _leaf(ref, quest_status(status))

    def _item(self, leaf: ItemLeaf) -> EvalResult:
        """satisfied: seen in a scan · unsatisfied: scanned and absent · unknown: never scanned.

        §6.5 phrases the negative case as *"not seen, but a scan covers the container"* —
        but an ``item:`` leaf never names a container: a Voidwaker counts whether it is
        banked, carried or wielded. "The container" is therefore all three, and the leaf
        only resolves ``unsatisfied`` once **every** container has been scanned at least
        once. With bank and inventory scanned but equipment never seen, *"you don't have
        a Voidwaker"* would be a guess about the one place we have not looked — precisely
        the absence-of-evidence conversion §4.5 forbids.

        An item with no numeric ``item_id`` can never appear in an observation, so it
        resolves ``unknown`` rather than reporting a permanent, unfixable blocker.
        """
        item = self._content.items.get(leaf.item_id)
        name = item.name if item is not None else leaf.item_id
        ref = LeafRef("item", leaf.item_id, name)

        if item is None or item.item_id is None:
            return _leaf(ref, Tri.UNKNOWN)

        observation = self._state.observed_items.get(item.item_id)
        if observation is not None and observation.quantity > 0:
            return _leaf(ref, Tri.SATISFIED)
        if _ALL_CONTAINERS <= self._state.container_scans.keys():
            return _leaf(ref, Tri.UNSATISFIED)
        return _leaf(ref, Tri.UNKNOWN)

    def _milestone(self, leaf: MilestoneLeaf) -> EvalResult:
        """satisfied: ``achieved`` · unsatisfied: attested, not achieved · unknown: never asked.

        Only a *self-attested* milestone can be unknown, and only for want of a prompt
        (§6.6, A7). A derived milestone is measured from counters nobody has to be asked
        about, so a missing row means the counter has not reached the threshold — not
        that we failed to ask.

        ``achieved`` wins outright and is never reconsidered in light of freshness: D8
        forbids the passage of time from revoking it (G1, G2).
        """
        authored = self._content.milestones.get(leaf.key)
        name = authored.name if authored is not None else leaf.key
        ref = LeafRef("milestone", leaf.key, name)

        observed = self._state.milestones.get(leaf.key)
        if observed is None:
            if authored is None or authored.kind is MilestoneKind.SELF_ATTESTED:
                return _leaf(ref, Tri.UNKNOWN)
            return _leaf(ref, Tri.UNSATISFIED)

        if observed.achieved:
            return _leaf(ref, Tri.SATISFIED)
        if observed.kind is MilestoneKind.SELF_ATTESTED and observed.attested is Tri.UNKNOWN:
            return _leaf(ref, Tri.UNKNOWN)
        return _leaf(ref, Tri.UNSATISFIED)

    def _capability_leaf(self, leaf: CapabilityLeaf) -> EvalResult:
        """satisfied/unsatisfied/unknown mirror the child capability's ``status``.

        The child counts as **one** leaf here, not as its own leaf count. ``unlock_fraction``
        is a local measure — §6.9 defines it over *this* capability's requirement leaves —
        and the child publishes its own ``CapabilityView`` with its own fraction and its
        own blockers. Flattening the child's leaves into the parent would silently weight
        capabilities by the size of their prerequisites' trees.

        ``contributing`` is the exception, and deliberately so: §6.9 calls the readiness
        walk *transitive*, so a stale execution milestone three capabilities down still
        lowers readiness up here.
        """
        capability = self._content.capabilities.get(leaf.capability_id)
        name = capability.name if capability is not None else leaf.capability_id
        ref = LeafRef("capability", leaf.capability_id, name)

        child = self.capability(leaf.capability_id)
        result = _leaf(ref, child.value)
        if child.value is Tri.SATISFIED:
            return EvalResult(
                value=result.value,
                satisfied_leaves=result.satisfied_leaves,
                total_leaves=result.total_leaves,
                contributing=_dedupe((ref, *child.contributing)),
            )
        return result

    def _combat_level(self, leaf: CombatLevelLeaf) -> EvalResult:
        """satisfied: ≥ target · unsatisfied: < target · unknown: never synced (A6)."""
        ref = LeafRef("combat_level", "combat_level", f"combat level {leaf.level}", leaf.level)
        if self._state.last_sync_at is None or self._state.combat_level is None:
            return _leaf(ref, Tri.UNKNOWN)
        return _leaf(ref, Tri.from_bool(self._state.combat_level >= leaf.level))

    def _quest_points(self, leaf: QuestPointsLeaf) -> EvalResult:
        """satisfied: ≥ target · unsatisfied: < target · unknown: never synced (A6)."""
        ref = LeafRef("quest_points", "quest_points", f"{leaf.points} quest points", leaf.points)
        if self._state.last_sync_at is None or self._state.quest_points is None:
            return _leaf(ref, Tri.UNKNOWN)
        return _leaf(ref, Tri.from_bool(self._state.quest_points >= leaf.points))

    def _account_type(self, leaf: AccountTypeLeaf) -> EvalResult:
        """satisfied: matches · unsatisfied: differs · unknown: **nobody has said** (§4.5).

        ``unknown`` is not gated on ``last_sync_at`` the way ``combat_level`` is, and the
        difference matters: account mode does not arrive from a sync at all (payload v1 has
        no field for it), so a fully-synced account can still have never been asked. The
        state that resolves this is a Settings answer, which is why §15 puts the control
        there rather than showing a "sync RuneLite" call to action nothing would satisfy.

        An unknown value **does not block** (§10.6, G3) — a main who never opened Settings
        keeps seeing acquisitions, while an ironman who answers once stops being told to buy
        things. Defaulting to ``main`` instead would assert the very fact whose absence is
        the bug.
        """
        ref = LeafRef("account_type", leaf.account_type, f"{leaf.account_type} account")
        if self._state.account_type is None:
            return _leaf(ref, Tri.UNKNOWN)
        return _leaf(ref, Tri.from_bool(self._state.account_type is AccountType(leaf.account_type)))

    def _members(self, leaf: MembersLeaf) -> EvalResult:
        """satisfied: matches · unsatisfied: differs · unknown: nobody has said (§4.5)."""
        wanted = "members" if leaf.members else "free-to-play"
        ref = LeafRef("members", str(leaf.members).lower(), f"{wanted} account")
        if self._state.members is None:
            return _leaf(ref, Tri.UNKNOWN)
        return _leaf(ref, Tri.from_bool(self._state.members is leaf.members))


# ---------------------------------------------------------------------------
# Result assembly
# ---------------------------------------------------------------------------


def _leaf(ref: LeafRef, value: Tri) -> EvalResult:
    """One leaf's result: exactly one leaf counted, filed under the matching list."""
    match value:
        case Tri.SATISFIED:
            return EvalResult(value=value, satisfied_leaves=1, total_leaves=1, contributing=(ref,))
        case Tri.UNSATISFIED:
            return EvalResult(value=value, blockers=(ref,), total_leaves=1)
        case Tri.UNKNOWN:
            return EvalResult(value=value, unknowns=(ref,), total_leaves=1)


def _combine(children: tuple[EvalResult, ...], value: Tri) -> EvalResult:
    """Assemble a combinator's result from its children's, given the §9.1 value.

    The value is computed by :mod:`tracker.progression.tri` and passed in, so the truth
    tables stay in one place and this function only does bookkeeping.
    """
    satisfied_leaves = sum(child.satisfied_leaves for child in children)
    total_leaves = sum(child.total_leaves for child in children)

    if value is Tri.SATISFIED:
        # A satisfied node blocks nothing and needs no further observation, so its
        # children's blockers and unknowns stop here. What survives is the justification.
        return EvalResult(
            value=value,
            satisfied_leaves=satisfied_leaves,
            total_leaves=total_leaves,
            contributing=_dedupe(
                _flatten(child.contributing for child in children if child.value is Tri.SATISFIED)
            ),
        )

    return EvalResult(
        value=value,
        blockers=_dedupe(_flatten(child.blockers for child in children)),
        unknowns=_dedupe(_flatten(child.unknowns for child in children)),
        satisfied_leaves=satisfied_leaves,
        total_leaves=total_leaves,
    )


def _flatten(groups: Iterable[tuple[LeafRef, ...]]) -> Iterator[LeafRef]:
    for group in groups:
        yield from group


def _dedupe(refs: Iterable[LeafRef]) -> tuple[LeafRef, ...]:
    """First-seen order, one entry per distinct leaf.

    Order is the requirement tree's own order, which is the order the author wrote —
    the closest thing the corpus has to a statement of priority.
    """
    return tuple(dict.fromkeys(refs))


def _titleize(key: str) -> str:
    """``ancient_magicks`` → ``Ancient Magicks``.

    Unlock keys are the one referent §10.7 does not check, because §6.3 leaves the key
    space open for the plugin's ``spellbook_*``/``diary_*``/``ca_*`` prefixes (A12).
    With no authored name to look up, the key itself is the only source of prose.
    """
    return key.replace("_", " ").title()
