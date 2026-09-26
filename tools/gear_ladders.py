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
from typing import Any

#: Slot -> the ladder for that slot, lowest rung first.
Ladder = Mapping[str, Sequence[str]]

# ---------------------------------------------------------------------------
# A name may appear on several ladders
# ---------------------------------------------------------------------------
#
# Barrows gloves are melee *and* ranged; an Antler guard is a tribrid shield the melee and
# ranged guides both reach for. Write the name on every ladder whose guide prints it.
#
# `generate_gear_items.render` emits one row per placement, sharing the numeric item id and
# suffixing the *content* id (`antler_guard`, `antler_guard_ranged`), and
# `_check_gear_ladders` requires those rows to be indistinguishable as items — same name,
# same ownership union, same wear gate, same acquisition, same pricing. Owning one Antler
# guard then places the account on both ladders, which is simply true.
#
# **This did not always work, and the way it failed is worth remembering.** The generator used
# to declare a name once and leave a comment where it recurred, so whichever style was walked
# first won the rung and the others lost it — silently, and worse than an omission, because
# `tier` is the position in *this* list while `ladder_size` counts what actually reached the
# corpus. A stolen rung left a gap, and the ranged hands ladder rendered its top rung as
# *"rung 5 of 4"*. `tests/tools/test_gear_ladders.py::TestEveryLadderIsContiguous` now fails
# on any such gap.

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
        "Oathplate helm",
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
        "Oathplate chest",
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
        "Oathplate legs",
        "Torva platelegs",
        "Justiciar legguards",
    ],
    "hands": ["Leather gloves", "Combat bracelet", "Barrows gloves", "Ferocious gloves"],
    "feet": [
        "Leather boots",
        "Fighting boots",
        "Rune boots",
        "Dragon boots",
        "Primordial boots",
        "Echo boots",
    ],
    # `Mixed hide cape` is the rung this ladder most needed: every other cape below the Fire
    # cape is a diary reward with no strength bonus at all, so before it landed the only
    # *buyable* melee cape on the ladder was a black cape.
    "cape": [
        "Black cape",
        "Ardougne cloak 1",
        "Ardougne cloak 2",
        "Mixed hide cape",
        "Fire cape",
        "Infernal cape",
    ],
    "neck": [
        "Amulet of strength",
        "Amulet of fury",
        "Amulet of torture",
        "Amulet of rancour",
        "Amulet of blood fury",
    ],
    "ring": [
        "Explorer's ring 1",
        "Explorer's ring 2",
        "Berserker ring",
        "Berserker ring (i)",
        "Ultor ring",
        "Ring of suffering",
        "Ring of suffering (i)",
        "Bellator ring",
    ],
    # Four rungs, and the guide's shield column really is this short: Mooleta at 40+, Antler
    # guard at 65+, Dragon defender at 70+, Avernic defender at the endgame. `Mooleta` is the
    # first shield the guide ever puts on, which is why it is rung 1.
    #
    # **This ladder was briefly eleven rungs long and that was a transcription error worth
    # naming.** The bronze/iron/steel/black/mithril/adamant/rune defenders were pulled in from
    # the wiki's `Shield_slot_table` — a stat table of every shield in the game — because a
    # research pass blended it with the progression guide. They are real items in a sensible
    # order and they are *not in the guide*, which is the only thing this file is allowed to
    # carry. A ladder padded from a stat table looks more complete and silently stops being
    # the guide's opinion, which is the one property `tier` is supposed to have.
    #
    # `Dinh's bulwark` came off this ladder rather than moving down it. It is a two-handed
    # *weapon*, not a shield, and the guide reaches for it only in the endgame Defence build,
    # where the shield slot is empty because the bulwark fills both hands.
    "shield": [
        "Mooleta",
        "Antler guard",
        "Dragon defender",
        "Avernic defender",
    ],
    # One rung, and a real ladder rather than an empty slot. The blessing is a prayer-bonus
    # filler and the guide lists nothing else for the slot in any melee loadout, so a
    # single-rung ladder is the honest transcription rather than a stub.
    "ammunition": ["Peaceful blessing"],
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
        # The guide prints the sunlight crossbow before the rune one, and the atlatl before
        # the blowpipe. Both were transcribed the other way round; corrected to the printed
        # order, which is the only order this file claims to carry.
        "Hunters' sunlight crossbow",
        "Rune crossbow",
        "Red chinchompa",
        "Black chinchompa",
        "Dragon crossbow",
        "Eclipse atlatl",
        "Toxic blowpipe",
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
        "Guthix coif",
        "Hueycoatl hide coif",
        "Masori mask",
        "Crystal helm",
        "Masori mask (f)",
    ],
    "body": [
        "Leather body",
        "Studded body",
        "Green d'hide body",
        "Blue d'hide body",
        "Mixed hide top",
        "Black d'hide body",
        "Elite void top",
        "Guthix d'hide body",
        "Hueycoatl hide body",
        "Masori body",
        "Crystal body",
        "Masori body (f)",
    ],
    "legs": [
        "Leather chaps",
        "Studded chaps",
        "Green d'hide chaps",
        "Blue d'hide chaps",
        "Mixed hide legs",
        "Black d'hide chaps",
        "Elite void robe",
        "Guthix chaps",
        "Hueycoatl hide chaps",
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
    "feet": [
        "Snakeskin boots",
        "Mixed hide boots",
        "Guthix d'hide boots",
        "Pegasian boots",
        "Avernic treads",
    ],
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
        "Lightbearer",
        "Venator ring",
    ],
    # Odium ward sat at the top of this ladder and the guide ranks it near the bottom: its
    # ranged-strength table runs Odium ward +4, Dragonfire ward +8, Twisted buckler +10.
    "shield": [
        "Green d'hide shield",
        "Book of law",
        "Antler guard",
        "Odium ward",
        "Dragonfire ward",
        "Twisted buckler",
    ],
    # The slot the ranged guide spends the most words on and the corpus had nothing for. Its
    # order is the guide's own, which interleaves arrows, bolts and darts by the band they are
    # printed in rather than by ammunition family — a bolt is not "above" an arrow, it is the
    # step the guide prints next for the crossbow you are by then holding.
    #
    # Steel cannonballs and revenant ether are in the guide's tables and are not here: one is
    # a deployable and the other is a charge, and neither is worn in the slot.
    # Nine rungs, and they are the nine the guide's ammo cells actually print. This ladder
    # was briefly twenty-three, padded with the rest of the arrow, bolt and dart families
    # because a research pass reached past the loadout tables into the wiki's slot tables —
    # the same error that put seven plain defenders on the melee shield ladder. The guide
    # skips Steel arrow and every dart, and a transcription is not allowed to tidy that up.
    #
    # Chinchompas are in the guide's *ammo* cells and are not here: in game they occupy the
    # weapon slot, and `slot` is an equipment slot rather than a column heading, so they sit
    # on the weapon ladder where the account will actually wear them.
    "ammunition": [
        "Iron arrow",
        "Mithril arrow",
        "Adamant arrow",
        "Bone bolts",
        "Rune arrow",
        "Amethyst arrow",
        "Moonlight antler bolts",
        "Ruby dragon bolts (e)",
        "Seeking dragon arrow",
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
        "Ancient sceptre",
        "Trident of the swamp",
        "Nightmare staff",
        "Dragon hunter wand",
        "Toxic staff of the dead",
        "Sanguinesti staff",
        "Eye of ayak",
        "Kodai wand",
        "Harmonised nightmare staff",
        "Purging staff",
        "Tumeken's shadow",
    ],
    "head": [
        "Blue wizard hat",
        "Xerician hat",
        "Mystic hat",
        "Bloodbark helm",
        "Ahrim's hood",
        "Virtus mask",
        "Ancestral hat",
        "Void mage helm",
    ],
    "body": [
        "Blue wizard robe",
        "Xerician top",
        "Mystic robe top",
        "Bloodbark body",
        "Ahrim's robetop",
        "Virtus robe top",
        "Ancestral robe top",
    ],
    "legs": [
        "Zamorak monk bottom",
        "Xerician robe",
        "Mystic robe bottom",
        "Bloodbark legs",
        "Ahrim's robeskirt",
        "Virtus robe bottom",
        "Ancestral robe bottom",
    ],
    "hands": ["Combat bracelet", "Tormented bracelet", "Confliction gauntlets"],
    "feet": ["Mystic boots", "Bloodbark boots", "Infinity boots", "Eternal boots"],
    "cape": ["Saradomin cape", "Imbued saradomin cape"],
    "neck": ["Amulet of magic", "Occult necklace"],
    "ring": ["Seers ring (i)", "Magus ring"],
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


