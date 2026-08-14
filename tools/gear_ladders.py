"""The three combat gear ladders, transcribed by hand from the wiki's progression guides.

This module is **data, not a fetch**. Its siblings in ``tools/`` pull from APIs; this one is
a transcription, and it is the one file in the pipeline a human has to edit when the guides
change. It is kept separate from the scripts that consume it so that updating the ladders is
never tangled up with re-running a network call.

Sources, one per style:

* https://oldschool.runescape.wiki/w/Guide:Melee_Gear_Progression
* https://oldschool.runescape.wiki/w/Guide:Ranged_Gear_Progression
* https://oldschool.runescape.wiki/w/Guide:Magic_Gear_Progression

**Order is the whole payload.** The position of a name in its list becomes its ``tier`` in
``content/items/items.yaml``, and tier is what lets §21's prompt say *"rung 5 of 12, next
rung Dragon scimitar"* instead of listing two hundred items alphabetically. Two consequences
are worth stating, because both are easy to get wrong later:

1. **It is the guide's order, not a power ranking.** Within a band the guides list several
   options and the transcription keeps that order. Inquisitor's mace sits below Scythe of
   vitur because the melee guide prints them that way, not because anyone measured.
   :func:`tracker.guidance.prompt._rung_line` says as much to the model, and re-tiering
   against real DPS numbers would be a different, deliberate act — not a tidy-up.
2. **Inserting a name renumbers every rung beneath it.** Tiers are positional, so a new rung
   shifts the ones below it and moves §21.5's context hash for any account holding one of
   them. That is correct — the advice really did change — but it means an edit here
   invalidates stored guidance, and that should be on purpose rather than a surprise.

Names must match the wiki's own page titles exactly, because that is what both id lookups
key on: the price API's ``/mapping`` catalog for tradeables, and the wiki's ``Infobox Item``
for everything else. ``capture_gear_ids.py`` fails loudly on a name it cannot resolve rather
than guessing, so a typo here surfaces as an error and never as a wrong item id.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

#: Slot -> the ladder for that slot, lowest rung first.
Ladder = Mapping[str, Sequence[str]]

MELEE: Ladder = {
    "weapon": [
        "Iron scimitar",
        "Steel scimitar",
        "Mithril scimitar",
        "Adamant scimitar",
        "Rune scimitar",
        "Dragon scimitar",
        "Abyssal whip",
        "Abyssal tentacle",
        "Ghrazi rapier",
        "Blade of saeldor",
        "Inquisitor's mace",
        "Scythe of vitur",
    ],
    "head": [
        "Iron full helm",
        "Steel full helm",
        "Mithril full helm",
        "Adamant full helm",
        "Rune full helm",
        "Berserker helm",
        "Helm of neitiznot",
        "Serpentine helm",
        "Neitiznot faceguard",
        "Inquisitor's great helm",
        "Torva full helm",
        "Justiciar faceguard",
    ],
    "body": [
        "Iron platebody",
        "Steel platebody",
        "Mithril platebody",
        "Adamant platebody",
        "Rune platebody",
        "Fighter torso",
        "Inquisitor's hauberk",
        "Torva platebody",
        "Justiciar chestguard",
    ],
    "legs": [
        "Iron platelegs",
        "Steel platelegs",
        "Mithril platelegs",
        "Adamant platelegs",
        "Rune platelegs",
        "Dragon platelegs",
        "Torag's platelegs",
        "Blood moon tassets",
        "Inquisitor's plateskirt",
        "Torva platelegs",
        "Justiciar legguards",
    ],
    "hands": ["Leather gloves", "Barrows gloves", "Ferocious gloves"],
    "feet": ["Leather boots", "Rune boots", "Dragon boots", "Primordial boots", "Echo boots"],
    "cape": ["Black cape", "Ardougne cloak 1", "Ardougne cloak 2", "Fire cape", "Infernal cape"],
    "neck": [
        "Amulet of strength",
        "Amulet of fury",
        "Amulet of torture",
        "Amulet of rancour",
        "Amulet of blood fury",
    ],
    "ring": [
        "Berserker ring",
        "Berserker ring (i)",
        "Ultor ring",
        "Ring of suffering",
        "Ring of suffering (i)",
        "Bellator ring",
    ],
    "shield": ["Dragon defender", "Avernic defender", "Dinh's bulwark"],
}

RANGED: Ladder = {
    "weapon": [
        "Shortbow",
        "Oak shortbow",
        "Willow shortbow",
        "Maple shortbow",
        "Dorgeshuun crossbow",
        "Magic shortbow",
        "Magic shortbow (i)",
        "Rune crossbow",
        "Hunters' sunlight crossbow",
        "Dragon crossbow",
        "Toxic blowpipe",
        "Eclipse atlatl",
        "Webweaver bow",
        "Scorching bow",
        "Dragon hunter crossbow",
        "Armadyl crossbow",
        "Bow of faerdhinen",
        "Zaryte crossbow",
        "Venator bow",
        "Twisted bow",
    ],
    "head": [
        "Leather cowl",
        "Coif",
        "Snakeskin bandana",
        "Archer helm",
        "Void ranger helm",
        "Masori mask",
        "Crystal helm",
        "Masori mask (f)",
    ],
    "body": [
        "Leather body",
        "Studded body",
        "Green d'hide body",
        "Blue d'hide body",
        "Black d'hide body",
        "Elite void top",
        "Masori body",
        "Crystal body",
        "Masori body (f)",
    ],
    "legs": [
        "Leather chaps",
        "Studded chaps",
        "Green d'hide chaps",
        "Blue d'hide chaps",
        "Black d'hide chaps",
        "Elite void robe",
        "Masori chaps",
        "Crystal legs",
        "Masori chaps (f)",
    ],
    "hands": [
        "Leather vambraces",
        "Green d'hide vambraces",
        "Barrows gloves",
        "Void knight gloves",
        "Zaryte vambraces",
    ],
    "feet": ["Snakeskin boots", "Pegasian boots", "Avernic treads"],
    "cape": ["Ava's attractor", "Ava's accumulator", "Ava's assembler", "Dizana's quiver"],
    "neck": [
        "Amulet of power",
        "Amulet of glory",
        "Necklace of anguish",
        "Necklace of rupture",
    ],
    "ring": [
        "Explorer's ring 1",
        "Explorer's ring 2",
        "Explorer's ring 3",
        "Explorer's ring 4",
        "Venator ring",
        "Lightbearer",
    ],
    "shield": [
        "Green d'hide shield",
        "Book of law",
        "Twisted buckler",
        "Dragonfire ward",
        "Odium ward",
    ],
}

MAGIC: Ladder = {
    "weapon": [
        "Staff of air",
        "Iban's staff (u)",
        "Ancient staff",
        "Twinflame staff",
        "Warped sceptre",
        "Trident of the seas",
        "Trident of the swamp",
        "Ancient sceptre",
        "Nightmare staff",
        "Dragon hunter wand",
        "Toxic staff of the dead",
        "Sanguinesti staff",
        "Kodai wand",
        "Harmonised nightmare staff",
        "Purging staff",
        "Eye of ayak",
        "Tumeken's shadow",
    ],
    "head": [
        "Blue wizard hat",
        "Mystic hat",
        "Bloodbark helm",
        "Ahrim's hood",
        "Xerician hat",
        "Virtus mask",
        "Ancestral hat",
    ],
    "body": [
        "Blue wizard robe",
        "Xerician top",
        "Mystic robe top",
        "Bloodbark body",
        "Ahrim's robetop",
        "Ancestral robe top",
        "Virtus robe top",
    ],
    "legs": [
        "Zamorak monk bottom",
        "Xerician robe",
        "Mystic robe bottom",
        "Bloodbark legs",
        "Ahrim's robeskirt",
        "Ancestral robe bottom",
        "Virtus robe bottom",
    ],
    "hands": ["Tormented bracelet", "Combat bracelet", "Confliction gauntlets"],
    "feet": ["Mystic boots", "Bloodbark boots", "Infinity boots", "Eternal boots"],
    "cape": ["Saradomin cape", "Imbued saradomin cape"],
    "neck": ["Amulet of magic", "Occult necklace"],
    "ring": ["Magus ring", "Seers ring", "Seers ring (i)"],
    "shield": [
        "Book of darkness",
        "Malediction ward",
        "Elidinis' ward",
        "Elidinis' ward (f)",
        "Tome of fire",
        "Tome of water",
    ],
}

#: Style -> slot -> ladder. Insertion order is the emitted order, so the generated corpus
#: reads melee, then ranged, then magic — the order the guides themselves are read in.
LADDERS: Mapping[str, Ladder] = {"melee": MELEE, "ranged": RANGED, "magic": MAGIC}


def every_name() -> list[tuple[str, str, int, str]]:
    """``(style, slot, tier, name)`` for every rung, tier being the 1-based position."""
    return [
        (style, slot, tier, name)
        for style, slots in LADDERS.items()
        for slot, names in slots.items()
        for tier, name in enumerate(names, start=1)
    ]


def unique_names() -> list[str]:
    """Every distinct name, in first-seen order. A name on two ladders is resolved once."""
    seen: dict[str, None] = {}
    for _, _, _, name in every_name():
        seen.setdefault(name, None)
    return list(seen)
