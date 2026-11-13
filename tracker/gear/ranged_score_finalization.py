"""Opt-in direct finalization of already cached ranged outgoing scores."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE: ContextVar[bool] = ContextVar("ranged_score_finalization", default=False)


@contextmanager
def ranged_score_finalization() -> Iterator[None]:
    """Limit the experimental score path to the caller's execution context."""
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def active() -> bool:
    """Whether cached outgoing records can finalize lightweight ranged scores."""
    return _ACTIVE.get()
