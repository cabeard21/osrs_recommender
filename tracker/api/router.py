"""The ``/api`` router — where §11.2 stops being a convention (§11.2, A16).

One line in this module carries the rule:

    APIRouter(prefix=API_PREFIX, dependencies=[Depends(require_bearer_token)])

§11.2 requires authentication *"at the router level, not per endpoint, so a future
``/api/*`` route inherits it by construction rather than by the author remembering"*. A
route added to this router is authenticated whether or not its author has read §11 — and
``tests/api/test_auth.py`` mounts a throwaway route here precisely to prove that a route
listed nowhere in this file still inherits the dependency.

The corollary is that nothing unauthenticated may be added here. ``/healthz`` lives
outside the prefix for exactly that reason (§11.7, A16); it is included on the application
directly, in :mod:`tracker.api.app`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from tracker.api import sync
from tracker.api.auth import require_bearer_token

#: §11.2's prefix. ``/healthz`` is deliberately *not* under it (§11.7).
API_PREFIX = "/api"


def build_api_router() -> APIRouter:
    """A fresh ``/api`` router with authentication attached at router level.

    A function rather than a module-level singleton so that each application object owns
    its own router instance — a shared router would accumulate one test's throwaway routes
    into the next test's application.
    """
    router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(require_bearer_token)])
    router.include_router(sync.router)
    return router
