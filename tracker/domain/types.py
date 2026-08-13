"""The engine's input and output types (§16.1).

§16.1 requires the recommendation engine to be a pure function over a state object.
These types are that object and its results. They are shared by the database projection
(§3b), the progression engine (§4) and the UI (§15), and belong to none of them — which
is why ``tracker/domain/`` exists as its own package (§14).

Everything here is frozen. Nothing here imports the content schema: ``Content`` and the
requirement AST live in ``tracker/content/`` because they are built from Pydantic models
that would otherwise make ``tracker.domain`` and ``tracker.content`` mutually recursive.
The engine depends on both; neither depends on the other.

**Three-valued logic is the point of this module.** ``Tri`` exists so that "we have not
observed this" is representable, and ``Tri.__bool__`` raises so that the idiom §9.1
explicitly warns about — ``if not satisfied`` — fails loudly instead of quietly
collapsing ``unknown`` into ``False`` and reintroducing the bug D8 removed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum
from typing import NoReturn

# ---------------------------------------------------------------------------
# Three-valued logic
# ---------------------------------------------------------------------------


class Tri(Enum):
    """A three-valued truth value, deliberately *not* a nullable boolean.

    A nullable boolean carries the same three states, but it invites ``if value:`` —
    which treats "no" and "never observed" alike. A distinct enum whose truthiness
    raises makes that collapse impossible to write by accident. Step 2a's exit criteria
    grep ``tracker/domain/`` for the nullable-boolean spellings; they must not appear,
    not even in prose.
    """

    SATISFIED = "satisfied"
    UNSATISFIED = "unsatisfied"
    UNKNOWN = "unknown"

    def __bool__(self) -> NoReturn:
        raise TypeError(
            f"{self!r} has no truth value. §9.1: 'Implementations that reach for "
            "`if not satisfied` collapse unknown into false and reintroduce exactly the "
            "bug D8 removes.' Compare explicitly against all three members instead — "
            "e.g. `if result is Tri.SATISFIED:`."
        )

    @classmethod
    def from_bool(cls, value: bool) -> Tri:
        """Lift a genuine boolean. Only valid where absence of evidence is impossible."""
        return cls.SATISFIED if value else cls.UNSATISFIED


class Status(Enum):
    """Objective capability status (§6.9). Never influenced by freshness (G2)."""

    UNLOCKED = "unlocked"
    LOCKED = "locked"
    UNKNOWN = "unknown"


class Confidence(IntEnum):
    """Ordered confidence (§6.9).

    An ``IntEnum`` because ``recommended_now`` compares against a declared threshold:
    ``readiness_confidence >= capability.recommended_readiness``. String comparison
    would order these alphabetically — ``high < low < medium`` — which is silently wrong.
    """

    LOW = 0
    MEDIUM = 1
    HIGH = 2


class Freshness(Enum):
    """Practice freshness for ``class: execution`` milestones only (§6.6)."""

    CURRENT = "current"
    STALE = "stale"
    VERY_STALE = "very_stale"


# ---------------------------------------------------------------------------
# Fact-level enums (§6)
# ---------------------------------------------------------------------------


class UnlockState(Enum):
    """§6.3. Four states, and ``available`` is **not** a positive one.

    ``available`` means purchasable or attainable but not yet held — Rigour visible in
    the Prayer book is not Rigour unlocked. §9.1 resolves it to ``unsatisfied``. The word
    reads as positive and is the single most likely place for an implementation to go
    wrong, which is why it is called out both here and at the leaf resolver.
    """

    UNLOCKED = "unlocked"
    AVAILABLE = "available"
    LOCKED = "locked"
    UNKNOWN = "unknown"


class QuestStatus(Enum):
    """§6.4. ``in_progress`` is ``unsatisfied``, not partially satisfied (§9.1).

    The requirement grammar has no partial-credit leaf; progress is expressed through
    ``unlock_fraction`` at the capability level, never by softening a leaf.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    UNKNOWN = "unknown"


class AccountType(Enum):
    """§4.2's account mode. Not a skill and not an unlock — a property that *removes* options.

    An ironman cannot buy a Voidwaker at any price, so an ``acquisition`` candidate is not
    merely expensive for them, it is impossible. That is why this is its own field rather
    than an ``unlock:`` key: §6.3's unlock space is plugin-sourced facts about what an
    account has *gained*, and account mode is a constraint it was created under.
    """

    MAIN = "main"
    IRONMAN = "ironman"
    HARDCORE = "hardcore"
    ULTIMATE = "ultimate"
    GROUP = "group"


