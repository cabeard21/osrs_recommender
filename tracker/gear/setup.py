"""The recommended gear setup: computed, never authored and never model-authored (§23.4, D17).

A ladder says which rung comes *next*. It does not say which rung the account can actually
put on, and those are different questions the moment a gate exists — a player forty Ranged
levels short of a Twisted bow is not helped by being told it is the rung above theirs.

So this module answers the second question, from three independent facts per rung:

``fit``         §9.1's three-valued evaluation of the item's wear gate (§23.2)
``held``        §4.5's three-valued answer to whether the account owns one
``obtainable``  §23.2's second axis — whether one can be got at all

They are deliberately **not** collapsed. *"You own it but cannot wear it"*, *"you can wear it
but do not own it"* and *"you can wear it and no amount of gp will buy you one"* are three
situations needing three answers, and a single "available" flag would erase the distinctions
at exactly the point they matter.

The third axis exists because the page without it recommended an Infernal cape to everybody.
That was *true* under the old rule — the cape's wear gate really is 40 Defence and nothing
else — and useless, which is a failure a rung's position cannot catch and a wear gate was
never going to.

Both axes use :class:`~tracker.domain.types.Tri` rather than a bespoke enum, and that is
worth one sentence: ``Tri`` raises on ``__bool__``, so ``if not pick.fit:`` cannot be
written. Every unknown has to be handled by name, which is the property §4.5 spends this
whole codebase defending.

**An unknown gate does not promote**, and this is a deliberate departure from §10.6's rule
that an unknown gate does not *block* a candidate. Both follow from one principle applied to
opposite polarities: never drop something from a list for want of evidence, and never assert
a capability for want of evidence. There, the output is a list and dropping an entry loses
the user something real. Here, the output is the positive claim *"you can wear this"*, and
making it from an unobserved quest is exactly the §4.5 conversion this design forbids.

**An unknown acquisition does not demote**, which looks like the opposite rule and is the
same one. The paragraph above is not a consequence of the *shape* of a three-state field; it
is a consequence of what the two errors cost, and that comparison comes out the other way on
this axis. An unknown gate demotes because being told to wear a Torva platebody you cannot
lift is a wrong claim about the account, and because half of *fit unknown* has a player-side
remedy — *sync your account* — so withholding is itself advice. An unknown acquisition has no
player-side remedy at all: it is purely a hole in the corpus, and dropping a rung on it would
withhold something the account can wear and may well own, punish the player for the author's
gap, and offer them nothing to do about it. Its worst case is a wasted trip to the Grand
Exchange rather than a false claim about what the account can do.

So the uncertainty is carried in the wording and not in the selection: an unclassified rung
stands, and every surface says the tracker has not recorded how it is obtained. Two things
keep that honest rather than merely convenient. ``tools.gear_ladders.missing_acquisitions``
makes the state unreachable for any authored rung, exactly as its sibling does for an
unauthored gate. And it is the polarity under which a corpus declaring no acquisition
anywhere behaves *identically* to one that never had the field — which is what let this land
without moving a page on the strength of an absence.

**Why this is not a §22 tool computation (D15).** Nothing here takes a hypothetical. The
inputs are the projected account and the authored corpus, the output is a projection of
them, and the advisor calls it once while freezing its snapshot rather than on demand with
model-chosen arguments. A function that could be asked *"what if my Ranged were 85"* would
be an evaluator, and D15 forbids the advisor one.

**A known divergence, recorded rather than fixed.**
:class:`tracker.progression.evaluate.Evaluator` matches an ``item:`` leaf on ``item_id``
alone, while :func:`~tracker.gear.ladders.held_observation` matches the whole
``owned_item_ids`` union (§10.5). A charged Toxic blowpipe is therefore *held* here and
*unsatisfied* as a gate. Correcting the evaluator is one line and probably right, but it
moves ``unlock_fraction``, ``proximity`` and blockers, and therefore the ranking and the
golden corpus — a §9 change, not a §23 one. Until it is made deliberately, gear gates
should prefer ``skill:`` and ``quest:`` leaves wherever they say the same thing.

Pure: no database, no network, no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tracker.content.loader import Content
from tracker.content.schema import Item
from tracker.domain.types import LeafRef, PlayerState, Tri
from tracker.gear.ladders import ALL_CONTAINERS, Ladder, build_ladders, held_observation
from tracker.progression.evaluate import Evaluator

#: Blocked or unknown rungs reported above the recommendation, per slot. Bounded because the
#: interesting ones are the near ones: a level-40 account has fifty rungs it cannot wear and
#: is served by the next two, not by all fifty.
MAX_ASPIRATIONAL = 3

#: Other held rungs below the best one, per slot. Two is enough to show a spare set exists
#: without turning a summary back into the bank listing this replaces.
MAX_ALSO_HELD = 2

#: The order styles are reported in — the order the guides are read in, and the order the
#: corpus is generated in. Fixed because §22.3 hashes the rendering.
STYLES: tuple[str, ...] = ("melee", "ranged", "magic")


@dataclass(frozen=True, slots=True)
class GearPick:
    """One rung, carrying enough to say why it was or was not chosen.

    ``item_id`` is the *content* id, not the numeric one — this is a projection for readers
    and renderers, and the numeric id is a detail of ownership matching and pricing.
    """

    item_id: str
    name: str
    tier: int
    fit: Tri
    held: Tri
    obtainable: Tri = Tri.UNKNOWN
    """§23.2's second axis: whether one can be got, as against whether one can be worn.

    ``Tri`` rather than ``bool`` for this module's usual reason — three answers, and ``Tri``
    raises on ``__bool__``, so ``if not pick.obtainable`` cannot be written and every unknown
    has to be handled by name.

    Defaults to ``UNKNOWN`` because that is what an unclassified corpus means, and because
    §23.4 does not demote on it: a caller that never sets it gets the behaviour the field
    never existed for.
    """

    acquired_from: str | None = None
    """The content that yields an untradeable piece, as the corpus authored it.

    A noun phrase, never a sentence — every surface composes it into one. ``None`` on an
    untradeable piece is legal and means the corpus knows you cannot buy it and has not
    recorded what wins it (§10.5).
    """

    blockers: tuple[LeafRef, ...] = ()
    """What is missing, when ``fit`` is UNSATISFIED. Empty otherwise."""

    unknowns: tuple[LeafRef, ...] = ()
    """What nobody has observed, when ``fit`` is UNKNOWN. Empty otherwise."""

    gate_unknown: bool = False
    """True when the *corpus* has no gate for this item, as against the account lacking one.

    Both render as ``fit`` UNKNOWN and they are not the same thing: one is *"sync your
    account"*, the other is *"nobody has written this requirement down"*. Telling a player
    to log in and refresh when the gap is in the corpus would waste their time.
    """

    price_gp: int | None = None
    """Cached only, and ``None`` is *no cached price* — never zero (§7.5, §8.3)."""


@dataclass(frozen=True, slots=True)
class SetupSlot:
    """One slot of one style: what to wear, what is owned, and what comes next."""

    style: str
    slot: str
    ladder_size: int
    recommended: GearPick | None = None
    """The highest rung whose gate is satisfied. The answer to *"what should I wear"*."""

    best_held: GearPick | None = None
    """The highest rung actually owned. Computed independently of ``recommended``."""

    next_rung: GearPick | None = None
    """The lowest rung above ``recommended``, whatever its gate, with what it needs."""

    earn: GearPick | None = None
    """The lowest rung above ``recommended`` that fits and must be won — a target, not a buy.

    *Lowest*, for the reason :data:`MAX_ASPIRATIONAL` is bounded at all: an account with no
    cape is served by the Fight Caves, not by the Inferno. It walks itself, too — once the
    Fire cape is held it becomes ``recommended`` and this advances one rung — so nothing here
    has to decide how far ahead to look.

    Never priced. A gp figure beside something the market does not sell is a number inviting
    an action nobody can take.
    """

    aspirational: tuple[GearPick, ...] = ()
    also_held: tuple[GearPick, ...] = ()

    rungs: tuple[GearPick, ...] = ()
    """Every rung on the ladder, lowest first — the thing the fields above are views of.

    Carried because a surface that draws only the role-bearing rungs cannot say **what it
    left out**, and one that announces *"11 rungs"* while drawing four has made a silent cut.
    §22.2's rule that a cut list must say it was cut is not a property of the advisor's prose;
    it is a property of any bounded projection, and until this existed the gear page had no
    way to obey it.

    Free to carry: :func:`_slot_plan` already evaluates every rung in order to choose among
    them, so this is the list it was discarding. Nothing here widens what a surface *shows* —
    the roles still decide that — it only lets one describe the remainder.
    """

    certain: bool = True
    """False when nothing here has been seen *and* some container was never scanned (§4.5)."""

    @property
    def holds_what_it_cannot_wear(self) -> bool:
        """They own a rung above the one they can equip — or the corpus is wrong about one.

        Reported rather than resolved. Silently taking the higher of the two would hide a
        transcription error behind a plausible answer, and the case is rare enough that
        showing both is cheap and tells the reader something true.
        """
        if self.best_held is None or self.recommended is None:
            return False
        return self.best_held.tier > self.recommended.tier


@dataclass(frozen=True, slots=True)
class GearSetup:
    """One style's whole setup, slots in a fixed order."""

    style: str
    slots: tuple[SetupSlot, ...] = ()

    @property
    def missing(self) -> tuple[GearPick, ...]:
        """The recommended pieces this account is not already holding.

        *Not* the rungs above the recommendation. A rung above it that the account could
        equip would **be** the recommendation — the selection rule takes the highest
        satisfied one — so "the next rung, if it were reachable" describes the empty set.
        The buyable thing is the gap between what is recommended and what is owned.

        A piece whose ownership is UNKNOWN is counted as missing, and that is the direction
        to err in: quoting a price for something they might already have wastes a moment,
        while omitting it understates the bill.

        **This can no longer contain something no amount of gp can buy, and it gets that from
        the selection rule rather than from a filter of its own.** A recommended piece is
        held-or-obtainable, so an *unheld* recommended piece is obtainable by construction. A
        second "do not count this" test here would have been one more thing to keep in step
        with :func:`_slot_plan`, and the two would eventually have disagreed — which is the
        argument for narrowing ``recommended`` rather than adding a parallel field beside it.
        """
        return tuple(
            slot.recommended
            for slot in self.slots
            if slot.recommended is not None and slot.recommended.held is not Tri.SATISFIED
        )

    @property
    def to_complete_gp(self) -> int | None:
        """What :attr:`missing` costs, or ``None`` if any of it has no cached price.

        Deliberately not a partial sum. A total assembled from the four prices that happened
        to be cached reads as *the* cost and understates it by however many were absent — a
        wrong number stated confidently, which §23.4 ranks as worse than no number at all.
        """
        wanted = self.missing
        if not wanted or any(pick.price_gp is None for pick in wanted):
            return None
        return sum(pick.price_gp or 0 for pick in wanted)


