"""§23.5's gear page: where the account stands, and what it can actually equip.

The page has one hard rule, and it is §15's: **a rung whose ownership is unknown must never
render as one that is known to be absent.** Unknown means nobody has looked, and drawing it
as *not held* turns a gap in observation into a claim about the account — the failure §4.5
exists to prevent, arriving through the stylesheet instead of through the engine.

That rule is enforced structurally rather than by care. Every state badge comes from the one
implementation in :mod:`tracker.ui.components.badges`, which draws its class from
:data:`~tracker.ui.states.STATE_CLASSES` — an injective mapping, so no two states can share
markup however this file is edited later.

*What you can wear* and *what you own* are two questions, and the read model keeps two
fields because the case where they disagree is the one most worth showing. They are also
badged in two vocabularies: a state's *word* is not its *identity*, so ownership says
"held / not held / not yet seen" while fit says "can equip", and sharing the lock scale's
words across both is what renders a piece the account can wear but does not own as "locked".
The :class:`~tracker.ui.states.UiState` is shared regardless, which is what keeps the
paragraph above true of these badges too.

**The slot is drawn as a ladder, because it is one.** Every rung previously got its own
label — *best you can equip*, *holding*, *next rung*, *above that* — repeated for each of
the five, so a single slot cost roughly fifteen lines on a phone and the reader had to
reassemble the ordering from four separate headings. A ladder is an ordered sequence, so
*position* can carry the ordering and the headings collapse into one word per rung, on the
rungs that have a role at all. This is ordinal structure that is earned rather than
decorative: the rungs really are ranked, and the number really is the thing the reader is
locating themselves against.

Ownership is also encoded in the rung glyph — filled, hollow, dotted — and not only in the
badge beside it, so the three ownership answers survive both a monochrome screen and a
reader who does not yet know what the colours mean.

**The ladder is bounded, and it says so.** Only rungs carrying a role are drawn, which is the
right bound — nobody reads a twenty-three rung ammunition ladder top to bottom. What was wrong
was doing it silently: a card headed *"11 rungs"* drew four of them on a continuous rail, and a
reader had no way to tell a rung that was skipped from one that does not exist. It produced
exactly the two questions you would predict — *"why is there nothing between rung 1 and rung
5"* and *"is Mooleta missing"* — and in both cases the ladder was complete and the drawing was
not. Every skipped run now renders as a gap that names what it passes over, which is §22.2's
rule about bounded sections arriving on the page where nothing enforced it.

**A third question arrived later and did not get a third badge.** *How is this obtained* is
as real as the other two — the page used to recommend an Infernal cape to anybody with 40
Defence — but two badges on the name line already wrapped on a phone once, and the fix was to
move the second one down beside the sentence explaining it. So acquisition is a *sentence*,
on its own line, and the earn target is a *rung with a role* rather than a fourth badge
vocabulary. Its role is deliberately not drawn in gold: gold means "wear this", and a piece
the market does not sell is the one thing on the rail a reader cannot act on by spending.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from nicegui import ui

from tracker.ui.components.badges import state_badge
from tracker.ui.shell import section
from tracker.ui.states import UiState
from tracker.ui.view_model import GearPickRow, GearSlotRow, GearStyleRow, GearView

#: Shown when the corpus authors no ladders at all — distinct from having no player.
EMPTY = "No gear ladders are authored, so there is nothing to place this account on."

NO_PLAYER = "No player yet. Sync from RuneLite and this page will fill in."

#: Said once per style rather than once per rung — see the note on ``price_label`` in
#: :func:`tracker.ui.read_model._gear_pick_row`. §8.3's fact is kept; its repetition is not.
NO_PRICES = "No prices are cached yet, so no rung here shows one."

#: Ownership as a glyph. Redundant with the badge on purpose: colour is not the only way a
#: reader arrives at this page, and a filled circle against a hollow one is legible without
#: it. ``UNKNOWN`` gets a dotted ring rather than a lighter fill, for §15's reason — a
#: quieter version of "not held" is still "not held".
RUNG_GLYPH = {
    UiState.UNLOCKED: "●",  # ● held
    UiState.LOCKED: "○",  # ○ not held
    UiState.UNKNOWN: "◌",  # ◌ not yet seen
    UiState.AVAILABLE: "○",
}

#: The ladder itself, and the one piece of the visual language that belongs to this page.
#:
#: The rail is a single absolutely-positioned line behind the glyph column, inset at both
#: ends so it stops at the first and last rung rather than running off into the card's
#: padding. The glyphs sit above it on the panel colour, which is what makes them read as
#: notches on a rail instead of as bullets beside a line.
GEAR_CSS = """
.rung-list { position: relative; display: flex; flex-direction: column; }
.rung-list::before {
  content: ""; position: absolute; left: 1.75rem; top: 0.7rem; bottom: 0.7rem;
  width: 1px; background: var(--ink-faint); opacity: 0.5;
}
.rung {
  display: grid; grid-template-columns: 0.85rem 1.1rem minmax(0, 1fr);
  gap: 0.35rem; align-items: start; padding: 0.3rem 0;
}
.rung-caret { font-size: 0.8rem; line-height: 1.55; text-align: right; color: transparent; }
.rung-mark {
  position: relative; z-index: 1; text-align: center; line-height: 1.55;
  font-size: 0.8rem; color: var(--ink-faint); background: var(--panel);
}
.rung-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.35rem; }
.rung-name { font-size: 0.875rem; color: var(--ink); }
.rung-meta {
  font-family: var(--font-data); font-size: 0.6875rem;
  color: var(--ink-faint); margin-top: 0.1rem;
}
/* The fit badge sits with the sentence that explains it rather than beside the item name.
   Two badges on the name line wrapped on a phone, which put the second one under the name
   and broke the rung back into the three ragged lines this layout exists to remove — and
   the pairing is better anyway: "requirements unknown" and "nobody has observed 30 Defence"
   are one statement made twice, so they should read as one line. */