class Source(Enum):
    """Observation provenance (§6). Precedence: runelite > wise_old_man > hiscores."""

    RUNELITE = "runelite"
    WISE_OLD_MAN = "wise_old_man"
    HISCORES = "hiscores"
    OSRS_WIKI_PRICES = "osrs_wiki_prices"
    MANUAL = "manual"
    DERIVED = "derived"


#: Source precedence for §7.4 conflict resolution, highest first.
SOURCE_PRECEDENCE: tuple[Source, ...] = (
    Source.RUNELITE,
    Source.WISE_OLD_MAN,
    Source.HISCORES,
)


class PriceSelectionPolicy(Enum):
    """§6.8, §8.3 — the rule used to pick a number out of the price cascade.

    ``ACQUISITION_COST`` is the only policy v1 defines: recent high -> recent low ->
    cached -> static hint -> unknown (§8.3), conservative because a recommendation to
    *buy* something should not understate its cost.
    """

    ACQUISITION_COST = "acquisition_cost"


class PriceSourceLayer(Enum):
    """§6.8, §8.3 — which layer of the price cascade supplied ``selected_price_gp``.

    Shares the word *source* with the provenance enum :class:`Source` above (``runelite
    | wise_old_man | ...``) and is a completely different axis, which is why it carries a
    distinct Python name even though §6.8's own column is also called ``source``.

    Both this and :class:`PriceSelectionPolicy` live in the domain package rather than
    with the persistence enums because they are **outputs of the §8.3 cascade**, which
    :mod:`tracker.estimation.prices` computes — §16.1 forbids that module from importing
    ``tracker.db``, and a vocabulary the estimator cannot name is a vocabulary the
    estimator cannot return. ``tracker.db.enums`` re-exports both; the string values are
    what the columns store and must not change.
    """

    LIVE = "live"
    CACHED = "cached"
    STATIC_HINT = "static_hint"
    UNKNOWN = "unknown"


#: Coins. The one numeric item id the domain names, because "how much money is there" is
#: not answerable without it and it is a game constant rather than authored content —
#: an ``Item`` row for coins would imply the corpus could rename or reprice them.
COINS_ITEM_ID = 995


class Container(Enum):
    """Where an item was observed (§6.5)."""

    BANK = "bank"
    INVENTORY = "inventory"
    EQUIPMENT = "equipment"


class PracticeDomain(Enum):
    """The six practice domains of §7.6. Adding a seventh is a code change (§10.8)."""

    LMS = "lms"
    NH_COMBAT = "nh_combat"
    WILDERNESS_PVP = "wilderness_pvp"
    VENGEANCE_PVP = "vengeance_pvp"
    ANTI_PKING = "anti_pking"
    GENERAL_PVP = "general_pvp"


class MilestoneKind(Enum):
    """How a milestone is *measured* (§6.6). Orthogonal to ``MilestoneClass``."""

    DERIVED = "derived"
    SELF_ATTESTED = "self_attested"


class MilestoneClass(Enum):
    """How a milestone *ages* (§6.6). Only ``EXECUTION`` decays."""

    KNOWLEDGE = "knowledge"
    EXECUTION = "execution"
    THRESHOLD = "threshold"


