"""Column types that keep a stored value honest about what it means.

So far this is one type, and it exists because SQLite has no native date storage. Every
``datetime`` in §6 is bound through :class:`UtcDateTime` rather than a plain
``sa.DateTime``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.engine import Dialect

__all__ = ["UtcDateTime"]


class UtcDateTime(sa.TypeDecorator[datetime]):
    """A ``DateTime`` that is timezone-aware UTC on both sides of the driver.

    **Why this is not ``sa.DateTime(timezone=True)``.** SQLite stores dates as strings and
    its SQLAlchemy dialect writes them in a format with no offset field, so ``timezone=True``
    is silently a no-op there: an aware value binds as its own wall clock and reads back
    naive. That is worse than losing the tag. A value written as ``17:29-04:00`` and one
    written as ``21:29+00:00`` are the same instant, but they store as two different strings
    and compare as four hours apart — the offset is not dropped, it is *absorbed into the
    number*.

    **Why it raises on naive input instead of assuming UTC.** A naive datetime reaching this
    boundary is a bug at its source, and the two plausible sources differ by hours:
    ``datetime.utcnow()`` (right value, missing tag) and ``datetime.now()`` (local wall
    clock). Guessing UTC silently converts the second into a timestamp that is wrong by the
    machine's offset and stays wrong forever. §4.5's entire argument rests on comparing two
    timestamps — ``now − scanned_at``, ``now − last_practiced_at``, ``now − high_trade_at``
    — and a silently shifted anchor makes freshness, staleness and price confidence all
    quietly incorrect rather than loudly broken. This is the same choice
    :meth:`tracker.domain.types.Tri.__bool__` makes one layer up: fail where the mistake is,
    not three layers downstream where the symptom is.

    On the wire the value is still a naive UTC string, so the emitted DDL is unchanged
    (``DATETIME``) and no migration is required to adopt this — only the Python-side
    contract changes.
    """

    impl = sa.DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Normalize to UTC and strip the tag, having first insisted there was one."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                f"refusing to store the naive datetime {value!r}. Every §6 timestamp is an "
                "instant, and a naive value does not name one — `datetime.utcnow()` and "
                "`datetime.now()` produce different numbers for the same moment and this "
                "layer cannot tell them apart. Pass an aware value, e.g. "
                "`datetime.now(UTC)`."
            )
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Re-attach UTC. Anything stored went through ``process_bind_param`` first."""
        if value is None:
            return None
        if value.tzinfo is not None:
            return value.astimezone(UTC)
        return value.replace(tzinfo=UTC)

    @property
    def python_type(self) -> type[datetime]:
        return datetime
