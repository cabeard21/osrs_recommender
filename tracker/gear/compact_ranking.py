"""Lazy exact lexical ties for immutable partial gear assignments."""

from __future__ import annotations

import json
from functools import total_ordering
from typing import Any

from tracker.gear.compact_states import AssignmentState


@total_ordering
class AssignmentTie:
    """Numeric keys decide first; retain historical JSON order on exact ties."""

    __slots__ = ("_assignment", "_identity", "_text")

    def __init__(self, assignment: AssignmentState) -> None:
        self._assignment: AssignmentState | None = assignment
        self._identity = assignment.identity
        self._text: str | None = None

    def text(self) -> str:
        if self._text is None:
            assert self._assignment is not None
            self._text = json.dumps(self._assignment.to_dict(), sort_keys=True)
            self._assignment = None
        return self._text

    def __eq__(self, other: object) -> bool:
        if isinstance(other, AssignmentTie):
            return self._identity == other._identity
        if isinstance(other, str):
            return self.text() == other
        return NotImplemented

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, AssignmentTie):
            return self._identity != other._identity and self.text() < other.text()
        if isinstance(other, str):
            return self.text() < other
        return NotImplemented
