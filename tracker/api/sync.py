"""``POST /api/sync`` — the plugin's entry point (§12, A14, A17).

This step accepts, validates and *audits*. It does not merge: §7.4's precedence rules and
the ``ContainerScan`` writes are Step 8b's, and the freshness mapping is Step 8c's. The
split is deliberate — a payload that conforms to the contract but loses a §7.4 tie should
fail Step 8b's tests, not this endpoint's.

**Rejection order matters.** ``payload_version`` is checked *before* schema validation.
§12.2 says an unsupported version is rejected with 409 "rather than silently parsing a
subset of fields" — and a genuinely newer payload will also fail this (older) schema, so
validating first would report a v2 payload as a malformed v1 one and send a plugin author
hunting a field-level bug that does not exist.

**Status codes.** 401 is §11.3 (in :mod:`tracker.api.auth`), 409 is §12.2. The SDD assigns
no code to a payload that is well-versioned but ill-shaped; 422 is used, matching what
FastAPI already returns for a body it cannot parse, so a plugin author sees one code for
"the shape is wrong" and a distinct one for "we do not speak your version".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, NoReturn

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from starlette.requests import Request

from tracker.api.auth import AUTH_SOURCE, record_rejection
from tracker.api.contract import validate_sync_payload
from tracker.api.deps import get_session_factory, remote_addr
from tracker.db.repository import get_player_by_username, record_sync_event
from tracker.db.session import session_scope

#: §12.2, A14. An explicit *set*, not a minimum: compatibility is not always an interval —
#: a server may support 1 and 3 while 2 was withdrawn. That is also why the field is a
#: plain integer with no major component.
SUPPORTED_PAYLOAD_VERSIONS: frozenset[int] = frozenset({1})

#: Spelled as a literal rather than taken from ``starlette.status``: the constant was
#: renamed there (``..._UNPROCESSABLE_ENTITY`` -> ``..._UNPROCESSABLE_CONTENT``) and using
#: either name binds this module to a version range for no benefit. The number is stable.
HTTP_422_UNPROCESSABLE = 422

REASON_UNPARSEABLE_BODY = "request body is not valid JSON"
REASON_NOT_AN_OBJECT = "request body is not a JSON object"
REASON_VERSION_MISSING = "payload_version absent or not an integer"
REASON_UNSUPPORTED_VERSION = "unsupported payload_version"
REASON_SCHEMA_VIOLATION = "payload does not conform to contracts/sync_payload.schema.json"

router = APIRouter()


class SyncAccepted(BaseModel):
    """The 202 body. Deliberately thin — the plugin needs a receipt, not a report."""

    status: str = "accepted"
    payload_version: int
    #: ``None`` when this username has no ``Player`` row yet. Creating one is Step 8b's
    #: job (it is a merge, and merges need §7.4); this endpoint only reports whether the
    #: account is already known, which is exactly the question a plugin author debugging
    #: a first sync is asking.
    player_id: int | None = None


def _reject(
    request: Request,
    *,
    status_code: int,
    reason: str,
    detail: str,
    payload_version: int | None = None,
) -> NoReturn:
    """Audit the rejection (§6.11), then fail the request."""
    record_rejection(request, reason=reason, payload_version=payload_version, error=detail)
    raise HTTPException(status_code=status_code, detail=detail)


def _payload_version(payload: dict[str, Any]) -> int | None:
    """The declared version, or ``None`` if it is absent or not an integer.

    ``bool`` is excluded explicitly: it is a subclass of ``int`` in Python, so
    ``payload_version: true`` would otherwise pass this check and then compare unequal to
    every supported version, producing a 409 that blames the version number rather than
    the type.
    """
    version = payload.get("payload_version")
    if isinstance(version, bool) or not isinstance(version, int):
        return None
    return version


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def post_sync(request: Request) -> SyncAccepted:
    """Validate a plugin snapshot against the §12.1 contract and record a ``SyncEvent``."""
    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        _reject(
            request,
            status_code=status.HTTP_400_BAD_REQUEST,
            reason=REASON_UNPARSEABLE_BODY,
            detail=f"{REASON_UNPARSEABLE_BODY}: {exc.msg} at position {exc.pos}",
        )

    if not isinstance(payload, dict):
        _reject(
            request,
            status_code=HTTP_422_UNPROCESSABLE,
            reason=REASON_NOT_AN_OBJECT,
            detail=REASON_NOT_AN_OBJECT,
        )

    version = _payload_version(payload)
    if version is None:
        _reject(
            request,
            status_code=HTTP_422_UNPROCESSABLE,
            reason=REASON_VERSION_MISSING,
            detail=REASON_VERSION_MISSING,
        )
    if version not in SUPPORTED_PAYLOAD_VERSIONS:
        supported = ", ".join(str(value) for value in sorted(SUPPORTED_PAYLOAD_VERSIONS))
        _reject(
            request,
            status_code=status.HTTP_409_CONFLICT,
            reason=REASON_UNSUPPORTED_VERSION,
            detail=f"payload_version {version} is not supported; this server speaks {supported}",
            payload_version=version,
        )

    violation = validate_sync_payload(payload)
    if violation is not None:
        _reject(
            request,
            status_code=HTTP_422_UNPROCESSABLE,
            reason=REASON_SCHEMA_VIOLATION,
            detail=violation,
            payload_version=version,
        )

    username = payload["player"]["username"]
    session_factory = get_session_factory(request)
    with session_scope(session_factory) as session:
        player = get_player_by_username(session, username)
        player_id = player.id if player is not None else None
        record_sync_event(
            session,
            source=AUTH_SOURCE,
            accepted=True,
            received_at=datetime.now(UTC),
            player_id=player_id,
            payload_version=version,
            remote_addr=remote_addr(request),
        )

    return SyncAccepted(payload_version=version, player_id=player_id)
