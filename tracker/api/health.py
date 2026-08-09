"""``GET /healthz`` — liveness, unauthenticated, **outside** ``/api`` (§11.7, A16).

The placement is the whole design. §11.2 is absolute: every ``/api/*`` request requires a
bearer token. A health check under ``/api`` would force one of two bad outcomes — qualify
rule 2 with an exception, or require a credential for a liveness probe, which defeats the
probe. Moving the endpoint out of the prefix keeps rule 2 unqualified and the check
useful.

It reports liveness only: that the process is up and serving. It deliberately does not
touch the database and does not report a version, because this is the one route with no
authentication and should therefore disclose nothing about the machine behind it (§11.5 —
there is no public deployment story, but a tailnet is not a trust boundary either).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class Health(BaseModel):
    status: str = "ok"


@router.get("/healthz")
async def healthz() -> Health:
    """Liveness. Unauthenticated by construction — this router never receives the §11.2
    dependency, because it is never included under the ``/api`` prefix.
    """
    return Health()