@dataclass(frozen=True, slots=True)
class GearProgress:
    """Every style's setup, plus the scan state every reader of it needs."""

    setups: tuple[GearSetup, ...] = ()
    fully_scanned: bool = False
    scanned_containers: tuple[str, ...] = ()

    def setup(self, style: str) -> GearSetup | None:
        return next((setup for setup in self.setups if setup.style == style), None)


def gear_progress(
    state: PlayerState,
    content: Content,
    *,
    prices: Mapping[int, int | None] = MappingProxyType({}),
) -> GearProgress:
    """The whole computed setup, one entry per style.

    ``prices`` is injected rather than read, keyed on the numeric ``item_id`` alone —
    pricing uses that id and never the ownership union (§10.5). Keeping the source out of
    this module is what lets the UI feed it from ``ItemPrice`` rows and the advisor feed it
    from its snapshot without either type leaking into the other.

    One :class:`~tracker.progression.evaluate.Evaluator` for the whole call, so the
    capability memoisation is shared across all two hundred rungs rather than rebuilt per
    item.
    """
    fully_scanned = ALL_CONTAINERS <= state.container_scans.keys()
    evaluator = Evaluator(state, content)
    ladders = build_ladders(content)

    setups: list[GearSetup] = []
    for style in STYLES:
        slots = tuple(
            _slot_plan(ladder, state, evaluator, prices, fully_scanned=fully_scanned)
            for ladder in ladders
            if ladder.style == style
        )
        if slots:
            setups.append(GearSetup(style=style, slots=slots))

    return GearProgress(
        setups=tuple(setups),
        fully_scanned=fully_scanned,
        scanned_containers=tuple(sorted(container.value for container in state.container_scans)),
    )


