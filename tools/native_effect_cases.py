"""Deterministic reviewed-item mechanism cases for native correctness acceptance.

Account levels, ownership and missing resource prices are synthetic. Equipment
mechanics are copied unchanged from the supplied frozen catalog. These cases
are deliberately distinct from a replay of the private original account.
"""

from dataclasses import replace
from typing import Any

from tools.benchmark_gear_desktop import case_provenance
from tracker.accounts.snapshot import ObservedItemFact
from tracker.domain.types import Container, QuestStatus, SkillState, Source, UnlockState
from tracker.gear.catalog import EquipmentCatalog
from tracker.gear.models import CombatTarget
from tracker.gear.optimizer import CombatOptionFilters, OptimizationRequest, RoleConfig
from tracker.gear.potions import PotionPolicy
from tracker.gear.prayers import PrayerPolicy
from tracker.integrations.prices.client import PriceDTO, PriceSource

EFFECT_CASES = (
    "effect_magic_fixed",
    "effect_magic",
    "effect_ranged_fixed",
    "effect_ranged",
    "effect_hopper",
    "effect_auto",
    "effect_multi",
)
_MAGIC = (1381, 20714, 20716, 25574, 25576, 30064, 30066, 34407, 34413, 34419, 34425, 34428)
_RANGED = (9185, 26374, 9144, 9236, 9238, 9242, 9243, 9244, 9245, 10499)
_RESOURCES = (
    554,
    555,
    556,
    557,
    558,
    562,
    560,
    565,
    566,
    21880,
    3040,
    3042,
    3044,
    3046,
    2444,
    169,
    171,
    173,
)


def derive_effect_case(
    base: Any, metadata: dict[str, Any], name: str
) -> tuple[Any, dict[str, Any]]:
    """Derive detached cases without changing physical definitions or work budgets."""
    if name not in EFFECT_CASES:
        raise ValueError(f"Unknown native effect case: {name}")
    both = name in {"effect_auto", "effect_multi"}
    magic = "magic" in name or both
    ranged = not magic or both
    ids = set((_MAGIC if magic else ()) + (_RANGED if ranged else ()))
    if name in {"effect_hopper", "effect_auto", "effect_multi"}:
        ids.add(32879)
    ids.update((3755, 10452))
    missing = ids - base.catalog.items.keys()
    if missing:
        raise ValueError(f"Frozen effect catalog lacks reviewed items: {sorted(missing)}")
    items = {i: base.catalog.items[i] for i in sorted(ids)}
    snapshot = replace(
        base.snapshot,
        skills={
            key: SkillState(99, None, Source.MANUAL, base.at)
            for key in set(base.snapshot.skills)
            | {"magic", "ranged", "attack", "strength", "defence", "prayer", "hitpoints"}
        },
        quests=dict.fromkeys(base.content.quests, QuestStatus.COMPLETE),
        unlocks={
            **base.snapshot.unlocks,
            "spellbook_standard": UnlockState.UNLOCKED,
            "spellbook_ancient": UnlockState.UNLOCKED,
        },
        observed_items={
            (i, Container.BANK): ObservedItemFact(
                i, Container.BANK, 100, "native-effect-fixture", base.at
            )
            for i in ids
        },
        members=True,
        quest_points=300,
        combat_level=126,
    )
    options = CombatOptionFilters(
        attack_types=("magic", "heavy"),
        stances=("accurate", "rapid", "longrange"),
        spells=(
            "wind_blast",
            "water_blast",
            "earth_blast",
            "fire_blast",
            "wind_wave",
            "water_wave",
            "earth_wave",
            "fire_wave",
        ),
    )
    target = CombatTarget(
        hitpoints=500,
        current_hitpoints=160,
        defence_level=110,
        magic_level=1,
        weakness_element="earth",
        weakness_percent=50,
        flat_armour=-2,
    )
    role = RoleConfig(
        id="effect",
        style="magic" if magic else "ranged",
        spell="fire_wave",
        stance="accurate" if magic else "rapid",
        target=target,
        combat_options=None if name.endswith("fixed") else options,
        allowed_disciplines=("magic", "ranged") if name == "effect_auto" else None,
        prayers=PrayerPolicy(
            mode="optimize", allowed_ids=("mystic_might", "eagle_eye", "steel_skin")
        ),
    )
    roles = (
        (role, role.model_copy(update={"id": "ranged", "style": "ranged", "stance": "rapid"}))
        if name == "effect_multi"
        else (role,)
    )
    request = OptimizationRequest(
        roles=roles,
        mode="owned",
        budget_gp=1_000_000,
        max_swaps=1,
        secondary_priority="prayer_bonus",
        max_dps_loss_pct=100,
        fire_tome_pages="searing",
        potions=PotionPolicy(mode="optimize", allowed_ids=("magic", "ranging"))
        if name == "effect_auto"
        else PotionPolicy(),
    )
    prices = dict(base.prices)
    for item in (*ids, *_RESOURCES):
        if item not in prices:
            prices[item] = PriceDTO(
                item_id=item,
                high_price_gp=5,
                high_trade_at=base.at,
                low_price_gp=None,
                low_trade_at=None,
                fetched_at=base.at,
                source=PriceSource.LIVE,
                provider="native-effect-fixture",
            )
    result = replace(
        base,
        name=name,
        snapshot=snapshot,
        request=request,
        catalog=EquipmentCatalog(items, revision=base.catalog.revision),
        prices=prices,
    )
    return result, case_provenance(
        result,
        **{
            **metadata,
            "effect_case": name,
            "case_name": name,
            "account_source": "native-effect-fixture",
            "original_account_replayed": False,
            "required_effect_styles": ["magic", "ranged"]
            if both
            else ["magic" if magic else "ranged"],
        },
    )
