"""Pydantic v2 models for every authored content type (§10).

§10.7: *"Every content file is parsed into Pydantic v2 models."* The models here own
the rules a single object can check on its own — field presence, types, numeric ranges.
Rules that span objects (referential integrity, uniqueness, acyclicity, κ ordering) live
in :mod:`tracker.content.validate`, because a model cannot see the rest of the corpus.

Requirement trees are parsed by :func:`tracker.content.requirements.parse` in a
``mode="before"`` validator rather than by Pydantic's own union machinery. The YAML form
(``{"all_of": [...]}``) is not the models' own shape, and the §10.2 missing-space trap
needs a diagnostic Pydantic cannot produce.

**Two content types beyond §10.1's directory listing: ``quests/`` and ``skills/``.**
§10.7 requires referential integrity for *"every referenced capability, quest, item,
skill and milestone id"*, but §10.1 lists directories for only three of those five. A
quest id can therefore be referenced and never declared, which is precisely the failure
§10.7 exists to prevent. §10.8 also names a quest as content — *"adding new game content
— a quest, an item, a capability …— never requires a code change"* — so a registry in
code would violate G9. Both are thin: an id and a name.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from tracker.content.requirements import Requirement, RequirementNode
from tracker.content.requirements import parse as parse_requirement
from tracker.domain.types import (
    CandidateKind,
    Confidence,
    Freshness,
    MilestoneClass,
    MilestoneKind,
    PracticeDomain,
)

_READINESS_NAMES: dict[str, Confidence] = {
    "low": Confidence.LOW,
    "medium": Confidence.MEDIUM,
    "high": Confidence.HIGH,
}


class ContentModel(BaseModel):
    """Base for authored content. Frozen, and unknown keys are an error.

    ``extra="forbid"`` is doing real work: a mistyped key in a YAML file would otherwise
    be silently dropped and the object would take a default the author never intended.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


def _requirement_field(field_name: str) -> Any:
    """Build a ``mode="before"`` validator that parses the §10.2 YAML form.

    The file being loaded arrives through Pydantic's validation *context* so the parser
    can name it in a diagnostic; ``RequirementSyntaxError`` is not a ``ValueError``, so
    it propagates out of ``model_validate`` intact rather than being flattened into a
    generic Pydantic message.
    """

    def validate(cls: type[ContentModel], value: Any, info: ValidationInfo) -> Any:
        if value is None or isinstance(value, RequirementNode):
            return value
        context = info.context or {}
        return parse_requirement(
            value,
            file=context.get("file"),
            path=field_name,
            line=context.get("line"),
        )

    return field_validator(field_name, mode="before")(classmethod(validate))


# ---------------------------------------------------------------------------
# Registries — the referents §10.7 checks against
# ---------------------------------------------------------------------------


class Skill(ContentModel):
    """A trainable skill. Referenced by ``skill:`` leaves and by training methods."""

    id: str
    name: str
    is_combat: bool = False


class Quest(ContentModel):
    """A quest. Referenced by ``quest:`` leaves (§9.1)."""

    id: str
    name: str
    quest_points: int = Field(default=0, ge=0)


#: §10.5. The equipment slots the gear ladders are authored against. Not every declared
#: item sits in one — a quest item or a resource has no slot — so the field is optional.
ItemSlot = Literal[
    "weapon",
    "ammunition",
    "head",
    "body",
    "legs",
    "hands",
    "feet",
    "cape",
    "neck",
    "ring",
    "shield",
]

#: Which ladder an item belongs to. A piece that serves two styles is declared once per
#: ladder, each with its own id, rather than as a single row that has to mean both — the rows
#: share the numeric ``item_id`` and differ only in ``id``, ``slot``, ``style`` and ``tier``,
#: which :func:`tracker.content.validate._check_gear_ladders` holds them to.
CombatStyle = Literal["melee", "ranged", "magic"]

