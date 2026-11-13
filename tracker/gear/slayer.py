"""Reviewed ordinary Slayer task effects; exact physical forms only.

Sources: https://oldschool.runescape.wiki/w/Black_mask
https://oldschool.runescape.wiki/w/Black_mask_(i)
https://oldschool.runescape.wiki/w/Slayer_helmet
https://oldschool.runescape.wiki/w/Slayer%27s_staff_(e)
Formula order: weirdgloop/osrs-dps-calc PlayerVsNPCCalc.ts at
74958b18f6559cf1bf58f7ac74e7a442a7ac8e2f.
Random charged-mask defence drain and protective helmet effects are excluded.
"""

import json
from types import MappingProxyType
from typing import Any

MODEL_VERSION = "slayer-task-v1"
MAGIC_DART_STAVES = frozenset({4170, 21255})
FORMS = MappingProxyType(
    {
        4170: ("Slayer's staff", "weapon"),
        8901: ("Black mask", "head"),
        8903: ("Black mask", "head"),
        8905: ("Black mask", "head"),
        8907: ("Black mask", "head"),
        8909: ("Black mask", "head"),
        8911: ("Black mask", "head"),
        8913: ("Black mask", "head"),
        8915: ("Black mask", "head"),
        8917: ("Black mask", "head"),
        8919: ("Black mask", "head"),
        8921: ("Black mask", "head"),
        11774: ("Black mask (i)", "head"),
        11775: ("Black mask (i)", "head"),
        11776: ("Black mask (i)", "head"),
        11777: ("Black mask (i)", "head"),
        11778: ("Black mask (i)", "head"),
        11779: ("Black mask (i)", "head"),
        11780: ("Black mask (i)", "head"),
        11781: ("Black mask (i)", "head"),
        11782: ("Black mask (i)", "head"),
        11783: ("Black mask (i)", "head"),
        11784: ("Black mask (i)", "head"),
        11864: ("Slayer helmet", "head"),
        11865: ("Slayer helmet (i)", "head"),
        19639: ("Black slayer helmet", "head"),
        19641: ("Black slayer helmet (i)", "head"),
        19643: ("Green slayer helmet", "head"),
        19645: ("Green slayer helmet (i)", "head"),
        19647: ("Red slayer helmet", "head"),
        19649: ("Red slayer helmet (i)", "head"),
        21255: ("Slayer's staff (e)", "weapon"),
        21264: ("Purple slayer helmet", "head"),
        21266: ("Purple slayer helmet (i)", "head"),
        21888: ("Turquoise slayer helmet", "head"),
        21890: ("Turquoise slayer helmet (i)", "head"),
        23073: ("Hydra slayer helmet", "head"),
        23075: ("Hydra slayer helmet (i)", "head"),
        24370: ("Twisted slayer helmet", "head"),
        24444: ("Twisted slayer helmet (i)", "head"),
        25177: ("Slayer helmet (i)", "head"),
        25179: ("Black slayer helmet (i)", "head"),
        25181: ("Green slayer helmet (i)", "head"),
        25183: ("Red slayer helmet (i)", "head"),
        25185: ("Purple slayer helmet (i)", "head"),
        25187: ("Turquoise slayer helmet (i)", "head"),
        25189: ("Hydra slayer helmet (i)", "head"),
        25191: ("Twisted slayer helmet (i)", "head"),
        25266: ("Black mask (i)", "head"),
        25267: ("Black mask (i)", "head"),
        25268: ("Black mask (i)", "head"),
        25269: ("Black mask (i)", "head"),
        25270: ("Black mask (i)", "head"),
        25271: ("Black mask (i)", "head"),
        25272: ("Black mask (i)", "head"),
        25273: ("Black mask (i)", "head"),
        25274: ("Black mask (i)", "head"),
        25275: ("Black mask (i)", "head"),
        25276: ("Black mask (i)", "head"),
        25898: ("Tztok slayer helmet", "head"),
        25900: ("Tztok slayer helmet (i)", "head"),
        25902: ("Tztok slayer helmet (i)", "head"),
        25904: ("Vampyric slayer helmet", "head"),
        25906: ("Vampyric slayer helmet (i)", "head"),
        25908: ("Vampyric slayer helmet (i)", "head"),
        25910: ("Tzkal slayer helmet", "head"),
        25912: ("Tzkal slayer helmet (i)", "head"),
        25914: ("Tzkal slayer helmet (i)", "head"),
        26674: ("Slayer helmet (i)", "head"),
        26675: ("Black slayer helmet (i)", "head"),
        26676: ("Green slayer helmet (i)", "head"),
        26677: ("Red slayer helmet (i)", "head"),
        26678: ("Purple slayer helmet (i)", "head"),
        26679: ("Turquoise slayer helmet (i)", "head"),
        26680: ("Hydra slayer helmet (i)", "head"),
        26681: ("Twisted slayer helmet (i)", "head"),
        26682: ("Tztok slayer helmet (i)", "head"),
        26683: ("Vampyric slayer helmet (i)", "head"),
        26684: ("Tzkal slayer helmet (i)", "head"),
        26771: ("Black mask (i)", "head"),
        26772: ("Black mask (i)", "head"),
        26773: ("Black mask (i)", "head"),
        26774: ("Black mask (i)", "head"),
        26775: ("Black mask (i)", "head"),
        26776: ("Black mask (i)", "head"),
        26777: ("Black mask (i)", "head"),
        26778: ("Black mask (i)", "head"),
        26779: ("Black mask (i)", "head"),
        26780: ("Black mask (i)", "head"),
        26781: ("Black mask (i)", "head"),
        29816: ("Araxyte slayer helmet", "head"),
        29818: ("Araxyte slayer helmet (i)", "head"),
        29820: ("Araxyte slayer helmet (i)", "head"),
        29822: ("Araxyte slayer helmet (i)", "head"),
        33066: ("Hooded slayer helmet", "head"),
        33068: ("Hooded slayer helmet (i)", "head"),
        33070: ("Hooded slayer helmet (i)", "head"),
        33072: ("Hooded slayer helmet (i)", "head"),
        33338: ("Oathplate slayer helmet", "head"),
        33340: ("Radiant slayer helmet", "head"),
        33439: ("Oathplate slayer helmet (i)", "head"),
        33441: ("Oathplate slayer helmet (i)", "head"),
        33443: ("Oathplate slayer helmet (i)", "head"),
        33445: ("Radiant slayer helmet (i)", "head"),
        33447: ("Radiant slayer helmet (i)", "head"),
        33449: ("Radiant slayer helmet (i)", "head"),
    }
)
REVISION = json.dumps([MODEL_VERSION, dict(FORMS)], sort_keys=True).encode()


def mask_factor(kind: str | None, style: str, on_task: bool) -> tuple[int, int]:
    if not on_task or kind is None:
        return (1, 1)
    if style in {"stab", "slash", "crush"}:
        return (7, 6)
    return (23, 20) if kind == "all" and style in {"magic", "ranged"} else (1, 1)


def dart_base(magic: int, enchanted: bool, on_task: bool) -> int:
    return 13 + magic // 6 if enchanted and on_task else 10 + magic // 10


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    form = FORMS.get(row["id"])
    if form is None:
        return row
    if (row["name"], row["slot"]) != form:
        raise ValueError(f"Reviewed Slayer physical form changed: {row['id']}")
    return {
        **row,
        "slayer_bonus": ("all" if "(i)" in form[0] else "melee") if form[1] == "head" else None,
        "slayer_staff_enchanted": row["id"] == 21255,
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
        "omitted_set_effects": ("Random Black mask charge defence drain is not simulated.",)
        if form[0].startswith("Black mask")
        else (),
    }
