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