# ---------------------------------------------------------------------------
# What it takes to wear each rung (§23.2)
# ---------------------------------------------------------------------------
#
# Tier says which rung comes next; it does not say whether the account can *use* it, and
# without that "next rung: Twisted bow" is advice for somebody forty Ranged levels away.
# These three tables answer the second question, and they are deliberately three rather
# than two: **an absent name must never read as ungated**. That is the failure this whole
# design is arranged around — silently telling a fresh account it can equip a Torva
# platebody is worse than admitting nobody has checked.
#
# So every rung lands in exactly one of:
#
#   REQUIREMENTS   somebody read the wiki and wrote the gate down
#   UNGATED        somebody read the wiki and there is no gate — an assertion, not a default
#   UNTRANSCRIBED  nobody has checked yet, or the gate is one this grammar cannot state
#
# `missing_requirements()` proves the partition is total, and a test asserts it is empty.
# An UNTRANSCRIBED rung reaches the corpus as `gate_unknown: true` and evaluates to
# Tri.UNKNOWN, which §23.4 forbids from ever becoming *"you can wear this"*. The cost of
# leaving a rung here is a slot that says "requirements not checked"; the cost of guessing
# is a confident lie, so this is the side to err on.
#
# **These are *equip* requirements only.** The wiki states them in prose rather than in any
# infobox field, and the prose freely mixes in the levels needed to *make* or *imbue* the
# item — 80 Fletching for a magic shortbow, 90 Smithing to repair Torva, 59 Crafting for a
# toxic staff of the dead. None of those gate wearing it, and none of them belong here.
#
# Requirement values are the plain nested mappings §10.2's parser reads, so this module
# stays free of any `tracker` import (as every other file in `tools/` is, bar the tuner).
# Ids are the corpus's, not the wiki's page titles: `monkey_madness_i`, not "Monkey Madness
# I". A typo surfaces as a ContentError from `_check_references` — which is why items were
# added to `_requirement_sources` in the same change — and never as advice nobody can act on.

