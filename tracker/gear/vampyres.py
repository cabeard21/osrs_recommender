"""Ordinary vampyrebane attacks and their exact physical equipment forms.

Sources: OSRS Wiki Silver weaponry, Silver bolts, Dorgeshuun crossbow,
Rod of Ivandis, Blisterwood stake, Hallowed flail, Sunspear and Poison.
Equipment IDs, handedness and wear levels also cross-checked against OSRS
game cache dump c4455dfa5ca75d4ecc0f309b36bce7097c695d69 (config/dump.obj).
"""

import json
from types import MappingProxyType
from typing import Any

from tracker.content.requirements import QuestLeaf, SkillLeaf

MODEL_VERSION = "vampyre-v1"
BLISTERWOOD_STAKE = 33716
EFARITAYS_AID = 21140
RODS = frozenset(range(7639, 7649))
SILVER_POISON_SEVERITY = MappingProxyType({9292: 6, 9299: 11, 9306: 16})
SILVER_BOLTS = frozenset({9145, *SILVER_POISON_SEVERITY})
AUTOCAST_STAVES = RODS | {22398, 24699}

# Accuracy and damage percentages for the delivered attack. The rod works
# through tier 2; all other specialists can damage tier 3. The enchanted
# diamond-based sickle is classified separately from the plain ruby-based one.
SPECIALISTS = MappingProxyType(
    {
        **dict.fromkeys(RODS, (0, 10)),
        22398: (0, 20),
        24697: (5, 15),
        24699: (5, 25),
        33718: (25, 25),
        BLISTERWOOD_STAKE: (25, 25),
        33722: (25, 50),
    }
)
_WEAPONS = {
    10491: "Blessed axe",
    2952: "Wolfbane",
    2961: "Silver sickle",
    2963: "Silver sickle (b)",
    22433: "Emerald sickle (b)",
    22435: "Enchanted emerald sickle (b)",
    24693: "Ruby sickle (b)",
    24695: "Enchanted ruby sickle (b)",
    33709: "Diamond sickle (b)",
    33711: "Enchanted diamond sickle (b)",
    33713: "Blisterwood sickle (e)",
    2402: "Silverlight",
    6745: "Silverlight",
    6746: "Darklight",
    19675: "Arclight",
    30305: "Arclight",
    29589: "Emberlight",
    **dict.fromkeys(RODS, "Rod of Ivandis"),
    22398: "Ivandis flail",
    24697: "Blisterwood sickle",
    24699: "Blisterwood flail",
    33718: "Hallowed flail",
    33722: "Sunspear",
}
SILVER_WEAPONS = frozenset(_WEAPONS)
FORMS = MappingProxyType(
    {
        **{i: (name, "weapon") for i, name in _WEAPONS.items()},
        **dict.fromkeys(SILVER_BOLTS, ("Silver bolts", "ammunition")),
        BLISTERWOOD_STAKE: ("Blisterwood stake", "weapon"),
        EFARITAYS_AID: ("Efaritay's aid", "ring"),
    }
)
TRADEABLE = SILVER_BOLTS | {2961, EFARITAYS_AID}
# The Dorgeshuun crossbow is an explicit exception to the iron-tier rule.
SILVER_CROSSBOWS = frozenset(
    {9177, 9179, 9181, 9183, 9185, 21902, 21012, 25916, 25918, 11785, 26374}
)
_STAFF = (
    ("crush", "accurate"),
    ("crush", "aggressive"),
    ("crush", "defensive"),
    ("magic", "accurate"),
    ("magic", "defensive"),
)
_PROFILES = MappingProxyType(
    {
        **dict.fromkeys(AUTOCAST_STAVES, _STAFF),
        33718: (("slash", "accurate"), ("slash", "aggressive"), ("slash", "defensive")),
        33722: (
            ("stab", "controlled"),
            ("slash", "controlled"),
            ("crush", "controlled"),
            ("stab", "defensive"),
        ),
        10491: (
            ("slash", "accurate"),
            ("slash", "aggressive"),
            ("crush", "aggressive"),
            ("slash", "defensive"),
        ),
        2952: (
            ("stab", "accurate"),
            ("stab", "aggressive"),
            ("slash", "aggressive"),
            ("stab", "defensive"),
        ),
    }
)
_LEVELS = MappingProxyType(
    {
        10491: ("attack", 20),
        22398: ("attack", 40),
        **dict.fromkeys((24697, 24699, 33718, 33722), ("attack", 50)),
        19675: ("attack", 75),
        30305: ("attack", 75),
        29589: ("attack", 77),
        **dict.fromkeys(SILVER_BOLTS, ("ranged", 26)),
        BLISTERWOOD_STAKE: ("ranged", 50),
    }
)
# Only the observed quest state is available, so an in-progress quest identifies
# a possible acquisition route. It does not claim the item has been obtained.
ACQUISITION_REQUIREMENTS = MappingProxyType(
    {
        i: QuestLeaf(quest_id=quest, status="in_progress")
        for quest, ids in (
            ("animal_magnetism", (10491,)),
            ("nature_spirit", (2963,)),
            ("in_aid_of_the_myreque", RODS),
            ("a_taste_of_hope", (22433, 22435, 22398)),
            ("sins_of_the_father", (24693, 24695, 24697, 24699)),
            ("the_blood_moon_rises", (33709, 33711, 33713, BLISTERWOOD_STAKE, 33718)),
        )
        for i in ids
    }
    | {
        2952: QuestLeaf(quest_id="priest_in_peril"),
        33722: QuestLeaf(quest_id="the_blood_moon_rises"),
    }
)
REVISION = json.dumps(
    [
        MODEL_VERSION,
        dict(FORMS),
        dict(SPECIALISTS),
        dict(_LEVELS),
        dict(_PROFILES),
        sorted(TRADEABLE),
        sorted(SILVER_CROSSBOWS),
        dict(SILVER_POISON_SEVERITY),
        {i: gate.to_yaml() for i, gate in ACQUISITION_REQUIREMENTS.items()},
    ],
    sort_keys=True,
).encode()


def requirement(item_id: int) -> SkillLeaf | None:
    gate = _LEVELS.get(item_id)
    if gate is None:
        return None
    return SkillLeaf(skill=gate[0], level=gate[1])


def apply_review(row: dict[str, Any]) -> dict[str, Any]:
    item_id = row["id"]
    if item_id in SILVER_CROSSBOWS:
        return {
            **row,
            "ammo_for": tuple(
                dict.fromkeys((*row["ammo_for"], *(f"bolt:{i}" for i in sorted(SILVER_BOLTS))))
            ),
        }
    form = FORMS.get(item_id)
    if form is None:
        return row
    if (row["name"], row["slot"]) != form:
        raise ValueError(f"Reviewed vampyre equipment physical form changed: {item_id}")
    profiles = _PROFILES.get(item_id)
    return {
        **row,
        "unsupported_effects": [
            e
            for e in row["unsupported_effects"]
            if e != "Offensive effects have not been validated."
        ],
        **({"ammo_type": f"bolt:{item_id}"} if item_id in SILVER_BOLTS else {}),
        **(
            {
                "attack_profiles": profiles,
                "attack_styles": tuple(dict.fromkeys(p[0] for p in profiles)),
            }
            if profiles
            else {}
        ),
    }
