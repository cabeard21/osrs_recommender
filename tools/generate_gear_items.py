"""Emit ``content/items/items.yaml`` from the ladders and the captured ids — by hand.

The last step of the three: :mod:`tools.gear_ladders` holds the transcribed order,
:mod:`tools.capture_gear_ids` resolves every name to numeric ids, and this turns the pair
into corpus YAML. It writes a file that is **read into the corpus and validated**, so a
mistake here surfaces as a ``ContentError`` from
:func:`tracker.content.validate._check_gear_ladders` rather than as bad advice.

Three decisions live here rather than in the capture, because each is a judgement about
meaning and not about data:

**Which variant gets priced.** One piece of gear wears several ids. Ownership counts all of
them — a charged blowpipe is a blowpipe — but only one is quoted by the market, and for the
charged items it is the *uncharged* one, since the charged form is untradeable.
:data:`PRICED_VARIANT` names that choice wherever the catalog cannot settle it, and every
other id becomes an ownership-only alias in ``variant_item_ids``.

**Which ids are already spoken for.** A name on two ladders (Barrows gloves is melee *and*
ranged) is declared once and left as a comment on the second. Declaring it twice would trip
validation's one-id-one-item rule, and picking a winner silently would be worse.

**What keeps its old id.** :data:`PRESERVED_SLUGS` and :data:`OFF_LADDER` carry the corpus
that existed before the ladders did. Those slugs are named by ``item:`` requirement leaves in
``content/candidates`` and ``content/capabilities``; minting a new slug for the same item
would break referential integrity, and dropping one would break it louder.

Run::

    python tools/capture_gear_ids.py        # refresh the ids first
    python tools/generate_gear_items.py     # then regenerate the corpus
    python -m pytest tests/content          # and let validation have the last word
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from gear_ladders import LADDERS

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IDS = REPO_ROOT / "tools" / "data" / "osrs_gear_ids.json"
DEFAULT_OUT = REPO_ROOT / "content" / "items" / "items.yaml"

#: Static hints for the expensive end of the ladders (§8.3's last cascade layer). Cheap
#: early-game gear is deliberately absent: a live price always beats a stale guess, and a
#: wrong hint on a 15k scimitar is not worth the line. Every number is a rounded
#: order-of-magnitude figure, which is exactly what ``Confidence.LOW`` on that layer means.
FALLBACKS: dict[str, int] = {
    "abyssal_tentacle": 2_500_000,
    "abyssal_whip": 1_500_000,
    "amulet_of_blood_fury": 12_000_000,
    "amulet_of_fury": 3_000_000,
    "amulet_of_torture": 12_000_000,
    "ancestral_hat": 130_000_000,
    "ancestral_robe_bottom": 200_000_000,
    "ancestral_robe_top": 250_000_000,
    "armadyl_crossbow": 38_000_000,
    "avernic_defender": 55_000_000,
    "bellator_ring": 60_000_000,
    "berserker_ring": 3_500_000,
    "blade_of_saeldor": 130_000_000,
    "blood_moon_tassets": 8_000_000,
    "bow_of_faerdhinen": 45_000_000,
    "dinhs_bulwark": 20_000_000,
    "dizanas_quiver": 200_000_000,
    "dragon_hunter_wand": 130_000_000,
    "dragonfire_ward": 60_000_000,
    "echo_boots": 40_000_000,
    "eclipse_atlatl": 3_000_000,
    "elidinis_ward": 25_000_000,
    "elidinis_ward_f": 200_000_000,
    "eternal_boots": 4_000_000,
    "eye_of_ayak": 90_000_000,
    "ferocious_gloves": 25_000_000,
    "ghrazi_rapier": 40_000_000,
    "harmonised_nightmare_staff": 900_000_000,
    "inquisitors_mace": 45_000_000,
    "justiciar_chestguard": 25_000_000,
    "justiciar_faceguard": 30_000_000,
    "justiciar_legguards": 20_000_000,
    "kodai_wand": 90_000_000,
    "magus_ring": 90_000_000,
    "malediction_ward": 25_000_000,
    "masori_body": 60_000_000,
    "masori_chaps": 40_000_000,
    "masori_mask": 20_000_000,
    "necklace_of_anguish": 12_000_000,
    "neitiznot_faceguard": 35_000_000,
    "nightmare_staff": 8_000_000,
    "occult_necklace": 800_000,
    "odium_ward": 4_000_000,
    "pegasian_boots": 35_000_000,
    "primordial_boots": 32_000_000,
    "purging_staff": 60_000_000,
    "ring_of_suffering": 3_500_000,
    "sanguinesti_staff": 60_000_000,
    "scorching_bow": 90_000_000,
    "scythe_of_vitur": 900_000_000,
    "serpentine_helm": 900_000,
    "torva_full_helm": 90_000_000,
    "torva_platebody": 130_000_000,
    "torva_platelegs": 110_000_000,
    "toxic_blowpipe": 3_000_000,
    "tumekens_shadow": 900_000_000,
    "twisted_bow": 1_400_000_000,
    "twisted_buckler": 55_000_000,
    "ultor_ring": 100_000_000,
    "venator_bow": 60_000_000,
    "virtus_mask": 30_000_000,
    "virtus_robe_bottom": 45_000_000,
    "virtus_robe_top": 60_000_000,
    "webweaver_bow": 90_000_000,
    "zaryte_crossbow": 400_000_000,
    "zaryte_vambraces": 40_000_000,
}

#: The wiki's ``Infobox Item`` is not consistent about which variant is ``id1``, so the id
#: used for *pricing* is named here wherever the price catalog has no row to settle it.
#: Anything not named falls back to the first id the infobox lists, and every other variant
#: becomes an ownership-only alias.
PRICED_VARIANT: dict[str, int] = {
    "Blade of saeldor": 23997,  # inactive
    "Bow of faerdhinen": 25862,  # inactive
    "Dizana's quiver": 28947,  # uncharged
    "Eye of ayak": 31115,  # uncharged
    "Sanguinesti staff": 22481,  # uncharged
    "Scythe of vitur": 22486,  # uncharged
    "Serpentine helm": 12929,  # uncharged
    "Tome of fire": 20716,  # empty
    "Tome of water": 25576,  # empty
    "Toxic blowpipe": 12924,  # only the empty form is tradeable
    "Toxic staff of the dead": 12902,  # uncharged
    "Trident of the swamp": 12900,  # uncharged
    "Tumeken's shadow": 27277,  # uncharged
    "Venator bow": 27612,  # uncharged
    "Warped sceptre": 28583,  # uncharged
    "Webweaver bow": 27652,  # uncharged
}

#: Items declared before the ladders existed, whose slugs ``item:`` leaves already name.
#: Renaming one would break referential integrity, so the ladder entry reuses the slug rather
#: than minting a parallel id for the same item.
PRESERVED_SLUGS: dict[str, str] = {
    "Ahrim's robetop": "ahrims_robetop",
    "Dragon hunter crossbow": "dragon_hunter_crossbow",
    "Mystic robe top": "mystic_robe_top",
    "Rune crossbow": "rune_crossbow",
}

#: The rest of the pre-ladder corpus: named by ``item:`` leaves, but by none of the three
#: guides, so no rung applies. Emitted verbatim rather than dropped or given an invented
#: tier — a rung nobody authored is worse than no rung at all.
OFF_LADDER = """\
# The pre-ladder entries. Each is named by an `item:` leaf in content/candidates or
# content/capabilities, so its id is load-bearing; none appears in the three progression
# guides, so none carries a tier. A slot and style without a rung would claim a place on a
# ladder the guides never put them on.
- id: voidwaker
  name: Voidwaker
  item_id: 27690
  price_mode: live
  fallback_price_gp: 85000000
  price_staleness_days: 7

