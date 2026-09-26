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
