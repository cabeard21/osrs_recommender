"""One FastAPI process for the private sync API and factual NiceGUI dashboard.

Authored Quest Cape and Gear content is loaded once at startup. The bind address and
RuneLite API token must be explicit so the sync endpoint cannot start anonymously.
"""

from __future__ import annotations

from datetime import UTC, datetime

import uvicorn
from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from tracker.api.app import create_app as create_api_app
from tracker.api.deps import CONTENT_ATTR, PRICES_CLIENT_ATTR
from tracker.config.settings import Settings, load_settings
from tracker.content.loader import Content, load_content
from tracker.db.session import build_engine, build_session_factory
from tracker.integrations.prices.client import PricesClient
from tracker.integrations.wise_old_man.client import WiseOldManClient
from tracker.sync.scheduler import RefreshScheduler
from tracker.sync.worker import SingleFlightRefresher


def create_app(
    settings: Settings | None = None,
    *,
    session_factory: sessionmaker[Session] | None = None,
    content: Content | None = None,
    prices_client: PricesClient | None = None,
    mount_ui: bool = True,
    start_scheduler: bool = False,
) -> FastAPI:
    """Build the whole application: sync API, health endpoint, and the NiceGUI UI.

    Every dependency is injectable so a test can build the real app over a temporary
    database — the same reasoning as :mod:`tracker.api.deps`. ``mount_ui`` exists because
    NiceGUI registers global page routes at import time, which makes a second mount inside
    one process an error; API-level tests do not need it and should not pay for it.
    """
    resolved = settings if settings is not None else load_settings()

    if not resolved.api_token:  # pragma: no cover — Settings already requires min_length=1
        raise RuntimeError("api_token is required (§11.2); there is no unauthenticated mode")

    factory = session_factory
    if factory is None:
        factory = build_session_factory(build_engine(resolved.database_url))

    app = create_api_app(resolved, factory)
    setattr(
        app.state,
        CONTENT_ATTR,
        content if content is not None else load_content(resolved.content_dir),
    )
    setattr(app.state, PRICES_CLIENT_ATTR, prices_client)

    from tracker.api.gear_ui import router as gear_router
    from tracker.gear.service import GearService

    app.state.gear_service = GearService(
        getattr(app.state, CONTENT_ATTR), equipment_root=resolved.content_dir / "equipment"
    )
    app.include_router(gear_router)

    from tracker.ui.gear_preview import mount_gear_preview

    mount_gear_preview(app)

    if mount_ui:
        _mount_ui(app, resolved)

    if start_scheduler:
        _attach_scheduler(app, resolved, factory, getattr(app.state, CONTENT_ATTR))

    return app


def _attach_scheduler(
    app: FastAPI,
    settings: Settings,
    session_factory: sessionmaker[Session],
    content: Content,
) -> None:
    """Start the periodic price + WOM refresh with the app, and stop it with the app.

    ``start_scheduler`` defaults to off so that importing or building the app in a test does
    not start a thread that outlives it and issues real outbound requests. ``main`` turns it
    on; that asymmetry is the point, and it mirrors ``mount_ui``.

    The client factories are passed rather than clients: each refresh opens and closes its
    own HTTP client, so a connection idle for an hour between ticks is never reused after the
    peer has forgotten it.
    """
    refresher = SingleFlightRefresher(
        session_factory,
        content,
        settings,
        client_factory=lambda: PricesClient(settings.integrations.prices),
        wom_client_factory=lambda: WiseOldManClient(settings.integrations.wise_old_man),
    )
    scheduler = RefreshScheduler(refresher, session_factory)

    @app.on_event("startup")
    async def _start_scheduler() -> None:  # pragma: no cover — exercised by the app run
        scheduler.start()

    @app.on_event("shutdown")
    async def _stop_scheduler() -> None:  # pragma: no cover — exercised by the app run
        await scheduler.stop()


def _mount_ui(app: FastAPI, settings: Settings) -> None:
    """Mount NiceGUI onto the existing FastAPI app (§5).

    The UI and the API share one application object, one port and one auth story. The views
    themselves live in :mod:`tracker.ui`; this function's whole job is that they are mounted
    onto the app rather than served beside it.

    ``storage_secret`` is the API token: NiceGUI signs its per-browser session cookie with
    it, and the app already treats that value as its one shared secret (§11.2). A second
    secret would mean either another config field nobody sets, or a random value that
    invalidates every open tab on restart.

    The imports are function-local because NiceGUI registers page routes globally at
    decoration time. Importing :mod:`tracker.ui.pages` at module scope would make the route
    table a side effect of importing ``tracker.app`` — which the API tests do with
    ``mount_ui=False`` precisely to avoid it.
    """
    from nicegui import ui

    from tracker.ui.pages import register_pages

    register_pages(app)
    ui.run_with(app, storage_secret=settings.api_token)


def startup_banner(settings: Settings, *, now: datetime | None = None) -> str:
    """The one line printed at start. It names the bind address, because §11.1 makes that a
    decision rather than a default and an operator should be able to see which one is in
    force without reading the config file.
    """
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    return (
        f"[{stamp}] OSRS tracker listening on http://{settings.bind_address}:{settings.port} "
        "(UI at /, sync API at /api/sync, health at /healthz)"
    )


def main() -> None:
    """Serve on the configured address and port (``make run``).

    ``uvicorn.run`` takes the app object rather than an import string: the bind address is
    configuration read at startup, and the reload-friendly string form would re-import this
    module in a subprocess that re-reads it anyway.
    """
    settings = load_settings()
    app = create_app(settings, start_scheduler=True)
    print(startup_banner(settings))
    uvicorn.run(app, host=settings.bind_address, port=settings.port)


if __name__ == "__main__":  # pragma: no cover
    main()
