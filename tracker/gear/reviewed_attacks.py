"""Exact physical forms reviewed for ordinary melee double-hit attacks only.

Sources: https://oldschool.runescape.wiki/w/Dual_macuahuitl
https://oldschool.runescape.wiki/w/Glacial_temotli
https://oldschool.runescape.wiki/w/Sulphur_blades
https://oldschool.runescape.wiki/w/Torag%27s_hammers
Set effects and special attacks are not certified by this review.
"""

from types import MappingProxyType

TORAG_USABLE_IDS = frozenset({4747, 4958, 4959, 4960, 4961})
DOUBLE_ATTACKS = MappingProxyType(
    {
        28997: ("Dual macuahuitl", "conditional_double", (("attack", 70), ("strength", 75))),
        29889: ("Glacial temotli", "independent_double", (("attack", 55),)),
        29084: ("Sulphur blades", "independent_double", (("attack", 55),)),
        **dict.fromkeys(
            sorted(TORAG_USABLE_IDS),
            ("Torag's hammers", "independent_double", (("attack", 70), ("strength", 70))),
        ),
    }
)
DUAL_PROFILES = (
    ("crush", "accurate"),
    ("crush", "aggressive"),
    ("stab", "controlled"),
    ("crush", "defensive"),
)