#: Name -> the §10.2 requirement tree gating *wearing* it.
#:
#: Name-keyed rather than (style, slot, tier)-keyed, for the reason the generator's
#: PRICED_VARIANT table is: Barrows gloves sit on the melee *and* ranged ladders, and one
#: piece of gear has one set of requirements. Keying by rung would let the two drift.
REQUIREMENTS: Mapping[str, Mapping[str, Any]] = {
    # --- melee ---
    "Steel scimitar": {"skill": {"attack": 5}},
    "Mithril scimitar": {"skill": {"attack": 20}},
    "Adamant scimitar": {"skill": {"attack": 30}},
    "Rune scimitar": {"skill": {"attack": 40}},
    "Dragon scimitar": {
        "all_of": [{"skill": {"attack": 60}}, {"quest": "monkey_madness_i"}],
    },
    "Abyssal whip": {"skill": {"attack": 70}},
    "Abyssal tentacle": {"skill": {"attack": 75}},
    "Ghrazi rapier": {"skill": {"attack": 80}},
    "Blade of saeldor": {"skill": {"attack": 80}},
    "Inquisitor's mace": {"skill": {"attack": 80}},
    "Scythe of vitur": {"skill": {"attack": 80, "strength": 90}},
    "Steel full helm": {"skill": {"defence": 5}},
    "Mithril full helm": {"skill": {"defence": 20}},
    "Adamant full helm": {"skill": {"defence": 30}},
    "Rune full helm": {"skill": {"defence": 40}},
    "Berserker helm": {
        "all_of": [{"skill": {"defence": 45}}, {"quest": "the_fremennik_trials"}],
    },
    "Helm of neitiznot": {
        "all_of": [{"skill": {"defence": 55}}, {"quest": "the_fremennik_isles"}],
    },
    "Serpentine helm": {"skill": {"defence": 75}},
    "Neitiznot faceguard": {
        "all_of": [{"skill": {"defence": 70}}, {"quest": "the_fremennik_exiles"}],
    },
    "Inquisitor's great helm": {"skill": {"defence": 30, "strength": 70}},
    "Torva full helm": {"skill": {"defence": 80}},
    "Justiciar faceguard": {"skill": {"defence": 75}},
    "Steel platebody": {"skill": {"defence": 5}},
    "Mithril platebody": {"skill": {"defence": 20}},
    "Adamant platebody": {"skill": {"defence": 30}},
    "Rune platebody": {
        "all_of": [{"skill": {"defence": 40}}, {"quest": "dragon_slayer_i"}],
    },
    "Fighter torso": {"skill": {"defence": 40}},
    "Inquisitor's hauberk": {"skill": {"defence": 30, "strength": 70}},
    "Torva platebody": {"skill": {"defence": 80}},
    "Justiciar chestguard": {"skill": {"defence": 75}},
    "Steel platelegs": {"skill": {"defence": 5}},
    "Mithril platelegs": {"skill": {"defence": 20}},
    "Adamant platelegs": {"skill": {"defence": 30}},
    "Rune platelegs": {"skill": {"defence": 40}},
    "Dragon platelegs": {"skill": {"defence": 60}},
    "Torag's platelegs": {"skill": {"defence": 70}},
    "Blood moon tassets": {"skill": {"defence": 50, "strength": 75}},
    "Inquisitor's plateskirt": {"skill": {"defence": 30, "strength": 70}},
    "Torva platelegs": {"skill": {"defence": 80}},
    "Justiciar legguards": {"skill": {"defence": 75}},
    # No Defence requirement of its own — the gate is the quest, which is the whole reason
    # the wiki page has to say "these gloves lack a Defence requirement" out loud.
    "Barrows gloves": {"quest": "recipe_for_disaster"},
    "Ferocious gloves": {"skill": {"attack": 80, "defence": 80}},
    "Rune boots": {"skill": {"defence": 40}},
    "Dragon boots": {"skill": {"defence": 60}},
    "Primordial boots": {"skill": {"defence": 75, "strength": 75}},
    "Echo boots": {"skill": {"defence": 75}},
    "Amulet of torture": {"skill": {"hitpoints": 75}},
    "Amulet of rancour": {"skill": {"hitpoints": 90}},
    "Oathplate helm": {"skill": {"defence": 78}},
    "Oathplate chest": {"skill": {"defence": 78}},
    "Oathplate legs": {"skill": {"defence": 78}},
    "Mixed hide cape": {"skill": {"ranged": 60, "defence": 50}},
    # The 68 Crafting the wiki prints beside this cape makes one; it does not wear one.
    "Antler guard": {"skill": {"prayer": 50}},
    "Dragon defender": {"skill": {"defence": 60}},
    "Avernic defender": {"skill": {"attack": 70, "defence": 70}},
    # --- ranged ---
    "Oak shortbow": {"skill": {"ranged": 5}},
    "Willow shortbow": {"skill": {"ranged": 20}},
    "Maple shortbow": {"skill": {"ranged": 30}},
    "Dorgeshuun crossbow": {"skill": {"ranged": 28}},
    "Magic shortbow": {"skill": {"ranged": 50}},
    "Magic shortbow (i)": {"skill": {"ranged": 50}},
    "Rune crossbow": {"skill": {"ranged": 61}},
    "Hunters' sunlight crossbow": {"skill": {"ranged": 66, "hunter": 50}},
    "Dragon crossbow": {"skill": {"ranged": 64}},
    "Toxic blowpipe": {"skill": {"ranged": 75}},
    "Eclipse atlatl": {"skill": {"ranged": 75, "attack": 50, "strength": 50}},
    "Webweaver bow": {"skill": {"ranged": 70}},
    "Scorching bow": {"skill": {"ranged": 77}},
    "Dragon hunter crossbow": {"skill": {"ranged": 70}},
    "Armadyl crossbow": {"skill": {"ranged": 70}},
    "Bow of faerdhinen": {"skill": {"ranged": 80, "agility": 70}},
    "Zaryte crossbow": {"skill": {"ranged": 80}},
    "Venator bow": {"skill": {"ranged": 80}},
    "Twisted bow": {"skill": {"ranged": 85}},
    "Coif": {"skill": {"ranged": 20}},
    "Snakeskin bandana": {"skill": {"ranged": 30, "defence": 30}},
    "Archer helm": {
        "all_of": [{"skill": {"defence": 45}}, {"quest": "the_fremennik_trials"}],
    },
    # The Void set gates on six levels at once, and on 22 Prayer — the one requirement a
    # player is most likely to be short of without noticing.
    "Void ranger helm": {
        "skill": {
            "attack": 42,
            "strength": 42,
            "defence": 42,
            "ranged": 42,
            "magic": 42,
            "hitpoints": 42,
            "prayer": 22,
        }
    },
    "Void knight gloves": {
        "skill": {
            "attack": 42,
            "strength": 42,
            "defence": 42,
            "ranged": 42,
            "magic": 42,
            "hitpoints": 42,
            "prayer": 22,
        }
    },
    "Elite void top": {
        "skill": {
            "attack": 42,
            "strength": 42,
            "defence": 42,
            "ranged": 42,
            "magic": 42,
            "hitpoints": 42,
            "prayer": 22,
        }
    },
    "Elite void robe": {
        "skill": {
            "attack": 42,
            "strength": 42,
            "defence": 42,
            "ranged": 42,
            "magic": 42,
            "hitpoints": 42,
            "prayer": 22,
        }
    },
    "Masori mask": {"skill": {"ranged": 80, "defence": 30}},
    "Masori mask (f)": {"skill": {"ranged": 80, "defence": 30}},
    "Masori body": {"skill": {"ranged": 80, "defence": 30}},
    "Masori body (f)": {"skill": {"ranged": 80, "defence": 30}},
    "Masori chaps": {"skill": {"ranged": 80, "defence": 30}},
    "Masori chaps (f)": {"skill": {"ranged": 80, "defence": 30}},
    "Crystal helm": {"skill": {"defence": 70, "agility": 50}},
    "Crystal body": {"skill": {"defence": 70, "agility": 50}},
    "Crystal legs": {"skill": {"defence": 70, "agility": 50}},
    "Studded body": {"skill": {"ranged": 20}},
    "Studded chaps": {"skill": {"ranged": 20}},
    # Every dragonhide *body* is gated on Dragon Slayer I; the chaps and vambraces are not.
    "Green d'hide body": {
        "all_of": [{"skill": {"ranged": 40, "defence": 40}}, {"quest": "dragon_slayer_i"}],
    },
    "Blue d'hide body": {
        "all_of": [{"skill": {"ranged": 50, "defence": 40}}, {"quest": "dragon_slayer_i"}],
    },
    "Black d'hide body": {
        "all_of": [{"skill": {"ranged": 70, "defence": 40}}, {"quest": "dragon_slayer_i"}],
    },
    "Green d'hide chaps": {"skill": {"ranged": 40}},
    "Blue d'hide chaps": {"skill": {"ranged": 50}},
    "Black d'hide chaps": {"skill": {"ranged": 70}},
    "Green d'hide vambraces": {"skill": {"ranged": 40}},
    "Zaryte vambraces": {"skill": {"ranged": 80, "defence": 45}},
    "Snakeskin boots": {"skill": {"ranged": 30, "defence": 30}},
    "Pegasian boots": {"skill": {"ranged": 75, "defence": 75}},
    "Avernic treads": {"skill": {"defence": 80, "strength": 80, "ranged": 80, "magic": 80}},
    "Ava's assembler": {"skill": {"ranged": 70}},
    "Ava's attractor": {"skill": {"ranged": 30}},
    "Ava's accumulator": {"skill": {"ranged": 50}},
    "Dizana's quiver": {"skill": {"ranged": 75}},
    "Necklace of anguish": {"skill": {"hitpoints": 75}},
    "Necklace of rupture": {"skill": {"hitpoints": 90}},
    "Green d'hide shield": {"skill": {"ranged": 40, "defence": 40}},
    "Twisted buckler": {"skill": {"ranged": 75, "defence": 75}},
    "Dragonfire ward": {
        "all_of": [{"skill": {"ranged": 70, "defence": 75}}, {"quest": "dragon_slayer_i"}],
    },
    "Odium ward": {"skill": {"defence": 60}},
    # --- magic ---
    "Red chinchompa": {"skill": {"ranged": 55}},
    "Black chinchompa": {"skill": {"ranged": 65}},
    "Guthix coif": {"skill": {"ranged": 70, "defence": 40}},
    "Hueycoatl hide coif": {"skill": {"ranged": 70, "defence": 40}},
    "Guthix d'hide body": {"skill": {"ranged": 70, "defence": 40}},
    "Hueycoatl hide body": {"skill": {"ranged": 70, "defence": 40}},
    "Mixed hide top": {"skill": {"ranged": 60, "defence": 50}},
    "Mixed hide boots": {"skill": {"ranged": 60, "defence": 50}},
    "Guthix d'hide boots": {"skill": {"ranged": 70, "defence": 40}},
    # These three leg pieces state a Ranged requirement and no Defence one on their own
    # pages, unlike their body counterparts. Transcribed as printed rather than made
    # consistent with the tops — a symmetry nobody checked is still a guess.
    "Mixed hide legs": {"skill": {"ranged": 60}},
    "Guthix chaps": {"skill": {"ranged": 70}},
    "Hueycoatl hide chaps": {"skill": {"ranged": 70}},
    # Ammunition. Most arrows carry no gate of their own — what stops a level-3 account
    # firing a rune arrow is the bow, not the arrow — so only the ones whose own page
    # states a requirement are here.
    "Bone bolts": {"skill": {"ranged": 28}},
    "Moonlight antler bolts": {"skill": {"ranged": 66}},
    "Void mage helm": {
        "skill": {
            "attack": 42,
            "strength": 42,
            "defence": 42,
            "ranged": 42,
            "magic": 42,
            "hitpoints": 42,
            "prayer": 22,
        }
    },
    "Iban's staff (u)": {"skill": {"magic": 50, "attack": 50}},
    "Ancient staff": {
        "all_of": [{"skill": {"magic": 50, "attack": 50}}, {"quest": "desert_treasure_i"}],
    },
    "Twinflame staff": {"skill": {"magic": 60}},
    "Warped sceptre": {"skill": {"magic": 62}},
    "Trident of the seas": {"skill": {"magic": 75}},
    "Trident of the swamp": {"skill": {"magic": 78}},
    "Ancient sceptre": {
        "all_of": [
            {"skill": {"magic": 70, "strength": 60, "attack": 50}},
            {"quest": "secrets_of_the_north"},
        ],
    },
    "Nightmare staff": {"skill": {"magic": 72, "hitpoints": 50}},
    "Dragon hunter wand": {"skill": {"magic": 65}},
    "Toxic staff of the dead": {"skill": {"magic": 75, "attack": 75}},
    "Sanguinesti staff": {"skill": {"magic": 82}},
    "Kodai wand": {"skill": {"magic": 80}},
    "Harmonised nightmare staff": {"skill": {"magic": 82, "hitpoints": 50}},
    "Purging staff": {"skill": {"magic": 77, "attack": 50}},
    "Eye of ayak": {"skill": {"magic": 83}},
    "Tumeken's shadow": {"skill": {"magic": 85}},
    "Mystic hat": {"skill": {"magic": 40, "defence": 20}},
    "Mystic robe top": {"skill": {"magic": 40, "defence": 20}},
    "Mystic robe bottom": {"skill": {"magic": 40, "defence": 20}},
    "Mystic boots": {"skill": {"magic": 40, "defence": 20}},
    "Xerician hat": {"skill": {"magic": 20, "defence": 10}},
    "Xerician top": {"skill": {"magic": 20, "defence": 10}},
    "Xerician robe": {"skill": {"magic": 20, "defence": 10}},
    "Bloodbark helm": {"skill": {"magic": 60, "defence": 60}},
    "Bloodbark body": {"skill": {"magic": 60, "defence": 60}},
    "Bloodbark legs": {"skill": {"magic": 60, "defence": 60}},
    "Bloodbark boots": {"skill": {"magic": 60, "defence": 60}},
    "Ahrim's hood": {"skill": {"magic": 70, "defence": 70}},
    "Ahrim's robetop": {"skill": {"magic": 70, "defence": 70}},
    "Ahrim's robeskirt": {"skill": {"magic": 70, "defence": 70}},
    "Ancestral hat": {"skill": {"magic": 75, "defence": 65}},
    "Ancestral robe top": {"skill": {"magic": 75, "defence": 65}},
    "Ancestral robe bottom": {"skill": {"magic": 75, "defence": 65}},
    "Virtus mask": {"skill": {"magic": 78, "defence": 75}},
    "Virtus robe top": {"skill": {"magic": 78, "defence": 75}},
    "Virtus robe bottom": {"skill": {"magic": 78, "defence": 75}},
    "Tormented bracelet": {"skill": {"hitpoints": 75}},
    "Confliction gauntlets": {"skill": {"hitpoints": 90}},
    "Infinity boots": {"skill": {"magic": 50, "defence": 25}},
    "Eternal boots": {"skill": {"magic": 75, "defence": 75}},
    "Imbued saradomin cape": {"skill": {"magic": 75}},
    "Occult necklace": {"skill": {"magic": 70}},
    "Malediction ward": {"skill": {"defence": 60}},
    "Elidinis' ward": {"skill": {"magic": 80, "defence": 80, "prayer": 80}},
    "Elidinis' ward (f)": {"skill": {"magic": 80, "defence": 80, "prayer": 80}},
    "Tome of fire": {"skill": {"magic": 50}},
    "Tome of water": {"skill": {"magic": 50}},
    "Ring of suffering": {"skill": {"hitpoints": 75}},
    "Ring of suffering (i)": {"skill": {"hitpoints": 75}},
    "Book of law": {"quest": "horror_from_the_deep"},
    "Book of darkness": {"quest": "horror_from_the_deep"},
    "Saradomin cape": {"skill": {"magic": 60}},
}

