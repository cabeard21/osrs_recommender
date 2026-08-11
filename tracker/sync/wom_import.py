"""The Wise Old Man importer — fetch one player's skills and merge them (§7.2, §7.4).

**Why this exists at all.** §7.2 gives WOM one job: keep skill data current *when RuneLite
is not running*. During a session RuneLite is strictly fresher and outranks WOM (§7.4), so
the import earns nothing there — its whole value is the gap. That shapes where it is called
from: the background worker (§5), never :func:`~tracker.sync.pipeline.run_pipeline`. A sync
POST is by definition a moment when the plugin just supplied better data, and firing an
outbound WOM request at exactly that moment would spend a request to learn something staler
than what is already in hand.

**Identity comes from the ``Player`` row, not from this module.** §6.11 makes ``username``
the only identity the server trusts, and :func:`~tracker.sync.merge.merge_sync_payload` is
the only thing that creates a row from a sync. The one other way a row can exist is the
settings page, where the user names the account they want tracked — that is what makes a
WOM-first bootstrap possible at all, since otherwise the app could not learn a username
without the very plugin WOM exists to cover for.

**A failed fetch is not an error here.** WOM is a third-party service reached over the
network on a schedule nobody asked for; a refresh that dies because WOM is down must not take
the price refresh or the recommendation run down with it. The outcome type says what happened
and the caller carries on, which is the same posture §7.5 takes for prices.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from tracker.db.repository import get_player
from tracker.integrations.http import CircuitBreakerOpen, RequestFailed
from tracker.integrations.wise_old_man.client import WiseOldManClient
from tracker.sync.merge import merge_wom_skills

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WomImportOutcome:
    """What one WOM import did, or why it did nothing.

    ``skills_ignored`` is the interesting field, not ``skills_written``: on an account that
    syncs RuneLite regularly, §7.4 rule 3 should be rejecting most of what WOM returns, and
    a run reporting only writes would mean precedence had stopped working.
    """

    ran: bool
    skipped_reason: str | None = None
    username: str | None = None
    skills_written: int = 0
    skills_ignored: int = 0


def import_wom_skills(
    session: Session,
    player_id: int,
    *,
    client: WiseOldManClient,
) -> WomImportOutcome:
    """Fetch this player's WOM snapshot and merge its skills. Never raises on WOM's account.

    The caller commits, matching :func:`~tracker.sync.merge.merge_sync_payload`'s contract —
    one import is one observation of one account at one instant, so the transaction boundary
    belongs to whoever owns the run.
    """
    player = get_player(session, player_id)
    if player is None:
        return WomImportOutcome(ran=False, skipped_reason="no such player")

    username = player.username
    try:
        snapshot = client.player(username)
    except (RequestFailed, CircuitBreakerOpen, httpx.HTTPError) as exc:
        # The three ways a fetch can fail to produce data, and no more. ``RequestFailed`` is
        # what the shared client actually raises once its retry schedule is exhausted, and
        # ``CircuitBreakerOpen`` is what it raises *instead of* trying — both mean "no new
        # skill data this hour". ``httpx.HTTPError`` is listed for a caller that passes a
        # client bypassing the retry helper.
        #
        # Everything else propagates on purpose. A parsing bug below is not a WOM outage, and
        # a bare ``except Exception`` here would turn every such bug into a silent no-op that
        # looked exactly like a third party being down — the failure mode that let this whole
        # integration sit unwired without anyone noticing.
        _log.warning("WOM fetch failed for %s: %s", username, exc)
        return WomImportOutcome(
            ran=False, skipped_reason=f"WOM unreachable: {exc}", username=username
        )

    entries: list[dict[str, Any]] = [
        {"skill": skill.skill, "level": skill.level, "xp": skill.xp} for skill in snapshot.skills
    ]
    outcome = merge_wom_skills(session, player_id, entries, observed_at=snapshot.observed_at)
    return WomImportOutcome(
        ran=True,
        username=username,
        skills_written=outcome.skills_written,
        skills_ignored=outcome.skills_ignored,
    )
