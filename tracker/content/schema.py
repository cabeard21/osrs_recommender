"""Factual authored skill, quest, and item schemas."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from tracker.content.requirements import Requirement, RequirementNode
from tracker.content.requirements import parse as parse_requirement


class ContentModel(BaseModel):
    """Frozen content objects reject unknown YAML fields."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


def _requirement_field(field_name: str) -> Any:
    def validate(cls: type[ContentModel], value: Any, info: ValidationInfo) -> Any:
        if value is None or isinstance(value, RequirementNode):
            return value
        context = info.context or {}
        return parse_requirement(
            value,
            file=context.get("file"),
            path=field_name,
            line=context.get("line"),
        )

    return field_validator(field_name, mode="before")(classmethod(validate))


class Skill(ContentModel):
    """A trainable skill named by requirement leaves and account snapshots."""

    id: str
    name: str
    is_combat: bool = False


class Quest(ContentModel):
    """Quest identity used by authored item requirements."""

    id: str
    name: str
    quest_points: int = Field(default=0, ge=0)


ItemSlot = Literal[
    "weapon",
    "ammunition",
    "head",
    "body",
    "legs",
    "hands",
    "feet",
    "cape",
    "neck",
    "ring",
    "shield",
]
CombatStyle = Literal["melee", "ranged", "magic"]
Acquisition = Literal["tradeable", "untradeable"]


class Item(ContentModel):
    """Authored Gear ladder placement, ownership variants, gates, and price hints.

    A numeric variant sighting counts as ownership of the same piece, while prices use
    the primary item_id. gate_unknown and absent acquisition remain explicit unknowns.
    """

    id: str
    name: str
    item_id: int | None = Field(default=None, gt=0)
    variant_item_ids: tuple[int, ...] = ()
    slot: ItemSlot | None = None
    style: CombatStyle | None = None
    tier: int | None = Field(default=None, ge=1)
    requires: Requirement | None = None
    gate_unknown: bool = False
    acquisition: Acquisition | None = None
    acquired_from: str | None = None
    price_mode: Literal["live", "static"] = "static"
    fallback_price_gp: int | None = Field(default=None, ge=0)
    price_staleness_days: int | None = Field(default=None, gt=0)

    _parse_requires = _requirement_field("requires")

    @property
    def owned_item_ids(self) -> frozenset[int]:
        """All observed ids that can identify this item."""
        if self.item_id is None:
            return frozenset(self.variant_item_ids)
        return frozenset({self.item_id, *self.variant_item_ids})
