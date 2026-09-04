# Authoring content

Everything the tracker knows about *the game* lives in `content/` as YAML. Adding a
capability, roadmap, milestone, item, quest, skill, training method or refresher — or
retuning the scoring profile — **never requires a Python change**. That is the boundary
§10.8 of [the SDD](SDD.md) draws, and `tests/content/test_g9.py` enforces it mechanically.

Adding a new *requirement type* or a new *practice domain* does require code. The engine
knows about requirement types, practice domains and factor names; it knows nothing about
Ice Barrage.

After any edit:

```bash
make validate-content
```

It exits non-zero and prints one located diagnostic per problem — file, line, and the
path inside the document. Fix them all in one pass; the validator does not stop at the
first.

## Layout

```
content/
    capabilities/      what the player can *do* in PvP, gated by a requirement tree
    roadmaps/          weighted capability sets — what "better" means for a playstyle
    roadmap_guides/    attributed preparation and encounter guidance for a roadmap
    milestones/        PvP milestones, with how they are measured and how they age
    refreshers/        practice-group templates that become candidates when stale
    training_methods/  xp/hour and gp/hour per skill and level band
    items/             numeric ids, price policy, fallback hints
    quests/            id + name; what `quest:` leaves resolve against
    skills/            id + name; what `skill:` leaves resolve against
    scoring/           profile.yaml — weights, τ, κ, thresholds
    candidates/        actions the player could take — the only objects that get ranked
```

One object per file, or a YAML list of objects in one file — both work. Use one file per
capability (they are large and individually interesting) and a single list file for
skills and quests (they are one line each).

**Ids are unique per kind, not globally.** `capabilities/anti_pk.yaml` and
`roadmaps/anti_pk.yaml` can coexist, exactly as §4.2 and §9.3 use them. Two capabilities
called `anti_pk` cannot.

## The requirement grammar

Leaves: `skill`, `unlock`, `quest`, `item`, `milestone`, `capability`, `combat_level`,
`quest_points`. Combinators: `all_of`, `any_of`, `not`, `at_least: {n, of: [...]}`.

```yaml
requires:
  all_of:
    - skill: {magic: 94}
    - unlock: ancient_magicks
    - any_of:
        - item: mystic_robe_top
        - item: ahrims_robetop
```

> **The space after the colon is mandatory.** `{magic: 94}` is a mapping; `{magic:94}` is
> the string `"magic:94"`. The v0.1 draft of the SDD contained this bug twice. The
> validator rejects it with the file and line, but it is worth knowing why the message
> talks about spaces.

Evaluation is three-valued (§9.1): every leaf is `satisfied`, `unsatisfied` or
`unknown`, and `unknown` means *we have never observed this*, not *no*. Two leaves read
backwards and are worth memorising:

- `unlock: available` is **unsatisfied**. "Available" means purchasable, not held.
- `quest: in_progress` is **unsatisfied**. There is no partial-credit leaf.

`unlock:` keys are an open set — no registry to declare them in. Spellbooks, achievement
diaries and combat achievements use the reserved prefixes `spellbook_`, `diary_` and
`ca_` (§6.3), so `unlock: spellbook_lunar` needs no new leaf type.

## Adding a capability

```yaml
# content/capabilities/my_capability.yaml
id: my_capability
name: My Capability
recommended_readiness: high     # high | medium | low (default medium)
pvp_value: 0.80                 # optional authoring hint, 0–1
requires:
  all_of:
    - capability: ice_barrage_nh
    - milestone: teleblock_understanding
```

`recommended_readiness` is the bar `recommended_now` compares against. Declare `high` for
capabilities where rusty execution is genuinely dangerous — deep Wilderness, high-risk
setups. Those capabilities show "not today, refresh first" when practice evidence has
decayed, **without** losing their unlocked status.

Capabilities compose into a DAG. `make validate-content` reports the actual cycle path if
you create one.

**`pvp_value` means "goal value", and nothing reads it.** The corpus is no longer PvP-only —
`content/roadmaps/pvm_ladder.yaml` is a bossing ladder — and its six tier capabilities
declare this field like any other. The name is kept because it is load-bearing in the schema,
the tuned scoring profile, the factor JSON persisted on every recommendation entry and every
golden fixture at once, and renaming it would rewrite all of them to change nothing the
engine computes. Tuning it moves nothing: what gives a capability weight in the ranking is a
*candidate's* `advances` map times the roadmap's capability weight (§9.3).

### Ordered progressions

If a roadmap needs a **mandatory dependency order** — for example, a quest chain — build it as a
chain of capabilities, each rung's `requires` naming the rung below:

