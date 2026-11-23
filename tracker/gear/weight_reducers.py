"""Reviewed worn weight reducers, ordinary combat stats and acquisition identities.

Sources for wear gates and cosmetic/acquisition requirements:
https://oldschool.runescape.wiki/w/Graceful_outfit
https://oldschool.runescape.wiki/w/Boots_of_lightness
https://oldschool.runescape.wiki/w/Penance_gloves
https://oldschool.runescape.wiki/w/Spotted_cape
https://oldschool.runescape.wiki/w/Spottier_cape
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING

from tracker.content.requirements import AllOf, MembersLeaf, QuestLeaf, Requirement, SkillLeaf
from tracker.content.schema import ItemSlot
from tracker.gear.models import EquipmentDefinition

if TYPE_CHECKING:
    from tracker.gear.optimizer import OptimizationRequest


WEIGHT_REDUCER_REVIEW_VERSION = "common-weight-reducers-v1"
# Each row lists inventory/worn pairs (hood, cape, top, legs, gloves, boots).
_GRACEFUL_SETS = {
    "": (
        (11850, 11851),
        (11852, 11853),
        (11854, 11855),
        (11856, 11857),
        (11858, 11859),
        (11860, 11861),
    ),
    "Arceuus": (
        (13579, 13580),
        (13581, 13582),
        (13583, 13584),
        (13585, 13586),
        (13587, 13588),
        (13589, 13590),
    ),
    "Piscarilius": (
        (13591, 13592),
        (13593, 13594),
        (13595, 13596),
        (13597, 13598),
        (13599, 13600),
        (13601, 13602),
    ),
    "Lovakengj": (
        (13603, 13604),
        (13605, 13606),
        (13607, 13608),
        (13609, 13610),
        (13611, 13612),
        (13613, 13614),
    ),
    "Shayzien": (
        (13615, 13616),
        (13617, 13618),
        (13619, 13620),
        (13621, 13622),
        (13623, 13624),
        (13625, 13626),
    ),
    "Hosidius": (
        (13627, 13628),
        (13629, 13630),
        (13631, 13632),
        (13633, 13634),
        (13635, 13636),
        (13637, 13638),
    ),
    "Kourend": (
        (13667, 13668),
        (13669, 13670),
        (13671, 13672),
        (13673, 13674),
        (13675, 13676),
        (13677, 13678),
    ),
    "Agility Arena": (
        (21061, 21063),
        (21064, 21066),
        (21067, 21069),
        (21070, 21072),
        (21073, 21075),
        (21076, 21078),
    ),
    "Hallowed": (
        (24743, 24745),
        (24746, 24748),
        (24749, 24751),
        (24752, 24754),
        (24755, 24757),
        (24758, 24760),
    ),
    "Trailblazer": (
        (25069, 25071),
        (25072, 25074),
        (25075, 25077),
        (25078, 25080),
        (25081, 25083),
        (25084, 25086),
    ),
    "Adventurer": (
        (27444, 27446),
        (27447, 27449),
        (27450, 27452),
        (27453, 27455),
        (27456, 27458),
        (27459, 27461),
    ),
    "Varlamore": (
        (30045, 30047),
        (30048, 30050),
        (30051, 30053),
        (30054, 30056),
        (30057, 30059),
        (30060, 30062),
    ),
}
_PIECES = (
    ("hood", "head"),
    ("cape", "cape"),
    ("top", "body"),
    ("legs", "legs"),
    ("gloves", "hands"),
    ("boots", "feet"),
)
_GRACEFUL = {
    item: (f"Graceful {piece}" + (f" ({colour})" if colour else ""), slot)
    for colour, ids in _GRACEFUL_SETS.items()
    for (_, item), (piece, slot) in zip(ids, _PIECES, strict=True)
}
REVIEWED_FORMS = MappingProxyType(
    {
        **_GRACEFUL,
        89: ("Boots of lightness", "feet"),
        10073: ("Spotted cape", "cape"),
        10074: ("Spottier cape", "cape"),
        10554: ("Penance gloves", "hands"),
    }
)
_WORN_BY_INVENTORY = {
    88: 89,
    10069: 10073,
    10071: 10074,
    10553: 10554,
    **{bag: worn for pairs in _GRACEFUL_SETS.values() for bag, worn in pairs},
}
_TRADEABLE = frozenset({10073, 10074})
_LEVELS = {
    10073: SkillLeaf(skill="hunter", level=40),
    10074: SkillLeaf(skill="hunter", level=66),
    10554: SkillLeaf(skill="defence", level=40),
}
_MEMBERS = MembersLeaf(members=True)
_HOUSE_QUESTS = {
    "Arceuus": "the_ascent_of_arceuus",
    "Piscarilius": "the_queen_of_thieves",
    "Lovakengj": "the_forsaken_tower",
    "Shayzien": "tale_of_the_righteous",
    "Hosidius": "the_depths_of_despair",
}
_RECOLOUR_GATES: dict[str, Requirement] = {
    **{house: QuestLeaf(quest_id=quest) for house, quest in _HOUSE_QUESTS.items()},
    "Kourend": AllOf(children=tuple(QuestLeaf(quest_id=q) for q in _HOUSE_QUESTS.values())),
    "Hallowed": AllOf(
        children=(QuestLeaf(quest_id="sins_of_the_father"), SkillLeaf(skill="agility", level=52))
    ),
    "Varlamore": AllOf(
        children=(QuestLeaf(quest_id="children_of_the_sun"), SkillLeaf(skill="agility", level=50))
    ),
}
ACQUISITION_REQUIREMENTS = MappingProxyType(
    {
        i: requirement
        for colour, requirement in _RECOLOUR_GATES.items()
        for _, i in _GRACEFUL_SETS[colour]
    }
)


def review_reducer(item: EquipmentDefinition) -> EquipmentDefinition:
    """Only approve an exact reviewed wearable with a sourced inventory form."""
    expected = REVIEWED_FORMS.get(item.id)
    if expected is None or item.inventory_form_id is None:
        return item
    if (
        expected != (item.name, item.slot)
        or _WORN_BY_INVENTORY.get(item.inventory_form_id) != item.id
    ):
        raise ValueError(f"Reviewed weight reducer physical form changed: {item.id}")
    skill = _LEVELS.get(item.id)
    omitted = item.omitted_set_effects
    if item.id in _GRACEFUL:
        omitted += ("Graceful run-energy restoration is outside the gear weight calculation.",)
    return item.model_copy(
        update={
            "requires": _MEMBERS if skill is None else AllOf(children=(_MEMBERS, skill)),
            "requirements_complete": True,
            "tradeable": item.id in _TRADEABLE,
            "unsupported_effects": tuple(
                effect
                for effect in item.unsupported_effects
                if effect != "Offensive effects have not been validated."
            ),
            "omitted_set_effects": omitted,
        }
    )


def compatible_locks(first: object, second: object) -> bool:
    if first == second:
        return True
    return (
        type(first) is int
        and type(second) is int
        and _WORN_BY_INVENTORY.get(first, first) == _WORN_BY_INVENTORY.get(second, second)
    )


def normalize_reducer_request[Request: OptimizationRequest](
    request: Request, items: Mapping[int, EquipmentDefinition]
) -> Request:
    """Resolve bank IDs only when they match a reviewed wearable in this catalog."""
    locks = (request.locks, *(role.locks for role in request.roles))
    requested = {
        *request.assumed_item_ids,
        *request.excluded_item_ids,
        *(item for group in locks for item in group.values() if item is not None),
    }
    aliases = {
        bag: worn
        for bag in requested
        if bag not in items
        if (worn := _WORN_BY_INVENTORY.get(bag)) is not None
        and (item := items.get(worn)) is not None
        and item.inventory_form_id == bag
    }
    # Schema validation can recognize a paired ID before the catalog is available.
    # A custom catalog still has to confirm that both IDs designate one item.
    for group in locks[1:]:
        for slot, value in group.items():
            if slot in request.locks:
                global_id = request.locks[slot]
                if value != global_id and (
                    value is None
                    or global_id is None
                    or aliases.get(value, value) != aliases.get(global_id, global_id)
                ):
                    raise ValueError("Conflicting global and role locks")
    if not aliases:
        return request

    def normalized_locks(group: Mapping[ItemSlot, int | None]) -> Mapping[ItemSlot, int | None]:
        return MappingProxyType(
            {slot: aliases.get(i, i) if i is not None else None for slot, i in group.items()}
        )

    excluded = tuple(dict.fromkeys(aliases.get(i, i) for i in request.excluded_item_ids))
    if any(item in excluded for group in locks for item in normalized_locks(group).values()):
        raise ValueError("Weight reducer lock conflicts with excluded_item_ids")
    return request.model_copy(
        update={
            "assumed_item_ids": tuple(
                dict.fromkeys(aliases.get(i, i) for i in request.assumed_item_ids)
            ),
            "excluded_item_ids": excluded,
            "locks": normalized_locks(request.locks),
            "roles": tuple(
                r.model_copy(update={"locks": normalized_locks(r.locks)}) for r in request.roles
            ),
        }
    )
