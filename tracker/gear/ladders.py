"""Where an account stands on each authored ladder (§10.5, §23.3).

Hoisted out of :mod:`tracker.guidance.context`, which was the first caller and is no longer
the only one. The move is the same one commit ``11d103a`` made for
:mod:`tracker.db.entry_decode`: two surfaces needed the same projection, and the second copy
is where they start to disagree. §21's note and §23's page must describe one account, and
the way to guarantee that is for them to run the same function rather than two written to
match.

**The behaviour here is frozen by §21.5.** :func:`tracker.guidance.prompt.context_hash`
hashes the rendering of the object this feeds, and stored guidance stays good only while
that rendering does not move. Adding a field is safe — the hash covers what is rendered,
not what is carried — but changing what :func:`gear_rungs` *decides* silently invalidates
every note ever written and re-bills the user for advice they already had.

Pure: no database, no network, no clock. Everything arrives as an argument.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.content.loader import Content
from tracker.content.schema import Item
from tracker.domain.types import Container, ItemObservation, PlayerState

#: Every container the plugin can scan. Absence is only evidence once all of them have been
#: looked in (§4.5), and this is the set that decides "all".
ALL_CONTAINERS: frozenset[Container] = frozenset(Container)

#: §4.5's three answers about holding something, as the words the surfaces render.
HELD = "held"
NOT_HELD = "not held"
UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Ladder:
    """One authored ladder — a style and a slot — with its rungs in order.

    ``rungs`` is sorted by ``(tier, id)``. The id tie-break can never fire, since
    :func:`tracker.content.validate._check_gear_ladders` forbids two items sharing a rung;
    it is there so a corpus bug degrades into a stable ordering rather than into a cache
    that misses at random.
    """

    style: str
    slot: str
    rungs: tuple[Item, ...]

    @property
    def size(self) -> int:
        return len(self.rungs)


@dataclass(frozen=True, slots=True)
class GearRung:
    """Where the account stands on one authored ladder — one style, one slot (§10.5).

    Two hundred items collapse to a handful of these. ``best_held`` is the highest rung the
    account has been seen wearing or banking, ``next_name`` is the rung above it, and
    ``ladder_size`` gives both a scale: *"rung 5 of 12"* says far more than *"Rune scimitar"*.

    ``certain`` is false when nothing on this ladder has been seen **and** some container has
    never been scanned. That combination is the one §4.5 cares about: it looks identical to
    owning nothing, and telling a player to go and buy their first scimitar when they are
    wearing a whip is the failure this whole section exists to prevent.
    """

    style: str
    slot: str
    ladder_size: int
    best_held: str | None = None
    best_tier: int | None = None
    next_name: str | None = None
    next_tier: int | None = None
    certain: bool = False


def build_ladders(content: Content) -> tuple[Ladder, ...]:
    """Group the equipment items into ladders, sorted so two runs cannot disagree.

    An item with no ``tier``, ``slot`` or ``style`` is not equipment on a ladder — a quest
    item, a resource, a rune — and is skipped rather than collected into a nameless group.
    """
    grouped: dict[tuple[str, str], list[Item]] = {}
    for item in content.items.values():
        if item.tier is None or item.slot is None or item.style is None:
            continue
        grouped.setdefault((item.style, item.slot), []).append(item)

    return tuple(
        Ladder(
            style=style,
            slot=slot,
            rungs=tuple(sorted(items, key=lambda item: (item.tier or 0, item.id))),
        )
        for (style, slot), items in sorted(grouped.items())
    )


def held_observation(item: Item, state: PlayerState) -> ItemObservation | None:
    """The observation for any id that counts as owning ``item`` (§10.5).

    One piece of gear wears several numeric ids — charged and uncharged, broken and locked —
    and matching only ``item_id`` is how a player holding a *charged* blowpipe is told they
    have no blowpipe. Ties break on the largest stack, then the lowest id, so two variants in
    the bank cannot make the rendering depend on set iteration order.
    """
    found = [
        observation
        for item_id in sorted(item.owned_item_ids)
        if (observation := state.observed_items.get(item_id)) is not None
        and observation.quantity > 0
    ]
    if not found:
        return None
    return max(found, key=lambda observation: (observation.quantity, -observation.item_id))


def item_state(*, held: bool, fully_scanned: bool) -> str:
    """§4.5's three states. Absence is only evidence once every container has been looked in."""
    if held:
        return HELD
    return NOT_HELD if fully_scanned else UNKNOWN


def gear_rungs(state: PlayerState, content: Content) -> tuple[GearRung, ...]:
    """Where this account stands on each authored ladder: best held, and the next rung up.

    This is the section that answers the question a player actually asks, and it exists
    because listing two hundred items cannot. A ladder collapses to two names — what they
    have and what comes next — which is both far cheaper and far more useful than the corpus
    dumped out in full.

    A ladder with nothing held is still worth a line: *"no ranged weapon on the ladder has
    been seen"* is exactly the state that produces bad advice when left unsaid, and it is
    reported as unknown rather than absent until every container has been scanned.
    """
    fully_scanned = ALL_CONTAINERS <= state.container_scans.keys()

    rungs: list[GearRung] = []
    for ladder in build_ladders(content):
        held = [item for item in ladder.rungs if held_observation(item, state) is not None]
        best = held[-1] if held else None
        following = [
            item for item in ladder.rungs if best is None or (item.tier or 0) > (best.tier or 0)
        ]
        rungs.append(
            GearRung(
                style=ladder.style,
                slot=ladder.slot,
                ladder_size=ladder.size,
                best_held=best.name if best is not None else None,
                best_tier=best.tier if best is not None else None,
                next_name=following[0].name if following else None,
                next_tier=following[0].tier if following else None,
                certain=bool(held) or fully_scanned,
            )
        )
    return tuple(rungs)