#: §10.5's acquisition axis — how a piece reaches the account's hands, as against what it
#: takes to wear it. **Absent is the third state** and means nobody classified it; see
#: :class:`Item` for why that needs no companion flag where ``gate_unknown`` did.
Acquisition = Literal["tradeable", "untradeable"]


class Item(ContentModel):
    """§10.5. ``item_id`` is the numeric in-game id the price API and plugin both use.

    ``slot``, ``style`` and ``tier`` place the item on a gear ladder. They are what let a
    reader be told *"their best melee weapon is a rune scimitar, and the next rung is a
    dragon scimitar"* rather than an alphabetical list of everything they own — an ordering
    the corpus knows and a model would otherwise have to guess. All three go together: an
    item that is not equipment has no rung, and a ``tier`` with no ladder to sit on is
    meaningless, which :func:`tracker.content.validate._check_gear_ladders` rejects rather
    than silently ignores.

    ``variant_item_ids`` is the answer to the failure this file's header comment describes.
    One piece of gear can wear several numeric ids — charged and uncharged, broken and
    locked, imbued from three different sources — and *owning any of them* is owning the
    item. Matching on ``item_id`` alone is how a player with a charged Toxic blowpipe gets
    told to go and buy one. **Ownership tests the union; pricing uses ``item_id`` alone**,
    because only one variant is the one the market quotes.

    ``requires`` and ``gate_unknown`` say what it takes to *wear* the item (§23.2), and
    they are two fields rather than one because there are three answers, not two:

    ===============================  ===========================================
    ``requires`` set                 the corpus knows the gate
    both unset                       the corpus asserts there is **no** gate
    ``gate_unknown`` set             nobody has established the gate
    ===============================  ===========================================

    Collapsing the last two — treating an unauthored item as ungated — is the failure
    §23.4 is built around: it reports a Torva platebody as wearable to an account that
    cannot lift it, and does so with no signal that anything is missing. So the third
    state is explicit, evaluates to :attr:`~tracker.domain.types.Tri.UNKNOWN`, and can
    never be promoted into *"you can wear this"*. Declaring both is a contradiction, and
    :func:`tracker.content.validate._check_item_requirements` rejects it.

    ``acquisition`` and ``acquired_from`` are §10.5's second axis: how the piece reaches the
    account's hands, which is a different question from what it takes to wear it and has a
    different answer. A Fire cape's wear gate is 40 Defence, which most accounts meet long
    before they could survive the Fight Caves, and no amount of gp buys one at all. Without
    this axis §23.4 recommended an Infernal cape to everybody — true, and useless.

    ===============================  ===========================================
    ``tradeable``                    the Grand Exchange carries it
    ``untradeable``                  it must be won from a piece of content
    neither                          nobody has established which
    ===============================  ===========================================

    **Two fields, not three, and the asymmetry with ``gate_unknown`` is deliberate.** That
    pair exists because ``requires=None`` was *already spoken for* — it asserts there is no
    gate — so the third answer had nowhere to live. Nothing is spoken for here: both values
    are positive assertions with their own spellings, which leaves ``None`` free to carry
    *nobody classified this*, in the polarity §4.5 actually asks for. An
    ``acquisition_unknown`` flag would have exactly two legal states and would buy a
    validation rule to forbid the other two, expressing nothing the two values did not.

    ``acquired_from`` is **prose and never an id**, for the reason :class:`MethodDetail`'s
    ``gear`` is: §10.7 checks ids against a registry, and "the Fight Caves" is none of the
    six the corpus keeps. It is also a **noun phrase and never a sentence**, because every
    surface composes it into one — *"untradeable — earned from {acquired_from}"* — and an
    author who writes a sentence sees that break the first time it renders. It is named
    ``acquired_from`` rather than ``source`` because
    :class:`tracker.domain.types.Source` is observation provenance, and a second ``source``
    in the adjacent model would collide with it at exactly the §4.5 machinery this sits
    beside. :func:`tracker.content.validate._check_item_acquisition` rejects it on an item
    that is not ``untradeable``.

    **Not derived from ``price_mode``**, which selects §8.3's cascade and is a pipeline
    setting rather than a fact about the game. Its polarity is backwards — it defaults to
    ``static``, so deriving from it would assert *untradeable* of everything nobody thought
    about — and the two genuinely disagree wherever the worn piece is untradeable while a
    sibling id trades, which is the whole reason ``PRICED_VARIANT`` exists.

    **This gates nothing in §9.** No candidate's requirement tree reads ``requires`` or
    ``acquisition``, and no estimate moves because of either — a wear requirement that fed
    the evaluator would silently reprice every candidate whose ``completion`` names an item,
    which is a ranking change wearing the clothes of a content edit.
    """

    id: str
    name: str
    item_id: int | None = Field(default=None, gt=0)
    variant_item_ids: tuple[int, ...] = ()
    slot: ItemSlot | None = None
    style: CombatStyle | None = None
    tier: int | None = Field(default=None, ge=1)
    requires: Requirement | None = None
    gate_unknown: bool = False
    acquisition: Acquisition | None = None
    acquired_from: str | None = None
    price_mode: Literal["live", "static"] = "static"
    fallback_price_gp: int | None = Field(default=None, ge=0)
    price_staleness_days: int | None = Field(default=None, gt=0)

    _parse_requires = _requirement_field("requires")

    @property
    def owned_item_ids(self) -> frozenset[int]:
        """Every id that means the player has this item. Empty when none was declared."""
        if self.item_id is None:
            return frozenset(self.variant_item_ids)
        return frozenset({self.item_id, *self.variant_item_ids})


