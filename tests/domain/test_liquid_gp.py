"""``PlayerState.liquid_gp`` — three states, and the middle one is the point (Step 10c).

*"You have 12M; this costs 85M"* is only sayable when someone has actually looked in the
bank. §6.5 keeps "no container has been scanned" and "a container was scanned and held no
coins" apart, and G3 forbids collapsing the first into ``0`` — so this property returns
``None``, ``0`` and a quantity, and never conflates the first two.

**Display only.** No scoring factor reads it, and the reason is recorded rather than
assumed: an ``affordable`` factor is a seventh exponent in ``ScoringWeights``, which §16.3
step 5 requires be re-tuned against the golden corpus with a human reviewing every
disagreement. Being able to *see* a number is not permission to rank on it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tracker.domain.types import (
    COINS_ITEM_ID,
    Container,
    ItemObservation,
    PlayerState,
)

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _state(*, scanned: bool, coins: int | None = None) -> PlayerState:
    observed = {}
    if coins is not None:
        observed[COINS_ITEM_ID] = ItemObservation(
            item_id=COINS_ITEM_ID,
            quantity=coins,
            containers=frozenset({Container.BANK}),
            observed_at=NOW,
        )
    return PlayerState(
        player_id=1,
        observed_items=observed,
        container_scans={Container.BANK: NOW} if scanned else {},
    )


def test_no_scan_is_unknown_and_never_zero() -> None:
    """G3's whole subject. An unscanned bank is not an empty one."""
    assert _state(scanned=False).liquid_gp is None


def test_no_scan_stays_unknown_even_when_items_were_somehow_observed() -> None:
    """The scan is the evidence that someone *looked*, not the items.

    An observation can survive a corpus change or arrive from a partial payload; the scan
    row is what §6.5 defines as the record of a look having happened, so it is the
    discriminator rather than the item list being non-empty.
    """
    assert _state(scanned=False, coins=5_000_000).liquid_gp is None


def test_a_scanned_bank_with_no_coins_is_zero_not_unknown() -> None:
    """This *is* a fact: someone looked, and there were none."""
    assert _state(scanned=True).liquid_gp == 0


def test_observed_coins_are_reported() -> None:
    assert _state(scanned=True, coins=12_000_000).liquid_gp == 12_000_000


def test_coins_are_counted_once_across_containers() -> None:
    """§6.5 already merged containers, so this must not re-add bank and inventory."""
    state = PlayerState(
        player_id=1,
        observed_items={
            COINS_ITEM_ID: ItemObservation(
                item_id=COINS_ITEM_ID,
                quantity=12_000_000,
                containers=frozenset({Container.BANK, Container.INVENTORY}),
                observed_at=NOW,
            )
        },
        container_scans={Container.BANK: NOW, Container.INVENTORY: NOW},
    )

    assert state.liquid_gp == 12_000_000


@pytest.mark.parametrize("scanned", [True, False])
def test_it_is_derived_and_therefore_cannot_drift(scanned: bool) -> None:
    """No stored field to fall out of step with the observations it summarises."""
    assert "liquid_gp" not in PlayerState.__slots__


# ---------------------------------------------------------------------------
# The note the UI renders from it
# ---------------------------------------------------------------------------


def test_the_note_is_silent_when_nobody_has_looked() -> None:
    """§4.5 showing through to the page.

    With no scan we do not know the account is poor — we know we have not looked, and
    "you cannot afford this" would be a claim about the player rather than the evidence.
    """
    from tracker.domain.types import Confidence
    from tracker.ui.view_model import recommendation_entry_row

    row = recommendation_entry_row(
        candidate_id="buy_voidwaker",
        rank=1,
        name="Buy a Voidwaker",
        is_refresher=False,
        score=1.0,
        factors={},
        reason="r",
        estimated_hours=None,
        estimated_gp=85_000_000,
        confidence=Confidence.LOW,
        liquid_gp=None,
    )

    assert row.affordability_note is None


@pytest.mark.parametrize(
    ("liquid", "cost", "expected"),
    [
        (12_000_000, 85_000_000, "you have 12M — short of the 85M this needs"),
        (12_000_000, 1_800_000, "you have 12M — covers the 1.8M this needs"),
        (0, 85_000_000, "you have 0 — short of the 85M this needs"),
    ],
)
def test_the_note_compares_what_is_held_against_what_is_needed(
    liquid: int, cost: int, expected: str
) -> None:
    from tracker.domain.types import Confidence
    from tracker.ui.view_model import recommendation_entry_row

    row = recommendation_entry_row(
        candidate_id="buy_voidwaker",
        rank=1,
        name="Buy a Voidwaker",
        is_refresher=False,
        score=1.0,
        factors={},
        reason="r",
        estimated_hours=None,
        estimated_gp=cost,
        confidence=Confidence.LOW,
        liquid_gp=liquid,
    )

    assert row.affordability_note == expected
