"""Bearer-token authentication for every ``/api`` route (§11.2, §11.3, A17).

§11.2 is deliberately unqualified: *all* ``/api/*`` requests require the token, **enforced
regardless of source address**. v0.1's "localhost only" and "reachable from a phone via
Tailscale" cannot both hold — Tailscale reachability means binding beyond loopback, at
which point any device on the tailnet can POST to ``/api/sync`` and rewrite account state.
"No public exposure" is a deployment property, not an access control.

This module supplies the check; :mod:`tracker.api.router` attaches it at **router** level,
which is the part that matters structurally. A per-endpoint decorator makes §11.2 true only
for as long as every future author remembers it; a router dependency makes a new
``/api/*`` route authenticated by construction, and the inheritance test in ``tests/api``
is what keeps that wiring honest.

**A rejection writes a ``SyncEvent`` (§11.3) in its own transaction.** The audit row must
survive the request that produced it, and that request is about to raise; sharing the
request's session would roll the row back together with the failure it exists to record.
"""

from __future__ import annotations

import hmac
from datetime import UTC, datetime

from fastapi import HTTPException, status
from starlette.requests import Request

from tracker.api.deps import get_session_factory, get_settings, remote_addr
from tracker.db.repository import record_sync_event
from tracker.db.session import session_scope
from tracker.domain.types import Source

_BEARER_PREFIX = "bearer "

#: What a rejected ``/api`` request is attributed to in the audit trail.
#:
#: ``Source`` has no ``unknown`` member and should not grow one for this: §6's enum
#: describes where an *observation* came from, and a rejected request produced no
#: observation. ``RUNELITE`` records the only thing actually known — which door was
#: knocked on. ``/api/sync`` exists for the companion plugin (§5, §12) and nothing else
#: posts to it, so this is the endpoint's own provenance, never a claim the caller made.
#: The caller's untrusted identity is recorded where it belongs: ``player_id = NULL`` plus
#: ``remote_addr``.
AUTH_SOURCE = Source.RUNELITE

#: §11.3 rejection reasons, recorded on the ``SyncEvent`` and *not* returned to the caller.
#: Which of the three occurred tells an operator whether the plugin is misconfigured or
#: whether someone is probing; telling the *caller* which would help only the latter.
REASON_MISSING_HEADER = "missing Authorization header"
REASON_MALFORMED_HEADER = "Authorization header is not a Bearer credential"
REASON_INVALID_TOKEN = "invalid bearer token"

#: One opaque message for all three (§11.3). The status code is the answer; the reason is
#: for the audit trail.
_UNAUTHORIZED_DETAIL = "an /api request requires a bearer token (§11.2)"


def record_rejection(
    request: Request,
    *,
    reason: str,
    payload_version: int | None = None,
    error: str | None = None,
) -> None:
    """Write the §11.3 audit row for a rejected request, in its own transaction.

    ``player_id`` is left ``NULL`` — A17. The two alternatives are both unacceptable:
    dropping the row defeats §11.3, and trusting a caller-supplied id writes
    attacker-controlled data into the audit trail.
    """
    session_factory = get_session_factory(request)
    with session_scope(session_factory) as session:
        record_sync_event(
            session,
            source=AUTH_SOURCE,
            accepted=False,
            received_at=datetime.now(UTC),
            player_id=None,
            payload_version=payload_version,
            remote_addr=remote_addr(request),
            reason=reason,
            error=error,
        )


def _extract_bearer_token(header: str | None) -> tuple[str | None, str]:
    """``(token, reason)`` — ``token`` is ``None`` when the header cannot supply one."""
    if header is None or not header.strip():
        return None, REASON_MISSING_HEADER
    if not header.lower().startswith(_BEARER_PREFIX):
        return None, REASON_MALFORMED_HEADER
    token = header[len(_BEARER_PREFIX) :].strip()
    if not token:
        return None, REASON_MALFORMED_HEADER
    return token, REASON_INVALID_TOKEN


def require_bearer_token(request: Request) -> None:
    """Reject any ``/api`` request that does not carry the configured token (§11.2, §11.3).

    ``hmac.compare_digest`` rather than ``==``: the token is a shared secret and ``==`` on
    strings short-circuits at the first differing byte. The exposure is small on a tailnet
    and the fix costs one import.
    """
    token, reason = _extract_bearer_token(request.headers.get("Authorization"))
    expected = get_settings(request).api_token

    if token is None or not hmac.compare_digest(token, expected):
        record_rejection(request, reason=reason)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_UNAUTHORIZED_DETAIL,
            headers={"WWW-Authenticate": "Bearer"},
        )
