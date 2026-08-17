"""Rows the pages render — pure, frozen, and free of both NiceGUI and the database.

Every §15 honesty rule that can be decided from data is decided **here**, not in a page
function:

* three status layers stay three fields (§4.4), and ``readiness_confidence`` renders as an
  em dash rather than as a value when ``status`` is not ``unlocked`` (G3);
* blockers and unknowns stay two collections all the way to the template (§6.9, §15);
* an unranked skill carries ``is_ranked=False`` and a label that is not a number (§6.2).

The reason for the split is that a rule living inside a ``ui.label(...)`` call can only be
tested by rendering a page in a browser, and a rule that expensive to test stops being
tested. These rows are plain dataclasses: the honesty properties are unit-testable, and the
browser test is left to assert only what genuinely needs a DOM — that the markup for two
states is disjoint, and that the layout does not overflow a phone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from tracker.domain.types import (
    AccountType,
    Confidence,
    GpSensitivity,
    LeafRef,
    Status,
    UnlockState,
)
from tracker.ui.states import UiState, ui_state_for_status, ui_state_for_unlock

#: What ``readiness_confidence`` renders as when there is none. §4.4's own worked example
#: uses this glyph for the ``unknown`` capability, and it matters that it is not a word:
#: "n/a" and "none" both read as a measured result, and this is the absence of one.
NO_READINESS = "—"

#: How each level of §6.9's readiness reads to a user. It is the *evidence* that is fresh
#: or stale, never the player.
READINESS_LABELS: Mapping[Confidence, str] = {
    Confidence.HIGH: "high",
    Confidence.MEDIUM: "medium",
    Confidence.LOW: "low",
}

#: Shown under an empty Unknowns or Blockers list. §15 gives the two lists *separate calls
#: to action*, so their empty states must differ too — otherwise the two containers look
#: interchangeable in exactly the case a user sees most often.
NO_UNKNOWNS = "Nothing unobserved — everything this needs has been seen."
NO_QUESTIONS = "Nothing to answer — you have been asked about everything this needs."
NO_BLOCKERS = "Nothing blocking — the objective requirements are met."

#: The two calls to action §15 requires. "Do this" against "sync this": one is work in the
#: game, the other is work in RuneLite, and a merged list could only carry one of them.
#: What a band with no authored method shows where the method name would go. §8.4 makes
#: §8.2's conservative default a claim the UI is *required* to qualify, and a blank cell
#: reads as "no information" when the truth is "a number we invented".
FALLBACK_METHOD_LABEL = "no method authored — conservative default, treat hours as an upper bound"

BLOCKERS_CTA = "Do these to unlock it"
UNKNOWNS_CTA = "Sync RuneLite to find out"
QUESTIONS_CTA = "Only you can answer these"
"""§15's third call to action, for unknowns no sync will ever resolve (§6.6, A7).