#: Rungs the wiki states have no requirement to equip.
#:
#: This is an *assertion*, not the absence of one. Level-1 metal, the jewellery that
#: enchants into its bonuses without a level check, the capes and the rings — all genuinely
#: wearable by a brand-new account. Moving a name from here into UNTRANSCRIBED is always
#: safe; the reverse needs someone to have read the page.
UNGATED: frozenset[str] = frozenset(
    {
        "Iron scimitar",
        "Iron full helm",
        "Iron platebody",
        "Iron platelegs",
        "Leather gloves",
        "Leather boots",
        # The rung that prompted the whole re-transcription. No requirements to wield at all,
        # which is most of why the guide keeps it in the shield slot from level 1 to 40+.
        "Mooleta",
        "Fighting boots",
        "Peaceful blessing",
        # Ammunition whose own page states no wear requirement. What stops a level-3 account
        # firing a rune arrow is the bow, and the bow is the weapon ladder's business.
        "Iron arrow",
        "Mithril arrow",
        "Adamant arrow",
        "Rune arrow",
        "Amethyst arrow",
        "Seeking dragon arrow",
        # The dragon bolts state no level of their own either; the guide gates them on
        # holding a dragon crossbow or better, which is again the weapon ladder's business.
        "Ruby dragon bolts (e)",
        "Black cape",
        "Ardougne cloak 1",
        "Ardougne cloak 2",
        "Fire cape",
        "Infernal cape",
        "Amulet of strength",
        "Amulet of fury",
        "Amulet of blood fury",
        "Berserker ring",
        "Berserker ring (i)",
        "Shortbow",
        "Leather cowl",
        "Leather body",
        "Leather chaps",
        "Leather vambraces",
        "Amulet of power",
        "Amulet of glory",
        "Explorer's ring 1",
        "Explorer's ring 2",
        "Explorer's ring 3",
        "Explorer's ring 4",
        "Lightbearer",
        "Staff of air",
        "Blue wizard hat",
        "Blue wizard robe",
        "Zamorak monk bottom",
        "Combat bracelet",
        "Amulet of magic",
        "Seers ring (i)",
    }
)

