"""A small real-server fixture for the surviving factual browser smoke."""

from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import uvicorn

from tracker.app import create_app
from tracker.config.settings import Settings
from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory


@pytest.fixture(scope="session")
def ui_base_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    database = Path(tmp_path_factory.mktemp("factual-ui")) / "ui.sqlite"
    engine = build_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    sessions = build_session_factory(engine)
    with sessions() as session:
        session.add(Player(username="player", display_name="Player", created_at=datetime.now(UTC)))
        session.commit()
    app = create_app(
        Settings(bind_address="127.0.0.1", api_token="ui-test-token-1234567890"),
        session_factory=sessions,
        mount_ui=True,
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        threading.Event().wait(0.05)
    if not server.started:
        raise RuntimeError("UI test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)
    engine.dispose()