def _slot_plan(
    ladder: Ladder,
    state: PlayerState,
    evaluator: Evaluator,
    prices: Mapping[int, int | None],
    *,
    fully_scanned: bool,
) -> SetupSlot:
    """§23.4's selection rule for one ladder, in the order the rule states it."""
    picks = [
        _pick(item, state, evaluator, prices, fully_scanned=fully_scanned) for item in ladder.rungs
    ]

    # The recommendation is the highest rung that fits *and* can be got — see the module
    # notes on why an unknown gate does not promote into this and an unknown acquisition does
    # not demote out of it. The asymmetry between `is SATISFIED` and `is not UNSATISFIED` is
    # the whole of that second note, in one line.
    recommended = next(
        (
            pick
            for pick in reversed(picks)
            if pick.fit is Tri.SATISFIED and pick.obtainable is not Tri.UNSATISFIED
        ),
        None,
    )

    # Ownership is computed independently, so "owns what they cannot wear" stays visible.
    held = [pick for pick in picks if pick.held is Tri.SATISFIED]
    best_held = held[-1] if held else None

    # The next rung is the lowest above the recommendation, gate or no gate: a player is
    # better served by "Dragon scimitar — needs 60 Attack" than by silence.
    above = [pick for pick in picks if recommended is None or pick.tier > recommended.tier]
    next_rung = above[0] if above else None

    # The nearest thing they could already wear if they went and won it. Lowest rather than
    # highest — see the field's own note.
    earn = next(
        (
            pick
            for pick in above
            if pick.fit is Tri.SATISFIED and pick.obtainable is Tri.UNSATISFIED
        ),
        None,
    )

    # A rung above the recommendation now fails to be it for two reasons rather than one, and
    # the filter has to widen with the rule or an untradeable rung would sit above the
    # recommendation and be named by nothing.
    aspirational = tuple(
        pick
        for pick in above
        if pick.fit is not Tri.SATISFIED or pick.obtainable is Tri.UNSATISFIED
    )

    return SetupSlot(
        style=ladder.style,
        slot=ladder.slot,
        ladder_size=ladder.size,
        recommended=recommended,
        best_held=best_held,
        next_rung=next_rung,
        earn=earn,
        aspirational=aspirational[:MAX_ASPIRATIONAL],
        also_held=tuple(reversed(held[:-1]))[:MAX_ALSO_HELD],
        rungs=tuple(picks),
        certain=bool(held) or fully_scanned,
    )


