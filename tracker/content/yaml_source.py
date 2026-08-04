"""YAML loading that remembers line numbers.

``yaml.safe_load`` discards position information, which makes every content diagnostic
"somewhere in this file". Since §10.2's canonical trap — a missing space after a colon —
is a *positional* mistake, the loader keeps the line each mapping started on so the
validator can point at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tracker.content.errors import ContentError, ContentLocation


class LineAwareMapping(dict[str, Any]):
    """A mapping that remembers the 1-based line its YAML node started on."""

    line: int = 0


class LineTrackingLoader(yaml.SafeLoader):
    """``SafeLoader`` that constructs :class:`LineAwareMapping` for every mapping."""

    def construct_yaml_map(self, node: yaml.Node) -> Any:
        data = LineAwareMapping()
        data.line = node.start_mark.line + 1
        yield data
        data.update(self.construct_mapping(node))  # type: ignore[arg-type]


LineTrackingLoader.add_constructor("tag:yaml.org,2002:map", LineTrackingLoader.construct_yaml_map)


def line_of(value: Any) -> int | None:
    """The line a parsed mapping came from, or ``None`` for anything else."""
    return value.line if isinstance(value, LineAwareMapping) else None


def load_yaml_file(path: Path) -> Any:
    """Parse one YAML file, preserving mapping line numbers.

    Raises :class:`ContentError` rather than ``yaml.YAMLError`` so callers handle a
    single exception type across parse and validation failures.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContentError(f"could not be read: {exc}", ContentLocation(file=path)) from exc
    try:
        return yaml.load(text, Loader=LineTrackingLoader)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark is not None else None
        raise ContentError(
            f"is not valid YAML: {getattr(exc, 'problem', exc)}",
            ContentLocation(file=path, line=line),
        ) from exc
