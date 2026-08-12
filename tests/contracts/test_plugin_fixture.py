"""The Python half of the cross-language contract test (plan step 12a task 4).

`plugin_sample.json` is written by the Java side — `plugin/src/test/java/.../
ContractSerializationTest.java` serializes a real `AccountSnapshot` and saves it here. This half
takes that exact file and POSTs it at the real application, so the seam is exercised end to end
by both languages against one schema file and one server.

Why the fixture rather than a hand-written payload: a payload the Python tests invent proves the
server accepts what *Python* thinks the plugin sends. Only the plugin's own serializer output
proves the plugin and the server agree. If the Java serializer changes, this file changes, and
the diff is the alarm.

These tests live in `tests/contracts/`, not `tests/api/`, because Steps 8 and 9 own the latter.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from tracker.app import create_app
from tracker.config.settings import Settings
from tracker.content.loader import Content, load_content
from tracker.db.models import Base
from tracker.db.session import build_engine, build_session_factory

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "contracts" / "sync_payload.schema.json"
FIXTURE = Path(__file__).parent / "fixtures" / "plugin_sample.json"

API_TOKEN = "test-token-1234567890"


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def content() -> Content:
    return load_content()


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'contract.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


@pytest.fixture
def client(session_factory: sessionmaker[Session], content: Content) -> Iterator[TestClient]:
    """The real application, API half only — NiceGUI may be mounted once per process."""
    app = create_app(
        Settings(bind_address="127.0.0.1", api_token=API_TOKEN),
        session_factory=session_factory,
        content=content,
        mount_ui=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_the_plugins_own_output_validates_against_the_contract(payload: dict) -> None:
    """Both languages validate the same bytes against the same schema file."""
    schema = json.loads(CONTRACT.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(payload)


def test_the_server_accepts_what_the_plugin_serializes(client: TestClient, payload: dict) -> None:
    response = client.post(
        "/api/sync",
        json=payload,
        headers={"Authorization": f"Bearer {API_TOKEN}"},
    )
    assert response.status_code == 202, response.text


def test_the_same_payload_without_a_token_is_refused(client: TestClient, payload: dict) -> None:
    """§11.2. The plugin's own guard refuses first, but the server must never rely on that."""
    response = client.post("/api/sync", json=payload)
    assert response.status_code == 401


def test_the_plugin_declares_a_payload_version_the_server_supports(payload: dict) -> None:
    """§12.2. `AccountSnapshot.PAYLOAD_VERSION` on the Java side; this is the other end of it."""
    from tracker.api.sync import SUPPORTED_PAYLOAD_VERSIONS

    assert payload["payload_version"] in SUPPORTED_PAYLOAD_VERSIONS


def test_the_fixture_carries_no_real_account_name(payload: dict) -> None:
    assert payload["player"]["username"] == "redacted"


def test_the_fixture_exercises_the_states_most_likely_to_be_inverted(payload: dict) -> None:
    """A5 and G5, the two the reconciliation flagged as easy to get backwards.

    `available` must survive the round trip as a distinct state from `unlocked` — it means
    purchasable, not owned — and an unranked skill must travel as `null`, never 0.
    """
    states = {unlock["key"]: unlock["state"] for unlock in payload["unlocks"]}
    assert states["rigour"] == "available"
    assert states["ancient_magicks"] == "unlocked"

    unranked = [skill for skill in payload["skills"] if skill["xp"] is None]
    assert unranked, "the fixture should keep exercising the nullable-xp path"
