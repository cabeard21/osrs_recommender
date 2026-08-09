"""The background refresher — periodic price TTL check, single-flight (§5, §7.5).

§5 lists a *"background sync worker"* alongside the UI and the API in one process. It
exists because the app's remote inputs arrive on their own schedule rather than on the
plugin's: WOM keeps polling the hiscores whether or not RuneLite is open (§7.2), and the
price cache expires on a clock (§7.5). Without it, a player who has not launched the game
today sees recommendations priced last week.

**Single-flight is the whole point of this module.** §7.5 allows *"at most one refresh
attempt per recommendation run"*, and a manual refresh from the UI can land while a
scheduled one is mid-flight. Two concurrent runs would issue two fetches for the same ids —
the sustained-volume pattern the provider reserves the right to limit — and, worse, would
have two pipelines writing the same ``CapabilityState`` rows from two different
``PlayerState`` reads, the loser silently overwriting the winner.

The lock is therefore around the **whole refresh**, not around the fetch: serializing only
the HTTP call would still leave two pipelines running.

A caller that finds the lock held is told so and does nothing. It does not queue and does
not wait — a refresh that is happening right now is as good as the one being asked for, and
a queue would let repeated clicking schedule exactly the work the throttle exists to prevent.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.db.persist_prices import DatabasePriceCache
from tracker.db.session import session_scope
from tracker.integrations.prices.client import PricesClient
from tracker.sync.pipeline import PipelineResult, run_pipeline

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
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._content = content
        self._settings = settings
        self._client_factory = client_factory
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
        """Recompute stages 4–7 for one player, if no other refresh holds the lock."""
        if not self._lock.acquire(blocking=False):
            return RefreshOutcome(ran=False, skipped_reason="a refresh is already in flight")
        try:
            now = self._clock()
            client = self._client_factory() if self._client_factory is not None else None

            with session_scope(self._session_factory) as session:
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

            return RefreshOutcome(ran=True, result=result)
        finally:
            self._lock.release()