.rung-fit {
  display: flex; flex-wrap: wrap; align-items: baseline;
  gap: 0.35rem; margin-top: 0.15rem;
}
.rung-note { font-size: 0.75rem; color: var(--ink-dim); }
.rung-acquire { margin-top: 0.15rem; }

/* A gap sits quieter than any rung: it is the one row on the rail that is not a piece of
   gear, and it must never compete with the rungs it separates. The glyph column keeps the
   ellipsis on the panel colour so the rail reads as interrupted rather than as broken. */
.rung-gap { padding: 0.15rem 0; }
.rung-gap .rung-note { color: var(--ink-faint); font-style: italic; }

/* The one rung the page is actually recommending. Everything above it is quiet so that
   this is what the eye lands on when the card comes into view.
   The caret and the name go gold; the glyph deliberately does not. The glyph's colour is
   how it encodes *ownership*, and a role tint over it would repaint a recommended rung you
   do not own as though you did — the same collapse §15 forbids, arriving through an
   emphasis rule. Role belongs to the gutter and the name; ownership keeps the glyph. */
.rung[data-role~=best] .rung-caret { color: var(--gold); }
.rung[data-role~=best] .rung-name { color: var(--gold); font-weight: 600; }
.rung[data-role~=holding] .rung-mark { color: var(--jade); }

/* The earn target gets its own weight and deliberately *not* gold. Gold means "wear this",
   and a piece the market does not sell is the one thing on the rail the reader cannot act on
   by spending — painting it in the recommendation's colour re-creates the exact conflation
   the acquisition axis was added to remove (§23.5). It also stays off the glyph, for the
   reason stated above: the glyph is ownership's, and role is the gutter's and the name's. */
.rung[data-role~=earn] .rung-name { color: var(--ink); font-weight: 600; }

.gear-absent { font-size: 0.75rem; color: var(--ink-faint); margin-top: 0.4rem; }
.gear-conflict {
  font-size: 0.75rem; color: var(--rust);
  border-left: 2px solid var(--rust); padding-left: 0.5rem; margin-top: 0.5rem;
}

