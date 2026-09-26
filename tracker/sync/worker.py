"""Single-flight background import of WOM skills and authored Gear price facts."""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.db.models import Player
from tracker.db.persist_prices import DatabasePriceCache
from tracker.db.session import session_scope
from tracker.integrations.prices.client import PricesClient
from tracker.integrations.wise_old_man.client import WiseOldManClient
from tracker.sync.pipeline import PipelineResult, run_pipeline
from tracker.sync.wom_import import WomImportOutcome, import_wom_skills

#: How often the scheduled refresh fires. Deliberately well under the 12-hour price TTL and
#: well over any plausible WOM update rate: the poll costs nothing when nothing has expired
#: (§7.5's "no request at all while valid cached data exists" makes it a no-op), so the
#: interval only bounds how stale a price can get before someone notices.
DEFAULT_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True)
class RefreshOutcome:
    """Whether the refresh ran, and what it produced if it did.

    ``ran=False`` is not a failure. It is the expected result when a manual refresh arrives
    during a scheduled one, and the caller should render it as *"already refreshing"*
    rather than as an error (§7.5: no user-visible failure).
    """

    ran: bool
    skipped_reason: str | None = None
    result: PipelineResult | None = None
    #: What the WOM import did, when one was attempted. ``None`` means no WOM client was
    #: configured; a ``WomImportOutcome`` with ``ran=False`` means one was tried and WOM was
    #: unreachable — a distinction the UI needs, since only the second is worth reporting.
    wom: WomImportOutcome | None = None


class SingleFlightRefresher:
    """Runs the pipeline for one player, never more than one run at a time.

    A plain :class:`threading.Lock` suffices because §5 puts everything in one process. It
    is acquired non-blocking, so a contended call returns immediately instead of stacking
    up behind the run in flight.

    The §7.5 manual-refresh throttle is carried across runs on this object rather than
    rebuilt per run: it is process-lifetime state (see
    :class:`~tracker.db.persist_prices.DatabasePriceCache`), and a fresh cache each time
    would forget the throttle and thereby defeat it.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        content: Content,
        settings: Settings,
        *,
        client_factory: Callable[[], PricesClient] | None = None,
        wom_client_factory: Callable[[], WiseOldManClient] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._content = content
        self._settings = settings
        self._client_factory = client_factory
        self._wom_client_factory = wom_client_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.Lock()
        self._last_manual_refresh_at: datetime | None = None

    @property
    def busy(self) -> bool:
        """Whether a refresh is in flight.

        Advisory only — for UI copy, not for control flow, since the answer can change
        between the check and the call. Callers decide by reading :attr:`RefreshOutcome.ran`.
        """
        return self._lock.locked()

    def refresh(self, player_id: int, *, manual: bool = False) -> RefreshOutcome:
        """Refresh account and price facts, if no other refresh holds the lock."""
        if not self._lock.acquire(blocking=False):
            return RefreshOutcome(ran=False, skipped_reason="a refresh is already in flight")
        try:
            now = self._clock()
            client = self._client_factory() if self._client_factory is not None else None

            with session_scope(self._session_factory) as session:
                wom = self._import_wom(session, player_id)
                cache = DatabasePriceCache(
                    session, last_manual_refresh_at=self._last_manual_refresh_at
                )
                result = run_pipeline(
                    session,
                    content=self._content,
                    now=now,
                    player_id=player_id,
                    prices_client=client,
                    prices_settings=self._settings.integrations.prices,
                    price_cache=cache,
                    manual_price_refresh=manual,
                )
                self._last_manual_refresh_at = cache.last_manual_refresh_at()

            return RefreshOutcome(ran=True, result=result, wom=wom)
        finally:
            self._lock.release()

    def _import_wom(self, session: Session, player_id: int) -> WomImportOutcome | None:
        """Import available WOM skill facts in the same single-flight transaction."""
        if self._wom_client_factory is None:
            return None
        with self._wom_client_factory() as client:
            return import_wom_skills(session, player_id, client=client)


def main(argv: Sequence[str] | None = None) -> int:
    """One-shot refresh from the command line — ``python -m tracker.sync.worker``.

    Exists because the scheduler's first tick used to be an hour away (Step 10a), and
    because "did the price fetch work?" was until now a question nobody could answer
    without leaving the app running and then reading SQLite by hand. A command that runs
    the refresh once and prints what it wrote turns a silent integration into a checkable
    one.

    It shares the real :class:`SingleFlightRefresher`, so it takes the same lock as the
    scheduler: running this while the app is up is safe and reports "already refreshing"
    rather than issuing a second fetch for the same ids (§7.5).
    """
    import argparse

    from sqlalchemy import func, select

    from tracker.config.settings import load_settings
    from tracker.content.validate import load_and_validate
    from tracker.db.models import ItemPrice
    from tracker.db.session import build_engine, build_session_factory

    parser = argparse.ArgumentParser(
        prog="python -m tracker.sync.worker",
        description="Run one refresh now and report what it wrote.",
    )
    parser.add_argument(
        "--prices",
        action="store_true",
        help="report the price cache afterwards (the refresh always includes prices)",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    content = load_and_validate()
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)

    refresher = SingleFlightRefresher(
        session_factory,
        content,
        settings,
        client_factory=lambda: PricesClient(settings.integrations.prices),
        wom_client_factory=lambda: WiseOldManClient(settings.integrations.wise_old_man),
    )

    with session_factory() as session:
        player_ids = list(session.scalars(select(Player.id).order_by(Player.id)))

    if not player_ids:
        print("no players yet — sync RuneLite or set a username in Settings first")
        return 1

    failures = 0
    for player_id in player_ids:
        outcome = refresher.refresh(player_id, manual=True)
        if not outcome.ran:
            print(f"player {player_id}: skipped — {outcome.skipped_reason}")
            failures += 1
            continue
        written = outcome.result.prices_written if outcome.result is not None else 0
        print(f"player {player_id}: refreshed, {written} price rows written")

    if args.prices:
        with session_factory() as session:
            rows = session.scalar(select(func.count()).select_from(ItemPrice)) or 0
            latest = session.scalar(select(func.max(ItemPrice.fetched_at)))
        print(f"price cache: {rows} rows, last fetched {latest or 'never'}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
