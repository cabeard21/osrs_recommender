# Factual content authoring

Content supplies named OSRS facts and curated Gear order. It does not assign utility
weights, score actions, or decide the player's next objective.

## Current sources

| Source | Purpose |
| --- | --- |
| `content/quest_cape/catalog.json` | Quest Cape goal quests and requirements |
| `content/items/items.yaml` | Item identity, requirements, acquisition facts, and authored Gear ladders |
| `content/skills/skills.yaml` | Skill identities used by factual requirements |
| `content/quests/quests.yaml` and `content/quests/generated/quests.yaml` | Quest identities and source metadata used by factual content |

Keep authored ordering distinct from recommendations. A Gear ladder says which rung
comes after another in a curated progression; `GearService` reports account eligibility,
ownership observations, and price facts for those rungs. ChatGPT decides which, if any,
purchase is worthwhile.

Requirements should reference canonical skill, quest, and item identities. Missing
account observations must remain unknown. An item absent from an old scan is not proof
of current non-ownership, and a missing market price is not zero GP.

## Changing factual content

1. Update the relevant factual source and keep source attribution where that source
   already records it.
2. Run `make validate-content` and `make validate-quest-cape`.
3. Run focused Quest Cape or Gear service tests for the changed contract, then the
   normal repository verification before merging.

The former candidate, capability, roadmap, practice-refresher, scoring-profile,
and golden-corpus authoring rules belong to the retired product. They are recorded
only in the [historical SDD](SDD.md), not in the current content contract.

## Optimizer equipment metadata

The optimizer catalog describes physical equipment, not progression position. Retain
the existing authored requirement trees where reviewed; a missing gate is **unknown**,
not an unrestricted item. Record requirement completeness separately from a known
requirement, since a skill requirement alone does not prove quest gates are complete.
Keep ownership aliases, attack-equivalent forms and purchasable forms distinct.

Every reviewed import must record source URL, retrieval date, source revision when
available, schema version, content hash, and required attribution. Review changes before
bundling them; optimization must not fetch an external catalog at runtime. Exclude
unreleased and alternate-mode items from normal-game candidates. A catalog item may
remain inspectable while its requirements or combat mechanics prevent optimization.

Equipment bonuses alone do not validate an item. Attack speed, legal attack styles,
handedness, ammunition, physical form and active effects must be known. Unsupported
offensive/set effects require explicit markers; never silently calculate ordinary DPS
for an exceptional weapon. Prices remain timestamped observations from the existing
price service, not manually assigned recommendation scores.

### Adding equipment and item icons

First look up the exact physical ID in `content/equipment/catalog.json`. An item
can already exist there but be excluded because requirements, account evidence,
or combat effects are unknown. Adding an icon does not make an item eligible.

For an existing physical item, add reviewed identity, wear requirements, and
acquisition metadata in an authored `content/items/*.yaml` file. The loader reads
all these files; `gear_high_impact.yaml` is a small example. Keep source evidence
and review ordinary effects before clearing an unsupported-effects marker.
The exact-ID capture/review workflow is documented by
`python -m tools.capture_bulk_gear --help` and
`python -m tools.bulk_review_gear --help`. A genuinely new physical item also
needs sourced statistics and an updated catalog manifest checksum. Preserve the
catalog's provenance and regenerate dependent community classification when its
input hashes change. Validate content and run relevant catalog/service tests.

The older curated progression lists are authored in `tools/gear_ladders.py`.
To extend those lists, update their requirements/acquisition tables, run
`python tools/capture_gear_ids.py`, then `python tools/generate_gear_items.py`.
Do not hand-edit the generated `content/items/items.yaml`. Ladder placement is
separate from optimizer support.

Rune gloves already have physical ID **7460** and reviewed metadata in
`content/items/gear_high_impact.yaml`. Their wear gate requires recorded
`daero_training_complete` **or** `recipe_for_disaster_culinaromancer` evidence.
Missing evidence stays unknown; Monkey Madness I completion or an ownership scan
alone does not establish that gate. See [the exact-ID review](GEAR_HIGH_IMPACT_COVERAGE.md).

