"""The FastAPI application object (§5, §11).

§5: *"NiceGUI runs on FastAPI/uvicorn, so the UI and the sync API are one process on one
port. There is no second service."* This module builds **the** application; Step 9 mounts
NiceGUI onto the object returned here rather than creating a second one.

Settings and the session factory are injected rather than imported, and stored on
``app.state`` for :mod:`tracker.api.deps` to read. That is what lets a test build a
complete application over a temporary database and a throwaway token without patching a
module global — the same reason ``build_engine`` in :mod:`tracker.db.session` is a
function rather than a singleton.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from tracker.api import health
from tracker.api.deps import SESSION_FACTORY_ATTR, SETTINGS_ATTR
from tracker.api.router import build_api_router
from tracker.config.settings import Settings


def create_app(settings: Settings, session_factory: sessionmaker[Session]) -> FastAPI:
    """Build the application: the authenticated ``/api`` router plus ``/healthz``.

    The two ``include_router`` calls are not interchangeable. ``build_api_router()``
    carries §11.2's authentication dependency; ``health.router`` must **not** be included
    under that prefix, or the liveness probe would require a credential (§11.7, A16).
    """
    app = FastAPI(
        title="OSRS PvP Progression Tracker",
        description="Local sync API for the RuneLite companion plugin (SDD §12).",
    )
    setattr(app.state, SETTINGS_ATTR, settings)
    setattr(app.state, SESSION_FACTORY_ATTR, session_factory)

    app.include_router(build_api_router())
    app.include_router(health.router)
    return app