- id: armadyl_godsword
  name: Armadyl godsword
  item_id: 11802
  price_mode: live
  fallback_price_gp: 15000000
  price_staleness_days: 7

- id: bandos_chestplate
  name: Bandos chestplate
  item_id: 11832
  price_mode: live
  fallback_price_gp: 17000000
  price_staleness_days: 7

- id: armadyl_chestplate
  name: Armadyl chestplate
  item_id: 11828
  price_mode: live
  fallback_price_gp: 30000000
  price_staleness_days: 7
"""

HEADER = """\
# §10.5. The three gear ladders, transcribed from the OSRS Wiki's own progression guides
# (Guide:Melee_Gear_Progression and its Ranged and Magic siblings).
#
# GENERATED by tools/generate_gear_items.py — edit tools/gear_ladders.py and re-run rather
# than editing here, or the next regeneration will quietly discard the change.
#
# `tier` is the rung: 1 is where a new account starts and the highest number is the best the
# guide lists for that slot. It is an *ordering*, not a rating — tier 6 is not twice tier 3 —
# and it exists so a reader can be told 'best melee weapon held: Rune scimitar, next rung:
# Dragon scimitar' instead of an alphabetical bag of names.
#
# Every `item_id` came from a lookup, never from recall: the price API's /mapping catalog for
# anything tradeable, and the wiki's own Infobox Item for the untradeables it does not carry
# (fire capes, void, the defenders, Barrows gloves). A wrong id here is a silently wrong GP
# estimate rather than an error, which is why tools/capture_gear_ids.py refuses to choose
# between near-identical names.
#
# `variant_item_ids` is why the Toxic blowpipe finally has an entry. One piece of gear wears
# several ids — charged and uncharged, broken and locked, imbued from three different sources
# — and owning any of them is owning the item. Ownership tests the union; `item_id` alone is
# what gets priced, so it names the variant the market actually quotes (the *empty* blowpipe,
# since the charged form is untradeable)."""