```yaml
# content/capabilities/dragon_bossing.yaml
requires:
  all_of:
    - capability: gwd_bossing     # <- the rung below
    - skill: {ranged: 80}
    - quest: dragon_slayer_ii
```

Do **not** add an ordering field to the roadmap. §4.2 keeps roadmaps free of a dependency
graph of their own precisely so there is only one graph to keep consistent with the facts,
and the DAG already produces the ordering — a rung whose predecessor is unmet is blocked, so
only the reachable rung is ever offered.

Difficulty ordering is not necessarily dependency ordering. The PvM bossing guide uses tier and
encounter order for presentation and tie-breaking only; its encounters stay independent so account
readiness, rather than completion of prior content, controls what is ready to try.

The chain pays a second dividend that is easy to miss. `tools/generate_candidates.py` reads
every `skill:` level the corpus references and emits training bands ending **exactly** at
those levels, so a rung gating on Slayer 55 and Prayer 43 causes bands ending at 55 and 43 to
exist. The path up the ladder appears by construction. That makes the rungs' `skill:` leaves
the most consequential thing you author — pick them as the levels you actually want the
player told to train to.

## Adding a roadmap

```yaml
# content/roadmaps/my_roadmap.yaml
id: my_roadmap
name: My Roadmap
capabilities:
  ice_barrage_nh: 1.00
  budget_nh: 0.40
```

A roadmap is a weighted capability set and **nothing else** — no dependency graph of its
own. "Pure NH", "Zerker" and "Anti-PKer" differ only in these weights and in which
capabilities they list.

Weights are in `[0, 1]`. A capability in two active roadmaps *blends*, never accumulates:
at selection weights `main_nh: 0.75, anti_pk: 0.25`, a capability weighted `1.00` and
`0.60` lands at `0.90`, never `1.80`.

## Authoring the PvM bossing guide

`content/roadmap_guides/pvm_ladder.yaml` is a `RoadmapGuide`: attributed authored content that
adds detailed preparation and encounters to the weighted `pvm_ladder` roadmap without changing
what a roadmap means. It contains source metadata and six ordered `BossingTier` values — Easy,
Medium, Hard, Elite, Master and Grandmaster. Each tier contains:

- `BossingPreparationStep` entries, either checkable through the normal requirement grammar or
  explicitly informational when the advice cannot be inferred from synced facts.
- `BossingEncounter` entries in source order, with a stable id and name, access requirements,
  advisory recommendations, paraphrased mechanics and rewards, and an HTTPS Wiki link.

Keep source-table rows intact. A combined row such as Obor/Bryophyta remains one encounter rather
than being split into facts the source did not distinguish. The six tiers express difficulty and
presentation order, not a mandatory completion chain: never require an earlier tier or encounter
to be completed before a later encounter can be ready.

### Readiness semantics

Access and recommendations are separate predicates because they answer different questions:

| Result | Meaning |
|---|---|
| `locked` | At least one enforced access requirement is known to be unsatisfied. |
| `building_toward` | Access is satisfied, but one or more advisory recommendations are unsatisfied. |
| `ready` | Access and the authored recommendations are satisfied (shown as “Ready to try”). |
| `sync_needed` | A relevant fact has not been observed; list it separately from actionable blockers. |

Use access requirements only for conditions the activity enforces: quests, keys or required items,
Slayer levels, and activity-entry skill levels. Suggested combat stats and equipment belong under
recommendations. `ready` means the account matches the guide's suggested setup; it never
claims mechanical mastery or completion.

Every checkable preparation step must reference one or more actionable `candidate_ids`, and every
referenced roadmap, capability and candidate id must resolve. Guide-linked candidates participate in **Next
up** through their associated PvM tier capability. When one candidate helps several steps or
encounters, the existing maximum relevance semantics apply; contributions never accumulate merely
because the guide mentions the action more than once.

### Source and refresh procedure

