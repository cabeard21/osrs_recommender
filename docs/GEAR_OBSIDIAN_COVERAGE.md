# Obsidian base-stat coverage

Reviewed November 8, 2026. All 13 equippable forms in the
[Wiki obsidian equipment list](https://oldschool.runescape.wiki/w/Obsidian_equipment)
are eligible for ordinary-stat evaluation. Existing pinned catalog bonuses, speed,
handedness and ammunition fields remain unchanged. An exact-ID runtime review
clears only the generic unreviewed-effects marker; explicit blockers remain.

| Exact forms | Wear requirement | Acquisition |
| --- | --- | --- |
| Helmet 21298, platebody 21301, platelegs 21304 | Defence 60 | Tradeable |
| Toktz-ket-xil 6524 | Defence 60 | Tradeable |
| Obsidian cape 6568, cape (r) 20050 | None | Tradeable |
| Toktz-xil-ak 6523, Toktz-xil-ek 6525, Tzhaar-ket-em 6527 | Attack 60 | Tradeable |
| Tzhaar-ket-om 6528 | Strength 60 | Tradeable |
| Tzhaar-ket-om (t) 23235 | Strength 60 | Untradeable |
| Toktz-mej-tal 6526 | Attack 60 and Magic 60 | Tradeable |
| Toktz-xil-ul 6522 | Ranged 60 | Tradeable |

Exact-item sources are linked in `content/items/obsidian.yaml`. The
[staff](https://oldschool.runescape.wiki/w/Toktz-mej-tal) supports ordinary crush
attacks and Standard elemental autocast (5 ticks for casting, 6 for melee).
Its imported aggressive Magic profile is removed; accurate/defensive casting
remain. Throwing rings need no separate ammunition and use light ranged defence.

The [trimmed maul](https://oldschool.runescape.wiki/w/Tzhaar-ket-om) retains
the normal maul's Strength 60 requirement; this overrides the community source's
incorrect Strength 40 map. Its
[ornament kit](https://oldschool.runescape.wiki/w/Tzhaar-ket-om_ornament_kit)
produces an untradeable item. The
[red cape](https://oldschool.runescape.wiki/w/Obsidian_cape_%28r%29) is separately
tradeable and has the ordinary cape's stats and wear requirements. Shop access,
clue completion and ornament assembly are acquisition paths, not wear gates.

Armour set and Berserker necklace bonuses are **not applied**. Armour pieces and
weapons carry a nonblocking `omitted_set_effects` disclosure, shown in item facts
and combat result limitations. The Berserker necklace itself remains unreviewed.
Full-set results use only summed ordinary stats; they do not represent full
in-game synergy DPS. Capes and shield do not claim an omitted set effect.

Tradeable forms require their own usable market quote for purchase planning.
No fabricated prices, ownership aliases, base-to-ornament conversion or new
acquisition preparation are supplied. Owned trimmed mauls can be scored normally.
Review data participates in the catalog revision used by search fingerprints.

Focused validation covers every form's eligibility, missing/below-level facts,
purchase quotes, locked weapon optimization, full-set base-stat parity, staff
compatibility, two-handed legality, blocker preservation, revision changes,
browser API transport and UI limitations rendering.
