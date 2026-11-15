"""Reviewed exact main-game halberd forms and ordinary attack profiles.

Sources: https://oldschool.runescape.wiki/w/Halberd and individual weapon pages.
Crystal uses current (post-2019) constant stats until charge depletion.
Special attacks, Gauntlet and event variants are not certified by this review.
"""

from types import MappingProxyType
from typing import Any

from tracker.content.requirements import AllOf, MembersLeaf, QuestLeaf, SkillLeaf, UnlockLeaf

MODEL_VERSION = "ordinary-halberds-v1"
FORMS = MappingProxyType(
    {
        3190: ("Bronze halberd", 1, 1),
        3192: ("Iron halberd", 1, 1),
        3194: ("Steel halberd", 5, 1),
        3196: ("Black halberd", 10, 5),
        3198: ("Mithril halberd", 20, 10),
        3200: ("Adamant halberd", 30, 15),
        3202: ("Rune halberd", 40, 20),
        3204: ("Dragon halberd", 60, 30),
        6599: ("White halberd", 10, 5),
        28049: ("Dragon halberd (cr)", 60, 30),
        23987: ("Crystal halberd", 70, 35),
        29796: ("Noxious halberd", 80, 1),
    }
)
PROFILES = (("stab", "controlled"), ("slash", "aggressive"), ("stab", "defensive"))
TRADEABLE = frozenset(FORMS) - {23987, 28049}
REVISION = repr((MODEL_VERSION, tuple(FORMS.items()), PROFILES)).encode()


def requirement(item_id: int) -> AllOf:
    _, attack, strength = FORMS[item_id]
    return AllOf(
        children=(
            MembersLeaf(members=True),
            SkillLeaf(skill="attack", level=attack),
            SkillLeaf(skill="strength", level=strength),
            *((QuestLeaf(quest_id="regicide"),) if item_id in {3204, 28049} else ()),
            *(
                (SkillLeaf(skill="agility", level=50), UnlockLeaf(key="diary_western_hard"))
                if item_id == 23987
                else ()
            ),
        )
    )


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    if row["id"] not in FORMS:
        return row
    name, _, _ = FORMS[row["id"]]
    if row["name"] != name or row["slot"] != "weapon" or not row["two_handed"]:
        raise ValueError(f"Reviewed halberd physical form changed: {row['id']}")
    return {
        **row,
        "attack_styles": ("stab", "slash"),
        "attack_profiles": PROFILES,
        "attack_speed": 5 if row["id"] == 29796 else 7,
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
    }