#: Rungs whose gate nobody has written down yet, or that this grammar cannot state.
#:
#: These reach the corpus as ``gate_unknown: true`` and evaluate to ``Tri.UNKNOWN``, so
#: §23.4 will never present one as *"you can wear this"*. Emptying this set is ordinary
#: content work; leaving a name in it costs a slot that says "requirements not checked",
#: which is the honest answer whenever it is the true one.
#:
#: The four Desert Treasure II rings are here for the second reason rather than the first.
#: Their real gate is *"you have killed this boss at least once"*, and the nearest thing
#: §10.2 can say — completion of the quest — is strictly weaker: it would report the ring
#: as wearable to a player who finished the quest and never went back. An under-strict gate
#: is exactly the confident lie the three-way split exists to prevent, so it is left unsaid.
UNTRANSCRIBED: frozenset[str] = frozenset(
    {
        "Ultor ring",
        "Bellator ring",
        "Magus ring",
        "Venator ring",
    }
)


# ---------------------------------------------------------------------------
# How you get each rung (§10.5's acquisition axis)
# ---------------------------------------------------------------------------
#
# The second axis, and **orthogonal to the first**: every rung is classified once for what it
# takes to *wear* it and once for how it reaches your hands. Two partitions over the same
# names rather than one six-way table, so `missing_requirements()` and `missing_acquisitions()`
# each fail for exactly one omission.
#
#   TRADEABLE                  gp alone can put one in your hands
#   EARNED_FROM                it has to be won, and from what
#   ACQUISITION_UNTRANSCRIBED  nobody has checked
#
# **What TRADEABLE means, since the game makes this a judgement rather than a lookup.** Half
# the late-game ladder is a tradeable component that becomes an untradeable item the moment
# you use it: an empty blowpipe, an inactive Blade of saeldor, an uncharged Sanguinesti staff,
# a crystal armour seed. The question this axis answers is *"can the player get one"*, so the
# component settles it and all of those are TRADEABLE. What is **not** tradeable is a piece
# whose chain reaches something the market does not sell at all — an Avernic defender needs a
# Dragon defender, and no amount of gp buys a Dragon defender.
#
# This is deliberately **not** the wiki's own tradeability flag, which is a fact about the
# item and answers a question nobody on this page asked.
#
# An ACQUISITION_UNTRANSCRIBED rung emits no `acquisition:` line, and §23.4 **does not demote
# on it** — it is still recommended, with every mention caveated. That asymmetry against the
# gate tables is argued at length in `tracker/gear/setup.py`; the practical consequence here is
# that this is the *safe* table to put a rung you are unsure of, where UNTRANSCRIBED on the
# gate side gives a page that says "requirements not checked". Guessing `untradeable` is the
# error that costs something: it withholds a rung the player could have gone and bought.

