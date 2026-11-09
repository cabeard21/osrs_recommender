"""Context-local opt-in for fixed-option partial Single reports; never a public policy."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE: ContextVar[bool] = ContextVar("fixed_reporting", default=False)


def active() -> bool:
    return _ACTIVE.get()


@contextmanager
def fixed_reporting() -> Iterator[None]:
    token = _ACTIVE.set(True)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
