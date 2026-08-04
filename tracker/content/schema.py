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


class Item(ContentModel):
    """§10.5. ``item_id`` is the numeric in-game id the price API and plugin both use."""

    id: str
    name: str
    item_id: int | None = Field(default=None, gt=0)
    price_mode: Literal["live", "static"] = "static"
    fallback_price_gp: int | None = Field(default=None, ge=0)
    price_staleness_days: int | None = Field(default=None, gt=0)


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
    assert its own priority."*"""
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
    weights: ScoringWeights
    refresher: RefresherPolicy = RefresherPolicy()
    epsilon: float = Field(default=0.01, gt=0.0, le=1.0)
    """§9.4's factor floor, so no single term can annihilate a score."""