/* Quasar's tabs, brought onto the palette. The 2.75rem floor is the tap-target minimum;
   Quasar's default leaves them under it on a phone.

   The `background: transparent` is not cosmetic tidying: `.q-tab-panels` ships an opaque
   white ground, so on the dark theme the entire gear page rendered as a white sheet behind
   the cards. Any Quasar container with its own background has to be brought onto the
   palette explicitly — inheriting is not the default there. */
.q-tab { color: var(--ink-dim); min-height: 2.75rem; }
.q-tab--active { color: var(--gold); }
.q-tabs__content { border-bottom: 1px solid var(--edge-soft); }
.q-tab-panels, .q-tab-panel { background: transparent; }
.q-tab-panel { padding: 0.75rem 0 0; }
"""


@dataclass(slots=True)
class _Rung:
    """One rung, with every role it plays in this slot gathered onto it.

    Roles accumulate rather than replace, because a rung genuinely can be two things at
    once — the piece you are holding *is* often the best you can equip. The previous layout
    handled that one case with a merged heading; carrying a list generalises to the pairs
    the merged heading could not express.
    """

    pick: GearPickRow
    roles: list[str] = field(default_factory=list)


def rungs(slot: GearSlotRow) -> tuple[_Rung, ...]:
    """The slot's rungs, highest first, each carrying every role it plays.

    Pure, and separate from the rendering, for the reason :func:`slot_labels` is: which
    rungs appear and in what order is a policy worth testing without a browser. It is also
    what lets :func:`render_style` ask whether *any* rung in a style has a price without
    walking the four fields itself.

    Deduplicated on ``name`` and ``tier`` together. The four source fields overlap by
    design — the rung you hold is frequently also the best you can equip — and drawing it
    twice reads as a distinction, sending the reader looking for one that is not there.
    """
    ordered: list[tuple[GearPickRow | None, str]] = [
        (slot.recommended, "best you can equip"),
        (slot.earn, "earn it"),
        (slot.best_held, "holding"),
        (slot.next_rung, "next rung"),
        *((pick, "") for pick in slot.aspirational),
        # A rung the account owns is drawn even when it sits below the recommendation and has
        # no other role. §23.4 has computed these since it shipped and this page discarded
        # them, so a spare set in the bank could go unmentioned on the page whose whole job is
        # to say what the account has.
        *((pick, "also holding") for pick in slot.also_held),
    ]

    collected: dict[tuple[str, int], _Rung] = {}
    for pick, role in ordered:
        if pick is None:
            continue
        rung = collected.setdefault((pick.name, pick.tier), _Rung(pick=pick))
        if role and role not in rung.roles:
            rung.roles.append(role)

    return tuple(sorted(collected.values(), key=lambda rung: -rung.pick.tier))


#: Skipped rungs named before the rest become a count.
#:
#: Six rather than the three ``render.MAX_NAMED_BLOCKERS`` uses, because the two truncations
#: are answering different questions. A blocker list is read for its *shape* — roughly how
#: much is missing — so three and a count says everything. A gap marker is read to answer
#: *"is the thing I am looking for in there?"*, which a count cannot answer at all and three
#: names answer only sometimes: the melee shield ladder skips seven rungs below its
#: recommendation, and Mooleta is the fourth of them.
MAX_NAMED_SKIPPED = 6


@dataclass(slots=True)
class _Gap:
    """Rungs the ladder passes over, said out loud.

    The page draws the rungs that carry a *role* and nothing else, which is the right bound —
    a twenty-three rung ammunition ladder is not a thing anyone reads top to bottom. What was
    wrong was doing it **silently**: the card announced "11 rungs", drew four of them on a
    continuous rail, and a reader who owned nothing in between had no way to tell a rung that
    was skipped from one that does not exist. Two separate reports of the same confusion —
    *"why is there nothing between rung 1 and rung 5"* and *"is Mooleta missing"* — and the
    answer to both was that the ladder was complete and the drawing was not.

    §22.2 already requires the advisor's bounded sections to announce that they are bounded.
    This is that rule arriving on the page, where it was never enforced.
    """

    tiers: tuple[int, ...]
    names: tuple[str, ...]

    @property
    def label(self) -> str:
        named = list(self.names[:MAX_NAMED_SKIPPED])
        remaining = len(self.names) - len(named)
        if remaining > 0:
            named.append(f"and {remaining} more")
        count = f"{len(self.tiers)} rung" if len(self.tiers) == 1 else f"{len(self.tiers)} rungs"
        return f"{count} not shown — {', '.join(named)}"


def ladder_rows(slot: GearSlotRow) -> tuple[_Rung | _Gap, ...]:
    """The rungs the page draws, highest first, with every skipped run named between them.

    Pure and separate from the rendering for the reason :func:`rungs` is: *what the page
    admits to leaving out* is a policy worth testing without a browser.

    A gap is emitted above the top drawn rung and below the bottom one as well as between
    them — the ladder does not stop at the highest rung with a role, and a card that quietly
    ended there would be making the same claim in a different place.
    """
    drawn = rungs(slot)
    if not slot.ladder:
        return drawn

    shown = {rung.pick.tier for rung in drawn}
    by_tier = dict(slot.ladder)
    # Descending, so the ladder reads top to bottom like the rungs themselves.
    every = sorted(by_tier, reverse=True)

    rows: list[_Rung | _Gap] = []
    pending: list[int] = []

    def flush() -> None:
        if pending:
            rows.append(_Gap(tuple(pending), tuple(by_tier[tier] for tier in pending)))
            pending.clear()

    drawn_by_tier = {rung.pick.tier: rung for rung in drawn}
    for tier in every:
        if tier in shown:
            flush()
            rows.append(drawn_by_tier[tier])
        else:
            pending.append(tier)
    flush()
    return tuple(rows)


def render(view: GearView, *, has_player: bool = True) -> None:
    """The whole page."""
    ui.add_css(GEAR_CSS)

    if not view.styles:
        ui.label(EMPTY if has_player else NO_PLAYER).classes("text-sm tracker-dim")
        return

    if view.scan_note is not None:
        # A caveat over the whole page rather than a note on any one row, because that is
        # the scope of what it qualifies.
        with section("Not everything has been looked at", testid="gear-scan-note"):
            ui.label(view.scan_note).classes("text-sm")

    with ui.tabs().classes("w-full") as tabs:
        for style in view.styles:
            ui.tab(style.style, label=style.style.capitalize())
    with ui.tab_panels(tabs, value=view.styles[0].style).classes("w-full"):
        for style in view.styles:
            with ui.tab_panel(style.style):
                render_style(style)


def render_style(style: GearStyleRow) -> None:
    ui.label(style.missing_label).classes("text-sm tracker-dim mb-2")
    if not any(rung.pick.price_label for slot in style.slots for rung in rungs(slot)):
        # Once, for the ladder it is true of. See NO_PRICES.
        ui.label(NO_PRICES).classes("text-xs tracker-faint mb-2")
    for slot in style.slots:
        render_slot(slot)


def render_slot(slot: GearSlotRow) -> None:
    """One slot, drawn as the ladder it is."""
    card = section(slot.slot, testid=f"gear-slot-{slot.slot}")
    with card:
        # The card title is the slot; the ladder's depth sits beside it as data rather than
        # inside the heading, where it read as part of the slot's own name.
        ui.label(slot.ladder_label).classes("tracker-data mb-1")

        with ui.element("div").classes("rung-list"):
            for row in ladder_rows(slot):
                if isinstance(row, _Gap):
                    render_gap(row)
                else:
                    render_rung(row)

        _absent(slot)

        if slot.conflict:
            ui.label(
                "You are holding a rung above the one whose requirements are met. Both are "
                "shown rather than the higher one taken — one of the two is wrong."
            ).classes("gear-conflict")


def render_rung(rung: _Rung) -> None:
    """One notch on the rail."""
    pick = rung.pick
    element = ui.element("div").classes("rung")
    element.props(f'data-testid=gear-rung data-tier={pick.tier} data-role="{" ".join(rung.roles)}"')
    with element:
        ui.html("▸" if "best you can equip" in rung.roles else "").classes("rung-caret")
        ui.html(RUNG_GLYPH[pick.held_state]).classes("rung-mark")

        with ui.element("div"):
            with ui.element("div").classes("rung-head"):
                ui.label(pick.name).classes("rung-name")
                # Ownership, in ownership's words. Passing no label falls back to
                # STATE_LABELS, which spells these states "unlocked"/"locked" — the *fit*
                # question — and so badges a piece you can wear but do not own as locked,
                # on the very rung the page is recommending. The state is unchanged, so
                # §15's guarantee is too.
                state_badge(pick.held_state, label=pick.held_label)

            meta = [pick.rung_label, *rung.roles]
            if pick.price_label:
                meta.append(pick.price_label)
            ui.label(" · ".join(meta)).classes("rung-meta")

            # Fit and its explanation on one line — see `.rung-fit`. The badge is still the
            # one implementation from `badges.py` carrying its own `data-state`, so moving
            # where it sits changes nothing about §15's guarantee.
            if pick.fit_label or pick.note:
                with ui.element("div").classes("rung-fit"):
                    if pick.fit_label:
                        state_badge(pick.fit_state, label=pick.fit_label)
                    if pick.note:
                        ui.label(pick.note).classes("rung-note")

            # How it is obtained sits on its own line rather than joining the one above.
            # `.rung-fit` pairs a badge with the sentence that explains it, and this is a
            # third statement rather than a gloss on that one — sharing the row would read as
            # though "cannot equip yet" and "earn it from the Inferno" were one thought.
            if pick.acquire_label:
                ui.label(pick.acquire_label).classes("rung-note rung-acquire")


def render_gap(gap: _Gap) -> None:
    """A break in the rail, with what it passes over named.

    It occupies the glyph column like a rung so the rail reads as continuous-but-interrupted
    rather than as two separate ladders, and it carries **no badge and no state** — it is not
    a rung and must not be mistaken for one the account is being told something about.
    """
    element = ui.element("div").classes("rung rung-gap")
    element.props(f"data-testid=gear-gap data-skipped={len(gap.tiers)}")
    with element:
        ui.html("").classes("rung-caret")
        ui.html("⋮").classes("rung-mark")
        ui.label(gap.label).classes("rung-note")


def _absent(slot: GearSlotRow) -> None:
    """What the ladder does *not* say, said out loud.

    A rail with no gold caret on it means "nothing here qualifies", and a reader who has
    seen a caret elsewhere will read it that way — but a reader who has not seen one yet
    cannot tell that from a page that simply forgot to mark one. §4.5's whole argument is
    that a silent absence and a stated one are different claims, so the three things the
    rail cannot draw are stated rather than implied.
    """
    # When every rung has to be earned there *is* no rung to buy, and saying "nothing
    # qualifies" would be false — they qualify, and the gap is acquisition rather than
    # requirements. The ranged cape ladder is entirely in this state.
    nothing_recommended = (
        "Nothing on this ladder can be bought — every rung has to be earned."
        if slot.earn is not None
        else "Nothing on this ladder qualifies."
    )
    for pick, message in (
        (slot.recommended, nothing_recommended),
        (slot.best_held, "Nothing on this ladder has been seen."),
        (slot.next_rung, "Top of the ladder."),
    ):
        if pick is None:
            ui.label(message).classes("gear-absent")


def slot_labels(view: GearView) -> Sequence[str]:
    """Every slot on the page, in render order. Pure, so a test need not open a browser."""
    return [slot.slot for style in view.styles for slot in style.slots]
