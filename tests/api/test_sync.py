"""``POST /api/sync`` — contract enforcement, versioning and the audit trail (§12, G8)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.sync import (
    REASON_SCHEMA_VIOLATION,
    REASON_UNPARSEABLE_BODY,
    REASON_UNSUPPORTED_VERSION,
    REASON_VERSION_MISSING,
    SUPPORTED_PAYLOAD_VERSIONS,
)
from tracker.db.models import Player, SyncEvent
from tracker.domain.types import GpSensitivity

pytestmark = pytest.mark.contract


def _post(client: TestClient, auth_header: dict[str, str], payload: Any) -> Response:
    return client.post("/api/sync", json=payload, headers=auth_header)


# ---------------------------------------------------------------------------
# The canonical payload
# ---------------------------------------------------------------------------


def test_the_canonical_payload_is_accepted_and_audited(
    client: TestClient,
    auth_header: dict[str, str],
    build_payload: Callable[..., Any],
    sync_events: Callable[[], list[SyncEvent]],
) -> None:
    response = _post(client, auth_header, build_payload())

    assert response.status_code == 202
    assert response.json()["payload_version"] == 1

    events = sync_events()
    assert len(events) == 1
    assert events[0].accepted is True
    assert events[0].payload_version == 1
    assert events[0].reason is None


def test_an_accepted_sync_names_the_player_when_the_account_is_already_known(
    client: TestClient,
    auth_header: dict[str, str],
    build_payload: Callable[..., Any],
    session_factory: sessionmaker[Session],
    now: datetime,
) -> None:
    """The username is resolved against existing rows and never used to *create* one.

    Creating the ``Player`` is Step 8b's job, because it is a merge and merges need §7.4.
    What this endpoint reports is whether the account is already known — the exact
    question a plugin author debugging a first sync is asking.
    """
    with session_factory() as session:
        session.add(
            Player(
                username="zezima",
                display_name="Zezima",
                created_at=now,
                gp_sensitivity=GpSensitivity.NORMAL,
            )
        )
        session.commit()

    response = _post(client, auth_header, build_payload())

    assert response.status_code == 202
    assert response.json()["player_id"] is not None


def test_an_unknown_username_is_accepted_with_a_null_player_id(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    response = _post(client, auth_header, build_payload())

    assert response.status_code == 202
    assert response.json()["player_id"] is None


# ---------------------------------------------------------------------------
# G8 — the collection boundary is the contract, not a convention (§7.6, §12.1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("extra_key", "extra_value"),
    [
        ("opponent_name", "SomeOtherPlayer"),
        ("opponent_names", ["SomeOtherPlayer", "AnotherPlayer"]),
        ("chat", ["gf", "ez"]),
        ("prayer_selections", ["protect_from_magic", "protect_from_missiles"]),
        ("location_ticks", [[3200, 3600], [3201, 3600]]),
        ("inventory_at_death", [{"item_id": 27690, "quantity": 1}]),
    ],
)
def test_a_practice_event_carrying_unsummarized_telemetry_is_rejected(
    client: TestClient,
    auth_header: dict[str, str],
    build_payload: Callable[..., Any],
    sync_events: Callable[[], list[SyncEvent]],
    extra_key: str,
    extra_value: Any,
) -> None:
    """**G8.** §7.6's boundary is enforced by ``additionalProperties: false``, so a plugin
    build that starts collecting more is rejected by the schema rather than by a reviewer
    noticing. Each parameter above is one of the things §7.6 names explicitly.
    """
    payload = build_payload()
    payload["practice_events"][0][extra_key] = extra_value

    response = _post(client, auth_header, payload)

    assert response.status_code == 422
    assert extra_key in response.json()["detail"]
    assert sync_events()[0].reason == REASON_SCHEMA_VIOLATION


def test_an_unknown_top_level_field_is_rejected(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """``additionalProperties: false`` at the root too — a field with no sink is a
    contract with no meaning (§7.1).
    """
    response = _post(client, auth_header, build_payload(fight_journal=[{"kills": 3}]))

    assert response.status_code == 422


def test_an_evidence_type_outside_the_enum_is_rejected(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """The enum is closed on purpose: an open string is where a richer evidence type
    arrives without anyone having decided it should.
    """
    payload = build_payload()
    payload["practice_events"][0]["evidence_type"] = "opponent_dashboard_screenshot"

    assert _post(client, auth_header, payload).status_code == 422


# ---------------------------------------------------------------------------
# §12.2 / A14 — versioning
# ---------------------------------------------------------------------------


def test_supported_versions_is_an_explicit_set() -> None:
    """§12.2, A14 — a set, not a minimum: a server may support 1 and 3 while 2 was
    withdrawn, which an interval cannot express.
    """
    assert SUPPORTED_PAYLOAD_VERSIONS == frozenset({1})


@pytest.mark.parametrize("version", [2, 99, 1_000])
def test_an_unsupported_version_is_409_and_audited(
    client: TestClient,
    auth_header: dict[str, str],
    build_payload: Callable[..., Any],
    sync_events: Callable[[], list[SyncEvent]],
    version: int,
) -> None:
    response = _post(client, auth_header, build_payload(payload_version=version))

    assert response.status_code == 409
    events = sync_events()
    assert events[0].accepted is False
    assert events[0].reason == REASON_UNSUPPORTED_VERSION
    assert events[0].payload_version == version


def test_an_unsupported_version_is_not_reported_as_a_schema_violation(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """§12.2's "rather than silently parsing a subset of fields", one step further.

    A genuinely newer payload carries fields this schema forbids, so validating before
    checking the version would report a v2 payload as a malformed v1 one and send a plugin
    author hunting a field-level bug that does not exist.
    """
    payload = build_payload(payload_version=2)
    payload["a_field_only_v2_has"] = {"anything": True}

    response = _post(client, auth_header, payload)

    assert response.status_code == 409


@pytest.mark.parametrize("version", ["1", 1.0, True, None])
def test_a_non_integer_version_is_422(
    client: TestClient,
    auth_header: dict[str, str],
    build_payload: Callable[..., Any],
    sync_events: Callable[[], list[SyncEvent]],
    version: Any,
) -> None:
    """``True`` is in the list deliberately: ``bool`` subclasses ``int`` in Python, so a
    naive ``isinstance(v, int)`` accepts it and then produces a 409 blaming the version
    number rather than its type.
    """
    response = _post(client, auth_header, build_payload(payload_version=version))

    assert response.status_code == 422
    assert sync_events()[0].reason == REASON_VERSION_MISSING


def test_a_missing_version_is_422(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    payload = build_payload()
    del payload["payload_version"]

    assert _post(client, auth_header, payload).status_code == 422


# ---------------------------------------------------------------------------
# Malformed bodies
# ---------------------------------------------------------------------------


def test_an_unparseable_body_is_400_and_audited(
    client: TestClient,
    auth_header: dict[str, str],
    sync_events: Callable[[], list[SyncEvent]],
) -> None:
    response = client.post(
        "/api/sync",
        content=b"{not json",
        headers={**auth_header, "Content-Type": "application/json"},
    )

    assert response.status_code == 400
    assert sync_events()[0].reason == REASON_UNPARSEABLE_BODY


def test_a_json_array_body_is_rejected(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """A plugin sending a *list* of snapshots is a real mistake to make, and it must fail
    before anything indexes ``payload["player"]``.
    """
    assert _post(client, auth_header, [build_payload()]).status_code == 422


# ---------------------------------------------------------------------------
# Field-level rules the contract carries for the engine's benefit
# ---------------------------------------------------------------------------


def test_unranked_xp_is_transmitted_as_null(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """G5's contract-side half. ``null`` is accepted; ``-1`` — what the hiscores return —
    is not, because normalizing it is the adapter's job (§7.3) and it must never reach a
    column where 0 and "unranked" would become the same fact.
    """
    payload = build_payload()
    assert _post(client, auth_header, payload).status_code == 202

    payload["skills"][1]["xp"] = -1
    assert _post(client, auth_header, payload).status_code == 422


def test_a_naive_timestamp_is_rejected(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """§4.5 — every age comparison needs an aware instant, and a naive value is not one.

    ``UtcDateTime`` rejects naive values at the column; the contract rejects them one
    layer earlier, where the error can still name the offending field.
    """
    response = _post(client, auth_header, build_payload(observed_at="2026-08-04T15:18:41"))

    assert response.status_code == 422


@pytest.mark.parametrize("state", ["unlocked", "available", "locked", "unknown"])
def test_every_unlock_state_is_transmissible(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any], state: str
) -> None:
    """§6.3 — all four, including ``unknown``: before the first sync the app does not
    know, and §15 renders that distinctly from ``locked``.
    """
    payload = build_payload()
    payload["unlocks"] = [{"key": "rigour", "state": state}]

    assert _post(client, auth_header, payload).status_code == 202


def test_a_container_scan_with_no_matching_items_is_transmissible(
    client: TestClient, auth_header: dict[str, str], build_payload: Callable[..., Any]
) -> None:
    """§6.5's staleness anchor: a scan of a container holding nothing tracked still
    carries a ``container_scans`` entry with no matching ``observed_items``. Without that,
    "you do not own it" and "we have never looked" are the same payload.
    """
    payload = build_payload()
    payload["observed_items"] = []

    assert _post(client, auth_header, payload).status_code == 202