A self-attested milestone is unknown because nobody has been *asked*, not because nobody
has *looked*. Leaving it under ``UNKNOWNS_CTA`` tells the reader to sync RuneLite, which
cannot work however many times they try it — and the instruction to do an impossible thing
is worse than no instruction, because it looks like the app is broken rather than waiting."""


@dataclass(frozen=True, slots=True)
class LeafRow:
    """One entry in a blockers or unknowns list.

    Carries ``leaf_type`` because §15's two calls to action are per-list, but the detail is
    per-leaf: "open your bank" and "finish Desert Treasure" are both unknowns and are not
    the same request.
    """

    leaf_type: str
    key: str
    description: str
    target: int | None = None

    @classmethod
    def of(cls, leaf: LeafRef) -> LeafRow:
        return cls(
            leaf_type=leaf.leaf_type, key=leaf.key, description=leaf.description, target=leaf.target
        )


@dataclass(frozen=True, slots=True)
class CapabilityRow:
    """One capability, with §4.4's three layers as three fields.

    They are three attributes rather than a single ``badge`` string for the reason §4.4
    gives: *"collapsing any two of these produces either backward progress or false
    confidence."* A row that exposed only a summary would make the collapse unavoidable
    downstream, and no page-level discipline could recover the distinction.
    """

    capability_id: str
    name: str
    status: Status
    state: UiState
    status_label: str
    unlock_fraction: float
    readiness: Confidence | None
    readiness_label: str
    warnings: tuple[str, ...]
    recommended_now: bool
    recommended_now_reason: str | None
    blockers: tuple[LeafRow, ...]
    unknowns: tuple[LeafRow, ...]

    @property
    def recommended_label(self) -> str:
        """§4.4's third line, rendered as the SDD writes it: ``no — <reason>``.

        The reason comes from ``CapabilityState.recommended_now_reason``, which §9.2's
        engine wrote. It is not composed here — a UI that phrased its own reason would
        eventually explain a decision the engine did not make.
        """
        if self.recommended_now:
            return "yes"
        if self.recommended_now_reason:
            return f"no — {self.recommended_now_reason}"
        return "no"


@dataclass(frozen=True, slots=True)
class UnlockRow:
    """One §6.3 unlock as a four-state card."""

    key: str
    name: str
    state: UiState
    unlock_state: UnlockState


@dataclass(frozen=True, slots=True)
class SkillRow:
    """One skill, where "unranked" is a state and not a level (§6.2).

    ``level`` is ``None`` for an unranked skill even though ``SkillSnapshot.level`` is not
    nullable. The storage column has to hold something; the *view* does not, and letting a
    ``1`` reach the template is exactly the §15 failure this row exists to prevent. The
    discriminator is ``xp is None``, which §6.2 defines as unranked ("``NULL`` means
    unranked, never ``0``").
    """

    skill_id: str
    name: str
    is_combat: bool
    is_ranked: bool
    level: int | None
    xp: int | None

    @property
    def level_label(self) -> str:
        return f"{self.level}" if self.is_ranked and self.level is not None else "unranked"

    @property
    def progress(self) -> float:
        """Fraction of the way to 99, for the §15 progress bar. Zero-width when unranked.

        Zero-width rather than absent: the bar's track still renders, so an unranked skill
        occupies the same row height as a ranked one and the list does not reflow as
        snapshots arrive.
        """
        if not self.is_ranked or self.level is None:
            return 0.0
        return min(1.0, max(0.0, self.level / 99.0))


@dataclass(frozen=True, slots=True)
class RecommendationRow:
    """The dashboard's single top recommendation (§9.10, §15).

    Only the fields the dashboard shows. The full ranked list with its factor breakdown is
    Step 11's; duplicating its row type here would give two definitions of one thing and
    guarantee they disagree.
    """

    candidate_id: str
    name: str
    reason: str
    estimated_hours: float | None
    estimated_gp: int | None
    confidence: Confidence


@dataclass(frozen=True, slots=True)
class RoadmapProgressRow:
    """One active roadmap's progress, with the §4.3 selection weight it was chosen under."""

    roadmap_id: str
    name: str
    selection_weight: float
    unlocked: int
    total: int

    @property
    def fraction(self) -> float:
        return self.unlocked / self.total if self.total else 0.0


@dataclass(frozen=True, slots=True)
class DashboardView:
    """Everything the dashboard shows, assembled once so the page has no logic left.

    ``current_goal`` is derived rather than stored: §15 names a "current goal" and §6
    defines no model for one, so it is the top-ranked entry of the latest snapshot. Adding
    a table would create a second answer to a question §6.10 already answers.
    """

    display_name: str
    combat_level: int | None
    quest_points: int | None
    last_sync_at_label: str
    unlocked_capabilities: int
    total_capabilities: int
    unknown_capabilities: int
    roadmaps: tuple[RoadmapProgressRow, ...]
    current_goal: RecommendationRow | None
    staleness_notes: tuple[str, ...]


def readiness_label(status: Status, readiness: Confidence | None) -> str:
    """§4.4's second line.

    Guarded on ``status`` as well as on ``readiness`` even though
    :class:`~tracker.domain.types.CapabilityView` already guarantees the two agree (G3).
    That guarantee holds for engine output; this function also renders rows read back from
    ``CapabilityState``, where the two are independent columns and a row left by a previous
    corpus could carry a readiness the current status does not license.
    """
    if status is not Status.UNLOCKED or readiness is None:
        return NO_READINESS
    return READINESS_LABELS[readiness]


def capability_row(
    *,
    capability_id: str,
    name: str,
    status: Status,
    unlock_fraction: float,
    blockers: Sequence[LeafRef],
    unknowns: Sequence[LeafRef],
    readiness: Confidence | None,
    warnings: Sequence[str],
    recommended_now: bool,
    recommended_now_reason: str | None,
) -> CapabilityRow:
    """Assemble one row, applying the §4.4 layering rules on the way in."""
    return CapabilityRow(
        capability_id=capability_id,
        name=name,
        status=status,
        state=ui_state_for_status(status),
        status_label=status.value,
        unlock_fraction=unlock_fraction,
        readiness=readiness if status is Status.UNLOCKED else None,
        readiness_label=readiness_label(status, readiness),
        warnings=tuple(warnings),
        recommended_now=recommended_now,
        recommended_now_reason=recommended_now_reason,
        blockers=tuple(LeafRow.of(leaf) for leaf in blockers),
        unknowns=tuple(LeafRow.of(leaf) for leaf in unknowns),
    )


def unlock_row(key: str, state: UnlockState, *, name: str | None = None) -> UnlockRow:
    """One unlock card. ``name`` falls back to a titled key when content names none.

    §6.3's unlock keys are free-form strings (``spellbook_ancient``, ``diary_varrock_hard``)
    with no registry to look a display name up in, so the fallback is not a placeholder for
    missing content — it is the normal path for most keys.
    """
    return UnlockRow(
        key=key,
        name=name if name is not None else key.replace("_", " ").title(),
        state=ui_state_for_unlock(state),
        unlock_state=state,
    )


def skill_row(
    *, skill_id: str, name: str, is_combat: bool, level: int | None, xp: int | None
) -> SkillRow:
    """One skill row. Unranked when ``xp`` is ``None`` or no snapshot exists (§6.2).

    A missing snapshot and an explicit ``xp: NULL`` are the same statement — nobody has
    seen a ranked value for this skill — and both must render as unranked rather than as
    the level 1 every OSRS account nominally starts at.
    """
    ranked = xp is not None and level is not None
    return SkillRow(
        skill_id=skill_id,
        name=name,
        is_combat=is_combat,
        is_ranked=ranked,
        level=level if ranked else None,
        xp=xp if ranked else None,
    )


# ---------------------------------------------------------------------------
# Step 11 — Recommendations (§9.10, §15)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactorRow:
    """One §9.5 factor: its raw value and what it contributed to the score.

    Both numbers are read off :class:`~tracker.db.models.RecommendationEntry.factors`
    verbatim — §9.5 generated the "Why" line from exactly these contributions, and a
    breakdown drawer computed separately from the same source would risk disagreeing with
    the sentence sitting next to it.
    """

    name: str
    value: float
    weight: float
    log_contribution: float


def _gp(amount: int) -> str:
    """Compact gp, because "1,800,000" and "85,000,000" do not compare at a glance."""
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M".replace(".0M", "M")
    if amount >= 1_000:
        return f"{amount // 1_000}K"
    return str(amount)


@dataclass(frozen=True, slots=True)
class BandRow:
    """One §8.2 level band, resolved for display — §15's "How" line.

    Built from the band **as it was persisted**, joined to content for the method's name
    and description. The method is never re-selected at read time: §8.2 step 3 picks among
    methods the account satisfied *when the run happened*, so re-deriving it later could
    name a method the quoted hours did not come from. Same drift argument that makes
    ``reason`` a stored string.

    ``method_name`` degrades to the raw ``method_id`` when content no longer declares it,
    and to ``None`` only when the band genuinely had no method. Content changes between
    runs — a renamed or deleted method must not raise on a History page.
    """

    from_level: int
    to_level: int
    method_id: str | None
    method_name: str | None
    hours: float
    gp: int
    fallback: bool
    location: str | None = None
    target: str | None = None
    gear: tuple[str, ...] = ()
    inventory: tuple[str, ...] = ()
    notes: str | None = None
    wiki_url: str | None = None

    @property
    def level_label(self) -> str:
        return f"{self.from_level}→{self.to_level}"

    @property
    def method_label(self) -> str:
        """What to show where the method goes.

        A fallback band says so in words rather than showing a blank: §8.4 makes the
        conservative default a claim the UI is *required* to qualify, and an empty cell
        reads as "no information" when the truth is "a number we invented".
        """
        if self.fallback or self.method_id is None:
            return FALLBACK_METHOD_LABEL
        return self.method_name or self.method_id

    @property
    def place_label(self) -> str:
        """Location and target joined, or empty when the corpus describes neither."""
        parts = [part for part in (self.target, self.location) if part]
        return " · ".join(parts)


@dataclass(frozen=True, slots=True)
class UnblockRow:
    """A capability this entry's completion would unlock outright (§9.10)."""

    name: str

    @property
    def label(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class NeededForRow:
    """Another task this entry is a prerequisite of, and how much of its gate it clears.

    The row that answers the user's actual question about a generated skill band: *"Train
    Slayer to 10"* is on the list because Desert Treasure I cannot start without it.

    ``goal_name`` carries the goal one hop further on, where the engine found one, so the
    label can read all the way from the chore to the point of it.
    """

    name: str
    remaining_before: int
    remaining_after: int
    goal_name: str | None = None
    goal_on_roadmap: bool = True

    @property
    def label(self) -> str:
        """ "Desert Treasure I (1 of 3 remaining) → Ice Barrage NH (not on your roadmap)".

        *"unblocks it"* rather than *"0 of 3 remaining"* when the gate comes fully clear:
        zero-of-anything reads as a broken template, and the whole point of that case is that
        the counting stops.

        "remaining", never "requirements" — the counts are over leaves the account is *known*
        to fail, and a gate also holds leaves nobody has been asked about (G3). Calling four
        of eleven "the requirements" would quietly promise that the other seven are met.
        """
        if self.remaining_after == 0:
            progress = "unblocks it"
        else:
            cleared = self.remaining_before - self.remaining_after
            progress = f"{cleared} of {self.remaining_before} remaining"
        label = f"{self.name} ({progress})"
        if self.goal_name is None:
            return label
        return f"{label} → {self.goal_name}{_off_roadmap(self.goal_on_roadmap)}"


@dataclass(frozen=True, slots=True)
class GoalProgressRow:
    """A capability whose own requirements this entry directly reduces (§9.10)."""

    name: str
    remaining_before: int
    remaining_after: int
    on_roadmap: bool = True

    @property
    def label(self) -> str:
        cleared = self.remaining_before - self.remaining_after
        return (
            f"{self.name} ({cleared} of {self.remaining_before} remaining)"
            f"{_off_roadmap(self.on_roadmap)}"
        )


@dataclass(frozen=True, slots=True)
class SpeedUpRow:
    """A grind this entry's completion would shorten, with both sizings (A30)."""

    name: str
    hours_before: float
    hours_after: float

    @property
    def label(self) -> str:
        return f"{self.name}: {_hours(self.hours_before)} → {_hours(self.hours_after)}"


def _off_roadmap(on_roadmap: bool) -> str:
    """The flag that turns a baffling recommendation into a legible one.

    Said in the player's own terms — *"your roadmap"* — because the fact being reported is
    about their selection and not about the corpus. The same capability is unflagged the
    moment they select a roadmap that weights it.
    """
    return "" if on_roadmap else " (not on your roadmap)"


def _hours(hours: float) -> str:
    """``113h``, or ``7.5h`` below ten — :func:`tracker.recommendations.details._hours`'s rule.

    Duplicated rather than imported because the two are the same *convention* and not the same
    *call*: one renders into a reason string the engine persists, the other into a row the
    browser draws, and a UI module importing from the ranking engine to format an hour would
    be a dependency nobody wants to explain later.
    """
    return f"{hours:.1f}h" if hours < 10.0 else f"{hours:.0f}h"


@dataclass(frozen=True, slots=True)
class RecommendationEntryRow:
    """One ranked entry of §9.10's output shape.

    ``unlocks`` and ``advances`` are read from **content**, not authored here: a candidate's
    ``grants_facts`` names the ``unlock:`` keys it grants, and ``advances`` names the
    capabilities it partly moves. Neither is stored on the entry itself (§6.10 stores only
    the score's inputs), so this row is assembled by joining the persisted entry back to the
    candidate or refresher template that produced it — never by composing new prose.
    """

    candidate_id: str
    rank: int
    name: str
    is_refresher: bool
    score: float
    factors: tuple[FactorRow, ...]
    reason: str
    estimated_hours: float | None
    estimated_gp: int | None
    confidence: Confidence
    unlocks: tuple[str, ...] = ()
    advances: tuple[str, ...] = ()
    unblocks: tuple[UnblockRow, ...] = ()
    """Capabilities this entry would unlock outright (§9.10).

    Kept separate from ``unlocks`` rather than merged into it, because the two are different
    facts: ``unlocks`` names the ``unlock:`` *keys* a candidate's ``grants_facts`` declares —
    "Ancient Magicks" — while this names the **capabilities** whose status those facts would
    flip — "Ice Barrage NH". Merging them would put a spellbook and a fighting style in one
    list under one verb, and no reader could tell which was which."""
    needed_for: tuple[NeededForRow, ...] = ()
    """Tasks this entry is a prerequisite of (§9.10) — the chain, read off the snapshot."""
    works_toward: tuple[GoalProgressRow, ...] = ()
    """Capabilities whose own requirements this entry directly reduces (§9.10)."""
    speeds_up: tuple[SpeedUpRow, ...] = ()
    """Grinds this entry would shorten, with both sizings (A30)."""
    practice_members: tuple[str, ...] = ()
    suggested_session: str | None = None
    bands: tuple[BandRow, ...] = ()
    """§8.2's breakdown, empty for anything that is not skill training."""
    liquid_gp: int | None = None
    """Coins the account is known to hold, or ``None`` when no container has been scanned.

    **Display only.** It is deliberately not a scoring input: an ``affordable`` factor
    means a seventh exponent in ``ScoringWeights``, which §16.3 step 5 requires be re-tuned
    against the golden corpus with a human reviewing every disagreement."""

    @property
    def affordability_note(self) -> str | None:
        """ "you have 12M; this costs 85M" — or nothing at all when either side is unknown.

        Silence when ``liquid_gp is None`` is the §4.5 rule showing through: with no
        container ever scanned we do not know the account is poor, we know we have not
        looked, and "you cannot afford this" would be a claim about the player rather than
        about the evidence.
        """
        if self.liquid_gp is None or self.estimated_gp is None or self.estimated_gp <= 0:
            return None
        verb = "covers" if self.liquid_gp >= self.estimated_gp else "short of"
        return f"you have {_gp(self.liquid_gp)} — {verb} the {_gp(self.estimated_gp)} this needs"

    @property
    def has_method_detail(self) -> bool:
        """Whether the "How" block has anything to say beyond the hours.

        A quest or an acquisition has no bands at all, and a band whose method fell back
        has only the qualification to show — both are still worth rendering, because
        "we do not know how" is information. What is *not* worth a block is an entry with
        no bands whatsoever.
        """
        return bool(self.bands)

    @property
    def kind_label(self) -> str:
        return "refresher" if self.is_refresher else "progression"

    @property
    def priority_stars(self) -> str:
        """§9.10's ``★★★★★`` line, five stars scaled from the raw score.

        The score is unbounded above (§9.4's geometric mean has no ceiling), so this is a
        deliberately coarse read — a relative sense of "how good", not a number anyone
        should subtract. Clamped at both ends so an outlier score cannot render six stars
        or minus one.
        """
        filled = min(5, max(1, round(self.score * 5)))
        return "★" * filled + "☆" * (5 - filled)


@dataclass(frozen=True, slots=True)
class BlockedRecommendationRow:
    """One collapsed-section entry (§15): a candidate that cannot rank at all.

    Carries no score and no factors — §16.2 leaves a blocked candidate unscored precisely
    so it is never sorted against actionable work (see
    ``tracker.recommendations.engine._blocked_entries``), and a row type that offered a
    score field would invite one to be shown anyway.
    """

    candidate_id: str
    name: str
    blockers: tuple[LeafRow, ...] = ()
    """Why it is blocked. Empty renders as nothing rather than as a reassurance — an empty
    blockers list on a *blocked* entry means the snapshot predates the column, and inventing
    "nothing is blocking this" for it would contradict the row it sits on."""


def recommendation_entry_row(
    *,
    candidate_id: str,
    rank: int,
    name: str,
    is_refresher: bool,
    score: float,
    factors: Mapping[str, Mapping[str, float]],
    reason: str,
    estimated_hours: float | None,
    estimated_gp: int | None,
    confidence: Confidence,
    unlocks: Sequence[str] = (),
    advances: Sequence[str] = (),
    unblocks: Sequence[UnblockRow] = (),
    needed_for: Sequence[NeededForRow] = (),
    works_toward: Sequence[GoalProgressRow] = (),
    speeds_up: Sequence[SpeedUpRow] = (),
    practice_members: Sequence[str] = (),
    suggested_session: str | None = None,
    bands: Sequence[BandRow] = (),
    liquid_gp: int | None = None,
) -> RecommendationEntryRow:
    """Assemble one row from a persisted entry's factors JSON (§6.10)."""
    factor_rows = tuple(
        FactorRow(
            name=factor_name,
            value=float(values.get("value", 0.0)),
            weight=float(values.get("weight", 0.0)),
            log_contribution=float(values.get("log_contribution", 0.0)),
        )
        for factor_name, values in factors.items()
    )
    return RecommendationEntryRow(
        candidate_id=candidate_id,
        rank=rank,
        name=name,
        is_refresher=is_refresher,
        score=score,
        factors=factor_rows,
        reason=reason,
        estimated_hours=estimated_hours,
        estimated_gp=estimated_gp,
        confidence=confidence,
        unlocks=tuple(unlocks),
        advances=tuple(advances),
        unblocks=tuple(unblocks),
        needed_for=tuple(needed_for),
        works_toward=tuple(works_toward),
        speeds_up=tuple(speeds_up),
        practice_members=tuple(practice_members),
        suggested_session=suggested_session,
        bands=tuple(bands),
        liquid_gp=liquid_gp,
    )


def assert_at_most_one_refresher(rows: Sequence[RecommendationEntryRow]) -> None:
    """G10, belt-and-braces (§9.8, D9).

    Step 6's engine already enforces this before anything is persisted
    (:func:`tracker.recommendations.refreshers.enforce_list_policy`). This assertion does
    not re-derive the policy — it only refuses to *render* a violation, so a future bug
    upstream fails loudly on the page that would otherwise quietly show two refreshers
    instead of failing where the policy lives.
    """
    refreshers = [row for row in rows if row.is_refresher]
    assert len(refreshers) <= 1, (
        f"G10 violated: {len(refreshers)} refreshers in the primary list "
        f"({[row.candidate_id for row in refreshers]}); at most one is allowed (§9.8)"
    )


# ---------------------------------------------------------------------------
# Step 11 — Practice freshness (§9.8, §15)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PracticeMemberRow:
    """One stale milestone inside a practice group (§9.8's "Practice:" bullets)."""

    key: str
    name: str


@dataclass(frozen=True, slots=True)
class PracticeGroupRow:
    """One composite refresher, as the Practice freshness view shows it (§9.8, §15).

    ``members`` holds only the milestones that actually triggered this run — the same set
    :class:`~tracker.recommendations.refreshers.PracticeCandidate.members` carries, so
    "mark session complete" refreshes exactly what is listed and nothing else.
    """

    template_id: str
    name: str
    suggested_session: str
    suggested_session_hours: float
    urgency: float
    members: tuple[PracticeMemberRow, ...]

    @property
    def member_keys(self) -> tuple[str, ...]:
        return tuple(member.key for member in self.members)


# ---------------------------------------------------------------------------
# Step 11 — Roadmaps (§4.3, §6.12, §15)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RoadmapOptionRow:
    """One roadmap as the selector shows it: content plus the live §6.12 selection.

    ``is_primary`` is a **display** convention, not a stored fact — §6.12's table has no
    primary/secondary column, only a weight. The highest selected weight renders as
    primary; ties break on id so the page is stable across renders. Rendering rather than
    storing the distinction means the schema still matches the SDD's own table exactly.
    """

    roadmap_id: str
    name: str
    selected: bool
    selection_weight: float

    @property
    def weight_label(self) -> str:
        return f"{self.selection_weight:g}" if self.selected else "not selected"


def mark_primary(rows: Sequence[RoadmapOptionRow]) -> tuple[RoadmapOptionRow, ...]:
    """Which selected roadmap is *shown* as primary: the highest weight, ties by id.

    Pure and separate from the row itself so the "which one is primary" rule is
    testable without a database — the same reason :func:`~tracker.ui.capabilities.sort_rows`
    lives beside its row type rather than inside a page function.
    """
    selected = [row for row in rows if row.selected]
    if not selected:
        return ()
    best = sorted(selected, key=lambda row: (-row.selection_weight, row.roadmap_id))[0]
    return (best,)


@dataclass(frozen=True, slots=True)
class RoadmapSelectorModel:
    """Everything the shell needs to draw the header roadmap selector.

    Rows plus one already-bound write, because :mod:`tracker.ui.shell` opens no session and
    knows no read model — the same contract every view function already has
    (``capabilities_view.render(rows, on_attest=...)``). The model is built in
    :mod:`tracker.ui.pages`, which is the only module allowed to bind the callback.

    ``value`` is :func:`mark_primary`'s answer, and is therefore a *display* rule rather
    than a stored field, exactly as :class:`RoadmapOptionRow` documents. The selector
    switches the primary only; secondaries and raw weights stay on ``/roadmaps`` (§4.3:
    first-run is *"a simple choice of playstyle rather than an abstract weighting
    exercise"*, and a one-value dropdown is that choice).
    """

    options: tuple[RoadmapOptionRow, ...]
    value: str | None
    on_select: Callable[[str], None]


def roadmap_selector_model(
    rows: Sequence[RoadmapOptionRow], on_select: Callable[[str], None]
) -> RoadmapSelectorModel | None:
    """``None`` when there is nothing to choose between — no player, or no roadmaps.

    Returning ``None`` rather than an empty or disabled model is the §4.5 rule applied to a
    control: a dropdown on a page with no account would imply a choice exists when it does
    not. Pure, so "is there a selector at all" is assertable without a browser.
    """
    if not rows:
        return None
    primary = mark_primary(rows)
    return RoadmapSelectorModel(
        options=tuple(rows),
        value=primary[0].roadmap_id if primary else None,
        on_select=on_select,
    )


# ---------------------------------------------------------------------------
# Step 11 — Settings (§9.6, §15)
# ---------------------------------------------------------------------------

#: The three-way question §9.6 mandates, in the user's language. The UI must never say "κ"
#: or "GP sensitivity" — this table is the one place the two vocabularies meet, and every
#: other module reaches the word through it rather than repeating the mapping.
GP_SENSITIVITY_LABELS: Mapping[GpSensitivity, str] = {
    GpSensitivity.HIGH: "Strongly",
    GpSensitivity.NORMAL: "Normally",
    GpSensitivity.LOW: "Barely",
}

SENSITIVITY_QUESTION = "How strongly should expensive upgrades be deprioritized?"


#: §15's account-mode question. Phrased as a question with an explicit "not set" option,
#: because ``None`` is a real state here and a radio group with no unselected choice would
#: force the user to assert something the moment they open the page (§4.5).
ACCOUNT_TYPE_QUESTION = "What kind of account is this?"
ACCOUNT_TYPE_UNSET = "Not set — nothing is assumed"
ACCOUNT_TYPE_LABELS: Mapping[AccountType, str] = {
    AccountType.MAIN: "Main",
    AccountType.IRONMAN: "Ironman",
    AccountType.HARDCORE: "Hardcore ironman",
    AccountType.ULTIMATE: "Ultimate ironman",
    AccountType.GROUP: "Group ironman",
}
ACCOUNT_TYPE_NOTE = (
    "Until this is set, purchases are still suggested — the app does not guess. "
    "An ironman cannot buy from the Grand Exchange at any price, so saying so here "
    "removes those suggestions rather than merely ranking them lower."
)

MEMBERS_QUESTION = "Is this a members account?"
MEMBERS_UNSET = "Not set"


@dataclass(frozen=True, slots=True)
class SettingsView:
    """Everything the settings page shows.

    ``api_token_present`` is a boolean, never the token itself (§11.2, §15) — the field name
    says so as loudly as the type does, so a future call site cannot pass the token through
    by accident and have it read as a boolean.
    """

    gp_sensitivity: GpSensitivity
    #: The account WOM follows (§7.2), or ``None`` when no character has been named yet.
    #: ``None`` is the state a fresh install is in before either a sync or a settings entry,
    #: and the page must offer to fix it rather than render an empty box.
    tracked_username: str | None
    bind_address: str
    port: int
    api_token_present: bool
    price_provider: str
    price_base_url: str
    wom_base_url: str
    #: ``None`` means nobody has been asked, and the page renders that as its own option
    #: rather than preselecting "Main" (§4.5).
    account_type: AccountType | None = None
    members: bool | None = None
    #: §8.3's cache, made visible. Until Step 10a there was no way to tell a price feed
    #: that had never run from one that ran and found nothing — both showed as estimates
    #: falling back to the authored hint, which §8.4 marks ``low`` either way.
    price_rows: int = 0
    price_last_fetched_at: datetime | None = None

    @property
    def price_cache_label(self) -> str:
        """ "never fetched" is a different sentence from "0 items priced" (§4.5)."""
        if self.price_last_fetched_at is None:
            return (
                "never fetched — leave the app running, or run "
                "`python -m tracker.sync.worker --prices`"
            )
        noun = "item" if self.price_rows == 1 else "items"
        return f"{self.price_rows} {noun} priced"

    @property
    def sensitivity_label(self) -> str:
        return GP_SENSITIVITY_LABELS[self.gp_sensitivity]


# ---------------------------------------------------------------------------
# Step 11 — History (§6.10, §15)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HistorySnapshotRow:
    """One §6.10 ``RecommendationSnapshot``, as the History list shows it."""

    snapshot_id: int
    run_at: datetime
    scoring_profile_version: int
    top_candidate_id: str | None
    top_candidate_name: str | None
    top_reason: str | None


@dataclass(frozen=True, slots=True)
class SkillXpPoint:
    """One §6.2 observation, for the Plotly XP chart."""

    observed_at: datetime
    xp: int


@dataclass(frozen=True, slots=True)
class FactorDiffRow:
    """One factor's movement between two snapshots (§6.10: *"two runs can be diffed to see
    which factor moved"*).

    ``before``/``after`` are ``None`` when the factor (or the candidate) is absent from one
    side — a candidate that only entered the ranking on the later run has nothing to diff
    against, and that absence is itself the information, not an error to hide.
    """

    candidate_id: str
    factor: str
    before: float | None
    after: float | None

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


# ---------------------------------------------------------------------------
# §21 — generated task guidance
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuidanceStepRow:
    """One step of §21.3's answer, with its number already composed into a label.

    Composed here rather than in the renderer for this layer's standing rule: a sentence
    assembled inside a ``ui.html(...)`` call can only be checked by driving a browser.
    """

    order: int
    title: str
    detail: str

    @property
    def label(self) -> str:
        return f"{self.order}. {self.title}"


@dataclass(frozen=True, slots=True)
class GuidanceView:
    """One generated explanation, ready to draw (§21, §15).

    ``warnings`` and ``uncertain`` stay separate all the way to the screen. *"This will get
    you killed in the Wilderness"* and *"this method may no longer exist"* are different
    sentences with different remedies, and merging them would leave the reader unable to tell
    which of the two they were being told.
    """

    candidate_id: str
    task_name: str
    summary: str
    prerequisites: tuple[str, ...] = ()
    steps: tuple[GuidanceStepRow, ...] = ()
    warnings: tuple[str, ...] = ()
    uncertain: tuple[str, ...] = ()
    estimated_session_minutes: int | None = None
    model: str = ""
    generated_at: datetime | None = None
    cached: bool = False

    @property
    def provenance_label(self) -> str:
        """Who wrote this. §15's honesty rule applied to a new source of prose.

        Every other number and sentence on the Recommendations page came from authored
        content and a pure function. This paragraph did not, and the reader is entitled to
        know which they are looking at without having to guess from the tone.
        """
        return f"Written by {self.model}" if self.model else "Written by a language model"

    @property
    def session_label(self) -> str | None:
        """The model's suggested sitting length — never merged with §8's hours (D14).

        Two numbers of different provenance printed in the same place become one number of
        unknown provenance, so this is labelled as a suggestion and kept apart from the
        estimate the ranked list already shows.
        """
        if self.estimated_session_minutes is None:
            return None
        return f"Suggested session: about {self.estimated_session_minutes} minutes"

    @property
    def uncertainty_label(self) -> str | None:
        """A heading for the model's own hedges, or ``None`` when it had none.

        ``None`` rather than an empty section: an empty heading reads as *"there is nothing
        to be unsure about"*, which is a stronger claim than the model actually made.
        """
        if not self.uncertain:
            return None
        return "The model was unsure about the following — verify before relying on it"


#: Shown in place of guidance when no provider is configured (§21.4, D14).
GUIDANCE_DISABLED = (
    "Task guidance is not configured on this install. Set integrations.llm.enabled and "
    "supply an API key to switch it on; nothing else on this page depends on it."
)

#: Shown when the provider could not be reached. Names what is *unaffected*, because the
#: ranked list and its estimates are computed locally and a provider outage cannot touch them.
GUIDANCE_UNAVAILABLE = (
    "Could not reach the guidance provider. The recommendation and its estimate are "
    "unaffected — try again in a moment."
)


# ---------------------------------------------------------------------------
# §22 — the general advisor
# ---------------------------------------------------------------------------

#: Tool ids to reader-facing words. Kept here rather than on the tool definitions, because the
#: catalogue's descriptions are written for the model and these are written for a person; one
#: string cannot serve both without serving neither well.
_TOOL_WORDS: dict[str, str] = {
    "search_candidates": "the task corpus",
    "get_candidate_detail": "a task's requirements",
    "get_capability_detail": "a capability's requirements",
    "list_training_methods": "training methods",
    "get_quest_status": "quest status",
    "get_skill_detail": "a skill's detail",
    "get_item_price": "item prices",
}


@dataclass(frozen=True, slots=True)
class AdvisorMessageRow:
    """One question or one answer, ready to draw (§22.8, §15).

    Three of §15's requirements get sharper on a chat surface, and all three are properties
    here rather than decisions in the renderer:

    * **Provenance is per message.** ``model`` comes from the stored row, never from current
      configuration — a thread outlives a model change, and relabelling old answers would be a
      false claim about who wrote them.
    * **A hedge is marked as a hedge**, which is why ``uncertain`` survives as its own field
      all the way to the screen rather than being folded into the prose.
    * **Lookups are visible.** ``tool_names`` lets a reader tell which parts of an answer rest
      on the application's own data and which on the model's knowledge of the game.
    """

    role: str
    """``you`` or ``advisor`` — the reader's words, not the wire's."""

    text: str
    uncertain: tuple[str, ...] = ()
    model: str = ""
    generated_at: datetime | None = None
    tool_names: tuple[str, ...] = ()
    truncated: bool = False
    stale_digest: bool = False

    @property
    def is_answer(self) -> bool:
        return self.role == "advisor"

    @property
    def who_label(self) -> str:
        """The attribution as a person would say it, not as the wire spells it.

        ``role`` stays the wire word because ``data-role`` is a query surface and the browser
        tests select on it. What the eye gets is a phrase: *"You asked"* reads as one half of
        an exchange in a way that a bare lowercase *"you"* — which is what this drew before —
        does not.
        """
        return "Advisor" if self.is_answer else "You asked"

    @property
    def provenance_label(self) -> str | None:
        """Who wrote this, or ``None`` for the reader's own question."""
        if not self.is_answer:
            return None
        return f"Written by {self.model}" if self.model else "Written by a language model"

    @property
    def uncertainty_label(self) -> str | None:
        """``None`` when the model hedged nothing — an empty heading would overclaim."""
        if not self.uncertain:
            return None
        return "The advisor was unsure about the following — verify before relying on it"

    @property
    def sources_label(self) -> str | None:
        """Which lookups this answer rests on, in human words.

        Names are rewritten because ``get_candidate_detail`` is an implementation detail and
        *"looked up a task's requirements"* is the fact the reader wants. ``None`` when the
        answer used no tool, which is itself informative: it came from the account summary and
        the model's own knowledge.
        """
        if not self.tool_names:
            return None
        described = sorted({_TOOL_WORDS.get(name, name) for name in self.tool_names})
        return "Looked up: " + ", ".join(described)

    @property
    def staleness_note(self) -> str | None:
        """§15's staleness discipline applied to a conversation.

        An answer written before the last sync may rest on levels that have since moved. That
        does not make it wrong, so it is a note rather than a warning.
        """
        if not self.stale_digest:
            return None
        return "Written before your most recent sync — your account may have moved since."

    @property
    def truncation_note(self) -> str | None:
        if not self.truncated:
            return None
        return "This answer was cut short by the length limit."


@dataclass(frozen=True, slots=True)
class AdvisorConversationRow:
    """One thread in the list beside the current one."""

    conversation_id: int
    title: str
    updated_at: datetime | None = None
    current: bool = False

    @property
    def when_label(self) -> str | None:
        """The day this thread last moved, or ``None`` if we never recorded one.

        A date rather than a *"2 days ago"*, because a relative phrase needs a clock and a
        clock is a dependency this row does not otherwise have — and the question a reader
        asks of a thread list is *which one was that*, which an absolute day answers as well.
        Omitted rather than filled with a placeholder: an unknown time is not a time.
        """
        if self.updated_at is None:
            return None
        return self.updated_at.strftime("%d %b").lstrip("0")


#: What the query string says for *a thread that does not exist yet*.
#:
#: The advisor keeps its position in the URL so a reload returns to the same conversation, which
#: leaves it needing a way to spell "none of them" — and an absent parameter cannot mean that,
#: because an absent parameter already means *whichever I was last reading*. Those are different
#: requests and were previously the same one: ``?conversation=0`` fell through the read path's
#: unknown-id fallback and landed back on the most recent thread, so *New conversation* returned
#: the reader to the conversation they were trying to leave.
#:
#: Zero rather than a word because the parameter is typed as an integer at the route, and no row
#: can collide with it: SQLite's ``INTEGER PRIMARY KEY`` starts at one.
NEW_CONVERSATION_ID = 0


@dataclass(frozen=True, slots=True)
class AdvisorThreadView:
    """The conversation on screen, and the threads beside it."""

    conversation_id: int | None
    title: str
    messages: tuple[AdvisorMessageRow, ...] = ()
    conversations: tuple[AdvisorConversationRow, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.messages

    @property
    def current_label(self) -> str:
        """What the picker calls the thread on screen.

        A thread is named after its first question, so one that has not been asked yet has no
        name to show. It says what it *is* rather than going blank, because the control has to
        read as a control whether or not there is anything behind it.
        """
        return self.title or "New conversation"

    @property
    def has_conversations(self) -> bool:
        """Whether there is anything to go back to.

        Decides whether the picker opens a list at all: on a first visit it would open onto
        nothing, and a control that does not act is worse than no control — the rule
        :func:`~tracker.ui.advisor.render_empty` already follows for its suggested prompts.
        """
        return bool(self.conversations)


#: Shown when the feature is not configured (§22.1, D14). Names both switches, because the
#: common mistake is enabling §21's guidance and expecting this to follow.
ADVISOR_DISABLED = (
    "The advisor is not configured on this install. Set integrations.llm.enabled and "
    "integrations.llm.advisor.enabled and supply an API key; nothing else in this app "
    "depends on it."
)

#: Names what is *unaffected*, because rankings and estimates are computed locally and a
#: provider outage cannot touch them (D14).
ADVISOR_UNAVAILABLE = (
    "Could not reach the advisor. Your recommendations and estimates are unaffected — they "
    "are computed locally."
)

#: A refusal is not an outage, and telling someone to retry something that will never succeed
#: is worse than the refusal itself (§21.4's three-way taxonomy, applied here).
ADVISOR_REFUSED = (
    "The advisor declined to answer that one. Rephrasing may help; nothing else is affected."
)

#: The empty state. Says what it can see, so the first question is an informed one.
ADVISOR_EMPTY = (
    "Ask anything about your account or about the game. The advisor can see your skills, "
    "capabilities, roadmaps and ranked tasks, and can look up quests, tasks, training "
    "methods and cached item prices."
)

#: Three questions to start from, offered beside :data:`ADVISOR_EMPTY`.
#:
#: An empty screen is an invitation to act, and the sentence above it only describes — it
#: tells a reader what the advisor can see and then leaves them to compose the first question
#: from a cold start. These are chosen to demonstrate the three *shapes* of question this
#: surface answers rather than to be good questions in themselves: one about the account
#: (needs the digest), one about the game (needs the corpus), one about a decision (needs
#: both). Someone who reads all three has learned the range without being told it.
ADVISOR_PROMPTS: tuple[str, ...] = (
    "What should I train next, and why that over the alternatives?",
    "What do I still need for Barrows gloves?",
    "Is my current gear holding me back anywhere?",
)


# ---------------------------------------------------------------------------
# §23 — gear progression
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GearPickRow:
    """One rung, pre-formatted. §15 renders rows; it does not compose sentences.

    ``held_state`` is a :class:`UiState` rather than a boolean because there are three
    answers, and the third has a rendering rule attached: *unknown* must never be drawn as
    *locked* or as *not held*. Reusing ``state_badge`` is the enforcement — ``STATE_CLASSES``
    is injective, so two states cannot share markup however the page is edited later.
    """

    name: str
    rung_label: str
    held_state: UiState
    fit_state: UiState
    price_label: str
    held_label: str = ""
    """The word for ``held_state``, in ownership vocabulary rather than on the lock scale.

    Carried explicitly because :data:`~tracker.ui.states.STATE_LABELS` spells these states
    ``unlocked | locked``, which answer the *other* question on the row — can you equip it.
    Badging ownership with those words renders a piece the account can wear but does not
    own as "locked", contradicting the layer that just recommended it.
    """
    fit_label: str = ""
    """The word for ``fit_state``. Empty where the row's own layer already implies it."""
    note: str | None = None
    """Why this rung is not usable, or that nobody has established what it takes."""
    acquire_label: str = ""
    """How this rung is obtained, when that is worth saying — §23.2's second axis.

    The *same layer* as ``note`` rather than a third badge, and that is a §23.5 rule rather
    than a layout preference: two badges on the name line already wrapped on a phone once, and
    the fix was to move the second one down beside the sentence explaining it. A third
    vocabulary on the row would undo that.

    Empty for a tradeable rung, on the rule ``fit_label`` follows — an answer of *yes* earns
    no space.
    """
    tier: int = 0
    """This rung's position on its ladder, as a number rather than as prose.

    ``rung_label`` already says "rung 2 of 5", but a page that wants to *order* rungs — or
    to draw the ladder as a ladder — would have to parse that sentence back into an integer
    to do it. Carrying both is not duplication: one is the sentence shown to a reader, the
    other is the value the layout is computed from, and deriving either from the other is
    how the two would come to disagree.
    """


@dataclass(frozen=True, slots=True)
class GearSlotRow:
    """One equipment slot: what to wear, what is owned, what comes next."""

    slot: str
    ladder_label: str
    recommended: GearPickRow | None
    best_held: GearPickRow | None
    next_rung: GearPickRow | None
    earn: GearPickRow | None = None
    """A rung the account can already wear and cannot buy — a target, never a purchase."""
    aspirational: tuple[GearPickRow, ...] = ()
    also_held: tuple[GearPickRow, ...] = ()
    """Other rungs the account owns, below the best one.

    Computed by §23.4 since it shipped and discarded by this layer until now, which meant the
    page could fail to mention gear the player actually has — on the page whose whole job is
    to say what they have.
    """

    ladder: tuple[tuple[int, str], ...] = ()
    """``(tier, name)`` for every rung, lowest first.

    Not for drawing. It is what lets the page say *which* rungs it left out: a card headed
    "11 rungs" that draws four is a silent cut, and naming the remainder is the difference
    between a summary and a page that merely looks complete.
    """

    conflict: bool = False
    """They hold a rung above the one they can equip — shown, never silently resolved."""
    held_is_recommended: bool = False
    """The best rung held *is* the recommended one, so the two layers name one item.

    The common case on a settled slot, and drawing it as two rows invites the reader to
    hunt for a difference that is not there. The layers stay separate fields rather than
    being merged in the read model: they answer different questions, and the case where
    they disagree is the one §23 exists to surface.
    """


@dataclass(frozen=True, slots=True)
class GearStyleRow:
    style: str
    slots: tuple[GearSlotRow, ...]
    missing_label: str
    """What the recommended setup still costs, or why there is no figure."""


@dataclass(frozen=True, slots=True)
class GearView:
    """§23.5's whole page.

    ``scan_note`` is not decoration. With a container unscanned, every *not held* on this
    page is really *unknown*, and a page that omitted to say so would read as a complete
    inventory of an account nobody has looked at.
    """

    styles: tuple[GearStyleRow, ...] = ()
    fully_scanned: bool = False
    scan_note: str | None = None