Item artwork lives in `tracker/ui/assets/items/{item_id}.png`. Both Gear interfaces
use these bundled files; no frontend rebuild is needed to add a sprite to a source
checkout. Repackage/redeploy the application to update an installed wheel or image.

Whenever you add optimizer item support, ensure every exact physical form is included
in the default missing-icon download logic in `tools/capture_gear_icons.py`, including
charged, uncharged, imbued, and cosmetic forms that can appear in results or preparation
steps. The default selection includes authored forms, catalog-supported equipment
(`requirements_complete` with no `unsupported_effects`), community equipment, and
reviewed bolt/crossbow, tome, leafy, and powered-staff preparation forms. Add any new
preparation forms that fall outside those groups and extend
`tests/gear/test_capture_gear_icons.py` to cover them. Check the complete default scope,
download missing sprites, and retain the corresponding `source.json` provenance.
Use the offline capture tool to preview or fill missing artwork:

```bash
python -m tools.capture_gear_icons --dry-run  # Missing icons across the default scope
python -m tools.capture_gear_icons           # Download those missing icons
python -m tools.capture_gear_icons 7460 7459 # Specific catalog IDs
```

The capture skips existing files, rejects unknown catalog IDs and non-PNG
responses, and records each new file's source, retrieval date, and SHA-256 in
`source.json` alongside the existing RuneLite/Jagex attribution. Explicit IDs may
also select physical catalog items that have no authored overlay yet. Failed
downloads return a nonzero exit status; rerun to resume the remaining files.
If the primary cache is unavailable, capture tries the same numeric-ID path in
[RuneLite's cache repository](https://github.com/runelite/static.runelite.net),
recording the actual download URL.

Docker builds run this capture in a separate build stage, then copy the completed
sprite directory into the Python wheel **before** packaging. The existing CI
container builds therefore bundle missing icons automatically for both AMD64 and
ARM64; no developer-machine downloads or runtime internet access are needed.
A missing icon that cannot be fetched fails the build. Docker's layer cache reuses
successful captures until the build inputs change. CI's container smoke check
verifies all authored physical forms have packaged sprites and that the installed
wheel serves both the whip and rune gloves PNGs. Transient connection failures
are retried before falling back to the mirror.

The catalog loader explicitly reviews Berserker ring (i) forms 25264 and 26770 as
equivalent to 11773, following the pinned Wiki calculator's
[equipment alias data](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment_aliases.json).
It compares every physical field except ID and the review marker before sharing
requirements, and requires an explicit authored variant membership. It retains each
form's own ID, statistics, and concrete ownership evidence. Other ownership aliases
do not inherit combat support; ambiguous source forms remain unsupported.

## Encounter template sources

The small templates in `tracker/gear/encounters.py` use target statistics from the
[Wiki calculator monster data](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/monsters.json),
reviewed 2026-10-19. Source NPC IDs are Supreme 2265, Prime 2266, Rex 2267, and Zulrah
serpentine/magma/tanzanite 2042/2043/2044. These basic factual values do not copy the
calculator implementation. Review source-specific licensing before broader data or
artwork imports; calculator code is GPL-3.0 and does not determine every upstream
asset's license.

Presets must convert into the same custom request model used by the optimizer. Declare
the chosen directed order, looping behavior, active-time assumptions and limitations.
Do not invent phase durations or label a form comparison as an actual rotation. The
current templates support ordinary attacks and matching standard-spell elemental
weakness. Zulrah's damage-cap marker permits ordinary hit distributions with maximum
hit at most 50 and blocks higher maximum hits; it does not approximate the above-cap
reroll. Add focused independently justified comparison tests before expanding these
mechanics. A completed data import is not combat-model acceptance. Keep target defence
bonuses separate from player equipment attack and defence bonuses.
