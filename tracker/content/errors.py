"""Content diagnostics that name a file, a line and a path inside the document.

§10.7's whole justification is that *"unvalidated YAML fails at runtime with an
unhelpful ``KeyError``, typically months later."* A diagnostic that says only
"validation failed" replaces one unhelpful error with another, so every content error
raised anywhere in ``tracker/content/`` carries a location.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ContentLocation:
    """Where in the corpus a problem was found.

    ``line`` is populated when the YAML was read through
    :mod:`tracker.content.yaml_source`, which records mapping line numbers; it is
    ``None`` for content constructed in memory (tests, synthesized refreshers).
    """

    file: Path | None = None
    line: int | None = None
    path: str | None = None
    """Dotted path within the document, e.g. ``requires.all_of[0]``."""

    def __str__(self) -> str:
        prefix = str(self.file) if self.file is not None else "<in memory>"
        if self.line is not None:
            prefix = f"{prefix}:{self.line}"
        if self.path:
            prefix = f"{prefix}: {self.path}"
        return prefix

    def with_path(self, path: str) -> ContentLocation:
        return ContentLocation(file=self.file, line=self.line, path=path)

    def with_line(self, line: int | None) -> ContentLocation:
        return ContentLocation(file=self.file, line=line, path=self.path)


class ContentError(Exception):
    """A content file is malformed, inconsistent, or violates a §10.7 rule."""

    def __init__(self, message: str, location: ContentLocation | None = None) -> None:
        self.message = message
        self.location = location or ContentLocation()
        super().__init__(f"{self.location}: {message}")


class RequirementSyntaxError(ContentError):
    """A requirement tree could not be parsed into the §10.2 grammar."""
