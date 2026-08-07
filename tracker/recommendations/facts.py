"""Counterfactual fact application — *"what if this candidate were done?"* (§10.6).

``leverage`` is defined as the *"normalized count of capabilities whose ``status`` would
flip to ``unlocked`` if ``grants_facts`` were applied"* (§10.6). That question cannot be
answered by reading facts; it needs a hypothetical :class:`PlayerState` in which the
candidate's stated grants are true, run back through the same progression engine that
produced the real one. This module builds that state, and :class:`LeverageOracle` asks the
question often enough to be worth memoizing.

**The hypothetical never escapes.** :func:`apply_facts` returns a new frozen
:class:`PlayerState`; nothing here mutates the real one and no caller persists the result.
A counterfactual that leaked into the projection would be indistinguishable from an
observation, which is the §4.5 error in its most damaging form.

**Flip, not state.** A capability already ``unlocked`` has not been unlocked *by* this
candidate and must not be counted — §10.6 says the status would *"become"* unlocked.
Otherwise every candidate would inherit credit for everything the player already has,
which is the same number for all of them and therefore no signal at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

from tracker.content.loader import Content
from tracker.content.requirements import (
    AllOf,
    AnyOf,
    AtLeast,
    CapabilityLeaf,
    CombatLevelLeaf,
    ItemLeaf,
    MilestoneLeaf,
    Not,
    QuestLeaf,
    QuestPointsLeaf,
    Requirement,
    SkillLeaf,
    UnlockLeaf,
)
from tracker.domain.types import (
    Container,
    ItemObservation,
    MilestoneClass,
    MilestoneKind,
    MilestoneState,
    PlayerState,
    QuestStatus,
    SkillState,
    Source,
    Status,
    Tri,
    UnlockState,
)
from tracker.estimation.xp_table import xp_for_level
from tracker.progression.engine import compute_capability_states

#: Where a granted item is imagined to appear. Bank rather than inventory or equipment
#: because acquisition is what ``grants_facts`` models: you buy a Voidwaker and it lands
#: in your bank. The choice is nearly inert — an ``item:`` leaf never names a container
#: (§9.1) — and is made explicit so the hypothetical state stays coherent.
_GRANTED_CONTAINER = Container.BANK

#: Stands in for ``observed_at`` when the account has never synced. Every leaf that could
#: read it already resolves ``unknown`` from ``last_sync_at IS NULL`` (A6), so this exists
#: to make the dataclass constructible, not so anything measures against it.
_NEVER_SYNCED = datetime(1970, 1, 1, tzinfo=UTC)


def apply_facts(state: PlayerState, grants: Requirement, content: Content) -> PlayerState:
    """The player's facts as they would be if ``grants`` were true (§10.6).

    Every applied fact is tagged :attr:`Source.DERIVED` — it was inferred, never observed —
    so a hypothetical state that somehow reached a writer would be identifiable as one.
    ``observed_at`` copies the real state's ``last_sync_at``: inventing a later timestamp
    would make a counterfactual look *fresher* than the observations it was derived from,
    and freshness feeds ``readiness_confidence`` (§6.9).

    Only facts are applied. A ``capability:`` leaf is not a fact — it is a *conclusion*
    about other facts — so granting one is refused rather than faked. Writing a capability
    straight into the state would let a candidate claim an unlock it never earned, and
    :class:`PlayerState` has nowhere to record such a claim in any case. A candidate that
    genuinely confers a capability says so by granting the facts that capability requires.
    """
    builder = _Builder(state, content)
    builder.apply(grants)
    return builder.build()


class _Builder:
    """Accumulates grants into copies of the mappings :class:`PlayerState` holds.

    A class rather than a recursive pure function because the eight leaf kinds write into
    six different mappings, and threading six accumulators through a fold would bury the
    one thing worth reading here: which leaf types are facts and which are not.
    """

    def __init__(self, state: PlayerState, content: Content) -> None:
        self._state = state
        self._content = content
        self._observed_at = state.last_sync_at or _NEVER_SYNCED
        self._skills = dict(state.skills)
        self._unlocks = dict(state.unlocks)
        self._quests = dict(state.quests)
        self._items = dict(state.observed_items)
        self._scans = dict(state.container_scans)
        self._milestones = dict(state.milestones)
        self._combat_level = state.combat_level
        self._quest_points = state.quest_points

    def apply(self, requirement: Requirement) -> None:
        """Walk one tree, applying every fact it asserts.

        The combinator arms fix what *"these facts become true"* means for a tree that is
        not a plain conjunction:

        * ``all_of`` — every child, which is the only shape the corpus authors.
        * ``any_of`` / ``at_least`` — the **first** ``n`` children. The candidate does not
          say which branch it takes, and satisfying all of them would credit it with more
          than it grants. Arbitrary but deterministic, and it errs low.
        * ``not`` — nothing. *"You will not have X"* is not something completing a
          candidate brings about, and retracting a fact is a decrement no derived source
          is permitted to make (G4).
        """
        match requirement:
            case AllOf(children=children):
                for child in children:
                    self.apply(child)
            case AnyOf(children=children):
                self.apply(children[0])
            case AtLeast(n=n, of=of):
                for child in of[:n]:
                    self.apply(child)
            case Not():
                pass
            case SkillLeaf(skill=skill, level=level):
                self._grant_skill(skill, level)
            case UnlockLeaf(key=key):
                self._unlocks[key] = UnlockState.UNLOCKED
            case QuestLeaf(quest_id=quest_id):
                self._quests[quest_id] = QuestStatus.COMPLETE
            case ItemLeaf(item_id=item_id):
                self._grant_item(item_id)
            case MilestoneLeaf(key=key):
                self._grant_milestone(key)
            case CombatLevelLeaf(level=level):
                self._combat_level = max(self._combat_level or 0, level)
            case QuestPointsLeaf(points=points):
                self._quest_points = max(self._quest_points or 0, points)
            case CapabilityLeaf():
                pass  # not a fact — see apply_facts' docstring

    def build(self) -> PlayerState:
        return PlayerState(
            player_id=self._state.player_id,
            skills=self._skills,
            unlocks=self._unlocks,
            quests=self._quests,
            observed_items=self._items,
            container_scans=self._scans,
            milestones=self._milestones,
            combat_level=self._combat_level,
            quest_points=self._quest_points,
            gp_sensitivity=self._state.gp_sensitivity,
            last_sync_at=self._state.last_sync_at,
        )

    def _grant_skill(self, skill: str, level: int) -> None:
        """Raise a skill to the granted level, never lower it.

        ``max`` semantics rather than assignment because a grant may name a level the
        player has already passed, and a grant that *reduced* a level would be a decrement
        from a derived source — G4 forbids it outright.

        XP is set from the curve rather than carried across, because the level is what
        every ``skill:`` leaf compares against and a stale XP value beside a raised level
        is an incoherent pair. This is a hypothetical account; its XP is exactly as real as
        its level.
        """
        current = self._skills.get(skill)
        if current is not None and current.level >= level:
            return
        self._skills[skill] = SkillState(
            level=level,
            xp=xp_for_level(level),
            source=Source.DERIVED,
            observed_at=self._observed_at,
        )

    def _grant_item(self, item_key: str) -> None:
        """Put one of an item in the bank, if the corpus gives it a numeric id.

        An item with no ``item_id`` can never appear in an observation (§10.5), so its leaf
        resolves ``unknown`` however much we imagine; granting it would build a state the
        evaluator reads differently from the one this function claims to have built.
        Quantity 1, because ``item:`` leaves test only ``> 0`` (§9.1).
        """
        item = self._content.items.get(item_key)
        if item is None or item.item_id is None:
            return
        existing = self._items.get(item.item_id)
        if existing is not None and existing.quantity > 0:
            return
        self._items[item.item_id] = ItemObservation(
            item_id=item.item_id,
            quantity=1,
            containers=frozenset({_GRANTED_CONTAINER}),
            observed_at=self._observed_at,
        )
        # An item is only *visible* where a scan covers it; without recording the scan the
        # hypothetical bank would hold something nobody has ever looked in.
        self._scans.setdefault(_GRANTED_CONTAINER, self._observed_at)

    def _grant_milestone(self, key: str) -> None:
        """Achieve a milestone, taking ``kind`` and ``class`` from the corpus.

        ``last_practiced_at`` is deliberately **not** set. Achieving an execution milestone
        is not the same as having practiced it recently — that is what a practice event
        records — and inventing one would let a progression candidate manufacture
        freshness, the mirror image of what G6 forbids. The milestone arrives achieved with
        no practice history, exactly as a first attestation does.

        An unauthored key gets ``threshold``/``derived``: the classes that never age, so a
        milestone the corpus does not describe cannot decay a hypothetical readiness.
        """
        authored = self._content.milestones.get(key)
        existing = self._milestones.get(key)
        self._milestones[key] = MilestoneState(
            key=key,
            achieved=True,
            attested=Tri.SATISFIED,
            kind=authored.kind if authored is not None else MilestoneKind.DERIVED,
            class_=authored.class_ if authored is not None else MilestoneClass.THRESHOLD,
            value=existing.value if existing is not None else None,
            last_practiced_at=existing.last_practiced_at if existing is not None else None,
        )


class LeverageOracle:
    """Answers §10.6's flip question for a whole run without recomputing the baseline.

    ``leverage`` needs, per candidate, the status of every capability under that
    candidate's grants. The naive form recomputes the *baseline* too, once per
    (candidate, capability) pair, so eight candidates over five capabilities walk the
    requirement DAG eighty times to learn forty facts. Here the baseline is computed once
    and each candidate's counterfactual once.

    Satisfies :data:`~tracker.domain.candidates.UnlocksAfterFacts` structurally through
    :meth:`__call__`, so it drops into the derivations without either module importing the
    other.

    ``state`` and ``content`` arrive at construction **and** per call, which looks
    redundant and is not: the protocol passes them because a derivation must not assume
    its oracle is pinned to one account, while the memo table is only sound because this
    one is. The per-call pair is checked rather than used, so a mismatch fails loudly
    instead of answering confidently from another account's cache.
    """

    def __init__(self, state: PlayerState, content: Content, now: datetime) -> None:
        self._state = state
        self._content = content
        self._now = now
        self._baseline = _statuses(state, content, now)
        self._counterfactuals: dict[int, dict[str, Status]] = {}

    def __call__(
        self,
        capability_id: str,
        grants: Requirement,
        state: PlayerState,
        content: Content,
    ) -> bool:
        """``True`` iff ``capability_id`` is not unlocked now but would be under ``grants``."""
        if state is not self._state or content is not self._content:
            raise ValueError(
                "LeverageOracle is pinned to the state and content it was built with; its "
                "memo table is only sound for that pair. Build a new oracle instead."
            )
        if self._baseline.get(capability_id) is Status.UNLOCKED:
            return False
        return self._after(grants).get(capability_id) is Status.UNLOCKED

    def baseline_status(self, capability_id: str) -> Status | None:
        """The capability's status as things actually stand.

        Exposed so the engine's other readers — §9.10's *"Unlocks"* line, refresher
        relevance — measure against the same baseline the flip question compares to,
        rather than recomputing one that could disagree at the boundary.
        """
        return self._baseline.get(capability_id)

    def _after(self, grants: Requirement) -> dict[str, Status]:
        """Capability statuses under one grants tree, memoized on the tree's identity.

        Keyed by ``id()`` rather than by value because requirement nodes are frozen models
        loaded once per corpus: the *same object* comes back for every call about a given
        candidate, so identity is both sufficient and free, where hashing the tree would
        walk it — the cost this memo exists to avoid. The trees belong to ``content`` and
        outlive the oracle, so no id can be recycled underneath it.
        """
        key = id(grants)
        cached = self._counterfactuals.get(key)
        if cached is not None:
            return cached
        statuses = _statuses(
            apply_facts(self._state, grants, self._content), self._content, self._now
        )
        self._counterfactuals[key] = statuses
        return statuses


def _statuses(state: PlayerState, content: Content, now: datetime) -> dict[str, Status]:
    """Capability id → objective status, discarding the layers below it.

    Only ``status`` is retained because only ``status`` answers §10.6's question.
    ``readiness_confidence`` in a hypothetical world would be a guess about freshness that
    nothing has observed, and letting it reach ``leverage`` would route practice decay into
    a candidate's ranking through a side door — G2's concern one layer out.
    """
    return {
        capability_id: view.status
        for capability_id, view in compute_capability_states(
            state, content, content.profile, now
        ).items()
    }