#: Name -> the content that yields it, as a **noun phrase** the surfaces compose into a
#: sentence — *"untradeable — earned from {value}"*. A sentence here renders as a sentence
#: inside a sentence, which is the one way this can go wrong and is visible immediately.
#:
#: This mapping **is** the untradeable set. Naming the source is only ever wanted for a piece
#: you cannot buy, so a frozenset beside it would be a second list nobody could keep in step.
EARNED_FROM: Mapping[str, str] = {
    # --- melee ---
    "Fighter torso": "Barbarian Assault",
    "Barrows gloves": "Recipe for Disaster",
    "Ardougne cloak 1": "the Ardougne Diary",
    "Ardougne cloak 2": "the Ardougne Diary",
    "Fire cape": "the Fight Caves",
    "Infernal cape": "the Inferno",
    "Dragon defender": "Cyclopes in the Warriors' Guild basement, shown a rune defender",
    "Mooleta": "Brutus, after the quest",
    "Fighting boots": "the Stronghold of Security, with two-factor authentication enabled",
    # The one that is untradeable despite a tradeable component: the hilt trades, and the
    # Dragon defender it attaches to does not.
    "Avernic defender": "a Dragon defender and a hilt from the Theatre of Blood",
    "Berserker ring (i)": "imbuing a Berserker ring at Nightmare Zone or Soul Wars",
    "Ring of suffering (i)": "imbuing a Ring of suffering at Nightmare Zone or Soul Wars",
    # --- ranged ---
    "Void ranger helm": "Pest Control",
    "Void mage helm": "Pest Control",
    "Elite void top": "Pest Control",
    "Elite void robe": "Pest Control",
    "Void knight gloves": "Pest Control",
    "Magic shortbow (i)": "imbuing a Magic shortbow at Nightmare Zone or Soul Wars",
    "Ava's attractor": "Animal Magnetism",
    "Ava's accumulator": "Animal Magnetism",
    "Ava's assembler": "Dragon Slayer II",
    "Dizana's quiver": "the Fortis Colosseum",
    "Explorer's ring 1": "the Lumbridge & Draynor Diary",
    "Explorer's ring 2": "the Lumbridge & Draynor Diary",
    "Explorer's ring 3": "the Lumbridge & Draynor Diary",
    "Explorer's ring 4": "the Lumbridge & Draynor Diary",
    "Book of law": "Horror from the Deep, from a damaged book and its pages",
    # --- magic ---
    "Iban's staff (u)": "Underground Pass",
    "Saradomin cape": "the Mage Arena",
    "Imbued saradomin cape": "the Mage Arena II",
    "Seers ring (i)": "imbuing a Seers ring at Nightmare Zone or Soul Wars",
    "Book of darkness": "Horror from the Deep, from a damaged book and its pages",
}

