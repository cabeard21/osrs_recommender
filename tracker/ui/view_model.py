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

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from tracker.domain.types import Confidence, GpSensitivity, LeafRef, Status, UnlockState
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
NO_BLOCKERS = "Nothing blocking — the objective requirements are met."

#: The two calls to action §15 requires. "Do this" against "sync this": one is work in the
#: game, the other is work in RuneLite, and a merged list could only carry one of them.
BLOCKERS_CTA = "Do these to unlock it"
UNKNOWNS_CTA = "Sync RuneLite to find out"


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
    practice_members: tuple[str, ...] = ()
    suggested_session: str | None = None

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
    practice_members: Sequence[str] = (),
    suggested_session: str | None = None,
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
        practice_members=tuple(practice_members),
        suggested_session=suggested_session,
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


@dataclass(frozen=True, slots=True)
class SettingsView:
    """Everything the settings page shows.

    ``api_token_present`` is a boolean, never the token itself (§11.2, §15) — the field name
    says so as loudly as the type does, so a future call site cannot pass the token through
    by accident and have it read as a boolean.
    """

    gp_sensitivity: GpSensitivity
    bind_address: str
    port: int
    api_token_present: bool
    price_provider: str
    price_base_url: str

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
