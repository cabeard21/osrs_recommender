"""The §8.3 price cascade, resolved to one number the estimator can spend (§6.8, A19).

.. code-block:: text

    Live market price          recent high price
        |  unavailable    ->   recent low price
    Cached last-known price    cached
        |  unavailable         static hint
    Static content hint        unknown
        |  absent
    unknown

The left column is §8.3's three-layer cascade; the right column is the acquisition
selection order **within** it, and the two are the same list read at two granularities —
which is why one function implements both. The order is conservative by design: a
recommendation to *buy* something must not understate its cost, so the high (instant-buy)
price is preferred over the low, and a recent trade of either kind is preferred over a
last-known figure.

:func:`resolve_price` is the writer §6.8 says it lacks (A19): the ``selected_price_gp``,
``selection_policy`` and ``selection_reason`` columns are *output of this policy*, not
data the feed supplies, so Step 9 persists what this returns rather than recomputing it.

**The subtle rule (§8.4, D10).** Price confidence comes from the **trade timestamp**, not
from ``fetched_at``. *"Fetching today does not make a three-day-old trade fresh — this is
the same defect as ``ContainerScan`` (§6.5) one layer out."* The plausible wrong version
is a one-line ``now - record.fetched_at``: it type-checks, it reads as freshness, and it
reports ``high`` for every number the app has ever retrieved. §6.8 stores ``high_trade_at``
and ``low_trade_at`` as separate columns for no other reason than to make the right
version writable.

**Why a Protocol instead of importing ``PriceDTO``.** The DTO is a frozen dataclass and
perfectly pure, but it lives in a module that imports ``httpx``, and §16.1 forbids this
package from importing an HTTP client at all — the import, not the call, is what loses the
purity guarantee. :class:`PriceRecord` names exactly the fields the cascade reads.
``tests/integration/test_price_seam.py`` statically asserts the real ``PriceDTO``
satisfies it; without that file both halves can be green while the seam is broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from tracker.content.schema import Item
from tracker.domain.types import Confidence, PriceSelectionPolicy, PriceSourceLayer

#: §8.4's first row: a trade younger than this is ``high`` confidence.
FRESH_TRADE = timedelta(hours=24)

#: §8.4's second row: a trade at most this old is ``medium``; older is ``low``.
RECENT_TRADE = timedelta(days=7)

#: Used when an item declares no ``price_staleness_days`` (§10.5). Seven days matches
#: both §8.3's own worked example and §8.4's medium/low boundary, so an item that says
#: nothing is treated exactly as one that says ``price_staleness_days: 7``.
DEFAULT_STALENESS = timedelta(days=7)

REASON_RECENT_HIGH = "recent high price"
REASON_RECENT_LOW = "recent low price"
REASON_CACHED_HIGH = "cached last-known high price"
REASON_CACHED_LOW = "cached last-known low price"
REASON_STATIC_HINT = "static content hint"
REASON_UNKNOWN = "no price available"


class PriceRecord(Protocol):
    """The §6.8 ``ItemPrice`` fields the cascade reads.

    **Every member is a read-only ``@property``, and that is load-bearing.** A protocol
    member written as a bare annotation — ``high_price_gp: int | None`` — demands read
    *and write* access, which the frozen dataclass the price client actually returns
    cannot provide; mypy then rejects the real DTO against a protocol nothing in this
    module ever assigns to. The same trap cost this project an integration pass at the
    Step 2.5 / Step 4 seam (see ``tests/integration/test_evaluator_seam.py``).

    ``source`` is typed ``str`` rather than :class:`PriceSourceLayer` for the same
    structural reason: the client tags its DTOs with its own ``StrEnum`` whose members
    *are* strings with the same values, and a read-only ``str`` member accepts that
    subtype where an enum-typed member would demand the identical class. §6.8's own
    column is a string enum, so this is the column's type rather than a widening.
    """

    @property
    def item_id(self) -> int: ...

    @property
    def high_price_gp(self) -> int | None: ...

    @property
    def high_trade_at(self) -> datetime | None: ...

    @property
    def low_price_gp(self) -> int | None: ...

    @property
    def low_trade_at(self) -> datetime | None: ...

    @property
    def fetched_at(self) -> datetime: ...

    @property
    def source(self) -> str:
        """§6.8's ``source`` column — which layer *supplied the row*, as written by the
        provider client. Distinct from :attr:`ResolvedPrice.layer`, which is which layer
        supplied the **number**; a live fetch that returned only a stale trade lands on
        the cached layer without its row ceasing to be a live fetch."""
        ...


@dataclass(frozen=True, slots=True)
class ResolvedPrice:
    """One item's price and the provenance of that figure (§6.8, §8.3, A19).

    ``gp is None`` only in the ``unknown`` layer, and means *we have no basis at all* —
    never ``0``. A zero would flow into §9.4's ``cost_decay = exp(−gp/κ)`` as *"free"*
    and flatter the very candidates whose cost the app failed to learn (G5).
    """

    gp: int | None
    layer: PriceSourceLayer
    selection_reason: str
    confidence: Confidence
    policy: PriceSelectionPolicy = PriceSelectionPolicy.ACQUISITION_COST
    #: When the trade behind ``gp`` happened; ``None`` for a static hint or unknown.
    #: This — not ``fetched_at`` — is what ``confidence`` was derived from (D10).
    trade_at: datetime | None = None


def resolve_price(
    item: Item | None,
    record: PriceRecord | None,
    *,
    now: datetime,
    policy: PriceSelectionPolicy = PriceSelectionPolicy.ACQUISITION_COST,
) -> ResolvedPrice:
    """Run the §8.3 cascade for one item. Pure — no clock, no network, no database.

    ``record`` is whatever the caller has: the row Step 7's fetch produced, the row Step 9
    read back from storage, or ``None`` for an item never priced. Its own ``source`` tag
    decides which cascade layers it may satisfy, so a static-hint row cannot be mistaken
    for market data with the trade timestamps stripped off.

    ``item`` supplies the last layer (``fallback_price_gp``) and the per-item staleness
    window (``price_staleness_days``, §10.5). ``None`` is legal and simply removes the
    static-hint layer — an item id the corpus does not declare has no hint to offer.

    ``policy`` is recorded rather than branched on: ``ACQUISITION_COST`` is the only rule
    v1 defines (§6.8), and the order below *is* that rule. A second policy — a disposal
    estimate would invert high and low — belongs as a branch here and a member there.
    """
    window = _staleness_window(item)

    if record is not None:
        layer = _declared_layer(record)

        if layer is PriceSourceLayer.LIVE:
            # §8.3's live layer, in order. "Recent" is the item's staleness window: the
            # feed returns the *latest* trade whenever it happened, so an illiquid item's
            # "high price" can be a month old, and taking it unconditionally would report
            # a live layer that no live trade supports.
            fresh = _fresh_leg(record, now=now, window=window)
            if fresh is not None:
                gp, trade_at, reason = fresh
                return _resolved(gp, PriceSourceLayer.LIVE, reason, trade_at, now, policy)

        if layer in (PriceSourceLayer.LIVE, PriceSourceLayer.CACHED) and (
            now - record.fetched_at <= window
        ):
            # §8.3's second layer — "cached last-known price (within TTL)". A live row
            # whose trades are all stale falls through to here, which is exactly what the
            # acquisition order "recent high → recent low → **cached**" describes.
            last_known = _last_known_leg(record)
            if last_known is not None:
                gp, last_trade_at, last_reason = last_known
                return _resolved(
                    gp, PriceSourceLayer.CACHED, last_reason, last_trade_at, now, policy
                )

    if item is not None and item.fallback_price_gp is not None:
        # §8.4: a hand-authored number has no trade behind it, so it is `low` however
        # recently the file was edited. That is the whole reason confidence is
        # three-valued — a cached price from yesterday is meaningfully better than this.
        return ResolvedPrice(
            gp=item.fallback_price_gp,
            layer=PriceSourceLayer.STATIC_HINT,
            selection_reason=REASON_STATIC_HINT,
            confidence=Confidence.LOW,
            policy=policy,
        )

    return ResolvedPrice(
        gp=None,
        layer=PriceSourceLayer.UNKNOWN,
        selection_reason=REASON_UNKNOWN,
        confidence=Confidence.LOW,
        policy=policy,
    )


def price_confidence(trade_at: datetime | None, *, now: datetime) -> Confidence:
    """§8.4's table, keyed on the age of the **selected trade** (D10).

    ``trade_at is None`` — a static fallback, or no price at all — is ``low``, not
    ``unknown``: §8.4's confidence scale has three ordered levels and no fourth value for
    "no evidence". The absence is already carried by
    :attr:`ResolvedPrice.layer`.
    """
    if trade_at is None:
        return Confidence.LOW
    age = now - trade_at
    if age < FRESH_TRADE:
        return Confidence.HIGH
    if age <= RECENT_TRADE:
        return Confidence.MEDIUM
    return Confidence.LOW


def _staleness_window(item: Item | None) -> timedelta:
    """§10.5's ``price_staleness_days`` as a per-item override, else seven days.

    One window governs both "is this trade recent enough to count as live" and "is this
    row recent enough to count as cached". §7.5's 12-hour ``ttl_hours`` deliberately is
    *not* reused: that one decides whether to re-fetch, and
    :mod:`tracker.integrations.prices.cache` already applies it. Reusing it here to
    *discard* data would mean an app not opened since yesterday preferring a
    hand-authored hint over a real price from the last session.
    """
    if item is not None and item.price_staleness_days is not None:
        return timedelta(days=item.price_staleness_days)
    return DEFAULT_STALENESS


def _declared_layer(record: PriceRecord) -> PriceSourceLayer:
    """§6.8's ``source`` column, as the enum. An unrecognised value is ``unknown``.

    Not a raise: this value crosses a process boundary (a database row written by an
    older version, a provider client from another package), and the cascade's job is to
    produce the most conservative usable answer rather than to fail a recommendation run
    over a tag it does not recognise.
    """
    try:
        return PriceSourceLayer(record.source)
    except ValueError:
        return PriceSourceLayer.UNKNOWN


def _fresh_leg(
    record: PriceRecord, *, now: datetime, window: timedelta
) -> tuple[int, datetime, str] | None:
    """Recent high, then recent low (§8.3). High first is the conservative choice: it is
    the instant-buy price, which is what actually leaves the player's bank."""
    if (
        record.high_price_gp is not None
        and record.high_trade_at is not None
        and now - record.high_trade_at <= window
    ):
        return record.high_price_gp, record.high_trade_at, REASON_RECENT_HIGH
    if (
        record.low_price_gp is not None
        and record.low_trade_at is not None
        and now - record.low_trade_at <= window
    ):
        return record.low_price_gp, record.low_trade_at, REASON_RECENT_LOW
    return None


def _last_known_leg(record: PriceRecord) -> tuple[int, datetime | None, str] | None:
    """The same high-then-low preference, with no recency test — the point of the cached
    layer is that the number is old and still the best one available."""
    if record.high_price_gp is not None:
        return record.high_price_gp, record.high_trade_at, REASON_CACHED_HIGH
    if record.low_price_gp is not None:
        return record.low_price_gp, record.low_trade_at, REASON_CACHED_LOW
    return None


def _resolved(
    gp: int,
    layer: PriceSourceLayer,
    reason: str,
    trade_at: datetime | None,
    now: datetime,
    policy: PriceSelectionPolicy,
) -> ResolvedPrice:
    return ResolvedPrice(
        gp=gp,
        layer=layer,
        selection_reason=reason,
        confidence=price_confidence(trade_at, now=now),
        policy=policy,
        trade_at=trade_at,
    )
