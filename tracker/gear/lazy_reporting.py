"""Context-local opt-in for partial Single beam reports; never a public policy."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE: ContextVar[bool] = ContextVar("lazy_reporting", default=False)


def active() -> bool:
    return _ACTIVE.get()


@contextmanager
def lazy_reporting() -> Iterator[None]:
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
