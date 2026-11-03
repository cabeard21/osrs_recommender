"""Typed requirement trees for factual account and Gear gates.

Requirements need boolean structure — *"Barrows gloves **or** rune gloves"*, *"Voidwaker
**or** AGS"* — which a flat list cannot express. The grammar is closed:

* **Leaves:** ``skill``, ``unlock``, ``quest``, ``item``, ``combat_level``,
  ``quest_points``, ``account_type``, ``members``
* **Combinators:** ``all_of``, ``any_of``, ``not``, ``at_least: {n, of: [...]}``

Adding a leaf type is a code change; adding a quest to the factual registry is not.

Every node is a single-key mapping in YAML, so parsing is a dispatch on that key. The
parser is hand-written rather than delegated to Pydantic's union machinery because the
error messages are the point: §10.2 calls out that ``skill: {magic:94}`` — no space after
the colon — parses as the *string* ``"magic:94"``, and that the v0.1 draft shipped this
bug twice. A generic "input should be a valid dictionary" would not have caught it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tracker.content.errors import ContentLocation, RequirementSyntaxError
from tracker.content.yaml_source import line_of


class RequirementNode(BaseModel):
    """Base for every AST node. Frozen — content is immutable once loaded."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    def to_yaml(self) -> dict[str, Any]:
        """Render back to the §10.2 mapping form. Round-trips through :func:`parse`."""
        raise NotImplementedError  # pragma: no cover — every concrete node overrides


# ---------------------------------------------------------------------------
# Leaves
# ---------------------------------------------------------------------------


class SkillLeaf(RequirementNode):
    """``skill: {magic: 94}``"""

    type: Literal["skill"] = "skill"
    skill: str
    level: int = Field(ge=1, le=99)

    def to_yaml(self) -> dict[str, Any]:
        return {"skill": {self.skill: self.level}}


class UnlockLeaf(RequirementNode):
    """``unlock: ancient_magicks``. Also covers ``spellbook_*``/``diary_*``/``ca_*`` (§6.3)."""

    type: Literal["unlock"] = "unlock"
    key: str

    def to_yaml(self) -> dict[str, Any]:
        return {"unlock": self.key}


class QuestLeaf(RequirementNode):
    """``quest: desert_treasure_i``"""

    type: Literal["quest"] = "quest"
    quest_id: str
    status: Literal["in_progress", "complete"] = "complete"

    def to_yaml(self) -> dict[str, Any]:
        if self.status == "complete":
            return {"quest": self.quest_id}
        return {"quest": {"id": self.quest_id, "status": self.status}}


class ItemLeaf(RequirementNode):
    """``item: voidwaker`` — the *content* item id, not the numeric OSRS id (§10.5)."""

    type: Literal["item"] = "item"
    item_id: str

    def to_yaml(self) -> dict[str, Any]:
        return {"item": self.item_id}


class CombatLevelLeaf(RequirementNode):
    """``combat_level: 100``"""

    type: Literal["combat_level"] = "combat_level"
    level: int = Field(ge=3, le=126)

    def to_yaml(self) -> dict[str, Any]:
        return {"combat_level": self.level}


class QuestPointsLeaf(RequirementNode):
    """``quest_points: 150``"""

    type: Literal["quest_points"] = "quest_points"
    points: int = Field(ge=0)

    def to_yaml(self) -> dict[str, Any]:
        return {"quest_points": self.points}


class AccountTypeLeaf(RequirementNode):
    """``account_type: main``

    A new leaf type rather than a reused ``unlock:`` key, and §10.8 explicitly allows a
    new leaf type as a legitimate code change. Reusing ``unlock:`` would be wrong twice:
    §6.3's unlock keys are plugin-sourced facts with reserved prefixes, and an ironman is
    not something an account *unlocked* — it is a constraint it was created under, and one
    that removes options rather than granting them.
    """

    type: Literal["account_type"] = "account_type"
    account_type: str

    def to_yaml(self) -> dict[str, Any]:
        return {"account_type": self.account_type}


