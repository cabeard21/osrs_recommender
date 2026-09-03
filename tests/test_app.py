"""The entrypoint's two jobs: one process on one port (§5), and refusing to start (§11)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.deps import CONTENT_ATTR, PRICES_CLIENT_ATTR
from tracker.api.router import API_PREFIX
from tracker.app import create_app, startup_banner
from tracker.config.settings import Settings
from tracker.content.loader import Content, load_content
from tracker.db.models import Base
from tracker.db.session import build_engine, build_session_factory

TOKEN = "token-for-tests-1234"


@pytest.fixture(scope="session")
def content() -> Content:
    return load_content()


@pytest.fixture
def session_factory(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(f"sqlite:///{tmp_path / 'app.db'}")
    Base.metadata.create_all(engine)
    yield build_session_factory(engine)
    engine.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(bind_address="127.0.0.1", api_token=TOKEN)


# ---------------------------------------------------------------------------
# §11 — the app refuses to start on an unsafe configuration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "*"])
def test_the_app_requires_an_explicit_opt_in_to_bind_every_interface(address: str) -> None:
    """§11.1. The rejection lives in ``Settings``, so it fires before an app object exists
    unless the isolated-container opt-in is set.
    """
    with pytest.raises(ValidationError):
        Settings(bind_address=address, api_token=TOKEN)


def test_the_app_accepts_the_container_bind_opt_in() -> None:
    settings = Settings(
        bind_address="0.0.0.0",
        allow_all_interfaces=True,
        api_token=TOKEN,
    )

    assert settings.bind_address == "0.0.0.0"
    assert settings.allow_all_interfaces is True


def test_the_app_cannot_be_configured_without_a_token() -> None:
    """§11.2 — there is no unauthenticated mode to fall back to. An app that started without
    a token and served ``/api`` anyway is the exact failure the rule exists to prevent.
    """
    with pytest.raises(ValidationError):
        Settings(bind_address="127.0.0.1", api_token="")


def test_a_hostname_bind_address_is_allowed() -> None:
    """A Tailscale MagicDNS name is a legitimate bind target, so the validator rejects
    unspecified *addresses* rather than demanding an IP literal.
    """
    assert Settings(bind_address="my-host.tailnet.ts.net", api_token=TOKEN).bind_address


# ---------------------------------------------------------------------------
# §5 — one process, one port
# ---------------------------------------------------------------------------


def test_the_api_surface_is_one_application(
    settings: Settings, session_factory: sessionmaker[Session], content: Content
) -> None:
    """§5: *"the UI and the sync API are one process on one port. There is no second
    service."*

    The half of that claim testable here is that one application object carries both the
    ``/api`` router and ``/healthz``. The other half — that NiceGUI's pages answer on the
    *same* client — is asserted in ``tests/ui/test_pages_browser.py``, against the one
    mounted application this process is allowed to have.

    That restriction is NiceGUI's, not a testing convenience: ``ui.run_with`` registers page
    routes on a process-global router and installs middleware, so a second
    ``create_app(mount_ui=True)`` in one interpreter fails. Mounting here as well would make
    this file's test order decide whether ``tests/ui`` can run at all.
    """
    app = create_app(settings, session_factory=session_factory, content=content, mount_ui=False)

    paths = set(app.openapi()["paths"])
    assert f"{API_PREFIX}/sync" in paths
    assert "/healthz" in paths


def test_health_is_reachable_without_a_token(
    settings: Settings, session_factory: sessionmaker[Session], content: Content
) -> None:
    """§11.7 / A16, on the real app rather than on the API object alone."""
    app = create_app(settings, session_factory=session_factory, content=content, mount_ui=False)

    with TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        assert client.post("/api/sync", json={}).status_code == 401


def test_content_is_loaded_once_at_startup(
    settings: Settings, session_factory: sessionmaker[Session], content: Content
) -> None:
    """Authored content changes between deployments, not between requests. Loading it per
    request would let a corpus edit take effect halfway through a pipeline run, so that one
    sync evaluated its capabilities against one corpus and scored its candidates against
    another.
    """
    app = create_app(settings, session_factory=session_factory, content=content, mount_ui=False)

    assert getattr(app.state, CONTENT_ATTR) is content


def test_the_app_starts_without_a_price_client(
    settings: Settings, session_factory: sessionmaker[Session], content: Content
) -> None:
    """§7.5 — *"no user-visible failure when a cached or static fallback exists"*. Running
    with no network is a supported configuration, not a broken one.
    """
    app = create_app(settings, session_factory=session_factory, content=content, mount_ui=False)

    assert getattr(app.state, PRICES_CLIENT_ATTR) is None


def test_the_banner_names_the_bind_address(settings: Settings) -> None:
    """§11.1 makes the bind address a decision rather than a default, so an operator should
    be able to see which one is in force without opening the config file.
    """
    banner = startup_banner(settings)

    assert settings.bind_address in banner
    assert str(settings.port) in banner
