"""Disposable real FastAPI + NiceGUI server for preview acceptance tests."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from sqlalchemy import delete, update

from tracker.app import _mount_ui, create_app
from tracker.config.settings import Settings
from tracker.db.models import Base, ContainerScan, ObservedItem, Player, SkillSnapshot
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
            mount_ui=False,
        )

        @app.post("/test/reset-gear")
        def reset_gear():
            # Test-only control over this disposable database; never mounted by create_app.
            with factory() as session:
                for model in (ObservedItem, ContainerScan, SkillSnapshot):
                    session.execute(delete(model))
                session.execute(update(Player).values(last_sync_at=None))
                session.commit()
            return {"status": "reset"}

        _mount_ui(app, app.state.settings)
        uvicorn.run(app, host="127.0.0.1", port=8766, log_level="warning")
