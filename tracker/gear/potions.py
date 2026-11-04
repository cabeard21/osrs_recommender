"""Reviewed fresh-dose boosts, independent of account facts and gear acquisition.

Mechanics: https://oldschool.runescape.wiki/w/Potions
IDs: RuneLite runelite-api/gameval/ItemID.java (unnoted physical dose forms).
No decay, drinking downtime, healing supplies or survival benefits are simulated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tracker.estimation.prices import PriceRecord, resolve_price

MODEL_VERSION = "fresh-potion-boost-v1"
CATALOG_REVISION = "combat-potions-2026-11-03"


@dataclass(frozen=True)
class Potion:
    id: str
    name: str
    skills: tuple[str, ...]
    flat: int
    percent: int
    forms: tuple[int, ...]  # four, three, two, one doses
    divine: bool = False


_ORDINARY = (
    Potion("attack", "Attack potion", ("attack",), 3, 10, (2428, 121, 123, 125)),
    Potion("strength", "Strength potion", ("strength",), 3, 10, (113, 115, 117, 119)),
    Potion("defence", "Defence potion", ("defence",), 3, 10, (2432, 133, 135, 137)),
    Potion("combat", "Combat potion", ("attack", "strength"), 3, 10, (9739, 9741, 9743, 9745)),
    Potion("super_attack", "Super attack", ("attack",), 5, 15, (2436, 145, 147, 149)),
    Potion("super_strength", "Super strength", ("strength",), 5, 15, (2440, 157, 159, 161)),
    Potion("super_defence", "Super defence", ("defence",), 5, 15, (2442, 163, 165, 167)),
    Potion(
        "super_combat",
        "Super combat potion",
        ("attack", "strength", "defence"),
        5,
        15,
        (12695, 12697, 12699, 12701),
    ),
    Potion("ranging", "Ranging potion", ("ranged",), 4, 10, (2444, 169, 171, 173)),
    Potion("magic", "Magic potion", ("magic",), 4, 0, (3040, 3042, 3044, 3046)),
)
_DIVINE_BASES = (
    ("super_combat", 23685),
    ("super_attack", 23697),
    ("super_strength", 23709),
    ("super_defence", 23721),
    ("ranging", 23733),
    ("magic", 23745),
)
_POTIONS = _ORDINARY + tuple(
    Potion(
        "divine_" + base.id,
        "Divine " + base.name.lower(),
        base.skills,
        base.flat,
        base.percent,
        tuple(start + offset for offset in (0, 3, 6, 9)),
        True,
    )
    for key, start in _DIVINE_BASES
    for base in _ORDINARY
    if base.id == key
)
_BY_ID = {potion.id: potion for potion in _POTIONS}


class PotionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["disabled", "optimize", "fixed"] = "disabled"
    allowed_ids: tuple[str, ...] = Field(default=(), max_length=len(_POTIONS))
    selected_ids: tuple[str, ...] = Field(default=(), max_length=len(_POTIONS))

    @model_validator(mode="after")
    def validate_selection(self) -> PotionPolicy:
        for ids in (self.allowed_ids, self.selected_ids):
            if len(set(ids)) != len(ids) or any(key not in _BY_ID for key in ids):
                raise ValueError("Potion IDs must be unique reviewed catalog IDs")
        if self.mode != "fixed" and self.selected_ids:
            raise ValueError("Selected potions require fixed mode")
        if self.mode != "optimize" and self.allowed_ids:
            raise ValueError("Allowed potions require optimize mode")
        return self


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": p.id,
            "name": p.name,
            "skills": list(p.skills),
            "divine": p.divine,
            "flat": p.flat,
            "percent": p.percent,
            "dose_forms": [{"item_id": i, "doses": 4 - n} for n, i in enumerate(p.forms)],
        }
        for p in _POTIONS
    ]


def resource_item_ids() -> frozenset[int]:
    return frozenset(i for p in _POTIONS for i in p.forms)


def boosted_levels(levels: Mapping[str, int], selected_ids: Sequence[str]) -> dict[str, int]:
    selected = tuple(_BY_ID[key] for key in selected_ids)
    return {
        skill: max(
            [level]
            + [
                level + p.flat + level * p.percent // 100
                for p in selected
                if skill in p.skills and level > 0
            ]
        )
        for skill, level in levels.items()
    }


def _dose(potion: Potion, prices: Mapping[int, PriceRecord], now: datetime) -> dict[str, Any]:
    quotes = [
        (i, 4 - n, resolve_price(None, prices.get(i), now=now)) for n, i in enumerate(potion.forms)
    ]
    item, doses, quote = min(
        quotes,
        key=lambda row: (
            row[2].gp is None,
            row[2].gp / row[1] if row[2].gp is not None else 0,
            row[0],
        ),
    )
    return {
        "potion_id": potion.id,
        "name": potion.name,
        "item_id": item,
        "doses_per_item": doses,
        "consumed_doses": 1,
        "cost_per_dose_gp": quote.gp / doses if quote.gp is not None else None,
        "price_layer": quote.layer.value,
        "price_confidence": str(quote.confidence),
        "price_trade_at": quote.trade_at.isoformat() if quote.trade_at else None,
    }


def potion_summary(
    levels: Mapping[str, int],
    selected_ids: Sequence[str],
    prices: Mapping[int, PriceRecord],
    now: datetime,
) -> dict[str, Any]:
    resources = [_dose(_BY_ID[key], prices, now) for key in sorted(selected_ids)]
    costs = [row["cost_per_dose_gp"] for row in resources]
    return {
        "selected_ids": sorted(selected_ids),
        "base_levels": dict(levels),
        "boosted_levels": boosted_levels(levels, selected_ids),
        "cost_per_application_gp": sum(costs) if all(c is not None for c in costs) else None,
        "model_version": MODEL_VERSION,
        "catalog_revision": CATALOG_REVISION,
        "resources": resources,
        "hp_cost": sum(10 for key in selected_ids if _BY_ID[key].divine),
        "limitations": [
            "Freshly boosted stats; no decay, drinking downtime or supply endurance.",
            "Potion access is assumed regardless of observed ownership.",
            "Defence boosts are displayed; survival is not scored.",
        ],
    }


def potion_setups(
    levels: Mapping[str, int],
    allowed_ids: Sequence[str],
    prices: Mapping[int, PriceRecord],
    now: datetime,
    relevant_skills: Iterable[str] | None = None,
) -> list[tuple[str, ...]]:
    """Keep cheapest setups for attainable vectors of skills used by the objective.

    Incidental boosts remain in the returned setup: a cheap combined potion may
    win over individual doses even when only some of its skills are scored.
    """
    relevant = frozenset(levels if relevant_skills is None else relevant_skills)

    def vector_for(ids: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
        return tuple(
            sorted((k, v) for k, v in boosted_levels(levels, ids).items() if k in relevant)
        )

    dose_costs = {key: _dose(_BY_ID[key], prices, now)["cost_per_dose_gp"] for key in allowed_ids}

    def rank(ids: tuple[str, ...]) -> tuple[Any, ...]:
        costs = [dose_costs[key] for key in ids]
        known = all(cost is not None for cost in costs)
        return (
            not known,
            sum(cost is None for cost in costs),
            sum(cost for cost in costs if cost is not None),
            len(ids),
            ids,
        )

    states: dict[tuple[tuple[str, int], ...], tuple[str, ...]] = {vector_for(()): ()}
    for key in sorted(set(allowed_ids)):
        additions = [tuple(sorted((*ids, key))) for ids in states.values()]
        for ids in additions:
            vector = vector_for(ids)
            if vector not in states or rank(ids) < rank(states[vector]):
                states = {**states, vector: ids}
    return sorted(states.values(), key=rank)


def relevant_boost_skills(request: Any) -> frozenset[str]:
    """Skills affecting ordinary attack scoring across configured roles/Auto branches."""
    skills_by_style = {
        "stab": ("attack", "strength"),
        "slash": ("attack", "strength"),
        "crush": ("attack", "strength"),
        "melee": ("attack", "strength"),
        "ranged": ("ranged",),
        "magic": ("magic",),
    }
    return frozenset(
        skill
        for role in request.roles
        if role.style != "special"
        for style in (getattr(role, "allowed_disciplines", None) or (role.style,))
        for skill in skills_by_style.get(style, ())
    )
