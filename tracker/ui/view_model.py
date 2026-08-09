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

from tracker.domain.types import Confidence, LeafRef, Status, UnlockState
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
