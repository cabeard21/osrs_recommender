"""Walk ``content/``, parse every file, and build the indexed :class:`Content` object.

``Content`` lives here rather than in ``tracker/domain/`` because it indexes the
Pydantic models of :mod:`tracker.content.schema`; putting it in the domain package would
make ``tracker.domain`` and ``tracker.content`` mutually recursive. The engine depends on
both packages and neither depends on the other, which preserves §16.1's purity boundary.

Loading is **error-accumulating**, not fail-fast. A corpus with six mistakes should
report six diagnostics, because an author fixing content one error per run is the slow
version of §10.7.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from tracker.content.errors import ContentError, ContentLocation
from tracker.content.schema import (
    Candidate,
    Capability,
    ContentModel,
    Item,
    Milestone,
    Quest,
    RefresherTemplate,
    Roadmap,
    ScoringProfile,
    Skill,
    TrainingMethod,
)
from tracker.content.yaml_source import line_of, load_yaml_file

DEFAULT_CONTENT_DIR = Path("content")
DEFAULT_PROFILE_RELATIVE_PATH = Path("scoring/profile.yaml")

#: directory name → (singular label, model). Order is load order; it does not matter,
#: because every cross-object rule runs after the whole corpus is in memory.
_DIRECTORIES: tuple[tuple[str, str, type[ContentModel]], ...] = (
    ("skills", "skill", Skill),
    ("quests", "quest", Quest),
    ("items", "item", Item),
    ("milestones", "milestone", Milestone),
    ("capabilities", "capability", Capability),
    ("candidates", "candidate", Candidate),
    ("roadmaps", "roadmap", Roadmap),
    ("training_methods", "training_method", TrainingMethod),
    ("refreshers", "refresher", RefresherTemplate),
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
    """The whole authored corpus, indexed by id.

    ``locations`` maps ``(kind, id)`` back to the file and line the object came from, so
    a cross-object rule violation — a dangling reference, a cycle — can point at the
    author's file rather than at the validator.

    **Ids are unique per kind, not globally.** §10.7's *"id uniqueness across the
    corpus"* reads as one namespace, but §4.2 declares a capability ``anti_pk`` while
    §4.3 and §9.3 select a roadmap ``anti_pk``; a global rule would reject the SDD's own
    examples. "Across the corpus" therefore means across every file of a kind, as opposed
    to within a single file — which is also how ids resolve at runtime, since a
    ``capability:`` leaf never searches roadmaps.
    """

    profile: ScoringProfile
    skills: Mapping[str, Skill] = field(default_factory=dict)
    quests: Mapping[str, Quest] = field(default_factory=dict)
    items: Mapping[str, Item] = field(default_factory=dict)
    milestones: Mapping[str, Milestone] = field(default_factory=dict)
    capabilities: Mapping[str, Capability] = field(default_factory=dict)
    candidates: Mapping[str, Candidate] = field(default_factory=dict)
    roadmaps: Mapping[str, Roadmap] = field(default_factory=dict)
    training_methods: Mapping[str, TrainingMethod] = field(default_factory=dict)
    refreshers: Mapping[str, RefresherTemplate] = field(default_factory=dict)
    locations: Mapping[tuple[str, str], ContentLocation] = field(default_factory=dict)

    def location_of(self, kind: str, object_id: str) -> ContentLocation:
        """Where an object was authored. ``kind`` is the singular label — ``capability``,
        ``roadmap``, ``milestone`` — because ids are only unique within a kind."""
        return self.locations.get((kind, object_id), ContentLocation())

    def item_by_numeric_id(self, item_id: int) -> Item | None:
        """Reverse of ``Item.item_id`` — how an ``item:`` leaf reaches an observation."""
        for item in self.items.values():
            if item.item_id == item_id:
                return item
        return None

    def methods_for_skill(self, skill_id: str) -> tuple[TrainingMethod, ...]:
        """Training methods for one skill, fastest first (§8.2 step 3 picks the first
        whose requirements the player satisfies)."""
        methods = [m for m in self.training_methods.values() if m.skill == skill_id]
        return tuple(sorted(methods, key=lambda m: (-m.xp_per_hour, m.id)))

    def milestones_in_group(self, practice_group: str) -> tuple[Milestone, ...]:
        """Members of a practice group (§9.8's refresher grouping)."""
        members = [m for m in self.milestones.values() if m.practice_group == practice_group]
        return tuple(sorted(members, key=lambda m: m.id))


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_content(
    root: Path | str = DEFAULT_CONTENT_DIR,
    *,
    profile_path: Path | str | None = None,
) -> Content:
    """Parse the corpus. Raises :class:`ContentValidationError` listing every problem.

    This is parse-and-per-object validation only. Cross-object rules — referential
    integrity, uniqueness, acyclicity, κ ordering — are
    :func:`tracker.content.validate.validate_content`; use
    :func:`tracker.content.validate.load_and_validate` to run both.
    """
    content, errors = parse_corpus(root, profile_path=profile_path)
    if content is None or errors:
        fallback = ContentError("the corpus could not be loaded", ContentLocation(file=Path(root)))
        raise ContentValidationError(errors or [fallback])
    return content


def parse_corpus(
    root: Path | str = DEFAULT_CONTENT_DIR,
    *,
    profile_path: Path | str | None = None,
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

    profile = _load_profile(root, profile_path, errors)
    if profile is None:
        return None, errors

    content = Content(
        profile=profile,
        skills=indexes["skills"],
        quests=indexes["quests"],
        items=indexes["items"],
        milestones=indexes["milestones"],
        capabilities=indexes["capabilities"],
        candidates=indexes["candidates"],
        roadmaps=indexes["roadmaps"],
        training_methods=indexes["training_methods"],
        refreshers=indexes["refreshers"],
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


def _load_profile(
    root: Path, profile_path: Path | str | None, errors: list[ContentError]
) -> ScoringProfile | None:
    path = Path(profile_path) if profile_path is not None else root / DEFAULT_PROFILE_RELATIVE_PATH
    if not path.is_file():
        errors.append(
            ContentError(
                "scoring profile is missing; §9.7 requires the tuning knobs to be content",
                ContentLocation(file=path),
            )
        )
        return None
    try:
        document = load_yaml_file(path)
    except ContentError as exc:
        errors.append(exc)
        return None

    if not isinstance(document, Mapping):
        errors.append(
            ContentError(
                f"expected a mapping, found {type(document).__name__}", ContentLocation(file=path)
            )
        )
        return None

    # §9.7 shows the profile nested under a `scoring_profile:` key; accept it flat too.
    raw = document.get("scoring_profile", document)
    location = ContentLocation(file=path, line=line_of(raw))
    built = _build(ScoringProfile, raw, location, "scoring profile", errors)
    return built if isinstance(built, ScoringProfile) else None