def _pick(
    item: Item,
    state: PlayerState,
    evaluator: Evaluator,
    prices: Mapping[int, int | None],
    *,
    fully_scanned: bool,
) -> GearPick:
    """One rung's two answers, plus its price and the reasons behind an unsatisfied gate."""
    blockers: tuple[LeafRef, ...] = ()
    unknowns: tuple[LeafRef, ...] = ()

    if item.gate_unknown:
        # The corpus has no gate for this item. Not the same as "no gate", and not the same
        # as the account being unsynced, so it gets its own flag and its own sentence.
        fit = Tri.UNKNOWN
    elif item.requires is None:
        fit = Tri.SATISFIED
    else:
        result = evaluator.evaluate(item.requires)
        fit = result.value
        blockers = result.blockers if fit is Tri.UNSATISFIED else ()
        unknowns = result.unknowns if fit is Tri.UNKNOWN else ()

    held = (
        Tri.SATISFIED
        if held_observation(item, state) is not None
        else (Tri.UNSATISFIED if fully_scanned else Tri.UNKNOWN)
    )

    if held is Tri.SATISFIED:
        # Already in the bank, so how one is *acquired* is a settled question whatever the
        # corpus says about buying one. This branch is what keeps a player who owns an
        # Infernal cape being told to wear it: the axis exists to remove advice nobody can
        # act on, and "wear the one you own" is the most actionable sentence on the page.
        obtainable = Tri.SATISFIED
    elif item.acquisition == "tradeable":
        obtainable = Tri.SATISFIED
    elif item.acquisition == "untradeable":
        obtainable = Tri.UNSATISFIED
    else:
        obtainable = Tri.UNKNOWN

    return GearPick(
        item_id=item.id,
        name=item.name,
        tier=item.tier or 0,
        fit=fit,
        held=held,
        obtainable=obtainable,
        acquired_from=item.acquired_from,
        blockers=blockers,
        unknowns=unknowns,
        gate_unknown=item.gate_unknown,
        price_gp=prices.get(item.item_id) if item.item_id is not None else None,
    )
