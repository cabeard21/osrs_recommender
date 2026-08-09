"""Request-scoped access to the two things every ``/api`` route needs (§5, §11).

Settings and the session factory are read off ``app.state`` rather than imported as module
globals. §5 says the UI and the sync API are **one process on one port** with no second
service, so there is exactly one application object and exactly one place for its
dependencies to live; a module-level singleton would be a second place, and the two would
disagree the first time a test built an app against a temporary database.

The indirection is also what makes the auth-inheritance test in ``tests/api`` possible: a
test can build a whole application over ``sqlite:///<tmp_path>`` with a throwaway token
and patch nothing.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from tracker.config.settings import Settings
from tracker.content.loader import Content
from tracker.integrations.prices.client import PricesClient

#: ``app.state`` attribute names. Written once here so a typo is a failure in one place
#: rather than a silently missing attribute at request time.
SETTINGS_ATTR = "settings"
SESSION_FACTORY_ATTR = "session_factory"
CONTENT_ATTR = "content"
PRICES_CLIENT_ATTR = "prices_client"


def get_settings(request: Request) -> Settings:
    """The application's :class:`Settings`, as installed by ``create_app``."""
    settings: Settings | None = getattr(request.app.state, SETTINGS_ATTR, None)
    if settings is None:  # pragma: no cover — a wiring bug, not a request-time condition
        raise RuntimeError(
            "no Settings on app.state; build the application with tracker.api.app.create_app"
        )
    return settings


def get_session_factory(request: Request) -> sessionmaker[Session]:
    """The application's session factory, as installed by ``create_app``."""
    factory: sessionmaker[Session] | None = getattr(request.app.state, SESSION_FACTORY_ATTR, None)
    if factory is None:  # pragma: no cover — see above
        raise RuntimeError(
            "no session factory on app.state; build the app with tracker.api.app.create_app"
        )
    return factory


def get_content(request: Request) -> Content:
    """The corpus, loaded once at startup by :func:`tracker.app.create_app`.

    Authored content changes between deployments, not between requests. Reloading it per
    request would let a corpus edit take effect halfway through a pipeline run, so that one
    sync evaluated its capabilities against one corpus and scored its candidates against
    another.
    """
    content: Content | None = getattr(request.app.state, CONTENT_ATTR, None)
    if content is None:
        raise RuntimeError(
            "no Content on app.state; build the app with tracker.app.create_app, which "
            "loads the corpus at startup"
        )
    return content


def get_prices_client(request: Request) -> PricesClient | None:
    """The live price client, or ``None`` when the app was started without one.

    ``None`` is a supported configuration rather than a broken one: §7.5 requires *"no
    user-visible failure when a cached or static fallback exists"*, so an app with no
    network still recommends — with its estimates flagged low-confidence by §8.4's own
    rules.
    """
    client: PricesClient | None = getattr(request.app.state, PRICES_CLIENT_ATTR, None)
    return client


def remote_addr(request: Request) -> str | None:
    """The caller's address for the §6.11 audit trail, or ``None`` behind no transport.

    Deliberately does **not** read ``X-Forwarded-For``. §11.5 rules out any public
    deployment and there is no reverse proxy in the design, so the header could only be
    caller-supplied — an attacker choosing what the audit log records about them.
    """
    return request.client.host if request.client is not None else None
