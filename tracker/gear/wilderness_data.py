"""Reviewed physical exceptions and the pinned official GE guide-price snapshot.

Game protection uses the GE guide price; replacement loss uses separate cached
market quotes. Sources are linked at each set of exceptions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from tracker.gear.powered import review as powered_review

_GUIDE_PATH = Path(__file__).with_name("wilderness-guide.json")
_GUIDE_BYTES = _GUIDE_PATH.read_bytes()
GE_GUIDE = MappingProxyType(
    {int(item_id): gp for item_id, gp in json.loads(_GUIDE_BYTES)["prices"].items()}
)
RULES_REVISION = f"wilderness-pvp-v1:{hashlib.sha256(_GUIDE_BYTES).hexdigest()[:16]}"

# https://oldschool.runescape.wiki/w/Items_Kept_on_Death#Items_that_are_always_kept
ALWAYS_KEPT = frozenset({30637})

# Exact current charged physical form to tradeable base IDs.
# https://oldschool.runescape.wiki/w/Wilderness_weapons
CHARGED_ETHER = MappingProxyType(
    {
        22542: 22545,  # Viggora's chainmace
        22547: 22550,  # Craw's bow
        22555: 22552,  # Thammaron's sceptre
        27788: 22552,  # Thammaron's sceptre (a)
        27660: 27657,  # Ursine chainmace
        27655: 27652,  # Webweaver bow
        27665: 27662,  # Accursed sceptre
        27679: 27662,  # Accursed sceptre (a)
    }
)

# Reviewed charged forms that retain their charges when protected.
# https://oldschool.runescape.wiki/w/Items_Kept_on_Death
# https://oldschool.runescape.wiki/w/Trident_of_the_seas
# https://oldschool.runescape.wiki/w/Trident_of_the_swamp
# https://oldschool.runescape.wiki/w/Warped_sceptre
# https://oldschool.runescape.wiki/w/Eye_of_ayak
_STAFF_CAPACITY = {
    11907: 2_500,
    12899: 2_500,
    22288: 20_000,
    22292: 20_000,
    22323: 20_000,
    27275: 20_000,
    28585: 20_000,
    31113: 50_000,
}
CHARGED_RECIPES = MappingProxyType(
    {
        item_id: (staff.uncharged_id, max_charges, staff.recipes[0])
        for item_id, max_charges in _STAFF_CAPACITY.items()
        if (staff := powered_review(item_id)) is not None
    }
)

# GP order is unknown for some reviewed outcomes. The evaluator checks all
# plausible positions for those items, including displacement of another item.
# https://oldschool.runescape.wiki/w/(broken)#PvP_breakable_items
# https://secure.runescape.com/m=news/bank-tags-trouver-system-rework--more?oldschool=1
# https://secure.runescape.com/m=news/the-blood-moon-rises-tweaks--fixes?oldschool=1
DepthLoss = tuple[int | None, int, int | None, Literal["broken", "mangled", "destroyed"]]
_BROKEN = {
    6570: (None, 150_000),
    24223: (None, 150_000),  # Legacy locked Fire cape.
    22109: (None, 240_000),
    24222: (None, 240_000),  # Legacy locked Ava's assembler.
    21791: (None, 96_000),
    21793: (None, 96_000),
    21795: (None, 96_000),
    24248: (None, 96_000),
    24249: (None, 96_000),
    24250: (None, 96_000),
    8844: (None, 1_000),
    8845: (None, 2_000),
    8846: (None, 2_500),
    8847: (None, 5_000),
    8848: (None, 15_000),
    8849: (None, 25_000),
    8850: (None, 35_000),
    12954: (None, 240_000),
    22322: (600_000, 600_000),  # Explicit game death rank, not the item's listed shop value.
    8841: (None, 20_000),
    25641: (None, 10_500),  # Barronite mace.
}
_TROUVER = {
    # Usable physical ID, locked physical ID, ordinary repair cost.
    (21295, 24224, 225_000),
    (10551, 24175, 150_000),
    (11663, 24183, 160_000),
    (11664, 24184, 160_000),
    (11665, 24185, 160_000),
    (8839, 24177, 180_000),
    (8840, 24179, 180_000),
    (8842, 24182, 120_000),
    (13072, 24178, 250_000),
    (13073, 24180, 250_000),
}
DEPTH_LOSSES: MappingProxyType[int, DepthLoss] = MappingProxyType(
    {
        **{i: (priority, fee, fee, "broken") for i, (priority, fee) in _BROKEN.items()},
        **{i: (None, fee, None, "destroyed") for i, _, fee in _TROUVER},
        **{i: (None, fee, 500_000, "mangled") for _, i, fee in _TROUVER},
    }
)

# https://oldschool.runescape.wiki/w/Dragon_defender_(t)
# https://oldschool.runescape.wiki/w/Rune_defender_(t)
ORNAMENTED_DEFENDERS = MappingProxyType(
    {
        19722: (None, 240_000, 20143),
        23230: (None, 35_000, 23227),
    }
)

# NPC replacement rather than the coins paid out to the PKer.
# https://oldschool.runescape.wiki/w/Chest_(Culinaromancer)
NPC_REPLACEMENTS = MappingProxyType(
    {
        7462: (None, 130_000),  # Barrows gloves. Full shop price before any diary discount.
    }
)

# Exceptions to the ordinary GE-tradeable drop rule requiring further review.
# https://oldschool.runescape.wiki/w/Items_Kept_on_Death
UNREVIEWED_TRADEABLE = frozenset(
    {
        *range(4708, 4760, 2),  # Barrows full forms.
        *range(4856, 4999),  # Barrows degraded and broken forms.
        *range(29004, 29077),  # Perilous Moons equipment.
        11905,  # Tradeable Trident of the Seas (full).
    }
)


def wilderness_price_item_ids() -> frozenset[int]:
    """Return market IDs needed to value reviewed Wilderness conversions and losses."""
    return frozenset(
        {
            21820,
            *CHARGED_ETHER.values(),
            *(row[2] for row in ORNAMENTED_DEFENDERS.values()),
            *(base for base, _, _ in CHARGED_RECIPES.values()),
            *(
                resource
                for _, _, recipe in CHARGED_RECIPES.values()
                for resource, _ in recipe
                if resource != 995
            ),
        }
    )
