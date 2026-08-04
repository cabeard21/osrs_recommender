"""The seam between Step 7's price client and Step 5's §8.3 cascade.

``tracker.estimation.prices`` may not import ``PriceDTO``: the dataclass is pure, but it
lives in a module that imports ``httpx``, and §16.1's boundary is enforced on **imports**
rather than on calls (``tests/progression/test_import_boundary.py``). So the cascade takes
a ``typing.Protocol`` instead — and a protocol is only verified where an implementation is
actually assigned to it. Without this file, ``tracker/estimation/`` and
``tracker/integrations/`` can both be green while the real DTO does not satisfy the
protocol the estimator was written against.

That is not hypothetical here. The same seam failed once already at Step 2.5 / Step 4 (see
``test_evaluator_seam.py``): the protocol declared bare annotated attributes, which demand
read *and write* access, and the implementation was a frozen dataclass.

The static half of this check is ``make typecheck``, which covers ``tests/`` for exactly
this reason. The annotation below is the assertion; mypy is what runs it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tracker.content.schema import Item
from tracker.domain.types import Confidence, PriceSourceLayer
from tracker.estimation.prices import (
    REASON_CACHED_HIGH,
    REASON_RECENT_HIGH,
    PriceRecord,
    resolve_price,
)
from tracker.integrations.prices.client import PriceDTO, PriceSource

NOW = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

# --- the static assertion --------------------------------------------------
# Not decoration: this line is a mypy check that the concrete DTO the price client
# returns satisfies the protocol the estimator declares.
_DTO_SATISFIES_PROTOCOL: type[PriceRecord] = PriceDTO

VOIDWAKER = Item(
    id="voidwaker",
    name="Voidwaker",
    item_id=27690,
    price_mode="live",
    fallback_price_gp=85_000_000,
    price_staleness_days=7,
)


def dto(
    *,
    high_price_gp: int | None = None,
    high_trade_at: datetime | None = None,
    low_price_gp: int | None = None,
    low_trade_at: datetime | None = None,
    fetched_at: datetime = NOW,
    source: PriceSource = PriceSource.LIVE,
) -> PriceDTO:
    """A real ``PriceDTO`` — the class the provider client constructs, not a stand-in."""
    return PriceDTO(
        item_id=27690,
        high_price_gp=high_price_gp,
        high_trade_at=high_trade_at,
        low_price_gp=low_price_gp,
        low_trade_at=low_trade_at,
        provider="osrs_wiki",
        fetched_at=fetched_at,
        source=source,
    )


class TestTheRealDtoRunsTheCascade:
    def test_a_live_dto_resolves_through_the_live_layer(self) -> None:
        """Runtime half. The static half is the module-level annotation above."""
        resolved = resolve_price(
            VOIDWAKER,
            dto(high_price_gp=39_153_913, high_trade_at=NOW - timedelta(hours=2)),
            now=NOW,
        )

        assert resolved.gp == 39_153_913
        assert resolved.layer is PriceSourceLayer.LIVE
        assert resolved.selection_reason == REASON_RECENT_HIGH
        assert resolved.confidence is Confidence.HIGH

    def test_the_clients_source_strenum_maps_onto_the_domain_layer_enum(self) -> None:
        """``PriceSource`` (a ``StrEnum`` in the integrations layer) and
        ``PriceSourceLayer`` (§6.8's column vocabulary, in the domain layer) are two
        spellings of one value set. The cascade reads the tag as a plain ``str``, so this
        pins that the two sets have not drifted apart — a renamed member on either side
        would silently route every row to the ``unknown`` branch."""
        assert {source.value for source in PriceSource} == {
            layer.value for layer in PriceSourceLayer
        }

    def test_a_cached_dto_is_recognised_as_the_cached_layer(self) -> None:
        resolved = resolve_price(
            VOIDWAKER,
            dto(
                high_price_gp=41_000_000,
                high_trade_at=NOW - timedelta(days=2),
                fetched_at=NOW - timedelta(days=2),
                source=PriceSource.CACHED,
            ),
            now=NOW,
        )

        assert resolved.layer is PriceSourceLayer.CACHED
        assert resolved.selection_reason == REASON_CACHED_HIGH
        assert resolved.confidence is Confidence.MEDIUM

    def test_a_dto_the_client_built_from_a_response_with_no_trades_falls_through(self) -> None:
        """``/latest`` omits ``high``/``low`` entirely for an item with no recent trade,
        which the client turns into a DTO of ``None``s. §8.3's job is to keep going."""
        resolved = resolve_price(VOIDWAKER, dto(), now=NOW)

        assert resolved.layer is PriceSourceLayer.STATIC_HINT
        assert resolved.gp == 85_000_000
        assert resolved.confidence is Confidence.LOW

    def test_the_dto_carries_a_trade_time_distinct_from_the_fetch_time(self) -> None:
        """D10, at the seam: a DTO fetched seconds ago whose trade is five days old must
        come back ``medium``. This is the field pair §6.8 stores separately, read by the
        module that has to honour the distinction."""
        resolved = resolve_price(
            VOIDWAKER,
            dto(
                high_price_gp=39_000_000,
                high_trade_at=NOW - timedelta(days=5),
                fetched_at=NOW - timedelta(seconds=30),
            ),
            now=NOW,
        )

        assert resolved.confidence is Confidence.MEDIUM