# ---------------------------------------------------------------------------
# Capabilities, roadmaps, milestones
# ---------------------------------------------------------------------------


class Capability(ContentModel):
    """§4.1, §10.2. Capabilities compose into a DAG via ``capability:`` leaves.

    ``recommended_readiness`` sets the bar ``recommended_now`` compares against (§6.9)
    and defaults to ``medium``; advanced capabilities declare ``high``.
    """

    id: str
    name: str
    requires: Requirement | None = None
    grants: tuple[str, ...] = ()
    """Capability ids this one confers. §10.7 checks each is declared."""
    pvp_value: float | None = Field(default=None, ge=0.0, le=1.0)
    """An authoring hint only. The §9.4 *scoring* factor of the same name is derived
    from candidates (§10.6) — *"none is authored directly, so no content file can
    assert its own priority."*

    **Read it as "goal value", not literally as "PvP value".** The corpus has carried a
    non-PvP roadmap since the bossing ladder (``content/roadmaps/pvm_ladder.yaml``), whose
    five rung capabilities declare this field like any other. The name is kept because it
    is load-bearing in five places at once — this schema, :class:`ScoringWeights`, the
    tuned ``content/scoring/profile.yaml``, the factor JSON persisted on every
    ``RecommendationEntry``, and every golden fixture — and renaming it would rewrite all
    of them to change nothing the engine computes.

    Worth stating plainly for whoever reads a rung file next: **no scoring factor reads
    this field**, so tuning it moves nothing. What gives a PvM capability weight is a
    candidate's ``advances`` map plus the roadmap's own capability weight (§9.3)."""
    recommended_readiness: Confidence = Confidence.MEDIUM

    _parse_requires = _requirement_field("requires")

    @field_validator("recommended_readiness", mode="before")
    @classmethod
    def _named_readiness(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return _READINESS_NAMES[value]
            except KeyError:
                raise ValueError(
                    f"recommended_readiness must be one of "
                    f"{', '.join(_READINESS_NAMES)}; got {value!r}"
                ) from None
        return value


class Roadmap(ContentModel):
    """§4.2. A weighted capability set with **no dependency graph of its own**.

    "Pure NH", "Zerker" and "Anti-PKer" differ only in these weights and in which
    capabilities they include — never in code.
    """

    id: str
    name: str
    capabilities: dict[str, float]

    @field_validator("capabilities")
    @classmethod
    def _weights_in_unit_interval(cls, value: dict[str, float]) -> dict[str, float]:
        for capability_id, weight in value.items():
            if not 0.0 <= weight <= 1.0:
                raise ValueError(
                    f"capability weight for {capability_id!r} is {weight}, outside [0, 1] (§10.7)"
                )
        return value

    @field_validator("capabilities")
    @classmethod
    def _not_empty(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("a roadmap must weight at least one capability")
        return value


class BossingGuideSource(ContentModel):
    """Pinned attribution metadata for an authored bossing guide."""

    url: str
    revision: int = Field(gt=0)
    checked_at: date
    license: str


class BossingPreparationStep(ContentModel):
    """Preparation advice, optionally checkable against observed account facts."""

    id: str
    label: str
    completion: Requirement | None = None
    candidate_ids: tuple[str, ...] = ()
    wiki_url: str | None = None

    _parse_completion = _requirement_field("completion")

    @model_validator(mode="after")
    def _checkable_steps_link_candidates(self) -> BossingPreparationStep:
        if self.completion is not None and not self.candidate_ids:
            raise ValueError("a checkable preparation step must reference at least one candidate")
        if self.completion is None and self.candidate_ids:
            raise ValueError("an informational preparation step cannot reference candidates")
        return self


class BossingEncounter(ContentModel):
    """One encounter row, with enforced access separate from advisory readiness."""

    id: str
    name: str
    access: Requirement | None = None
    recommendations: Requirement | None = None
    mechanics: tuple[str, ...] = Field(min_length=1)
    rewards: tuple[str, ...] = Field(min_length=1)
    wiki_url: str

    _parse_access = _requirement_field("access")
    _parse_recommendations = _requirement_field("recommendations")


class BossingTier(ContentModel):
    """An ordered display tier associated with one capability in the roadmap."""

    id: str
    name: str
    summary: str
    capability_id: str
    preparation: tuple[BossingPreparationStep, ...] = ()
    encounters: tuple[BossingEncounter, ...] = Field(min_length=1)


class RoadmapGuide(ContentModel):
    """Authored, attributed detail layered over a capability roadmap."""

    id: str
    roadmap_id: str
    name: str
    source: BossingGuideSource
    tiers: tuple[BossingTier, ...] = Field(min_length=1)


class Milestone(ContentModel):
    """§6.6, §10.3. ``kind`` (how measured) and ``class`` (how it ages) are orthogonal.

    Only ``class: execution`` milestones may declare ``practiced_by`` or
    ``practice_group`` — enforced here rather than in :mod:`validate` because it needs
    no other object to check.
    """

    id: str
    name: str
    class_: MilestoneClass = Field(alias="class")
    kind: MilestoneKind
    practice_group: str | None = None
    practiced_by: tuple[PracticeDomain, ...] = ()
    threshold: int | None = Field(default=None, ge=0)
    """For derived threshold milestones — the counter value that achieves it."""

    @model_validator(mode="after")
    def _only_execution_milestones_practice(self) -> Milestone:
        if self.class_ is MilestoneClass.EXECUTION:
            return self
        declared = [
            name
            for name, value in (
                ("practiced_by", self.practiced_by),
                ("practice_group", self.practice_group),
            )
            if value
        ]
        if declared:
            raise ValueError(
                f"milestone {self.id!r} has class {self.class_.value!r} but declares "
                f"{', '.join(declared)}. Only class: execution milestones practice (§10.7). "
                "Where a threshold achievement also has an ongoing practice component, §6.6 "
                "requires a separate execution milestone rather than one row meaning both"
            )
        return self


# ---------------------------------------------------------------------------
# Candidates (§10.6)
# ---------------------------------------------------------------------------


class Candidate(ContentModel):
    """§10.6, D11. *"An action the player could take that changes facts"* (§4).

    Candidates are the only objects the recommendation engine ranks: capabilities define
    what *better* means, and candidates are the moves available for getting there.

    ``advances`` and ``grants_facts`` are deliberately separate. ``grants_facts`` is
    objective — it states what changes. ``advances`` is editorial — it states how much
    each capability cares. A candidate may advance a capability it does not unlock:
    training Magic to 94 fully enables Ice Barrage NH while only partly advancing Deep
    Wilderness NH.

    **No scoring factor appears here, and that is the whole point.** §10.6: every factor
    of §9.4 derives from these fields, *"none is authored directly, so no content file
    can assert its own priority."* There is no ``pvp_value``, ``leverage``, ``proximity``
    or ``priority`` field — see :mod:`tracker.domain.candidates` for the derivations. For
    the same reason there is no ``hours`` or ``gp_cost``: §8 estimates both from the
    training methods and item prices the ``completion`` predicate names, so an author
    cannot make a candidate look cheap by declaring it so.
    """

    id: str
    name: str
    kind: CandidateKind
    source: Literal["authored", "generated"] = "authored"
    """Provenance, and nothing else.

    Declared because :class:`ContentModel` forbids extra keys, so a generated file could
    not otherwise say where it came from. It is read by ``tools/generate_candidates.py``
    and by nothing under ``tracker/`` — a generated candidate is scored by exactly the
    same derivations as a hand-authored one (§10.6). Were this ever consulted by
    :mod:`tracker.domain.candidates` or :mod:`tracker.recommendations.scoring`, it would
    become a way for a file to assert its own priority, which is the one thing §10.6
    forbids."""
    advances: dict[str, float] = Field(default_factory=dict)
    """Capability id → marginal contribution ∈ [0,1]. §10.7 checks each id is declared.

    Empty is legal and means *this advances nothing* — the honest authoring of a
    genuinely irrelevant action, which then ranks last because the content says so rather
    than because code recognises its name (§10.8)."""
    requires: Requirement | None = None
    """Optional gate, same grammar as §10.2. ``unsatisfied`` blocks; ``unknown`` does
    **not** — an unknown gate is *"sync this"*, not *"do this"* (§10.6, G3)."""
    completion: Requirement
    """Predicate over facts; ``satisfied`` ⇒ the candidate is done (§16.2)."""
    grants_facts: Requirement | None = None
    """What becomes true on completion. Drives ``leverage`` (§10.6)."""

    _parse_requires = _requirement_field("requires")
    _parse_completion = _requirement_field("completion")
    _parse_grants_facts = _requirement_field("grants_facts")

    @model_validator(mode="before")
    @classmethod
    def _completion_is_declared(cls, data: Any) -> Any:
        """§10.7: *"every candidate declares a non-empty ``completion`` predicate — a
        candidate that can never be complete would rank forever."*

        Checked here rather than by field presence alone so the diagnostic names the
        consequence. An omitted key, an explicit ``null`` and an empty mapping are the
        same authoring mistake and deserve the same message.
        """
        if isinstance(data, Mapping) and not data.get("completion"):
            # The loader prefixes the candidate id, so this states only the rule.
            raise ValueError(
                "declares no non-empty completion predicate. §16.2 tests completion before "
                "scoring, so a candidate that can never be complete would rank forever (§10.7)"
            )
        return data

    @field_validator("advances")
    @classmethod
    def _advances_in_unit_interval(cls, value: dict[str, float]) -> dict[str, float]:
        """§10.7 — ``advances`` weights lie in [0,1].

        The bound is not decoration: ``pvp_value`` is ``effective_weight × advances`` and
        §9.3's blend already guarantees the first term is in [0,1]. A weight above 1 would
        let one candidate escape the range every other factor is normalized to, and the
        §9.4 geometric mean has no upper clamp to catch it.
        """
        for capability_id, weight in value.items():
            if not 0.0 <= weight <= 1.0:
                raise ValueError(
                    f"advances weight for {capability_id!r} is {weight}, outside [0, 1] (§10.7)"
                )
        return value


# ---------------------------------------------------------------------------
# Training methods (§8.1)
# ---------------------------------------------------------------------------


class LevelRange(ContentModel):
    min: int = Field(ge=1, le=99)
    max: int = Field(ge=1, le=99)

    @model_validator(mode="after")
    def _ordered(self) -> LevelRange:
        if self.min > self.max:
            raise ValueError(f"level_range min {self.min} exceeds max {self.max}")
        return self


class MethodDetail(ContentModel):
    """*Where, on what, and with what* — §15's "How" line. **Descriptive only.**

    Read by :mod:`tracker.ui` and by nothing else. It is never consulted by
    :mod:`tracker.domain.candidates` or :mod:`tracker.recommendations.scoring`, and
    ``tests/content/test_method_detail.py`` asserts that two corpora differing only here
    produce byte-identical recommendations. §10.6's rule that no content file may assert
    its own priority extends to *how* a thing is done: a method does not become more
    urgent because someone wrote a better description of it.

    **``gear`` and ``inventory`` are free text, deliberately, and this is the one field
    where the type matters more than it looks.** An ``item:`` leaf would be resolved by
    the evaluator and would flow into ``_acquisition_charges``, silently changing every GP
    estimate for anyone who happens not to own a listed item — so naming a Kodai wand as
    *display* would quietly reprice the candidate. Where gear must genuinely gate a
    method, :attr:`TrainingMethod.requires` already does that, and it is checked.
    """

    location: str | None = None
    target: str | None = None
    """The monster or activity. Separate from ``location`` because the same target is
    trained in several places and the same place hosts several targets."""
    gear: tuple[str, ...] = ()
    inventory: tuple[str, ...] = ()
    notes: str | None = None
    wiki_url: str | None = None


class TrainingMethod(ContentModel):
    """§8.1. Methods carry their own requirement trees.

    The fast method is frequently gated behind the very content the recommender is
    trying to sequence, so §8.2 step 3 selects only among methods the player *currently*
    satisfies.
    """

    id: str
    name: str
    skill: str
    xp_per_hour: int = Field(gt=0)
    level_range: LevelRange
    cost_per_hour_gp: int = 0
    requires: Requirement | None = None
    detail: MethodDetail = MethodDetail()
    """§15's "How" line. Descriptive; see :class:`MethodDetail`."""

    _parse_requires = _requirement_field("requires")


# ---------------------------------------------------------------------------
# Refreshers (§10.4)
# ---------------------------------------------------------------------------


class RefresherTrigger(ContentModel):
    any_member_freshness_at_least: Freshness = Freshness.STALE


class RefresherTemplate(ContentModel):
    """§10.4. Refreshers are generated from practice groups, not authored per milestone.

    ``suggested_session_hours`` is **mandatory and not a formality** (A8): a refresher is
    scored by §9.4 like any candidate, and an absent hours value gives
    ``effort_decay = exp(0) = 1.0`` — a perfect effort score that would make every
    refresher maximally attractive and defeat the §9.8 list policy (G10).
    """

    id: str
    name: str
    practice_group: str
    trigger: RefresherTrigger = RefresherTrigger()
    suggested_session: str
    suggested_session_hours: float = Field(gt=0.0)
    advances: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Scoring profile (§9.7)
# ---------------------------------------------------------------------------


class KappaPresets(ContentModel):
    """κ per ``gp_sensitivity`` (§9.6). κ *is* the purchase size at which cost bites."""

    high: int
    normal: int
    low: int


class ScoringWeights(ContentModel):
    """The §9.4 exponents. Provisional priors until Step 13 tunes them (§16.3)."""

    pvp_value: float = Field(ge=0.0, le=1.0)
    leverage: float = Field(ge=0.0, le=1.0)
    proximity: float = Field(ge=0.0, le=1.0)
    effort_decay: float = Field(ge=0.0, le=1.0)
    cost_decay: float = Field(ge=0.0, le=1.0)
    method_unlock: float = Field(ge=0.0, le=1.0)
    """§9.4's sixth factor (A30) — *"this makes another candidate faster"*.

    ``leverage`` counts capability **status** flips, so a candidate that unblocks no
    capability scores zero on it however much it changes the rest of the plan. Desert
    Treasure I is the corpus's example: with Ancients already unlocked it flips nothing,
    and yet completing it swaps §8.1's ``magic_conservative`` (35k xp/hr) for
    ``magic_bursting`` (250k xp/hr) and makes the *same seven Magic levels* seven times
    cheaper. No weight over the other five factors can express that, because none of them
    is a function of what another candidate would cost afterwards.

    Weighted separately rather than folded into ``leverage`` because the two answer
    different questions — *"what becomes possible"* against *"what becomes cheap"* — and a
    corpus may want either to dominate. **Authored, like every other exponent**: the
    derivation is code (§10.6, D11) and only its weight is content (§10.8).

    A weight of ``0.0`` is a legitimate authored value and means the factor is inert:
    ``0 · ln(f) = 0`` for every candidate, so a profile predating A30 scores exactly as it
    did. That is what the shipped v1 profile carries until §16.3's retune authors a
    measured value."""


class RefresherPolicy(ContentModel):
    """§9.8's list policy, as content so it can be tuned without a code change."""

    max_in_primary_list: int = Field(default=1, ge=0)
    breadth_bonus_per_extra_member: float = Field(default=0.03, ge=0.0, le=1.0)
    breadth_bonus_cap: float = Field(default=0.10, ge=0.0, le=1.0)


class ScoringProfile(ContentModel):
    """§9.7. Tuning knobs are content, not code (§10.8)."""

    version: int = Field(ge=1)
    tuned_against_corpus: str | None = None
    tau_hours: float = Field(default=10.0, gt=0.0)
    kappa_gp: KappaPresets
    observation_aged_days: int = Field(default=14, gt=0)
    """A4 — when a positive observation stops counting as fresh for readiness (§6.9)."""
    unknown_effort_hours: float = Field(default=10.0, gt=0.0)
    """What ``effort_decay`` charges a candidate §8 cannot size at all.

    §9.4 defines ``effort_decay = exp(−hours / τ)``, and §8 returns ``hours = None`` for a
    candidate whose completion names neither a skill target nor a session length — a
    ``quest:`` candidate is the corpus's example, since the SDD authors no quest duration
    anywhere. Reading that absence as ``0`` gives ``exp(0) = 1.0``: a *perfect* effort mark
    for the one candidate kind whose effort is least known. That is A8's defect one
    candidate kind over, and A8 closed it for refreshers by making
    ``suggested_session_hours`` mandatory.

    Quests have no equivalent field to make mandatory, so the charge is **authored** here
    rather than invented in code — the same reasoning §10.8 applies to every other
    tunable. The default equalling the default ``tau_hours`` is not a coincidence:
    charging exactly one effort scale yields ``exp(−1) ≈ 0.37``, which says *"assume this
    costs a full session's worth of effort until something measures it"* instead of either
    extreme.

    The GP half of the same gap needs no field of its own: an unknown cost is charged one
    **κ**, which ``kappa_gp`` already authors, for the identical ``exp(−1)``."""
    weights: ScoringWeights
    refresher: RefresherPolicy = RefresherPolicy()
    max_primary_entries: int = Field(default=12, ge=1)
    """How many entries §9.8's primary list shows. Authored, for §10.8's reason.

    §9.8 describes a *list*, and nothing in the SDD caps its length — which was harmless
    while the corpus held eight candidates and stops being harmless the moment it holds
    four hundred. An uncapped ranking renders every open candidate onto one page and
    persists a row per entry per run.

    This is **not** a scoring input, and the distinction is what keeps it honest: the cut
    is applied to an already-ordered list, after §9.9's hysteresis and §9.8's refresher
    policy, so it can only remove entries from the bottom. It cannot promote, demote or
    reorder anything, and a candidate the cut drops was put there by its own score."""
    epsilon: float = Field(default=0.01, gt=0.0, le=1.0)
    """§9.4's factor floor, so no single term can annihilate a score."""
