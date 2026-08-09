"""§11.2, §11.3, A16, A17 — authentication is structural, and rejections are audited."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tracker.api.auth import (
    REASON_INVALID_TOKEN,
    REASON_MALFORMED_HEADER,
    REASON_MISSING_HEADER,
)
from tracker.api.router import API_PREFIX, build_api_router
from tracker.db.models import SyncEvent


def test_sync_without_a_token_is_rejected(
    client: TestClient, build_payload: Callable[..., Any]
) -> None:
    """§11.2 — enforced regardless of source address, and the test client is loopback."""
    response = client.post("/api/sync", json=build_payload())

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_rejection_records_a_sync_event_with_a_null_player_id(
    client: TestClient,
    build_payload: Callable[..., Any],
    sync_events: Callable[[], list[SyncEvent]],
) -> None:
    """§11.3 + A17 — the audit row exists and claims no identity it cannot verify.

    ``player_id IS NULL`` is the assertion that matters. The payload names a username; had
    the endpoint trusted it, this row would carry attacker-supplied identity.
    """
    client.post("/api/sync", json=build_payload())

    events = sync_events()
    assert len(events) == 1
    assert events[0].player_id is None
    assert events[0].accepted is False
    assert events[0].reason == REASON_MISSING_HEADER
    assert events[0].remote_addr is not None


@pytest.mark.parametrize(
    ("header", "expected_reason"),
    [
        ({}, REASON_MISSING_HEADER),
        ({"Authorization": "   "}, REASON_MISSING_HEADER),
        ({"Authorization": "Basic dXNlcjpwYXNz"}, REASON_MALFORMED_HEADER),
        ({"Authorization": "Bearer"}, REASON_MALFORMED_HEADER),
        ({"Authorization": "Bearer "}, REASON_MALFORMED_HEADER),
        ({"Authorization": "Bearer wrong-token"}, REASON_INVALID_TOKEN),
    ],
)
def test_each_rejection_reason_is_recorded_distinctly(
    client: TestClient,
    build_payload: Callable[..., Any],
    sync_events: Callable[[], list[SyncEvent]],
    header: dict[str, str],
    expected_reason: str,
) -> None:
    """The *caller* learns only "401"; the operator learns which of the three it was.

    That distinction separates "the plugin is misconfigured" from "something is probing
    the port", and it belongs in the audit trail rather than in the response body.
    """
    response = client.post("/api/sync", json=build_payload(), headers=header)

    assert response.status_code == 401
    assert response.json()["detail"] == "an /api request requires a bearer token (§11.2)"
    assert sync_events()[0].reason == expected_reason


def test_bearer_scheme_is_matched_case_insensitively(
    client: TestClient, build_payload: Callable[..., Any], auth_header: dict[str, str]
) -> None:
    """RFC 7235 makes the scheme token case-insensitive, and a Java client may well send
    ``bearer``. Rejecting it would be a contract bug diagnosable only by packet capture.
    """
    token = auth_header["Authorization"].split(" ", 1)[1]
    response = client.post(
        "/api/sync", json=build_payload(), headers={"Authorization": f"bearer {token}"}
    )

    assert response.status_code == 202


def test_a_valid_token_is_accepted(
    client: TestClient, build_payload: Callable[..., Any], auth_header: dict[str, str]
) -> None:
    assert client.post("/api/sync", json=build_payload(), headers=auth_header).status_code == 202


def test_a_new_api_route_inherits_auth_without_being_listed_anywhere(app: FastAPI) -> None:
    """§11.2's structural claim, proved rather than asserted.

    The route below is added to a router built by ``build_api_router()`` and is named in
    no security configuration, no decorator, no allowlist. If authentication were attached
    per endpoint this would be an open ``/api`` route — precisely the failure mode §11.2
    describes: a rule that holds only "by the author remembering".
    """
    router = build_api_router()

    @router.get("/a-route-nobody-secured")
    async def unsecured_by_its_author() -> dict[str, str]:
        return {"leaked": "everything"}

    app.include_router(router)

    with TestClient(app) as client:
        response = client.get(f"{API_PREFIX}/a-route-nobody-secured")

    assert response.status_code == 401


def test_healthz_is_unauthenticated_and_outside_the_api_prefix(
    app: FastAPI, client: TestClient
) -> None:
    """§11.7, A16. Both halves matter: unauthenticated *and* not under ``/api``.

    Under the prefix it could only work by weakening §11.2, and §11.2 is absolute — which
    is the whole reason A16 moved it out.
    """
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    # Read the mounted paths from the OpenAPI document rather than walking ``app.routes``:
    # FastAPI wraps an included router in an internal node whose own ``path`` is ``None``,
    # so a naive walk finds nothing and the assertion passes vacuously.
    paths = set(app.openapi()["paths"])

    assert "/healthz" in paths
    assert f"{API_PREFIX}/sync" in paths, "the /api prefix is not what this test thinks it is"
    assert not any(path.startswith(API_PREFIX) and "healthz" in path for path in paths)
