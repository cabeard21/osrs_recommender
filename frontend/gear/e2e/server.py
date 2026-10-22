"""Disposable real FastAPI + NiceGUI server for preview acceptance tests."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tracker.app import create_app
from tracker.config.settings import Settings
from tracker.db.models import Base, Player
from tracker.db.session import build_engine, build_session_factory

if __name__ == "__main__":
    with TemporaryDirectory(prefix="gear-preview-browser-") as directory:
        engine = build_engine(f"sqlite:///{directory}/preview.sqlite")
        Base.metadata.create_all(engine)
        factory = build_session_factory(engine)
        with factory() as session:
            session.add(
                Player(username="player", display_name="Player", created_at=datetime.now(UTC))
            )
            session.commit()
        app = create_app(
            Settings(
                bind_address="127.0.0.1",
                api_token="isolated-preview-test-token",
                content_dir=Path(__file__).resolve().parents[3] / "content",
            ),
            session_factory=factory,
        )
        uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