The shipped baseline is [OSRS Wiki Bossing Ladder revision
15319480](https://oldschool.runescape.wiki/w/Guide:Bossing_Ladder?oldid=15319480), checked on
2026-09-04. The adapted guide content is attributed to the Old School RuneScape Wiki contributors
and licensed under [CC BY-NC-SA 3.0](https://creativecommons.org/licenses/by-nc-sa/3.0/).
The application never scrapes the Wiki at runtime.

To refresh the guide:

1. Choose and record a specific Wiki revision; never author against the moving current-page URL.
2. Compare all six preparation sections and encounter tables with the previously pinned revision.
3. Update the YAML by hand, paraphrasing mechanics and rewards while retaining the source order and
   direct Wiki links. Update the revision and checked date in the same change.
4. Confirm that access conditions remain enforced and recommendations remain advisory, and link any
   new checkable preparation step to a real candidate.
5. Run `make validate-content` and the focused guide/read-model tests, then review
   `/roadmaps/pvm-ladder` at desktop and phone widths.

The guide is a read-only projection over existing account facts. Do not add boss KC, manual
completion controls, database state, or sync-payload fields as part of a content refresh.

## Adding a candidate

A candidate is *an action the player could take that changes facts*. Capabilities define
what **better** means; candidates are the moves available for getting there, and they are
the only objects the engine ranks.

```yaml
# content/candidates/skill_training.yaml — grouped by kind, one file per kind
- id: train_magic_87_to_94
  name: Train Magic 87 → 94
  kind: skill_training        # skill_training | acquisition | quest | unlock
  advances:
    ice_barrage_nh: 1.00
    deep_wildy_nh: 0.60
  requires:                   # optional gate — omit if there is none
    unlock: ancient_magicks
  completion:                 # mandatory
    skill: {magic: 94}
  grants_facts:               # optional
    skill: {magic: 94}
```

**There is no priority field, and that is the whole point.** No `pvp_value`, `leverage`,
`proximity`, `hours` or `gp_cost` — every scoring factor is *derived* from the fields
above, so no content file can assert its own importance. If a candidate ranks lower than
you think it should, the fix is to correct a weight or a requirement, never to add a
thumb on the scale.

The four fields do genuinely different jobs, and conflating them is the common mistake:

| Field | Job | Wrong if… |
|---|---|---|
| `advances` | **Editorial.** How much each capability *cares*, `0`–`1` per capability. | you list a capability the action does not help, to boost the ranking. |
| `requires` | **Gate.** What must already be true to start. | you put the goal here — that belongs in `completion`. |
| `completion` | **Predicate.** When this is satisfied, the candidate is done. | it can never be satisfied; the validator rejects an empty one outright. |
| `grants_facts` | **Objective.** What becomes true afterwards. | it restates `advances` — one is measurable, the other is a judgment. |

`advances` and `grants_facts` differ most obviously on a quest. Desert Treasure I grants
exactly two facts — the quest is complete, and Ancients are unlocked — but it *advances*
three capabilities by very different amounts, because two of them need far more than
Ancients before they are usable. `grants_facts` is what drives `leverage`: a candidate
scores well when completing it stops *other* things being blocked.

A few rules worth knowing before you author one:

- **`advances` takes the maximum across capabilities, never the sum.** `buy_voidwaker`
  advances `deep_wildy_nh: 0.80` and `anti_pk: 0.60`; blended under the active roadmaps
  those contribute a single figure, not `1.40`. Authoring more entries cannot inflate a
  candidate.
- **An empty `advances` is legal** and means *this advances nothing*. That is the honest
  way to author a genuinely irrelevant action — it then ranks last because the content
  says so, not because code recognises its name. `train_woodcutting` is the corpus's
  example. It also puts the candidate outside every roadmap's price-fetch scope.
- **`advances` is also what a candidate's *prerequisites* advertise (§9.10).** A generated
  skill band carries no `advances` of its own, so the card for *"Train Slayer to 10"* names
  its goal by looking one hop on — to Desert Treasure I, which the band gates, and then to
  that quest's `advances` map. The heaviest entry wins, which is why DT1's
  `ice_barrage_nh: 0.90` and not its `deep_wildy_nh: 0.60` is the goal a player is shown.
  The weights you set here are read as *"what is this mostly for"* by every band that feeds
  the candidate, so a padded map now misleads in two places rather than one.
- **An `unsatisfied` gate blocks; an `unknown` gate does not.** A candidate whose
  `requires` cannot be evaluated because nothing has been synced reads *"sync this"*, not
  *"do this"*, and must stay rankable.
- **Cost and duration are estimated, not authored.** A `skill_training` candidate's hours
  come from the training methods for its skill; an `acquisition`'s gp comes from pricing
  the `item:` leaves in its `completion`. You cannot make a candidate look cheap by
  declaring it so.

`kind: practice` is not authored. Refreshers are synthesized into practice candidates at
recommendation time; see *Adding a refresher*.

## Adding a milestone

Two attributes, and they are **orthogonal**:

| `kind` | Meaning |
|---|---|
| `derived` | Measured for you — LMS wins, boss KC, anything the plugin or hiscores can see. Never prompts. |
| `self_attested` | The app asks you. Keep this set small; it is what makes "almost no manual data entry" true. |

| `class` | Ages? |
|---|---|
| `threshold` | No. A thing that happened, permanently. |
| `knowledge` | No. Understanding, once acquired. |
| `execution` | **Yes.** Mechanical skill: `<30d` current, `30–90d` stale, `>90d` very stale. |

Only `class: execution` milestones may declare `practiced_by` and `practice_group`. The
validator rejects the others, because a milestone that cannot decay cannot be refreshed.

```yaml
- id: comfortable_4_way_switches
  name: Comfortable 4-way switches
  class: execution
  kind: self_attested
  practice_group: nh_fundamentals
  practiced_by: [lms, nh_combat, wilderness_pvp]
```

`practiced_by` names which of the six practice domains refresh it: `lms`, `nh_combat`,
`wilderness_pvp`, `vengeance_pvp`, `anti_pking`, `general_pvp`. Adding a seventh domain is
a code change.

> **When something is both an achievement and an ongoing skill, author two milestones.**
> Freeze logging is the clear case: `successfully_freeze_log` is `threshold` and stays
> achieved forever, while `freeze_logging_practice` is `execution` and decays. One row
> meaning both would make `achieved` ambiguous — and staleness must never set `achieved`
> back to false.

## Adding a refresher

Refreshers are authored per practice **group**, never per milestone. Ungrouped refreshers
give accurate but useless coaching: *"Refresh 4-way switches / Refresh overhead prayers /
Refresh freeze logging / …"*.

```yaml
id: refresh_nh_fundamentals
name: Refresh NH fundamentals
practice_group: nh_fundamentals
trigger:
  any_member_freshness_at_least: stale
suggested_session: 5 LMS matches
suggested_session_hours: 0.5
advances: [deep_wildy_nh, ice_barrage_nh]
```

`suggested_session_hours` is **mandatory and is not a formality**. A refresher is scored
by the same function as everything else, and that function includes
`effort_decay = exp(−hours/τ)`. With no hours it scores `1.0` — a perfect effort mark —
which would make every refresher maximally attractive. `suggested_session` is the string
a human reads; `suggested_session_hours` is the number the engine reads.

The group must have at least one `class: execution` member, or the refresher can never
trigger.

## Adding a training method

```yaml
- id: magic_bursting
  name: Magic bursting
  skill: magic
  xp_per_hour: 250000
  level_range: {min: 82, max: 99}
  cost_per_hour_gp: 400000
  requires:                    # optional — omit for an always-available method
    all_of:
      - unlock: ancient_magicks
      - quest: desert_treasure_i
```

Methods carry their own requirement trees, because the fast method is frequently gated
behind the very content the recommender is trying to sequence. The estimator picks, per
level band, the highest-xp/hour method whose requirements the player *currently*
satisfies — so a gated method does not silently flatter an estimate.

Prefer pessimistic rates. An understated cost flatters a candidate in the ranking; an
overstated one merely makes a good suggestion look slightly worse than it is.

## Adding an item

```yaml
- id: voidwaker
  name: Voidwaker
  item_id: 27690              # required when price_mode is live
  price_mode: live            # live | static
  fallback_price_gp: 85000000
  price_staleness_days: 7
```

`item_id` is the numeric in-game id — the key the OSRS Wiki price API and the plugin both
use. `price_mode: live` without one is rejected: it could never be priced.

### Equipment: ladders and wear gates (§10.5, §23)

Equipment carries more fields, and they go together:

```yaml
- id: dragon_scimitar
  name: Dragon scimitar
  item_id: 4587
  variant_item_ids: [4588]    # owning *any* of these is owning the item
  slot: weapon
  style: melee
  tier: 6                     # the rung — the wiki guide's printed order, not a rating
  requires:                   # what it takes to WEAR it
    all_of:
      - skill: {attack: 60}
      - quest: monkey_madness_i
  acquisition: tradeable      # how you GET it — a different question (§23.2)
```

An untradeable rung names what wins it instead:

```yaml
- id: fire_cape
  name: Fire cape
  item_id: 6570
  slot: cape
  style: melee
  tier: 4
  acquisition: untradeable
  acquired_from: the Fight Caves
```

**Do not hand-edit these rows.** `content/items/items.yaml` is generated. Edit
`tools/gear_ladders.py` and re-run `python tools/generate_gear_items.py`, or the next
regeneration discards your change.

Three things are easy to get wrong here:

1. **`requires` is what it takes to *wear* the item, never to make or repair it.** The wiki
   states these in prose and mixes the two freely — 80 Fletching for a magic shortbow, 90
   Smithing to repair Torva. Neither gates the equipment screen. A test rejects any wear gate
   naming an artisan skill.
2. **An unauthored gate is not an absent gate.** Every rung must land in exactly one of
   `REQUIREMENTS`, `UNGATED` or `UNTRANSCRIBED` in `tools/gear_ladders.py`. An item in the
   third emits `gate_unknown: true` and reads as *nobody has checked*; letting it default to
   ungated is how a level-3 account gets told it can equip a Twisted bow.
   `missing_requirements()` proves the partition is total, and a test asserts it is empty.
3. **Inserting a rung renumbers the ones below it.** Tiers are positional, so an insertion
   shifts every lower rung and moves §21.5's context hash for any account holding one —
   invalidating stored guidance. That is correct, but it should be on purpose.
4. **A rung must come from the guide's own loadout tables — never from a slot table.** The
   wiki also publishes `Shield_slot_table`, `Cape_slot_table` and friends, which list *every*
   item in a slot with its stats. They are tempting and they are a different document: a
   ladder padded from one looks more complete while quietly ceasing to be the guide's
   opinion, which is the only thing `tier` encodes. This has gone wrong twice — seven plain
   defenders on the melee shield ladder, and the whole arrow/bolt/dart family on the ranged
   ammunition one — and in both cases every added name was a real item in a sensible order,
   which is exactly why nothing caught it. `tests/tools/test_gear_ladders.py` now pins both
   ladders by name. If a slot looks too short, that is the guide being opinionated rather
   than the guide being incomplete.
4. **How a piece is *got* is a second question, with a second partition.** `acquisition`
   answers it, and it is orthogonal to `requires`: a Fire cape's whole wear gate is 40
   Defence, and no amount of gp buys one. Every rung lands in exactly one of `TRADEABLE`,
   `EARNED_FROM` or `ACQUISITION_UNTRANSCRIBED`, and `missing_acquisitions()` proves that
   partition total the same way its sibling does.

   `TRADEABLE` means **gp alone can get you one**, which includes the tradeable component of
   a piece that turns untradeable on use — an empty blowpipe, an inactive Blade of saeldor, a
   crystal armour seed. It is *not* the wiki's tradeability flag. What is untradeable is a
   piece whose chain reaches something the market never sells: an Avernic defender needs a
   Dragon defender, and nothing buys a Dragon defender.

   `EARNED_FROM`'s value is a **noun phrase, never a sentence** — every surface composes it
   into *"cannot be bought — earned from {value}"*.

   Unlike the gate tables, leaving a rung in `ACQUISITION_UNTRANSCRIBED` is the *safe*
   choice: §23.4 does not demote on an unknown acquisition, so the rung is still recommended
   and merely hedged. Guessing `untradeable` is the error that costs something — it withholds
   a rung the player could have gone and bought.

## The scoring profile

`content/scoring/profile.yaml` holds the tuning knobs — factor weights, τ, the κ presets,
`observation_aged_days`. These are **not** game facts, which is exactly why they are
content: a retune should not be a code change.

The shipped weights are provisional priors, not measured values. `tuned_against_corpus`
stays `null` until the golden corpus tunes them.

κ is constrained: each preset between 1,000,000 and 250,000,000 gp, ordered
`high < normal < low`. That ordering reads backwards until you remember what the setting
means — *high* sensitivity to cost discourages spending **sooner**, which is a **smaller**
κ.

## What the validator checks

- ids unique within each kind
- every referenced capability, quest, item, skill and milestone id resolves
- every `grants` target is a declared capability
- every candidate declares a non-empty `completion`, and every `advances` target is a
  declared capability — a typo'd id would otherwise make a candidate quietly less
  relevant rather than loudly wrong
- every `practiced_by` entry is one of the six practice domains
- every refresher's `practice_group` has at least one `class: execution` member
- only `class: execution` milestones declare `practiced_by` / `practice_group`
- every `price_mode: live` item has a numeric `item_id`
- a gear `tier` has a `slot` and a `style`, each rung holds one item, and no numeric item id
  is claimed by two items
- every id an item's wear gate references resolves, and no item declares both `requires` and
  `gate_unknown` — the gate is either known or it is not
- item-to-item wear gates are acyclic — and it names the cycle
- the capability graph is acyclic — and it names the cycle
- weights, `pvp_value` and roadmap capability weights lie in `[0, 1]`
- κ presets satisfy the min/max/ordering constraints
- unknown keys are errors, so a typo cannot silently take a default