#: Rungs gp alone can put in your hands — see the note above on what that includes.
TRADEABLE: frozenset[str] = frozenset(
    {
        # --- melee ---
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
        "Iron platebody",
        "Steel platebody",
        "Mithril platebody",
        "Adamant platebody",
        "Rune platebody",
        "Inquisitor's hauberk",
        "Torva platebody",
        "Justiciar chestguard",
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
        "Leather gloves",
        "Ferocious gloves",
        "Leather boots",
        "Rune boots",
        "Dragon boots",
        "Primordial boots",
        "Echo boots",
        "Black cape",
        "Amulet of strength",
        "Amulet of fury",
        "Amulet of torture",
        "Amulet of rancour",
        "Amulet of blood fury",
        "Berserker ring",
        "Ultor ring",
        "Ring of suffering",
        "Bellator ring",
        "Oathplate helm",
        "Oathplate chest",
        "Oathplate legs",
        "Mixed hide cape",
        "Antler guard",
        "Peaceful blessing",
        # --- ranged ---
        "Shortbow",
        "Oak shortbow",
        "Willow shortbow",
        "Maple shortbow",
        "Dorgeshuun crossbow",
        "Magic shortbow",
        "Rune crossbow",
        "Hunters' sunlight crossbow",
        "Dragon crossbow",
        "Toxic blowpipe",
        "Eclipse atlatl",
        "Webweaver bow",
        "Dragon hunter crossbow",
        "Armadyl crossbow",
        "Bow of faerdhinen",
        "Zaryte crossbow",
        "Venator bow",
        "Twisted bow",
        "Leather cowl",
        "Coif",
        "Snakeskin bandana",
        "Archer helm",
        "Masori mask",
        "Crystal helm",
        "Masori mask (f)",
        "Leather body",
        "Studded body",
        "Green d'hide body",
        "Blue d'hide body",
        "Black d'hide body",
        "Masori body",
        "Crystal body",
        "Masori body (f)",
        "Leather chaps",
        "Studded chaps",
        "Green d'hide chaps",
        "Blue d'hide chaps",
        "Black d'hide chaps",
        "Masori chaps",
        "Crystal legs",
        "Masori chaps (f)",
        "Leather vambraces",
        "Green d'hide vambraces",
        "Zaryte vambraces",
        "Snakeskin boots",
        "Pegasian boots",
        "Avernic treads",
        "Amulet of power",
        "Amulet of glory",
        "Necklace of anguish",
        "Necklace of rupture",
        "Venator ring",
        "Lightbearer",
        "Green d'hide shield",
        "Red chinchompa",
        "Black chinchompa",
        "Guthix coif",
        "Hueycoatl hide coif",
        "Mixed hide top",
        "Guthix d'hide body",
        "Hueycoatl hide body",
        "Mixed hide legs",
        "Guthix chaps",
        "Hueycoatl hide chaps",
        "Mixed hide boots",
        "Guthix d'hide boots",
        "Iron arrow",
        "Mithril arrow",
        "Adamant arrow",
        "Rune arrow",
        "Amethyst arrow",
        "Bone bolts",
        "Moonlight antler bolts",
        "Ruby dragon bolts (e)",
        "Seeking dragon arrow",
        "Twisted buckler",
        "Dragonfire ward",
        "Odium ward",
        # --- magic ---
        "Staff of air",
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
        "Tumeken's shadow",
        "Blue wizard hat",
        "Mystic hat",
        "Bloodbark helm",
        "Ahrim's hood",
        "Xerician hat",
        "Virtus mask",
        "Ancestral hat",
        "Blue wizard robe",
        "Xerician top",
        "Mystic robe top",
        "Bloodbark body",
        "Ahrim's robetop",
        "Ancestral robe top",
        "Virtus robe top",
        "Zamorak monk bottom",
        "Xerician robe",
        "Mystic robe bottom",
        "Bloodbark legs",
        "Ahrim's robeskirt",
        "Ancestral robe bottom",
        "Virtus robe bottom",
        "Tormented bracelet",
        "Combat bracelet",
        "Mystic boots",
        "Bloodbark boots",
        "Infinity boots",
        "Eternal boots",
        "Amulet of magic",
        "Occult necklace",
        "Magus ring",
        "Malediction ward",
        "Elidinis' ward",
        "Tome of fire",
        "Tome of water",
    }
)