class MembersLeaf(RequirementNode):
    """``members: true``"""

    type: Literal["members"] = "members"
    members: bool

    def to_yaml(self) -> dict[str, Any]:
        return {"members": self.members}


# ---------------------------------------------------------------------------
# Combinators
# ---------------------------------------------------------------------------


class AllOf(RequirementNode):
    """``all_of: [...]`` — Kleene conjunction (§9.1)."""

    type: Literal["all_of"] = "all_of"
    children: tuple[Requirement, ...] = Field(min_length=1)

    def to_yaml(self) -> dict[str, Any]:
        return {"all_of": [child.to_yaml() for child in self.children]}


class AnyOf(RequirementNode):
    """``any_of: [...]`` — Kleene disjunction (§9.1)."""

    type: Literal["any_of"] = "any_of"
    children: tuple[Requirement, ...] = Field(min_length=1)

    def to_yaml(self) -> dict[str, Any]:
        return {"any_of": [child.to_yaml() for child in self.children]}


class Not(RequirementNode):
    """``not: <requirement>`` — swaps satisfied/unsatisfied; unknown maps to unknown."""

    type: Literal["not"] = "not"
    child: Requirement

    def to_yaml(self) -> dict[str, Any]:
        return {"not": self.child.to_yaml()}


class AtLeast(RequirementNode):
    """``at_least: {n: 2, of: [...]}``"""

    type: Literal["at_least"] = "at_least"
    n: int = Field(ge=1)
    of: tuple[Requirement, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _n_is_reachable(self) -> AtLeast:
        if self.n > len(self.of):
            raise ValueError(
                f"at_least requires n={self.n} of only {len(self.of)} alternatives, "
                "which can never be satisfied"
            )
        return self

    def to_yaml(self) -> dict[str, Any]:
        return {"at_least": {"n": self.n, "of": [child.to_yaml() for child in self.of]}}


Requirement = Annotated[
    SkillLeaf
    | UnlockLeaf
    | QuestLeaf
    | ItemLeaf
    | CombatLevelLeaf
    | QuestPointsLeaf
    | AccountTypeLeaf
    | MembersLeaf
    | AllOf
    | AnyOf
    | Not
    | AtLeast,
    Field(discriminator="type"),
]

for _model in (AllOf, AnyOf, Not, AtLeast):
    _model.model_rebuild()

LEAF_TYPES: frozenset[str] = frozenset(
    {
        "skill",
        "unlock",
        "quest",
        "item",
        "combat_level",
        "quest_points",
        "account_type",
        "members",
    }
)
COMBINATOR_TYPES: frozenset[str] = frozenset({"all_of", "any_of", "not", "at_least"})
REQUIREMENT_TYPES: frozenset[str] = LEAF_TYPES | COMBINATOR_TYPES


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_MISSING_SPACE_HINT = (
    "YAML requires a space after the colon: `{magic: 94}` is a mapping, but `{magic:94}` "
    "is the string 'magic:94' (§10.2)"
)

#: (value, file, path, location) -> Requirement
_NodeParser = Callable[[Any, "Path | None", str, ContentLocation], "Requirement"]


def parse(
    raw: Any,
    *,
    file: Path | None = None,
    path: str = "requires",
    line: int | None = None,
) -> Requirement:
    """Parse one node of the §10.2 grammar.

    ``file``, ``path`` and ``line`` are threaded through purely so a failure points at
    the offending place in the corpus rather than at this module.
    """
    location = ContentLocation(file=file, line=line_of(raw) or line, path=path)

    if isinstance(raw, str):
        raise RequirementSyntaxError(
            f"expected a requirement mapping such as `unlock: ancient_magicks`, but found "
            f"the string {raw!r}. {_MISSING_SPACE_HINT}",
            location,
        )
    if not isinstance(raw, Mapping):
        raise RequirementSyntaxError(
            f"expected a requirement mapping, found {type(raw).__name__}", location
        )

    key, value = _single_key(raw, location)
    parser = _PARSERS.get(key)
    if parser is None:
        raise RequirementSyntaxError(
            f"unknown requirement type {key!r}. Valid types are "
            f"{', '.join(sorted(REQUIREMENT_TYPES))} (§10.2)",
            location,
        )
    return parser(value, file, f"{path}.{key}", location)


def _single_key(raw: Mapping[str, Any], location: ContentLocation) -> tuple[str, Any]:
    if len(raw) != 1:
        keys = ", ".join(repr(key) for key in raw)
        raise RequirementSyntaxError(
            f"a requirement node must be a single-key mapping, found {len(raw)} keys "
            f"({keys}). Wrap them in `all_of` if you meant all of them (§10.2)",
            location,
        )
    key, value = next(iter(raw.items()))
    if isinstance(key, str) and ":" in key and value is None:
        # `- skill:magic` parses as the single key 'skill:magic' with a null value.
        raise RequirementSyntaxError(
            f"{key!r} is one key, not a mapping. {_MISSING_SPACE_HINT}", location
        )
    return str(key), value


def _construct(location: ContentLocation, build: Callable[[], Requirement]) -> Requirement:
    """Run a model constructor, converting Pydantic's complaint into a located error."""
    try:
        return build()
    except ValueError as exc:
        raise RequirementSyntaxError(str(exc).replace("\n", " "), location) from exc


def _parse_skill(
    value: Any, _file: Path | None, path: str, location: ContentLocation
) -> Requirement:
    where = location.with_path(path)
    if isinstance(value, str):
        raise RequirementSyntaxError(
            f"a skill leaf must be a mapping like `{{magic: 94}}`, but found the string "
            f"{value!r}. {_MISSING_SPACE_HINT}",
            where,
        )
    if not isinstance(value, Mapping):
        raise RequirementSyntaxError(
            f"a skill leaf must be a mapping like `{{magic: 94}}`, found {type(value).__name__}",
            where,
        )
    if len(value) != 1:
        raise RequirementSyntaxError(
            f"a skill leaf names exactly one skill, found {len(value)}. Use `all_of` with one "
            "skill leaf each (§10.2)",
            where,
        )
    skill, level = next(iter(value.items()))
    if level is None:
        raise RequirementSyntaxError(f"skill {skill!r} has no level. {_MISSING_SPACE_HINT}", where)
    if not isinstance(level, int) or isinstance(level, bool):
        raise RequirementSyntaxError(
            f"skill {skill!r} needs an integer level, found {level!r}", where
        )
    return _construct(where, lambda: SkillLeaf(skill=str(skill), level=level))


def _parse_quest(
    value: Any, file: Path | None, path: str, location: ContentLocation
) -> Requirement:
    if not isinstance(value, Mapping):
        return _string_leaf("quest", lambda key: QuestLeaf(quest_id=key))(
            value, file, path, location
        )
    where = location.with_path(path)
    if set(value) != {"id", "status"} or not isinstance(value.get("id"), str) or not value["id"]:
        raise RequirementSyntaxError("quest mapping requires a nonempty id and status", where)
    return _construct(where, lambda: QuestLeaf(quest_id=value["id"], status=value["status"]))


def _string_leaf(label: str, build: Callable[[str], Requirement]) -> _NodeParser:
    def parser(value: Any, _file: Path | None, path: str, location: ContentLocation) -> Requirement:
        where = location.with_path(path)
        if not isinstance(value, str):
            raise RequirementSyntaxError(
                f"a {label} leaf names one id as a string, found {type(value).__name__}", where
            )
        return _construct(where, lambda: build(value))

    return parser


def _integer_leaf(label: str, build: Callable[[int], Requirement]) -> _NodeParser:
    def parser(value: Any, _file: Path | None, path: str, location: ContentLocation) -> Requirement:
        where = location.with_path(path)
        if not isinstance(value, int) or isinstance(value, bool):
            raise RequirementSyntaxError(
                f"a {label} leaf needs an integer target, found {value!r}", where
            )
        return _construct(where, lambda: build(value))

    return parser


def _bool_leaf(label: str, build: Callable[[bool], Requirement]) -> _NodeParser:
    """A leaf whose target is a literal ``true``/``false``.

    Strict about the type for :func:`_integer_leaf`'s reason inverted: YAML happily reads
    ``members: yes`` as ``True`` but ``members: 1`` as an integer, and silently accepting
    the latter would make ``members: 0`` a requirement that the account *not* be a member
    rather than a syntax error.
    """

    def parser(value: Any, _file: Path | None, path: str, location: ContentLocation) -> Requirement:
        where = location.with_path(path)
        if not isinstance(value, bool):
            raise RequirementSyntaxError(
                f"a {label} leaf needs true or false, found {value!r}", where
            )
        return _construct(where, lambda: build(value))

    return parser


def _child_list(build: Callable[[tuple[Requirement, ...]], Requirement]) -> _NodeParser:
    def parser(value: Any, file: Path | None, path: str, location: ContentLocation) -> Requirement:
        where = location.with_path(path)
        children = _parse_sequence(value, file, path, where)
        return _construct(where, lambda: build(children))

    return parser


def _parse_not(value: Any, file: Path | None, path: str, location: ContentLocation) -> Requirement:
    where = location.with_path(path)
    child = parse(value, file=file, path=path, line=where.line)
    return _construct(where, lambda: Not(child=child))


def _parse_at_least(
    value: Any, file: Path | None, path: str, location: ContentLocation
) -> Requirement:
    where = location.with_path(path)
    if not isinstance(value, Mapping):
        raise RequirementSyntaxError(
            f"at_least takes a mapping `{{n: 2, of: [...]}}`, found {type(value).__name__}", where
        )
    missing = {"n", "of"} - set(value)
    if missing:
        raise RequirementSyntaxError(
            f"at_least is missing {', '.join(sorted(missing))}; the form is "
            "`at_least: {n: 2, of: [...]}`",
            where,
        )
    count = value["n"]
    if not isinstance(count, int) or isinstance(count, bool):
        raise RequirementSyntaxError(f"at_least.n must be an integer, found {count!r}", where)
    children = _parse_sequence(value["of"], file, f"{path}.of", where)
    return _construct(where, lambda: AtLeast(n=count, of=children))


def _parse_sequence(
    value: Any, file: Path | None, path: str, location: ContentLocation
) -> tuple[Requirement, ...]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise RequirementSyntaxError(
            f"expected a list of requirements, found {type(value).__name__}", location
        )
    return tuple(
        parse(child, file=file, path=f"{path}[{index}]", line=location.line)
        for index, child in enumerate(value)
    )


_PARSERS: dict[str, _NodeParser] = {
    "skill": _parse_skill,
    "unlock": _string_leaf("unlock", lambda value: UnlockLeaf(key=value)),
    "quest": _parse_quest,
    "item": _string_leaf("item", lambda value: ItemLeaf(item_id=value)),
    "combat_level": _integer_leaf("combat_level", lambda value: CombatLevelLeaf(level=value)),
    "quest_points": _integer_leaf("quest_points", lambda value: QuestPointsLeaf(points=value)),
    "account_type": _string_leaf("account_type", lambda value: AccountTypeLeaf(account_type=value)),
    "members": _bool_leaf("members", lambda value: MembersLeaf(members=value)),
    "all_of": _child_list(lambda children: AllOf(children=children)),
    "any_of": _child_list(lambda children: AnyOf(children=children)),
    "not": _parse_not,
    "at_least": _parse_at_least,
}


# ---------------------------------------------------------------------------
# Walking
# ---------------------------------------------------------------------------


def iter_nodes(requirement: Requirement) -> Iterator[Requirement]:
    """Yield every node in the tree, parents before children."""
    yield requirement
    if isinstance(requirement, AllOf | AnyOf):
        for child in requirement.children:
            yield from iter_nodes(child)
    elif isinstance(requirement, Not):
        yield from iter_nodes(requirement.child)
    elif isinstance(requirement, AtLeast):
        for child in requirement.of:
            yield from iter_nodes(child)


def iter_leaves(requirement: Requirement) -> Iterator[Requirement]:
    """Yield only the leaves — what ``unlock_fraction`` counts over (§6.9)."""
    for node in iter_nodes(requirement):
        if node.type in LEAF_TYPES:
            yield node