def slug(name: str) -> str:
    """``Ahrim's robetop`` -> ``ahrims_robetop``.

    The apostrophe is *dropped*, not turned into a separator: ``ahrim_s_robetop`` would be a
    new id, and the old one is named by a requirement leaf.
    """
    out: list[str] = []
    for char in name.lower().replace("'", ""):
        if char.isalnum():
            out.append(char)
        elif out and out[-1] != "_":
            out.append("_")
    return "".join(out).strip("_")


def render(catalog: Mapping[str, int], wiki: Mapping[str, Sequence[Sequence[Any]]]) -> str:
    """The whole corpus file, as text. Pure — every input arrives as an argument."""
    seen_ids: dict[int, str] = {}
    seen_slugs: set[str] = set()
    lines: list[str] = [HEADER]

    for style, slots in LADDERS.items():
        lines += ["", f"# {'=' * 74}", f"# {style.upper()}", f"# {'=' * 74}"]
        for slot, names in slots.items():
            lines += ["", f"# --- {style} / {slot} ---"]
            for tier, name in enumerate(names, start=1):
                identifier = PRESERVED_SLUGS.get(name, slug(name))
                if identifier in seen_slugs:
                    identifier = f"{identifier}_{style}"
                seen_slugs.add(identifier)

                catalog_id = catalog.get(name)
                wiki_ids = [int(row[1]) for row in wiki.get(name, [])]

                if catalog_id is not None:
                    priced = catalog_id
                    variants = [value for value in wiki_ids if value != catalog_id]
                elif wiki_ids:
                    priced = PRICED_VARIANT.get(name, wiki_ids[0])
                    variants = [value for value in wiki_ids if value != priced]
                else:  # pragma: no cover — the capture refuses to leave a name unresolved
                    raise SystemExit(f"no id for {name!r} — refusing to author it")

                claimed = [value for value in [priced, *variants] if value in seen_ids]
                if claimed:
                    lines.append(
                        f"# {name} is already declared as `{seen_ids[claimed[0]]}`; "
                        f"it is also {style} {slot} tier {tier}."
                    )
                    continue
                for value in [priced, *variants]:
                    seen_ids[value] = identifier

                lines += [f"- id: {identifier}", f"  name: {name}", f"  item_id: {priced}"]
                if variants:
                    lines.append(f"  variant_item_ids: [{', '.join(map(str, variants))}]")
                lines += [
                    f"  slot: {slot}",
                    f"  style: {style}",
                    f"  tier: {tier}",
                    f"  price_mode: {'live' if catalog_id is not None else 'static'}",
                ]
                fallback = FALLBACKS.get(identifier)
                if fallback is not None:
                    lines.append(f"  fallback_price_gp: {fallback}")
                if catalog_id is not None:
                    lines.append("  price_staleness_days: 30")
                lines.append("")

    lines += ["", f"# {'=' * 74}", "# OFF-LADDER", f"# {'=' * 74}", "", OFF_LADDER.rstrip()]
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", type=Path, default=DEFAULT_IDS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    arguments = parser.parse_args(argv)

    with arguments.ids.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    rendered = render(payload["catalog"], payload["wiki"])
    # Explicit encoding and newline: the corpus is UTF-8 with LF, and Windows' default text
    # mode would turn every `§` in the header into a byte the loader refuses to decode.
    with arguments.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(rendered)
    print(f"# wrote {arguments.out} ({rendered.count(chr(10) + '- id:')} items)")
    return 0


if __name__ == "__main__":  # pragma: no cover — run by hand
    sys.exit(main())
