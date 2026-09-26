"""Load factual skill, quest, and item content with located diagnostics."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tracker.content.errors import ContentError, ContentLocation
from tracker.content.schema import (
    ContentModel,
    Item,
    Quest,
    Skill,
)
from tracker.content.yaml_source import line_of, load_yaml_file

DEFAULT_CONTENT_DIR = Path("content")

#: directory name → (singular label, model). Order is load order; it does not matter,
#: because every cross-object rule runs after the whole corpus is in memory.
_DIRECTORIES: tuple[tuple[str, str, type[ContentModel]], ...] = (
    ("skills", "skill", Skill),
    ("quests", "quest", Quest),
    ("items", "item", Item),
)

_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


class ContentValidationError(Exception):
    """One or more content files are invalid. Carries **every** diagnostic found."""

    def __init__(self, errors: Sequence[ContentError]) -> None:
        self.errors = tuple(errors)
        count = len(self.errors)
        noun = "problem" if count == 1 else "problems"
        detail = "\n".join(f"  - {error}" for error in self.errors)
        super().__init__(f"{count} content {noun} found:\n{detail}")


@dataclass(frozen=True)
class Content:
    """Factual authored content indexed by id, with source locations for errors."""

    skills: Mapping[str, Skill] = field(default_factory=dict)
    quests: Mapping[str, Quest] = field(default_factory=dict)
    items: Mapping[str, Item] = field(default_factory=dict)
    locations: Mapping[tuple[str, str], ContentLocation] = field(default_factory=dict)

    def location_of(self, kind: str, object_id: str) -> ContentLocation:
        """Where an object was authored; ids are unique within a kind."""
        return self.locations.get((kind, object_id), ContentLocation())

    def item_by_numeric_id(self, item_id: int) -> Item | None:
        """Reverse of ``Item.item_id`` — how an ``item:`` leaf reaches an observation."""
        for item in self.items.values():
            if item.item_id == item_id:
                return item
        return None


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_content(
    root: Path | str = DEFAULT_CONTENT_DIR,
) -> Content:
    """Parse the corpus. Raises :class:`ContentValidationError` listing every problem.

    This is parse-and-per-object validation only. Cross-object rules — referential
    integrity and unique gear rungs — are
    :func:`tracker.content.validate.validate_content`; use
    :func:`tracker.content.validate.load_and_validate` to run both.
    """
    content, errors = parse_corpus(root)
    if content is None or errors:
        fallback = ContentError("the corpus could not be loaded", ContentLocation(file=Path(root)))
        raise ContentValidationError(errors or [fallback])
    return content


def parse_corpus(
    root: Path | str = DEFAULT_CONTENT_DIR,
) -> tuple[Content | None, list[ContentError]]:
    """Parse without raising. Returns whatever loaded plus every diagnostic."""
    root = Path(root)
    errors: list[ContentError] = []

    if not root.is_dir():
        return None, [ContentError("content directory does not exist", ContentLocation(file=root))]

    indexes: dict[str, dict[str, Any]] = {name: {} for name, _, _ in _DIRECTORIES}
    locations: dict[tuple[str, str], ContentLocation] = {}

    for directory, label, model in _DIRECTORIES:
        for obj, location in _load_directory(root / directory, label, model, errors):
            object_id = getattr(obj, "id", None)
            if not isinstance(object_id, str):  # pragma: no cover — every model declares id
                errors.append(ContentError(f"{label} has no id", location))
                continue
            key = (label, object_id)
            if key in locations:
                errors.append(
                    ContentError(
                        f"duplicate {label} id {object_id!r}; already declared at "
                        f"{locations[key]}. §10.7 requires ids to be unique across every file "
                        "of a kind, not merely within one file",
                        location,
                    )
                )
                continue
            indexes[directory][object_id] = obj
            locations[key] = location

    content = Content(
        skills=indexes["skills"],
        quests=indexes["quests"],
        items=indexes["items"],
        locations=locations,
    )
    return content, errors


def _yaml_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.rglob("*") if p.suffix in _YAML_SUFFIXES and p.is_file())


def _load_directory(
    directory: Path,
    label: str,
    model: type[ContentModel],
    errors: list[ContentError],
) -> list[tuple[ContentModel, ContentLocation]]:
    loaded: list[tuple[ContentModel, ContentLocation]] = []
    for path in _yaml_files(directory):
        try:
            document = load_yaml_file(path)
        except ContentError as exc:
            errors.append(exc)
            continue
        for raw in _documents_in(document, path, label, errors):
            location = ContentLocation(file=path, line=line_of(raw))
            built = _build(model, raw, location, label, errors)
            if built is not None:
                loaded.append((built, location))
    return loaded


def _documents_in(
    document: Any, path: Path, label: str, errors: list[ContentError]
) -> Iterable[Any]:
    """A content file holds either one object or a list of them.

    Both forms exist because 23 skills in 23 files is absurd while one capability per
    file is exactly right.
    """
    if document is None:
        return []
    if isinstance(document, Mapping):
        return [document]
    if isinstance(document, list):
        for index, entry in enumerate(document):
            if not isinstance(entry, Mapping):
                errors.append(
                    ContentError(
                        f"entry {index} is a {type(entry).__name__}, expected a {label} mapping",
                        ContentLocation(file=path),
                    )
                )
        return [entry for entry in document if isinstance(entry, Mapping)]
    errors.append(
        ContentError(
            f"expected a {label} mapping or a list of them, found {type(document).__name__}",
            ContentLocation(file=path),
        )
    )
    return []


def _build(
    model: type[ContentModel],
    raw: Any,
    location: ContentLocation,
    label: str,
    errors: list[ContentError],
) -> ContentModel | None:
    """Validate one object, flattening Pydantic's report into located diagnostics."""
    context = {"file": location.file, "line": location.line}
    try:
        return model.model_validate(raw, context=context)
    except ContentError as exc:
        # A requirement-tree diagnostic: already located and already readable.
        errors.append(exc)
    except ValidationError as exc:
        identifier = raw.get("id") if isinstance(raw, Mapping) else None
        prefix = f"{label} {identifier!r}" if isinstance(identifier, str) else label
        for detail in exc.errors():
            where = ".".join(str(part) for part in detail["loc"]) or "<root>"
            errors.append(ContentError(f"{prefix}: {where}: {detail['msg']}", location))
    return None
