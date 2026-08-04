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
    milestones/        PvP milestones, with how they are measured and how they age
    refreshers/        practice-group templates that become candidates when stale
    training_methods/  xp/hour and gp/hour per skill and level band
    items/             numeric ids, price policy, fallback hints
    quests/            id + name; what `quest:` leaves resolve against
    skills/            id + name; what `skill:` leaves resolve against
    scoring/           profile.yaml — weights, τ, κ, thresholds
    candidates/        actions the player could take (added in step 2.5)
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
- every `practiced_by` entry is one of the six practice domains
- every refresher's `practice_group` has at least one `class: execution` member
- only `class: execution` milestones declare `practiced_by` / `practice_group`
- every `price_mode: live` item has a numeric `item_id`
- the capability graph is acyclic — and it names the cycle
- weights, `pvp_value` and roadmap capability weights lie in `[0, 1]`
- κ presets satisfy the min/max/ordering constraints
- unknown keys are errors, so a typo cannot silently take a default