#: Rungs nobody has classified on this axis yet — every one of them recent content whose
#: reward chain the transcriber could not state without guessing. §23.4 does not demote on
#: these, so the cost of leaving one here is one hedged sentence rather than a withheld rung.
ACQUISITION_UNTRANSCRIBED: frozenset[str] = frozenset(
    {
        "Confliction gauntlets",
        "Elidinis' ward (f)",
        "Eye of ayak",
        "Purging staff",
        "Scorching bow",
    }
)


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


def missing_requirements() -> list[str]:
    """Rungs in none of the three tables — the failure the three-way split exists to catch.

    A name that reaches here is one nobody classified, and the whole point of
    :data:`UNGATED` being an explicit assertion is that such a name must not silently
    become *"no requirements"*. ``tests/tools/test_gear_ladders.py`` asserts this is empty,
    so adding a rung to a ladder without saying what it takes to wear it fails the suite
    before it can reach the corpus.
    """
    known = REQUIREMENTS.keys() | UNGATED | UNTRANSCRIBED
    return [name for name in unique_names() if name not in known]


def orphan_requirements() -> list[str]:
    """Table entries naming a rung no ladder holds any more.

    The mirror of :func:`missing_requirements`, and the one that catches the other edit:
    removing a name from a ladder leaves its requirement behind, where it is dead weight
    that reads as maintained. Sorted, because this is a diagnostic and not a projection.
    """
    live = set(unique_names())
    return sorted((REQUIREMENTS.keys() | UNGATED | UNTRANSCRIBED) - live)


def missing_acquisitions() -> list[str]:
    """Rungs on no acquisition table. The second axis's copy of the same proof.

    Its consequence is milder than :func:`missing_requirements`', because §23.4 does not
    demote on an unknown acquisition — a rung that reaches here is still recommended, just
    hedged. What this catches is the *silence*: an unclassified rung would say nothing about
    how it is obtained, which reads exactly like a piece the market sells.
    """
    known = EARNED_FROM.keys() | TRADEABLE | ACQUISITION_UNTRANSCRIBED
    return [name for name in unique_names() if name not in known]


def orphan_acquisitions() -> list[str]:
    """Acquisition entries naming a rung no ladder holds any more. Sorted, as a diagnostic."""
    live = set(unique_names())
    return sorted((EARNED_FROM.keys() | TRADEABLE | ACQUISITION_UNTRANSCRIBED) - live)


def acquisition_for(name: str) -> tuple[str | None, str | None]:
    """``(acquisition, acquired_from)`` for one rung — the pair the corpus emits.

    ``("tradeable", None)``, ``("untradeable", <source>)``, or ``(None, None)`` for a name
    parked in :data:`ACQUISITION_UNTRANSCRIBED`.

    **Raises for a name in none of the three**, rather than returning ``(None, None)``, for
    the reason :func:`requirement_for` raises: that pair is a *meaning* — nobody has checked —
    and a name nobody classified must not be able to produce it by accident. The two are
    indistinguishable in the corpus and completely distinguishable here, which is the only
    place the difference can still be caught.
    """
    if name in TRADEABLE:
        return "tradeable", None
    if name in EARNED_FROM:
        return "untradeable", EARNED_FROM[name]
    if name in ACQUISITION_UNTRANSCRIBED:
        return None, None
    raise KeyError(
        f"{name!r} is on no acquisition table. Absence must never default to tradeable — "
        f"a piece the page offers as a purchase and the market does not sell is advice "
        f"nobody can act on. Put it in TRADEABLE, EARNED_FROM or ACQUISITION_UNTRANSCRIBED"
    )


def _canonical(requirement: Mapping[str, Any]) -> Mapping[str, Any]:
    """Expand the table's compact multi-skill form into §10.2's canonical one.

    §10.2 is strict that *a skill leaf names exactly one skill*, which is right for the
    grammar and miserable for this table: Void equipment gates on seven levels at once, and
    seven stacked ``{"skill": {...}}`` leaves buries the one number a reader came for. So
    the table is allowed to write ``{"skill": {"ranged": 80, "defence": 30}}`` and this
    function turns it into the ``all_of`` the parser wants, on the way out.

    The compaction is *only* a spelling. Nothing else is rewritten, an already-canonical
    single-skill leaf is returned unchanged, and a nested combinator is expanded in place —
    so what reaches the corpus is exactly the tree the table states, in longhand.
    """
    if "skill" in requirement and len(requirement["skill"]) > 1:
        return {
            "all_of": [{"skill": {name: level}} for name, level in requirement["skill"].items()]
        }
    for combinator in ("all_of", "any_of"):
        if combinator in requirement:
            return {combinator: [_canonical(child) for child in requirement[combinator]]}
    if "not" in requirement:
        return {"not": _canonical(requirement["not"])}
    if "at_least" in requirement:
        inner = requirement["at_least"]
        return {"at_least": {**inner, "of": [_canonical(child) for child in inner["of"]]}}
    return requirement


def requirement_for(name: str) -> Mapping[str, Any] | None:
    """The gate for ``name`` in §10.2's canonical shape, or ``None`` when there is none.

    Raises for an unclassified name rather than returning ``None``, because ``None`` here
    means *"there is no gate"* and an unclassified rung means *"nobody knows"* — the two
    answers this module exists to keep apart. Callers wanting the third state test
    ``name in UNTRANSCRIBED`` first; :mod:`tools.generate_gear_items` does exactly that.
    """
    if name in REQUIREMENTS:
        return _canonical(REQUIREMENTS[name])
    if name in UNGATED or name in UNTRANSCRIBED:
        return None
    raise KeyError(
        f"{name!r} is on a ladder but in none of REQUIREMENTS, UNGATED or UNTRANSCRIBED. "
        f"Classify it — an unclassified rung must never default to ungated."
    )
