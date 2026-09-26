"""The periodic driver for :class:`~tracker.sync.worker.SingleFlightRefresher` (§5, §7.2).

``SingleFlightRefresher`` knows how to run *one* refresh safely. Nothing in it decides *when*
— that is this module, and the split is deliberate: the locking rules are worth unit-testing
without a clock, and the scheduling is worth reading without the locking.

**Why the refresh has to be periodic at all.** Two of the app's inputs arrive on their own
schedule rather than the plugin's. Prices expire on a TTL (§7.5), and Wise Old Man keeps
polling the hiscores whether or not RuneLite is open (§7.2) — which is the entire reason WOM
is in the design, since it is the only source that can advance while the plugin is silent. A
tracker that only recomputed on sync would show a player who has not launched the game today
stale price and skill facts.

**It runs in a thread, not on the event loop.** The refresh does blocking database and HTTP
work; awaiting it on uvicorn's loop would stall every websocket the UI holds open, which is
the one thing §15's live dashboard cannot tolerate. ``asyncio.to_thread`` keeps the loop free
and costs nothing, because single-flight already serializes the work.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from tracker.db.models import Player
from tracker.sync.worker import DEFAULT_INTERVAL, SingleFlightRefresher

_log = logging.getLogger(__name__)


def tracked_player_ids(session: Session) -> Sequence[int]:
    """Every known account, oldest first.

    §6.1 supports multiple characters and §17 keeps multi-character *UI* out of v1 — but the
    background refresh is not UI, and skipping a row here would mean a second character's
    prices and WOM data silently never updated. Ordering by id keeps a run deterministic.
    """
    return list(session.scalars(select(Player.id).order_by(Player.id)))


class RefreshScheduler:
    """Fires a refresh for every tracked player, forever, until cancelled."""

    def __init__(
        self,
        refresher: SingleFlightRefresher,
        session_factory: sessionmaker[Session],
        *,
        interval: timedelta = DEFAULT_INTERVAL,
    ) -> None:
        self._refresher = refresher
        self._session_factory = session_factory
        self._interval = interval
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        # Refresh **first**, then sleep. The reverse order — which this loop had — meant a
        # price was never fetched until the app had been running for a whole interval, so
        # an app opened to check account or Gear facts and closed again fetched nothing.
        # That is why `item_price` was empty on a working install: not a broken fetch, a
        # first tick an hour away.
        #
        # An immediate first tick is close to free by construction. §7.5 makes a refresh a
        # no-op while valid cached data exists ("no request at all"), so a warm cache costs
        # one TTL comparison; a cold one is exactly the case that needs filling.
        while True:
            try:
                await asyncio.to_thread(self._refresh_all)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A scheduled refresh that dies must not kill the schedule: the next tick is
                # a free retry, and an app that stopped refreshing because one WOM call threw
                # would look identical to one that was simply idle.
                _log.exception("scheduled refresh failed; continuing")
            await asyncio.sleep(self._interval.total_seconds())

    def _refresh_all(self) -> None:
        with self._session_factory() as session:
            player_ids = tracked_player_ids(session)
        for player_id in player_ids:
            outcome = self._refresher.refresh(player_id)
            if not outcome.ran:
                _log.debug("refresh skipped for player %s: %s", player_id, outcome.skipped_reason)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