class GpSensitivity(Enum):
    """Sets κ in ``cost_decay = exp(−gp / κ)`` (§9.6)."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class CandidateKind(Enum):
    """§10.6. ``PRACTICE`` is what synthesized refreshers carry."""

    SKILL_TRAINING = "skill_training"
    ACQUISITION = "acquisition"
    QUEST = "quest"
    UNLOCK = "unlock"
    PRACTICE = "practice"


# ---------------------------------------------------------------------------
# PlayerState — the engine's sole view of the account
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SkillState:
    """§6.2. ``xp`` is nullable and ``None`` means unranked — never ``0`` (G5)."""

    level: int
    xp: int | None
    source: Source
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ItemObservation:
    """§6.5. An item seen in at least one container.

    Ownership is *not* recorded as a boolean. The absence of an ``ItemObservation`` is
    only meaningful when read together with ``PlayerState.container_scans``.
    """

    item_id: int
    quantity: int
    containers: frozenset[Container]
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class MilestoneState:
    """§6.6 projected into the engine's view.

    ``attested`` is ``Tri``, not ``bool``, because ``attested_at IS NULL`` — never
    prompted — is a different fact from a milestone the user was asked about and
    declined (§4.5, A7). ``achieved: bool`` alone cannot express it, and the difference
    decides whether the leaf resolves ``unknown`` or ``unsatisfied``.

    ``kind`` is carried because §9.1's unknown rule is specifically *"self-attested with
    ``attested_at IS NULL``"* — a derived milestone is never unknown for want of a prompt.
    """

    key: str
    achieved: bool
    attested: Tri
    kind: MilestoneKind
    class_: MilestoneClass
    value: int | None = None
    last_practiced_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class PlayerState:
    """The complete input to the progression and recommendation engines (§16.1).

    Produced only by ``tracker.db.projection.build_player_state``. The engines never
    query the database; this object is the entire bridge.
    """

    player_id: int
    skills: Mapping[str, SkillState] = field(default_factory=dict)
    unlocks: Mapping[str, UnlockState] = field(default_factory=dict)
    quests: Mapping[str, QuestStatus] = field(default_factory=dict)
    #: Keyed by *numeric* OSRS item id, matching ``Item.item_id`` in content (§10.5).
    observed_items: Mapping[int, ItemObservation] = field(default_factory=dict)
    #: When each container was last seen *in full* (§6.5). Absence means never scanned.
    container_scans: Mapping[Container, datetime] = field(default_factory=dict)
    milestones: Mapping[str, MilestoneState] = field(default_factory=dict)
    combat_level: int | None = None
    quest_points: int | None = None
    account_type: AccountType | None = None
    """``None`` means nobody has said, which is **not** "main" (§4.5).

    Defaulting to main would assert a fact we do not have, and the fact it would assert is
    exactly the one that makes the app recommend a Voidwaker to an ironman. ``None``
    evaluates ``unknown``, and an unknown gate does not block (§10.6, G3) — so a main who
    never opened Settings loses nothing, while an ironman who answers once stops being told
    to buy things."""
    members: bool | None = None
    """``None`` means nobody has said — same rule as :attr:`account_type`."""
    gp_sensitivity: GpSensitivity = GpSensitivity.NORMAL
    #: ``None`` means the account has never been synced — makes ``combat_level`` and
    #: ``quest_points`` leaves resolve ``unknown`` rather than ``unsatisfied`` (A6).
    last_sync_at: datetime | None = None

    @property
    def liquid_gp(self) -> int | None:
        """Coins the account is *known* to hold, or ``None`` when nobody has looked (§6.5).

        Derived rather than stored, so it cannot drift from the observations it summarises.

        **Three states, and the middle one is the whole reason this is not an ``int``:**

        * no container has ever been scanned ⇒ ``None``. Not ``0``: an unscanned bank is
          not an empty one, and G3 forbids the collapse.
        * a container was scanned and held no coins ⇒ ``0``. That *is* a fact — someone
          looked, and there were none.
        * coins observed ⇒ their quantity.

        Coins are item 995 and stack, so the observation's quantity is the amount; §6.5
        already merged containers, so this does not re-add bank and inventory separately.

        **Display only.** No scoring factor reads this. Making affordability a §9.4 factor
        means a seventh exponent in ``ScoringWeights``, which §16.3 step 5 requires be
        re-tuned against the golden corpus with a human reviewing every disagreement —
        that is its own step, not a side effect of being able to see the number.
        """
        if not self.container_scans:
            return None
        observation = self.observed_items.get(COINS_ITEM_ID)
        return observation.quantity if observation is not None else 0


# ---------------------------------------------------------------------------
# Roadmap selection (§4.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadmapSelection:
    """Active roadmaps and their selection weights (§4.3).

    Weights are normalized to sum to 1 **at read time**, not at write time, so removing
    a roadmap cannot silently rescale the others' stored values (§6.12).
    """

    weights: Mapping[str, float] = field(default_factory=dict)

    def normalized(self) -> Mapping[str, float]:
        """Selection weights scaled to sum to 1. An empty selection stays empty."""
        total = sum(self.weights.values())
        if total <= 0:
            return {}
        return {roadmap_id: weight / total for roadmap_id, weight in self.weights.items()}


# ---------------------------------------------------------------------------
# Engine outputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeafRef:
    """A reference to one requirement leaf, for ``blockers`` and ``unknowns`` (§6.9).

    Content-free by design: the requirement AST lives in ``tracker/content/``, and
    ``CapabilityState.blockers`` is persisted as JSON, so this carries the identity and
    a rendered description rather than the AST node itself.
    """

    leaf_type: str
    key: str
    description: str
    target: int | None = None


@dataclass(frozen=True, slots=True)
class CapabilityView:
    """The three status layers of §4.4, computed in strict order (§9.2).

    ``readiness_confidence`` is ``None`` unless ``status is Status.UNLOCKED`` — unknown
    evidence stops at ``status`` and never flows down (G3). The pair *"Unlocked: yes /
    Confidence: low because ownership is unknown"* must be unrepresentable, not merely
    unwritten.
    """

    capability_id: str
    status: Status
    unlock_fraction: float
    blockers: tuple[LeafRef, ...] = ()
    unknowns: tuple[LeafRef, ...] = ()
    readiness_confidence: Confidence | None = None
    warnings: tuple[str, ...] = ()
    recommended_now: bool = False
    recommended_now_reason: str | None = None


@dataclass(frozen=True, slots=True)
class BandEstimate:
    """One level band of a skill-training estimate (§8.2)."""

    from_level: int
    to_level: int
    method_id: str | None
    hours: float
    gp: int
    #: True when no authored method was available and a conservative default was used.
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class Estimate:
    """Time and GP for a candidate (§8).

    ``confidence`` is the **minimum** of price confidence and training-method confidence
    (§8.4): an estimate is only as good as its weakest input.
    """

    hours: float | None
    gp: int | None
    confidence: Confidence
    bands: tuple[BandEstimate, ...] = ()
    #: Which layer of the §8.3 cascade supplied the price, for UI traceability.
    price_selection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class FactorContribution:
    """One factor's contribution to a score (§9.5).

    Both halves are kept because the "Why" line is read off ``log_contribution``
    (§9.10) while the UI's factor breakdown shows ``value``. Generating the reason from
    the same numbers that produced the ranking is what stops the prose drifting from the
    ordering.
    """

    name: str
    value: float
    weight: float
    log_contribution: float


@dataclass(frozen=True, slots=True)
class Recommendation:
    """One ranked entry (§6.10, §9.10)."""

    candidate_id: str
    name: str
    kind: CandidateKind
    score: float
    factors: Mapping[str, FactorContribution] = field(default_factory=dict)
    reason: str = ""
    estimate: Estimate | None = None
    blocked: bool = False
    unknown_gate: bool = False
    """``requires`` evaluated ``unknown`` — *"sync this"*, not *"do this"* (§10.6, G3)."""
    blockers: tuple[LeafRef, ...] = ()
    """Why a blocked entry is blocked — the ``unsatisfied`` leaves of its own gate (§15).

    A *candidate's* gate is not a capability's requirement tree, which is what the
    original design assumed when it left this off: ``complete_lunar_diplomacy`` is blocked
    by four quest leaves that appear in no capability at all, so "the capability views
    already carry the latter" was true only while every blocked candidate happened to be
    gated on something a capability also named.

    Empty for anything that is not blocked. Unknown leaves are deliberately **not** here:
    a gate evaluating ``unknown`` is not blocked (G3), so by construction every entry that
    reaches this field failed on evidence rather than for want of it — one list, one verb
    (§15)."""
    practice_members: tuple[str, ...] = ()
    """Milestone keys a ``kind: practice`` entry would refresh (§9.8's bullet list).

    Computed rather than authored: the group's *stale* members on this run, not the
    template's whole membership. §9.8's two completion actions — *"mark session
    complete"* and *"review individual skills"* — both operate on exactly this set, so it
    has to reach the UI rather than being recomputed there against a different rule."""


@dataclass(frozen=True, slots=True)
class IncumbentRecommendation:
    """The previous run's top entry, for §9.9's hysteresis.

    §9.9 and §16.1 both write this parameter as ``RecommendationSnapshot | None``, which
    is a **database** row (§6.10) — and §16.1's whole purpose is that ``recommend()``
    never reaches the database. The two reconcile because hysteresis needs exactly two of
    that row's fields: which candidate held the top slot, and what it scored. Narrowing to
    those here keeps the signature honest about the dependency and leaves the
    snapshot-to-incumbent translation with Step 9's pipeline, where the session lives.

    Nothing else from the snapshot belongs here. Any further field would be a fact the
    engine could branch on without the caller realising it had supplied one.

    **The recorded score is deliberately absent.** §9.9's rule reads
    ``challenger.score > 1.10 × incumbent.score``, and both sides are scores *in the
    current ranking*: the snapshot only says which candidate held the top slot. Comparing
    today's challenger against yesterday's stored number would measure the two under
    different prices and possibly a different ``scoring_profile_version``, so an incumbent
    could be displaced — or defended — by drift in its own inputs rather than by any
    challenger being better.
    """

    candidate_id: str
