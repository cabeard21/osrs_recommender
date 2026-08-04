# OSRS PvP Progression Tracker — Software Design Document

| | |
|---|---|
| **Version** | 0.5.1 |
| **Date** | 2026-08-04 |
| **Status** | Implementation in progress against `plans/osrs-tracker-sdd-implementation.md`. All design questions resolved and all known specification gaps closed (§20). |

## Changelog

| Version | Date | Summary |
|---|---|---|
| 0.1 | — | Initial draft. |
| 0.2 | 2026-08-04 | Promoted capabilities to the core model; roadmaps redefined as weighted capability sets. Replaced the recommendation scoring function (previous form ranked *slower and further* tasks higher). Added observation provenance and staleness to the data model. Reconciled the localhost/Tailscale contradiction with an explicit security model. Added sections on time/cost estimation, the content schema and its validation, the sync payload contract, and testing strategy. |
| 0.3 | 2026-08-04 | Resolved D1–D5 (§18). Milestones gain class and freshness; staleness decays confidence, never achievement. Live item prices with cached and static fallback layers. Multiple active roadmaps merge into one effective capability-weight map via convex combination. Scoring weights externalized to a versioned profile with a defined tuning method. Side-loading fixed as the v1 plugin distribution path. Separated `unlocked` from `readiness_confidence`; estimate confidence expanded to three levels. |
| 0.4 | 2026-08-04 | Resolved D6–D10 (§18). **`CapabilityState.unlocked: bool` replaced by tri-valued `status`**, with three-valued requirement evaluation throughout (§9.1). Added `PracticeEvent` and the derived-practice-proxy model. Refresher candidates grouped by practice domain with a one-per-list cap. κ presets retained and relabelled in user terms. Price feed pinned to the OSRS Wiki real-time prices API, with confidence derived from **trade** timestamps rather than fetch time. Added the `recommended_now` status layer. |
| 0.5 | 2026-08-04 | Closed 21 specification gaps found while planning implementation; each is traced in §20. **Added the missing `Candidate` schema (§10.6)** — a core noun that had a content directory and drove every scoring factor, but no defined fields — together with the derivations for `pvp_value`, `leverage`, `proximity`, `completed` and `blocked` (D11). Completed the three-valued leaf resolution table (§9.1), pinning `unlock: available` and `quest: in_progress` as **unsatisfied**. Fixed the `unlock_fraction` denominator and defined *contributing* and *aged* for `readiness_confidence` (§6.9). Added `Milestone.attested_at` semantics so "never prompted" is representable (§6.6). Added `ActiveRoadmap` (§6.12) and made `SyncEvent.player_id` nullable so §11.3's audit requirement is satisfiable (§6.11). Moved the health endpoint outside `/api` (§11). Added **§4.5**, naming the observation/truth distinction that now recurs three times in the design. Sync contract declared provisional until validated against a real snapshot (D12). |
| 0.5.1 | 2026-08-04 | Closed A22, found while implementing §10.7's validator: added `content/quests/`, `content/skills/` and `content/refreshers/` to §10.1. §10.7 demanded referential integrity for quest and skill ids that the layout gave nowhere to declare, and §10.4's refresher templates had no directory. Quests and skills are content rather than a code table because §10.8 names a quest as precisely the thing that must never require a code change. Status moved from *design* to *implementation in progress*. |

---

# 1. Purpose

The OSRS PvP Progression Tracker is a locally hosted web application whose goal is to answer one question:

> **"What should I work on next to become a better Wilderness PKer?"**

Unlike existing OSRS tracking tools, this application is not intended to maximize XP gains or completion percentage. It models an account's progression toward specific PvP **capabilities** and recommends the highest-value next action.

The application is designed primarily for a single user, though the schema supports multiple characters from day one (see §6.1).

---

# 2. Goals

The application should:

* require almost no manual data entry
* synchronize automatically with RuneLite whenever possible
* remain accessible from desktop and mobile
* support multiple long-term PvP goals
* recommend the next highest-value task, **and explain why**
* distinguish what it knows from what it merely hasn't observed
* surface uncertainty rather than hiding it
* visualize progression
* remember historical progress
* adapt recommendations as progress changes, **without thrashing**
* **never move a player's progress backward** as a side effect of modelling
* **never infer competence the player has not demonstrated**

---

# 3. Non-goals

The application is **not** intended to become:

* a RuneLite replacement
* a wiki
* **a general-purpose XP calculator** — XP arithmetic exists solely to estimate time-to-unlock (§8), and is never a user-facing feature in its own right
* an efficiencyscape optimizer
* a bank value tracker
* a clan management tool
* **an item database** — prices are fetched only for items the active roadmap actually references (§8.3)
* **a combat telemetry recorder** — practice evidence is summarized, never detailed (§7.6)

---

# 4. Core Concepts

Four nouns carry the whole design. Everything else is plumbing.

| Concept | Definition | Source |
|---|---|---|
| **Fact** | An observed property of the account: a skill level, a completed quest, an owned item, a milestone. | Synced or self-attested |
| **Capability** | Something the player can *do* in PvP, gated by a requirement tree over facts. | Authored YAML |
| **Candidate** | An action the player could take that changes facts. | Authored YAML |
| **Roadmap** | A weighted set of target capabilities defining what "better" means for a given playstyle. | Authored YAML |

The engine's job reduces to: *given current facts, which candidate most efficiently advances the capabilities this roadmap weights most heavily?*

## 4.1 Capabilities are the core abstraction

A capability is the answer to *"what PvP activities am I actually capable of today?"* and *"what's preventing me from trying deep Wilderness NH?"*

```yaml
id: deep_wildy_nh
name: Deep Wilderness NH
requires:
  all_of:
    - capability: ice_barrage_nh
    - milestone: freeze_logging
    - milestone: teleblock_understanding
    - any_of:
        - item: voidwaker
        - item: armadyl_godsword
recommended_readiness: high
```

Capabilities compose — a capability may require other capabilities — producing a DAG rather than a hand-maintained linear tree.

## 4.2 Roadmaps are weighted capability sets

**Roadmaps do not have their own dependency graph.** A roadmap is a selection of capabilities with weights; the ordering the user sees is derived from the capability DAG plus current facts. This deletes the second graph that v0.1 would have required us to keep in sync with the first.

```yaml
id: main_nh
name: Main NH
capabilities:
  ice_barrage_nh: 1.00
  deep_wildy_nh: 0.90
  budget_nh: 0.40      # already largely satisfied for a main; low marginal value
  anti_pk: 0.60
```

"Pure NH", "Zerker", "Vengeance PKer" and "Anti-PKer" differ only in these weights and in which capabilities they include — not in any additional code or graph.

## 4.3 Multiple active roadmaps

A player may pursue more than one roadmap. Roadmaps are selected with **selection weights**:

```yaml
active_roadmaps:
  main_nh: 1.00       # primary
  anti_pk: 0.25       # secondary
```

Selection weights are normalized to sum to 1 before use. The engine merges all selected roadmaps into a **single effective capability-weight map** (§9.3) before scoring anything. The maximum across roadmaps is explicitly *not* used — see D3.

**UI defaults:** one primary roadmap at `1.00`, zero or more secondaries at `0.25`. Weights are editable only in advanced settings, so first-run is a simple choice of playstyle rather than an abstract weighting exercise.

## 4.4 Three status layers

Capability status is deliberately three-layered. Collapsing any two of these produces either backward progress or false confidence.

| Layer | Question it answers | Type |
|---|---|---|
| `status` | Are the objective requirements met? | `unlocked \| locked \| unknown` |
| `readiness_confidence` | How fresh is the evidence that the player can execute today? | `high \| medium \| low` |
| `recommended_now` | Does the recommender think this is a sensible activity today? | bool + reason |

Worked examples:

```
Budget Wilderness NH
  Status:               unlocked
  Readiness confidence: medium
  Recommended now:      yes

High-risk Deep Wilderness NH
  Status:               unlocked
  Readiness confidence: low
  Recommended now:      no — complete a refresher session first

Voidwaker NH
  Status:               unknown
  Readiness confidence: —
  Recommended now:      no — bank contents have never been observed
```

Conservative coaching lives entirely in `recommended_now`. It never reaches back and revokes `status`.

## 4.5 Observation time is not truth

The same modelling error appears at three different layers of this design, and each time it
was expensive enough to warrant a schema change. It is worth naming once, so the fourth
instance is caught before it ships.

> **When we looked at something is a different fact from what is true about it. Storing only
> the first and inferring the second is always wrong.**

| Layer | Naïve model | What it cannot distinguish | Fix |
|---|---|---|---|
| Item ownership | `ObservedItem` rows only | "you don't own it" vs **"we have never looked"** | `ContainerScan` (§6.5) |
| Market price | `fetched_at` only | a fresh fetch of **stale market data** vs a fresh trade | `high_trade_at` / `low_trade_at` (§6.8, D10) |
| Self-attestation | `achieved: bool` only | "asked, the user said no" vs **"never asked"** | `attested_at` nullable (§6.6) |

In every case the naïve model silently converts *absence of evidence* into *evidence of
absence*, which is precisely what §2 forbids: *"distinguish what it knows from what it merely
hasn't observed."*

The consequence for implementation is uniform. Any fact whose observation is opportunistic
rather than continuous needs **two timestamps** — when the underlying event occurred, and
when we learned of it — and its absence must resolve to `unknown` rather than to a negative.

---

# 5. High-level Architecture

```text
        ┌──────────────────────┐
        │  RuneLite Companion  │  (Java, side-loaded — §13)
        │        Plugin        │
        └──────────┬───────────┘
                   │ HTTP POST + bearer token
                   │ contracts/sync_payload.schema.json
                   ▼
        ┌──────────────────────────────────────┐
        │  Python app (single uvicorn process)   │
        │                                       │
        │  NiceGUI UI          /                │
        │  FastAPI sync API    /api/sync        │
        │  Progression engine                   │
        │  Freshness service                    │
        │  Recommendation engine                │
        │  Background sync worker               │
        └──────────┬───────────────────────────┘
                   │ SQLAlchemy + Alembic
                   ▼
        ┌──────────────────────┐
        │        SQLite        │
        └──────────────────────┘
                   ▲
                   │ background poll
        ┌──────────┴────────────────────────────┐
        │  Wise Old Man API                      │
        │  OSRS Wiki real-time prices (scoped)   │
        │  (contingency: official hiscores)      │
        └────────────────────────────────────────┘
```

NiceGUI runs on FastAPI/uvicorn, so the UI and the sync API are **one process on one port** (default `8502`). There is no second service.

**Bind address is configuration, not an assumption.** See §11 for the security model — the app is reachable from a phone over Tailscale, which means it is not loopback-only and cannot rely on being so.

---

# 6. Data Model

All tables carry provenance. The observation source enum is shared:

```
Source = runelite | wise_old_man | hiscores | osrs_wiki_prices | manual | derived
```

Precedence when sources disagree, highest first: `runelite > wise_old_man > hiscores`. Rationale in §7.4.

## 6.1 Player

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | Multi-character is supported by the schema from v1; the UI may expose only one. |
| `username` | str | Hiscores/WOM lookup key. |
| `display_name` | str | |
| `created_at` | datetime | |
| `last_sync_at` | datetime | |
| `combat_level` | int | |
| `quest_points` | int | |
| `gp_sensitivity` | enum | `high \| normal \| low` — sets κ (§9.6) |

## 6.2 SkillSnapshot

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `player_id` | int FK | |
| `skill` | str | |
| `level` | int | |
| `xp` | int | **Nullable.** `NULL` means unranked, never `0`. |
| `source` | Source | |
| `observed_at` | datetime | |

> Hiscores return `-1` for unranked skills and bosses. This must be normalized to `NULL` at the adapter boundary, never stored or treated as zero.

## 6.3 Unlock

Permanent account unlocks (Ancient Magicks, Lunars, Rigour, Augury, Assembler, Barrows Gloves, …). Most are derivable from RuneLite varbits; the rest are inferred or self-attested.

| Column | Type | Notes |
|---|---|---|
| `player_id` | int FK | |
| `key` | str | `ancient_magicks`, `rigour`, `assembler` |
| `state` | enum | `unlocked \| available \| locked \| unknown` |
| `source` | Source | |
| `observed_at` | datetime | |

**`unknown` is a first-class state.** Before the first RuneLite sync the app does not know, and §15 must render unknown distinctly from locked.

**`available` is not a positive state.** It means *purchasable or attainable but not yet
held* — Rigour visible in the Prayer book is not Rigour unlocked. Requirement leaves treat
`available` as `unsatisfied` (§9.1). The word reads as positive and is the single most likely
place for an implementation to go wrong.

**Reserved key prefixes.** Spellbook, achievement diaries and combat achievements are
plugin-provided (§7.1) but need no tables of their own; they are `Unlock` rows under reserved
prefixes:

| Prefix | Example | Meaning |
|---|---|---|
| `spellbook_` | `spellbook_ancient` | Spellbook access |
| `diary_` | `diary_varrock_hard` | Achievement diary tier |
| `ca_` | `ca_grandmaster` | Combat achievement tier |

This keeps §10.2's leaf-type list closed: authored content references them with the existing
`unlock:` leaf and no new requirement type is needed.

## 6.4 QuestState

| Column | Type | Notes |
|---|---|---|
| `player_id` | int FK | |
| `quest_id` | str | |
| `status` | enum | `not_started \| in_progress \| complete \| unknown` |
| `source` | Source | |
| `observed_at` | datetime | |

## 6.5 ObservedItem and ContainerScan

Item ownership is **observed opportunistically**, not known continuously. Bank contents are only visible while the bank interface is open; equipment only while worn.

**ObservedItem**

| Column | Type |
|---|---|
| `player_id` | int FK |
| `item_id` | int |
| `quantity` | int |
| `container` | enum `bank \| inventory \| equipment` |
| `source` | Source |
| `observed_at` | datetime |

**ContainerScan** — the staleness anchor, without which "no row" is ambiguous.

| Column | Type | Notes |
|---|---|---|
| `player_id` | int FK | |
| `container` | enum | |
| `scanned_at` | datetime | Last time this container was seen *in full*. |

Ownership resolves three ways, and the distinction drives capability status (§9.1):

| Evidence | Ownership | Effect |
|---|---|---|
| Item seen in a scan | `satisfied` | Aged positive evidence lowers `readiness_confidence` but stays satisfied |
| Not seen, but a scan covers the container | `unsatisfied` | A genuine blocker |
| No scan of that container has ever occurred | `unknown` | Propagates to capability `status: unknown` |

The UI must say *"last saw your bank 3 weeks ago"* rather than *"you don't have a Voidwaker."*

## 6.6 Milestone

PvP milestones carry two orthogonal attributes: **how they are measured** (`kind`) and **how they age** (`class`).

| Column | Type | Notes |
|---|---|---|
| `player_id` | int FK | |
| `key` | str | |
| `kind` | enum | `derived \| self_attested` — how it is measured |
| `class` | enum | `knowledge \| execution \| threshold` — how it ages |
| `achieved` | bool | **Never set back to false by the passage of time.** |
| `value` | int | nullable — for threshold milestones |
| `attested_at` | datetime | **Nullable. `NULL` means never prompted** — see below |
| `last_practiced_at` | datetime | nullable — most recent evidence of practice (§7.6) |
| `freshness` | enum | nullable — `current \| stale \| very_stale`. Materialized from `last_practiced_at` after each freshness-service run; `NULL` for classes that do not age |
| `source` | Source | |
| `observed_at` | datetime | |

**`attested_at IS NULL` means the milestone has never been prompted**, which is a different
fact from a milestone the user was asked about and declined. A self-attested milestone with
`attested_at IS NULL` resolves its requirement leaf to `unknown`, never `unsatisfied` (§9.1).
`achieved: bool` alone cannot express this — it is the §4.5 pattern applied to attestation.

`freshness` is derived, never authoritative. It is materialized purely for query convenience
and may be rebuilt from `last_practiced_at` at any time.

Content-side attributes on execution milestones — `practiced_by` (which practice domains refresh it) and `practice_group` (which refresher session it belongs to) — are defined in §10.3.

### Measurement (`kind`)

**Derived** — never prompt the user: LMS score/rank thresholds, boss KC thresholds, all hiscores-visible counters.

**Self-attested** — the only milestones that prompt: *comfortable 4-way switches*, *consistent overhead prayers*, *teleblock understanding*, *successfully freeze log*.

Keeping the self-attested set small is what makes §2's "almost no manual data entry" true.

### Ageing (`class`)

| Class | Meaning | Ages? |
|---|---|---|
| `knowledge` | Understanding, once acquired | No — persists indefinitely |
| `execution` | Mechanical skill requiring practice | Yes — freshness decays |
| `threshold` | A thing that happened | No — permanent |

Classification of the current milestone set:

| Milestone | Class | Behaviour |
|---|---|---|
| First Wilderness kill | `threshold` | Permanent |
| First anti-PK | `threshold` | Permanent |
| Successfully freeze log | `threshold` | Permanent achievement |
| 10 / 100 LMS wins | `threshold` (derived) | Permanent |
| Teleblock understanding | `knowledge` | Persists; may display an informational staleness note, but never affects readiness |
| Comfortable 4-way switches | `execution` | Persists with confidence decay |
| Consistent overhead prayers | `execution` | Persists with confidence decay |

> Where a `threshold` achievement also has an ongoing practice component — *freeze logging* is the clear case — author a **separate `execution` milestone** for the practice rather than making one row mean both. This keeps `achieved` unambiguous.

### Freshness policy (applies to `class: execution` only)

| Time since `last_practiced_at` | Freshness | Effect |
|---|---|---|
| < 30 days | `current` | Full credit |
| 30–90 days | `stale` | Still satisfied; may generate a refresher recommendation |
| > 90 days | `very_stale` | Still satisfied; lowers `readiness_confidence` on advanced capabilities |

**Staleness never sets `achieved` to false, and stale milestones are never hard blockers — in v1 or afterwards** (D8). Their only effects are `readiness_confidence` (§6.9), `recommended_now` (§4.4), and refresher candidates (§9.8).

## 6.7 PracticeEvent

Normalized evidence that relevant PvP activity occurred. Integrations write `PracticeEvent` rows; the **freshness service** maps events onto milestones. Client-side detection logic never touches milestone rows directly.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `player_id` | int FK | |
| `domain` | enum | see §7.6 |
| `started_at` | datetime | |
| `ended_at` | datetime | |
| `source` | Source | |
| `confidence` | enum | `high \| medium` |
| `evidence_type` | str | `lms_match_completed`, `wilderness_player_combat`, `lms_score_increased` |
| `metadata` | JSON | summarized only — see the collection boundary in §7.6 |

```json
[
  { "domain": "lms",         "source": "runelite",
    "confidence": "high",    "evidence_type": "lms_match_completed" },

  { "domain": "general_pvp", "source": "wise_old_man",
    "confidence": "medium",  "evidence_type": "lms_score_increased" }
]
```

## 6.8 ItemPrice

The real-time feed exposes recent high and low prices with their own trade timestamps. **Both the prices and their trade times are stored**, because fetch time and trade time are different facts (§8.4).

| Column | Type | Notes |
|---|---|---|
| `item_id` | int PK | |
| `high_price_gp` | int | nullable |
| `high_trade_at` | datetime | nullable — when that trade occurred |
| `low_price_gp` | int | nullable |
| `low_trade_at` | datetime | nullable |
| `selected_price_gp` | int | nullable — the value used in scoring |
| `selection_policy` | enum | `acquisition_cost` |
| `selection_reason` | str | which layer supplied `selected_price_gp` |
| `provider` | str | `osrs_wiki` |
| `fetched_at` | datetime | when *we* called the API |
| `source` | enum | `live \| cached \| static_hint \| unknown` |

The provider client (§7.5) writes everything above except the three `selected_*` columns.
Those are the *output of the resolution policy* in §8.3 rather than data the feed supplies,
so they are computed by the estimator and persisted alongside the fetch. Recording them means
any figure the UI shows can be traced to the layer that produced it without re-running the
cascade.

## 6.9 CapabilityState

Materialized output of the progression engine.

| Column | Type | Notes |
|---|---|---|
| `player_id` | int FK | |
| `capability_id` | str | |
| `status` | enum | **`unlocked \| locked \| unknown`** — objective; never influenced by freshness |
| `unlock_fraction` | float | 0–1, `satisfied_leaves / total_leaves` — see below |
| `blockers` | JSON | leaves evaluating to `unsatisfied` |
| `unknowns` | JSON | leaves evaluating to `unknown` — "sync this", not "do this" |
| `readiness_confidence` | enum | `high \| medium \| low` — only meaningful when `status = unlocked` |
| `warnings` | JSON | human-readable caveats |
| `recommended_now` | bool | |
| `recommended_now_reason` | str | nullable |
| `computed_at` | datetime | |

**`status` replaces the v0.3 boolean `unlocked`** (D8). A boolean cannot represent "we have never observed your bank," and the app must never emit the logically inconsistent pair *"Unlocked: yes / Confidence: low because item ownership is unknown."* Unknown objective evidence produces an unknown capability, not an unlocked one with a caveat.

`blockers` and `unknowns` are separate lists because they demand different user actions.

### `unlock_fraction`

```
unlock_fraction = count(leaves evaluating to satisfied) / count(all leaves)
```

**Unknown leaves sit in the denominator but are never credited.** A capability with one
satisfied, one unsatisfied and one unknown leaf reports `0.33`, not `0.50`. Crediting unknowns
would let an unobserved account appear to be making progress; removing them from the
denominator would make an unobserved capability appear *closer* than an observed one with the
same real progress. Neither is acceptable, so unknowns count against the fraction without
being called blockers.

### `readiness_confidence`

Evaluated only when `status = unlocked`, so unknowns cannot reach it.

**Contributing** means: the leaves reached by the transitive requirement walk that evaluated
to `satisfied`. A leaf that played no part in unlocking the capability — a losing branch of an
`any_of`, or a leaf under an unsatisfied sibling — never affects readiness.

**Aged**, for a positive observation, means `now − ContainerScan.scanned_at >
observation_aged_days`, a scoring-profile constant defaulting to **14 days** (§9.7). It is a
profile value rather than a code constant because it is a tuning knob, not a fact about the
game (§10.8).

| Confidence | Condition |
|---|---|
| `high` | All contributing `execution` milestones `current`; all contributing positive observations fresh |
| `medium` | ≥1 contributing execution milestone `stale`, **or** a contributing observation is aged |
| `low` | ≥1 contributing execution milestone `very_stale` |

`high | medium | low` is **an ordered enum** — `low < medium < high` — because
`recommended_now` compares against a threshold. Implementations must give it a total order
rather than relying on string comparison.

### `recommended_now`

```
recommended_now = (status == unlocked)
                  AND readiness_confidence >= capability.recommended_readiness
```

Capabilities declaring `recommended_readiness: high` (§10.2) will show `recommended_now: false` with a refresher suggestion when execution evidence has decayed — discouraging deployment without revoking progress.

`recommended_now_reason` is **generated, never authored**, from exactly three cases:

| Case | Reason text |
|---|---|
| `status = unknown` | names the unknown evidence — *"bank contents have never been observed"* |
| `status = locked` | names the highest-value blocker — *"requires 94 Magic"* |
| Confidence below the declared bar | *"complete a refresher session first"* |

### `warnings`

Human-readable caveats, also generated, from three sources:

1. Contributing `execution` milestones that are `stale` or `very_stale`.
2. Contributing observations that are aged — phrased as observation age, never as absence:
   *"last saw your bank 3 weeks ago"* (§6.5).
3. An informational staleness note on `class: knowledge` milestones. §6.6 permits the note and
   forbids any readiness effect, so this is the only place such a milestone may appear.

Warnings never alter `status`, `readiness_confidence` or `recommended_now`. They explain a
computed result; they are never an input to one.

## 6.10 RecommendationSnapshot / RecommendationEntry

Required by the History UI (§15) and, more importantly, by engine debuggability — two runs can be diffed to see which factor moved.

**RecommendationSnapshot**: `id`, `player_id`, `run_at`, `roadmap_selection` (JSON), `scoring_profile_version`

**RecommendationEntry**

| Column | Type | Notes |
|---|---|---|
| `snapshot_id` | int FK | |
| `rank` | int | |
| `candidate_id` | str | |
| `candidate_kind` | enum | `progression \| refresher` |
| `score` | float | |
| `factors` | JSON | per-factor values **and** log-contributions (§9.5) |
| `reason` | str | generated from `factors` |
| `estimated_hours` | float | nullable |
| `estimated_gp` | int | nullable |
| `estimate_confidence` | enum | `high \| medium \| low` (§8.4) |
| `blocked` | bool | |

## 6.11 SyncEvent

An audit trail for plugin/app version drift **and for rejected requests**.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `player_id` | int FK | **Nullable** — see below |
| `source` | Source | |
| `payload_version` | int | nullable — absent or unparseable on malformed requests |
| `remote_addr` | str | nullable |
| `received_at` | datetime | |
| `accepted` | bool | |
| `reason` | str | nullable — why a request was rejected |
| `error` | str | nullable |

**`player_id` must be nullable.** §11.3 requires recording a `SyncEvent` for unauthenticated
writes, but an unauthenticated caller has no trusted identity. The alternatives are both
unacceptable: dropping the audit row defeats §11.3, and trusting an attacker-supplied
`player_id` writes attacker-controlled data into the audit trail. A rejected request is
recorded with `player_id = NULL`, `accepted = false`, and a `reason`.

## 6.12 ActiveRoadmap

The player's current roadmap selection (§4.3). This is live configuration, distinct from
`RecommendationSnapshot.roadmap_selection`, which records what a *particular past run* used.

| Column | Type | Notes |
|---|---|---|
| `player_id` | int FK | |
| `roadmap_id` | str | |
| `selection_weight` | float | 0–1; normalized to sum to 1 at read time (§9.3) |

Normalization happens on read rather than on write so that removing a roadmap cannot silently
rescale the others' stored values.

## 6.13 Migrations

**Alembic from the first commit.** The schema will churn for months while the engine's needs are discovered, and by the time it stabilizes there will be historical XP snapshots worth preserving. Retrofitting migrations after that point is the expensive version of this decision.

---

# 7. Data Sources

## 7.1 RuneLite Companion Plugin — primary

Java plugin, side-loaded from a local build (§13).

Provides: quest completion and quest points, skills and XP, spellbook, diaries, combat achievements, observed equipment, observed bank contents, unlock flags, and summarized practice events (§7.6).

Most unlock and quest state is read from varbits, which is why the plugin is authoritative and freshest.

Spellbook, diaries and combat achievements are transmitted as `Unlock` entries under the
reserved key prefixes of §6.3 (`spellbook_`, `diary_`, `ca_`). They get no tables and no leaf
types of their own — a field in the sync payload with no storage and no way to reference it
from content would be a contract with no sink.

## 7.2 Wise Old Man — primary remote source

WOM already polls the hiscores, stores history, and exposes gains — covering both the "official hiscores" and "XP history" roles from v0.1 with one integration, one parser, and one rate-limit budget.

Provides: skills, total level, boss KC, LMS score, XP history and gains.

Requires a descriptive `User-Agent`; respect published rate limits with backoff.

## 7.3 Official Hiscores — contingency only

Direct hiscores access is retained as a documented fallback should WOM be unavailable, but is **not built for v1**. If implemented, use the `index_lite.json` endpoint and normalize `-1` to `NULL`.

## 7.4 Source precedence and conflict resolution

The hiscores (and therefore WOM) **only update on logout**, so RuneLite is nearly always fresher and the two *will* disagree during a session. Rules:

1. Prefer the most recent `observed_at`.
2. On ties, prefer by source precedence: `runelite > wise_old_man > hiscores`.
3. **Never allow a lower-precedence source to decrease a skill's stored XP.** A stale hiscores read must not roll back a fresh RuneLite observation.

## 7.5 OSRS Wiki real-time prices

Provider: the OSRS Wiki real-time prices API (`https://prices.runescape.wiki/api/v1/osrs`), whose data is supplied via RuneLite. The provider asks automated clients to set a descriptive `User-Agent` and notes that generic identifiers — `python-requests`, `Python-urllib`, `Apache-HttpClient`, Java defaults, bare `curl` — may be blocked. It publishes no fixed numeric rate limit, but reserves the right to limit clients whose sustained volume threatens service stability. It also cautions that endpoints may have downtime and that prices are not always accurate, particularly for low-volume items.

**User-Agent** — application, version, purpose, optional public contact. Configurable, so no private information is exposed without intent:

```yaml
integrations:
  prices:
    provider: osrs_wiki
    base_url: https://prices.runescape.wiki/api/v1/osrs
    user_agent: >-
      osrs-pvp-progression-tracker/0.1
      (private local progression app; contact: github.com/example/osrs-tracker)
    ttl_hours: 12
    manual_refresh_min_interval_seconds: 60
```

**Request behaviour.** A 12-hour cache over a roadmap-scoped item set sits far below any plausible concern threshold, but the client is defensive regardless:

* At most one refresh attempt per recommendation run.
* No request at all while valid cached data exists.
* Retry schedule: immediate → 2s → 8s, then stop and fall back.
* Honour `Retry-After` whenever present; exponential backoff on `429` and `5xx`.
* Circuit breaker after repeated failures.
* **No user-visible failure** when a cached or static fallback exists.
* Log response status and the provider's own timestamp.
* Manual refresh rate-limited to once per 60 seconds.

**Attribution** — shown in the settings page footer:

> Market prices provided by the OSRS Wiki real-time prices API and RuneLite contributors. Prices are estimates and may be stale for low-volume items.

## 7.6 Derived practice proxies

Practice proxies refresh `last_practiced_at` from **affirmative evidence of relevant PvP participation**. They exist so that §2's near-zero manual entry survives contact with milestone freshness.

The governing distinction:

```
achieved           = "The user has established this skill before."
last_practiced_at  = "The user recently exercised the general skill domain."
```

A proxy may update `last_practiced_at` only when all four hold:

1. The signal proves relevant PvP activity occurred.
2. The milestone explicitly declares that signal via `practiced_by`.
3. The proxy does **not** set `achieved = true`.
4. The proxy does **not** claim competence from mere participation.

### Practice domains

```
lms · nh_combat · wilderness_pvp · vengeance_pvp · anti_pking · general_pvp
```

### Accepted and rejected signals

| Signal | May refresh | Confidence |
|---|---|---|
| RuneLite observes entry into and exit from an LMS match | `lms`, `nh_combat`, `general_pvp` | high |
| RuneLite observes sustained player combat in LMS | `lms`, `nh_combat` | high |
| RuneLite observes sustained player combat inside the Wilderness | `wilderness_pvp`, `general_pvp` | high |
| RuneLite observes the player attacked on a PvM setup in the Wilderness | `anti_pking` — **only if the player fights back** | medium |
| WOM LMS score increases | `lms`, `general_pvp` | medium |
| Player merely enters the Wilderness | nothing | — |
| Player equips multiple combat styles | nothing | — |
| Player switches prayers rapidly | nothing on its own | — |
| Player logs in after a long break | nothing | — |

**"Combat occurred" threshold for v1:** at least two player-directed attacks, **or** at least ten seconds in a player-combat state. This prevents a milestone refreshing because someone misclicked another player or took a single hit while escaping.

### Evidence asymmetry

WOM evidence is positive-only. An LMS score increase proves recent activity; a *lack* of movement proves nothing.

* Positive WOM evidence may refresh practice.
* **Absent WOM evidence must never accelerate staleness.**
* RuneLite session evidence takes precedence when available.

### Collection boundary

The plugin submits **summarized** practice events. It does not collect opponent names, attack sequences, chat, individual prayer selections, fight-time inventories, or tick-by-tick location history. This is a hard boundary, restated as a non-goal in §3.

```json
{
  "practice_events": [
    {
      "domain": "lms",
      "started_at": "2026-08-04T15:12:00Z",
      "ended_at":   "2026-08-04T15:18:41Z",
      "evidence_type": "lms_match_completed"
    }
  ]
}
```

---

# 8. Time and Cost Estimation

The recommendation output ("Train Magic 87 → 94, ~4.5 hours, ~1.8M gp") requires a real estimator. This is a subsystem, not a formula.

## 8.1 Training methods are content

```yaml
id: magic_bursting
skill: magic
xp_per_hour: 250000
level_range: {min: 82, max: 99}
cost_per_hour_gp: 400000
requires:
  all_of:
    - unlock: ancient_magicks
    - quest: desert_treasure_i
```

Methods have their own requirement trees — the fast method is frequently gated behind the very content the recommender is trying to sequence.

## 8.2 Estimation algorithm

1. Compute remaining XP to target.
2. Partition it into the level bands spanned.
3. For each band, select the highest-XP/hr method **whose requirements the player currently satisfies**.
4. Integrate hours and GP cost across bands.

If no available method covers a band, fall back to a conservative default rate and mark the band low-confidence.

## 8.3 Item prices

GP cost is a ranking factor (§9.4), so stale prices materially reorder recommendations. Items like the Voidwaker, dragon claws, toxic staff, ancient godsword and prayer scrolls move far too much for hand-authored values to remain honest.

**Three-layer resolution**, first hit wins:

```
Live market price
    ↓  unavailable
Cached last-known price (within TTL)
    ↓  unavailable or too old
Static content hint
    ↓  absent
unknown
```

**Selection policy for acquisition.** A recommendation to *buy* something should estimate cost conservatively, so the selection order within the live layer is:

```
recent high price  →  recent low price  →  cached  →  static hint  →  unknown
```

`selection_reason` records which layer supplied the number, so the UI can explain any figure it shows.

Item content declares its own price policy rather than pretending a static number is authoritative:

```yaml
id: voidwaker
item_id: 27690
price_mode: live
fallback_price_gp: 85000000
price_staleness_days: 7
```

**Fetch scope — this is what keeps the integration small.** Only items referenced by the active roadmap's capabilities, candidates and training methods are fetched. The full item economy is never pulled; doing so would recreate the item database that §3 rules out.

## 8.4 Estimate confidence

`estimate_confidence` is **three-valued** — `high | medium | low`. Two levels were insufficient: a cached price from yesterday is meaningfully better than a hand-authored fallback, and collapsing them hides real information.

**Price confidence is derived from the underlying trade timestamp, not from `fetched_at`.** Fetching today does not make a three-day-old trade fresh — this is the same defect as `ContainerScan` (§6.5) one layer out, and it is why §6.8 stores `high_trade_at` and `low_trade_at` separately.

| Age of the selected trade | Price confidence |
|---|---|
| < 24 hours | high |
| 1–7 days | medium |
| > 7 days | low |
| No trade data — static fallback or unknown | low |

The reported `estimate_confidence` is the **minimum** across price confidence and training-method confidence (high when every band has an available authored method; low when any band falls back to the default rate).

The UI must visually distinguish anything below `high`. An unqualified "4.5 hours" that is actually a guess erodes trust in every other number on the page.

---

# 9. Progression and Recommendation Engines

## 9.1 Three-valued requirement evaluation

Because `CapabilityState.status` is tri-valued (§6.9), requirement evaluation is tri-valued throughout. Every leaf returns `satisfied | unsatisfied | unknown`, and combinators follow **Kleene three-valued logic**:

| Combinator | Result |
|---|---|
| `all_of` | `unsatisfied` if any child is unsatisfied; else `unknown` if any child is unknown; else `satisfied` |
| `any_of` | `satisfied` if any child is satisfied; else `unknown` if any child is unknown; else `unsatisfied` |
| `not` | swaps satisfied ↔ unsatisfied; `unknown` maps to `unknown` |
| `at_least: {n, of}` | `satisfied` if `count(satisfied) ≥ n`; `unsatisfied` if `count(satisfied) + count(unknown) < n`; else `unknown` |

This ordering matters: a definite `unsatisfied` in an `all_of` short-circuits to `unsatisfied` even when siblings are unknown, because the requirement genuinely cannot be met. Conversely a definite `satisfied` in an `any_of` wins outright. Implementations that reach for `if not satisfied` collapse unknown into false and reintroduce exactly the bug D8 removes.

Leaf resolution, in full. All eight leaf types of §10.2 must resolve to exactly one of the
three values:

| Leaf | `satisfied` | `unsatisfied` | `unknown` |
|---|---|---|---|
| `skill` | level ≥ target | level < target | no snapshot from any source |
| `unlock` | `state = unlocked` | `state ∈ {available, locked}` | `state = unknown` |
| `quest` | `status = complete` | `status ∈ {not_started, in_progress}` | `status = unknown` |
| `item` | seen in a scan | a scan covers the container, item absent | no `ContainerScan` has ever covered the container (§6.5) |
| `milestone` | `achieved` | attested and not achieved | self-attested with `attested_at IS NULL` (§6.6) |
| `capability` | child `status = unlocked` | child `status = locked` | child `status = unknown` |
| `combat_level` | ≥ target | < target | account never synced (`last_sync_at IS NULL`) |
| `quest_points` | ≥ target | < target | account never synced (`last_sync_at IS NULL`) |

Two rows deserve emphasis because their natural-language reading is misleading:

* **`unlock: available` is `unsatisfied`, not `satisfied`.** "Available" means purchasable,
  not held (§6.3).
* **`quest: in_progress` is `unsatisfied`, not partially satisfied.** The requirement grammar
  has no partial-credit leaf; progress is expressed through `unlock_fraction` at the
  capability level, not by softening a leaf.

`unlock_fraction` credits **satisfied** leaves only; unknown leaves are never counted as
blockers and appear in `CapabilityState.unknowns`. They do, however, remain in the denominator
— see §6.9 for why both halves of that rule matter.

## 9.2 Capability status, readiness, and recommendation

The three layers of §4.4 are computed in strict order, and information only flows downward:

```
requirement tree  ──►  status
                            └──►  readiness_confidence   (only when status = unlocked)
                                        └──►  recommended_now
```

Freshness never flows upward into `status`. Unknown evidence never flows downward into `readiness_confidence` — it stops at `status: unknown`.

## 9.3 Effective capability weights

Before any candidate is scored, all active roadmaps collapse into **one** capability-weight map.

1. Normalize selection weights so they sum to 1.
2. For each capability:

```
effective_weight(c) = Σ  selection_weight(r) × roadmap_capability_weight(r, c)
                      r
```

Because the selection weights sum to 1 and each roadmap's capability weights lie in `[0,1]`, the result is a **convex combination** — automatically in `[0,1]`, with no separate normalization pass.

This also dissolves the double-counting problem. A capability appearing in two roadmaps blends rather than accumulates:

```
Main NH      ice_barrage_nh = 1.0     selection 0.75
Deep Wildy   ice_barrage_nh = 0.8     selection 0.25
                                      ─────────────────
effective_weight = 0.75(1.0) + 0.25(0.8) = 0.95      (never 1.8)
```

Worked candidate example, with `main_nh: 0.75, anti_pk: 0.25`:

| Candidate | Main NH | Anti-PK | Combined |
|---|---|---|---|
| Train Magic to 94 | 1.00 | 0.60 | **0.90** |
| Practice vengeance timing | 0.20 | 0.90 | **0.375** |

A candidate's `pvp_value` factor is its relevance scored against this single blended map:

```
pvp_value(cand) = max  effective_weight(c) × advances(cand, c)
                   c
```

where `advances` is the candidate's declared contribution to each capability (§10.6).

**The order of operations is load-bearing.** Blend the capability map first, *then* take the
maximum across the candidate's `advances` entries. Taking a maximum per roadmap and blending
afterwards gives different answers for candidates advancing more than one capability, because
`max` and convex combination do not commute. The blend-then-max form is the one that agrees
with the table above.

**Maximum, never sum** — for the same reason §9.8 forbids summing refresher group members. A
candidate advancing four capabilities weakly must not outrank one advancing a single
capability strongly; summation would make breadth a substitute for relevance.

## 9.4 Scoring function

A **weighted geometric mean** over factors normalized to `(0, 1]`:

```
score = Π  fᵢ ^ wᵢ
```

| Factor | Definition | v1 default weight |
|---|---|---|
| `readiness` | Hard gate, `{0, 1}`. Blocked candidates are excluded and surfaced separately. | — (gate) |
| `pvp_value` | Candidate relevance under the effective capability-weight map (§9.3). | 1.0 |
| `leverage` | Normalized count of capabilities this unblocks. | 0.8 |
| `proximity` | `1 − (remaining / total)` — closer is better. | 0.6 |
| `effort_decay` | `exp(−hours / τ)` | 0.7 |
| `cost_decay` | `exp(−gp_cost / κ)` | 0.5 |

Every factor is floored at ε = 0.01 so no single term can annihilate a score.

The default weights encode a defensible priority order — *does this matter for PvP → does it unlock several things → is it close → how long → how much* — but they are **provisional priors, not tuned values**. See §16.3.

**This replaces the v0.1 formula**, which multiplied by raw `distance` and `time_estimate` and therefore ranked *further away and slower* as *better* — "Train Magic 1→99" would have outranked "Train Magic 87→94" by construction.

## 9.5 Evaluation in log space

```
ln(score) = Σ  wᵢ · ln(fᵢ)
```

Mathematically identical, but each factor's contribution becomes an **additive term in shared units**. Persist these contributions in `RecommendationEntry.factors`; the "Reason" line in the UI is then generated by reading off the largest terms, rather than being separately authored prose that can drift from the actual ranking.

## 9.6 Scale constants τ and κ

**τ (effort scale) — default 10 hours.**

**κ (cost scale)** is derived from the player's `gp_sensitivity` preference rather than from an exact bank value. Since `cost_decay = exp(−gp/κ)` equals ≈0.37 at `gp = κ`, κ *is* the purchase size at which cost becomes a strong negative influence.

The UI never says "κ" or even "GP sensitivity". It asks:

> **How strongly should expensive upgrades be deprioritized?**

| UI option | Internal | κ |
|---|---|---|
| Strongly | `high` | 8M |
| Normally | `normal` | 20M |
| Barely | `low` | 50M |

Resulting `cost_decay` behaviour:

| Purchase | κ = 8M | κ = 20M | κ = 50M |
|---|---:|---:|---:|
| 2M | 0.78 | 0.90 | 0.96 |
| 10M | 0.29 | 0.61 | 0.82 |
| 25M | 0.04 | 0.29 | 0.61 |
| 50M | 0.01 (floor) | 0.08 | 0.37 |

Under *Strongly*, a 25M purchase is heavily discouraged; under *Barely* it stays viable when its PvP value is high.

**Validation constraints** on the tuning process:

```yaml
validation:
  kappa_gp:
    min: 1000000
    max: 250000000
    ordering:
      - high < normal
      - normal < low
```

κ is **not** inferred from observed bank contents, cash stack, owned PvP gear, or recent purchases. Bank value is not disposable progression budget — a player may own expensive gear they will not sell. An optional exact budget remains a future advanced setting (§19).

## 9.7 Scoring profile is content, not code

```yaml
# content/scoring/profile.yaml
scoring_profile:
  version: 1
  tuned_against_corpus: null        # provisional; not yet tuned
  tau_hours: 10
  kappa_gp: {high: 8000000, normal: 20000000, low: 50000000}
  observation_aged_days: 14         # when a positive observation stops counting as fresh (§6.9)
  weights:
    pvp_value: 1.0
    leverage: 0.8
    proximity: 0.6
    effort_decay: 0.7
    cost_decay: 0.5
  refresher:
    max_in_primary_list: 1
    breadth_bonus_per_extra_member: 0.03
    breadth_bonus_cap: 0.10
```

`RecommendationSnapshot.scoring_profile_version` records which profile produced a given ranking, so history remains interpretable across retunes.

## 9.8 Refresher candidates and grouping

Ungrouped refreshers produce technically accurate but useless coaching:

```
Refresh 4-way switches
Refresh overhead prayers
Refresh freeze logging
Refresh DDing
Refresh offensive prayers
```

**Milestones declare a `practice_group`.** When several members of a group are stale, the engine emits **one composite candidate**:

```
Refresh NH fundamentals

  Practice:
    • defensive overheads
    • 4-way switches
    • freeze-and-step-under

  Suggested session: 5 LMS matches
```

### Urgency

Normalized freshness urgency per milestone:

| Freshness | Urgency |
|---|---|
| `current` | 0.00 |
| `stale` (30–90d) | 0.40 → 0.70, linear in age |
| `very_stale` (>90d) | 0.70 → 1.00, linear to 270d, then clamped |

Group urgency takes the **maximum** member, plus a small breadth bonus that is itself capped before being added:

```
breadth_bonus = min(0.10, 0.03 × (member_count − 1))
group_urgency = min(1.00, max(member_urgency) + breadth_bonus)
```

The inner cap is what matters: without it a group of 20 stale milestones would saturate at 1.0 on breadth alone. With it, a 5-member group and a 20-member group both contribute at most +0.10, so urgency stays driven by *how stale the worst item is*, not by how many boxes are unticked. Several stale mechanics make a session more worthwhile; ten stale checkboxes must not overwhelm objective account progression.

### List policy

* **At most one refresher in the primary recommendation list.**
* A refresher may never be top-ranked *solely* because many milestones were grouped.
* Group size never multiplies `pvp_value`; the candidate inherits the **maximum** relevant capability value, never the sum.
* Remaining stale groups appear in a dedicated **Practice freshness** view, not the main list.

### Completion

Two explicit actions, because a single tap must not silently attest to five separate skills:

| Action | Effect |
|---|---|
| **Mark session complete** | Refreshes every milestone listed in that session |
| **Review individual skills** | Lets the user refresh a subset |

A RuneLite-derived LMS session refreshes all milestones whose `practiced_by` includes `lms` **without any prompt** — derived evidence needs no confirmation.

## 9.9 Anti-thrash (hysteresis)

The incumbent top recommendation is displaced only when:

* `challenger.score > 1.10 × incumbent.score`, or
* the incumbent becomes complete, or
* the incumbent becomes blocked.

The comparison is on **raw scores, not log scores.** A 10% margin in log space is a different
threshold from a 10% margin in raw space, and the raw form is the one that means "10% better".

The incumbent is read from the most recent `RecommendationSnapshot` **by the caller** and
passed into the engine. §16.1 requires `recommend()` to be pure over its arguments, so it
cannot fetch its own incumbent:

```python
def recommend(state, selection, content, profile, incumbent) -> list[Recommendation]
```

## 9.10 Output

```
Next Recommendation

  Train Magic  87 → 94
  Unlocks      Ice Barrage
  Advances     Ice Barrage NH, Deep Wilderness NH
  Estimate     ~4.5 hours  ·  ~1.8M gp    [medium — price from a 3-day-old trade]
  Priority     ★★★★★

  Why: high PvP value (+0.61) · unblocks 2 capabilities (+0.44) · close to target (+0.30)
```

---

# 10. Content Schema and Validation

## 10.1 Layout

```
content/
    capabilities/
    candidates/
    roadmaps/
    training_methods/
    milestones/
    refreshers/       # practice-group templates (§10.4)
    items/            # ids, price policy, fallback hints
    quests/           # id + name; the referents `quest:` leaves resolve against
    skills/           # id + name; the referents `skill:` leaves resolve against
    scoring/          # profile.yaml
```

`quests/`, `skills/` and `refreshers/` were added in v0.5.1 (A22). §10.7 requires referential
integrity for *"every referenced capability, quest, item, skill and milestone id"*, which is
unenforceable for two of those five without somewhere to declare them; and §10.4's refresher
templates are authored content that had no directory. Quests and skills are thin — an id and a
name — but they must be **content** rather than a table in code, because §10.8 names a quest as
exactly the thing that must never require a code change.

## 10.2 Requirement grammar

Requirements need boolean structure — *"Barrows gloves **or** rune gloves"*, *"Voidwaker **or** AGS"* — which v0.1's flat list could not express.

**Leaf types:** `skill`, `unlock`, `quest`, `item`, `milestone`, `capability`, `combat_level`, `quest_points`

**Combinators:** `all_of`, `any_of`, `not`, `at_least: {n, of: [...]}` — evaluated per §9.1.

```yaml
id: ice_barrage
name: Ice Barrage
requires:
  all_of:
    - skill: {magic: 94}
    - unlock: ancient_magicks
    - any_of:
        - item: mystic_robe_top
        - item: ahrims_robetop
grants: [ice_barrage_nh]
pvp_value: 0.95
recommended_readiness: medium
```

`recommended_readiness` (optional, default `medium`) sets the bar for `recommended_now` (§6.9). Advanced capabilities declare `high`.

> Note on YAML: a space after the colon is mandatory. `magic:94` parses as the *string* `"magic:94"`, not a mapping — the v0.1 example contained this error in two places, which is precisely the class of bug §10.7 exists to catch.

## 10.3 Execution milestones

```yaml
id: comfortable_4_way_switches
class: execution
kind: self_attested
practice_group: nh_fundamentals
practiced_by: [lms, nh_combat, wilderness_pvp]
```

```yaml
id: consistent_overhead_prayers
class: execution
kind: self_attested
practice_group: nh_fundamentals
practiced_by: [lms, nh_combat, wilderness_pvp, anti_pking]
```

```yaml
id: vengeance_timing
class: execution
kind: self_attested
practice_group: vengeance_fundamentals
practiced_by: [vengeance_pvp, wilderness_pvp]
```

## 10.4 Refresher candidates

Refreshers are generated from practice groups rather than authored one-per-milestone:

```yaml
id: refresh_nh_fundamentals
name: Refresh NH fundamentals
practice_group: nh_fundamentals
trigger:
  any_member_freshness_at_least: stale
suggested_session: "5 LMS matches"
suggested_session_hours: 0.5
advances: [deep_wildy_nh, ice_barrage_nh]
```

Once generated they are ordinary candidates — scored, ranked and displaced by the same rules — subject to the list policy in §9.8. This is how staleness influences behaviour *additively* (a new suggestion) rather than *subtractively* (a removed capability).

**`suggested_session_hours` is mandatory, and this is not a formality.** Being an ordinary
candidate means being scored by §9.4, which includes `effort_decay = exp(−hours/τ)`. A
refresher with no declared hours scores `effort_decay = 1.0` — a perfect effort score — which
would make every refresher maximally attractive and defeat the list policy §9.8 exists to
enforce. `suggested_session` is the human-readable form; `suggested_session_hours` is the one
the engine reads. `gp_cost` is `0` for refreshers, which is correct and needs no declaration.

## 10.5 Item metadata

```yaml
id: voidwaker
item_id: 27690
price_mode: live          # live | static
fallback_price_gp: 85000000
price_staleness_days: 7
```

## 10.6 Candidates

A candidate is *"an action the player could take that changes facts"* (§4). Candidates are the
only objects the recommendation engine ranks: capabilities define what *better* means, and
candidates are the moves available for getting there.

```yaml
id: train_magic_87_to_94
name: Train Magic 87 → 94
kind: skill_training            # skill_training | acquisition | quest | unlock | practice
advances:                       # capability id → marginal contribution ∈ [0,1]
  ice_barrage_nh: 1.00
  deep_wildy_nh: 0.70
requires:                       # optional gate — same grammar as §10.2
  all_of:
    - unlock: ancient_magicks
completion:                     # predicate over facts; satisfied ⇒ the candidate is done
  skill: {magic: 94}
grants_facts:                   # what becomes true on completion — drives `leverage`
  skill: {magic: 94}
```

`advances` and `grants_facts` are deliberately separate. `grants_facts` is objective: it states
what changes. `advances` is editorial: it states how much each capability cares. A candidate may
advance a capability it does not unlock — training Magic to 94 fully enables Ice Barrage NH
while only partly advancing Deep Wilderness NH.

### Factor derivations

Every factor in §9.4 derives from the fields above. **None is authored directly**, so no content
file can assert its own priority.

| Factor | Derivation |
|---|---|
| `pvp_value` | §9.3 — blend the capability map, then `max_c effective_weight(c) × advances(c)` |
| `leverage` | Count of capabilities whose `status` would become `unlocked` if `grants_facts` were applied, normalized by the largest such count across the current candidate set so the factor lands in `(0,1]` |
| `proximity` | Skill training: `1 − remaining_xp / span_xp`. Every other kind: the `unlock_fraction` (§6.9) of the `completion` predicate — the same machinery, and it generalizes to candidates with no numeric target |
| `readiness` | Gate `{0,1}` — `0` when `requires` evaluates `unsatisfied` |
| `completed` | `completion` evaluates `satisfied` |

Two consequences of three-valued evaluation (§9.1) apply here and are easy to get wrong:

* **A candidate whose `requires` evaluates `unknown` is not blocked.** It is unknown, and
  belongs with the capability unknowns — *"sync this"*, not *"do this"* (§15). Collapsing
  unknown into blocked is the D8 error one layer out.
* **A completed candidate never ranks** (§16.2). Completion is tested before scoring, not
  approximated by giving completed candidates a low score.

### Refreshers are candidates

Refreshers (§10.4) are synthesized from practice groups rather than authored, but once
generated they carry these same fields and are scored by the same function: `kind: practice`,
`advances` inherited from the group, `gp_cost: 0`, and hours from `suggested_session_hours`.

## 10.7 Validation

Every content file is parsed into **Pydantic v2 models**. A `make validate-content` target — run in CI and as a pre-commit hook — asserts:

* id uniqueness across the corpus
* referential integrity: every referenced capability, quest, item, skill and milestone id resolves
* every `grants` target is a declared capability
* every `practiced_by` entry is a declared practice domain (§7.6)
* every `practice_group` referenced by a refresher has ≥1 member with `class: execution`
* only `class: execution` milestones declare `practiced_by` or `practice_group`
* every item with `price_mode: live` has a numeric `item_id`
* every candidate `advances` target is a declared capability (§10.6)
* every candidate declares a non-empty `completion` predicate — a candidate that can never be
  complete would rank forever
* every refresher declares `suggested_session_hours` (§10.4)
* the capability and requirement graphs are acyclic
* weights, `pvp_value`, `advances` weights and roadmap capability weights lie in `[0,1]`
* κ presets satisfy the §9.6 min/max/ordering constraints

Unvalidated YAML fails at runtime with an unhelpful `KeyError`, typically months later.

## 10.8 The "no logic in code" principle, stated precisely

v0.1 said *"No Python if-statements. Everything comes from YAML."* Taken literally this is false — something evaluates the requirement tree, and that evaluator is Python with branches.

The actual, defensible boundary:

> **No game content lives in code.** The engine knows about requirement *types*, practice *domains*, and factor *names*. Adding new game content — a quest, an item, a capability, a roadmap, a milestone, a scoring profile — never requires a code change. Adding a new requirement type or practice domain does.

---

# 11. Security and Network Exposure

v0.1 stated both "localhost only" and "accessible from a phone via Tailscale". These are incompatible: Tailscale reachability requires binding beyond loopback, at which point **any device on the tailnet can POST to `/api/sync`** and rewrite account state. "No public exposure" is a deployment property, not an access control.

The seven rules below are cited elsewhere in this document as §11.1 – §11.7.

1. **Bind address is explicit configuration** — the loopback address or the Tailscale interface address. Never `0.0.0.0`.
2. **All `/api/*` requests require a bearer token**, a shared secret stored in app config and in the RuneLite plugin's settings. Enforced regardless of source address. Authentication attaches at the **router** level, not per endpoint, so a future `/api/*` route inherits it by construction rather than by the author remembering.
3. **Reject unauthenticated writes** with 401 and record a `SyncEvent` (`player_id = NULL`, §6.11).
4. **Tailscale ACLs** restrict which devices may reach the port, as defense in depth — not as the primary control.
5. No inbound port forwarding, ever. There is no public deployment story.
6. **Outbound requests carry only what the provider needs**: a username for WOM, item ids for prices. Practice events never leave the machine.
7. **The health endpoint lives at `GET /healthz`, outside the `/api` prefix**, and is unauthenticated. Rule 2 is absolute, so a liveness check cannot live under `/api` without either weakening the rule or making the check useless. Moving it out keeps rule 2 unqualified.

---

# 12. Synchronization and the Payload Contract

```
RuneLite launches
    ↓
Plugin POSTs snapshot + practice_events to /api/sync (token, payload_version)
    ↓
Server validates against JSON Schema; records SyncEvent
    ↓
Facts merged under precedence rules (§7.4)
    ↓
Freshness service maps PracticeEvents onto milestones (§7.6)
    ↓
Prices refreshed for referenced items, if TTL expired (§8.3)
    ↓
Progression engine recomputes CapabilityState (status → readiness → recommended_now)
    ↓
Recommendation engine runs; snapshot persisted
    ↓
Dashboard refreshes over websocket
```

## 12.1 Cross-language contract

The plugin is Java; the app is Python. The payload schema is the seam, and it needs a single owner:

```
contracts/sync_payload.schema.json     # JSON Schema, source of truth
```

Python validates incoming payloads against it. The Java plugin is written to match it. Both sides reference the same file. The schema constrains `practice_events` to the summarized shape of §7.6 — the collection boundary is enforced by the contract, not by convention.

**The schema is provisional until a real RuneLite snapshot has validated against it** (D12).
It carries `"x-status": "provisional"` until then. Quest identity, the varbit-to-unlock-key
mapping, diary and combat-achievement representation, and whether a *complete* bank scan is
even detectable are all facts about the RuneLite API that cannot be settled from the app side.
Writing the schema first and discovering those from the plugin second is the correct order;
declaring it frozen before the discovery is not. Once reconciled, the marker is removed and
further changes require a `payload_version` bump under §12.2.

## 12.2 Versioning

Payloads carry an integer `payload_version`. The server declares the set it understands:

```python
SUPPORTED_PAYLOAD_VERSIONS = {1}
```

and **rejects anything outside that set with 409**, recording the `SyncEvent`, rather than
silently parsing a subset of fields. Plugin and app *will* drift; the failure should be loud
and diagnosable.

An explicit set rather than a minimum, because compatibility is not always an interval — a
server may support versions 1 and 3 while 2 was withdrawn. It is also why the field is a plain
integer and this document no longer speaks of "major" versions: an integer has no major
component, and the earlier phrasing implied a semantic-versioning scheme that does not exist
here.

---

# 13. Plugin Distribution

**Side-loading is the only supported distribution path for v1.** Plugin Hub submission is a future distribution decision, triggered by external adoption — it is not an architectural requirement and must not appear on the critical path.

Side-loading buys fast iteration, no review latency, freedom to evolve the payload contract aggressively, and no obligation to support unknown environments. Given that the plugin and app are tightly coupled through §12's schema and early development will churn it, that freedom is worth more than distribution reach.

## 13.1 Distribution maturity ladder

| Stage | Audience | Mechanics |
|---|---|---|
| **1 — Personal** *(v1)* | Just the author | Local source checkout · Gradle build · side-loaded plugin · manually matched app/plugin versions |
| **2 — Trusted few** | A handful of known users | GitHub releases · prebuilt plugin artifact · versioned app release · compatibility matrix · install guide |
| **3 — Public** | Plugin Hub | Only after the gate below |

Stage 3 is considered only once **all** of the following hold: the sync payload has stabilized; configuration is user-friendly; the shared secret is stored safely; error handling is comprehensible to a stranger; the plugin collects nothing it does not need; the app has a supportable release process; several external users have side-loaded it successfully; and the author is willing to track RuneLite API changes indefinitely.

## 13.2 Distribution is not an architectural concern

The plugin exposes a narrow seam:

```java
interface TrackerSyncClient {
    void submit(AccountSnapshot snapshot);
}
```

How the plugin is *distributed* must not influence snapshot construction, JSON serialization, authentication, versioning, or app-side ingestion. If a future Plugin Hub submission requires changes to any of those, that is a signal the boundary has eroded.

---

# 14. Repository Layout

```
osrs-tracker/
    tracker/                # Python application
        domain/             # Tri, Status, PlayerState — the engine's input types (§16.1)
        ui/
        api/
        db/                 # models, session, PlayerState projection
        migrations/         # Alembic
        sync/
        progression/        # three-valued evaluation, capability status
        freshness/          # PracticeEvent → milestone mapping
        recommendations/    # scoring, roadmap blending, refresher grouping, hysteresis
        estimation/         # time and GP estimates
        integrations/
            wise_old_man/
            hiscores/
            prices/
        content/            # loader + Pydantic schemas
        config/
    plugin/                 # RuneLite companion plugin (Java)
    contracts/
        sync_payload.schema.json
    content/                # YAML game content (§10.1)
    tools/                  # weight tuning (§16.3) and other dev utilities
    tests/
        golden/             # fixture states → ranking judgments
        contracts/          # cross-language payload fixtures (§12.1)
    docs/
```

`tracker/domain/` exists because §16.1 requires the engine to be a pure function over a state
object. Those types are shared by the database projection, the engine and the UI, and belong
to none of them.

## 14.1 Technology stack

| Concern | Choice | Rationale |
|---|---|---|
| UI | NiceGUI | Python, mobile-friendly, websocket updates, built-in routing, trivial deployment |
| Backend | Python 3.12+ | 3.13 preferred but not required. Nothing in the design depends on a 3.13-only feature; the real floor is Pydantic v2 and modern typing syntax. Pinning a version the development machine does not have buys nothing and blocks the first commit. |
| Database | SQLite | Local, tiny, zero configuration |
| ORM / migrations | SQLAlchemy + Alembic | |
| Validation | Pydantic v2 | Content schemas and API payloads |
| Charts | Plotly | |
| Config | YAML | |
| HTTP | httpx | |
| Plugin | Java (RuneLite API), Gradle | |

---

# 15. UI

## Dashboard
Character summary · overall readiness · roadmap progress · top recommendation with generated reason · current goal · quick actions.

## Capabilities
The headline view — *"what can I actually do today?"* Each capability shows all three layers of §4.4 as **distinct** fields: `status`, `readiness_confidence` with warnings, and `recommended_now` with its reason. Blockers ("do this") and unknowns ("sync this") are separate lists with separate calls to action.

## Roadmaps
Primary roadmap selector plus optional secondaries. Selection weights hidden behind advanced settings; defaults `1.00` primary / `0.25` secondary.

## Recommendations
Sortable ranked list with per-item factor breakdown, estimate, and a confidence marker for anything below `high`. Blocked candidates in a separate collapsed section. **At most one refresher** appears here (§9.8).

## Practice freshness
Dedicated view for all stale practice groups, with **Mark session complete** and **Review individual skills** actions. This is where refreshers beyond the first live, so freshness never crowds out objective progression.

## Skills
Progress bars. Unranked skills render as unranked, not as level 1.

## Unlocks
Cards, four states:

| State | Rendering |
|---|---|
| Unlocked | green |
| Available | yellow |
| Locked | gray |
| **Unknown** | **outlined / hatched** |

Unknown must never render as locked. It means "sync RuneLite", not "go do this." The same rule applies to capability `status: unknown`.

## Settings
GP sensitivity as *"How strongly should expensive upgrades be deprioritized?"* — Strongly / Normally / Barely. Price provider attribution footer (§7.5).

## History
XP charts · roadmap progress over time · recommendation history, including *why* the top recommendation changed and under which `scoring_profile_version`.

## Mobile
Reached over Tailscale (§11). Responsive, phone-first layout.

---

# 16. Testing and Weight Tuning

## 16.1 Golden corpus — judgments, not exact orderings

`tests/golden/` holds fixture account states paired with **ranking judgments**. Asserting a full exact ordering is brittle: two near-tied candidates flip on noise and the test fails for no meaningful reason.

```yaml
scenario:
  player_state: ...
  roadmap_selection: {main_nh: 1.0}

expectations:
  must_rank_above:
    - [complete_desert_treasure_i, train_woodcutting]
    - [train_magic_87_to_94, buy_voidwaker]
  top_3_contains:
    - train_magic_87_to_94
    - unlock_rigour
  must_not_be_top:
    - buy_high_risk_gear
```

This constrains the engine's design: **the entry point must be a pure function** over a state object —

```python
def recommend(
    state: PlayerState,
    selection: RoadmapSelection,
    content: Content,
    profile: ScoringProfile,
    incumbent: RecommendationSnapshot | None,
) -> list[Recommendation]
```

— not something that reads the database internally. Database access belongs to the caller.

`incumbent` is a parameter for exactly this reason. Hysteresis (§9.9) needs the previous
ranking, and letting the engine fetch it would reintroduce the database dependency this
signature exists to remove.

## 16.2 Three test types

**Invariant tests** — must always hold, regardless of tuning:

* A blocked candidate never appears in the actionable list.
* A completed candidate never ranks.
* Of two otherwise identical candidates, the more expensive one does not outrank the cheaper.
* Of two otherwise identical candidates, the closer one ranks higher.
* Increasing a roadmap capability's weight never *lowers* a candidate that exclusively advances it.
* **No more than one refresher appears in the primary list.**
* **A refresher never outranks every progression candidate purely on group size.**
* **`achieved` never transitions true → false from the passage of time alone.**
* **Absent WOM evidence never advances a milestone's freshness state.**
* **An `unknown` leaf never produces `status: unlocked`.**
* **`unlock: available` and `quest: in_progress` never evaluate `satisfied`.**
* **A candidate whose gate is `unknown` is never reported as blocked.**

The last three follow from §9.1 but are listed explicitly because each has a plausible-looking
wrong implementation that passes every other test in this document.

Note that two of these invariants cannot be tested against `recommend()`: `achieved` is never
mutated by a pure function, and WOM is not visible to one. They belong to the freshness service
and the WOM adapter respectively (§16.4).

**Pairwise judgment tests** — expert preferences between specific candidates:

* DT1 outranks buying a Voidwaker while Ancients are still locked.
* 94 Magic outranks 99 Strength when the target capability requires Barrage.
* Rigour does not outrank Protect Item for an account below 25 Prayer, when Protect Item gates initial Wilderness practice.

**Stability tests** — small input changes must not cause large reorderings:

* +10,000 Magic XP does not replace the top recommendation unless a threshold is crossed.
* A 2% item price movement does not move a candidate from rank 8 to rank 1.
* A milestone crossing 30 days does not reorder the primary progression list.

## 16.3 Tuning method

Weights are **not** optimized against exact expected ranks. Procedure:

1. Build ~20 realistic scenarios.
2. Record pairwise expert preferences for each.
3. Run a small grid or Bayesian search over weights, τ and κ, subject to the §9.6 constraints.
4. Maximize pairwise-agreement rate.
5. Review every disagreement manually — a disagreement is as likely to reveal a bad judgment as a bad weight.
6. Round the result to humanly interpretable values.
7. Persist to `content/scoring/profile.yaml`, incrementing `version` and setting `tuned_against_corpus`.

## 16.4 Other layers

| Layer | Approach |
|---|---|
| Content corpus | `make validate-content` (§10.7), run in CI |
| Three-valued evaluator | Truth-table tests for every combinator, including unknown propagation and short-circuit ordering (§9.1) |
| Leaf resolution | One test per row of §9.1's table — especially `unlock: available` and `quest: in_progress` resolving to `unsatisfied` |
| Capability layering | Tests asserting freshness never alters `status`, and unknowns never reach `readiness_confidence` |
| `unlock_fraction` | Mixed case — 1 satisfied / 1 unsatisfied / 1 unknown must report `0.33`, not `0.50` (§6.9) |
| Candidate factors | `pvp_value` takes the maximum, never the sum; an unknown gate does not mark a candidate blocked (§10.6) |
| Merge/precedence | Unit tests for stale-source-must-not-regress (§7.4) |
| Freshness service | `achieved` is never written. **Owns §16.2's "`achieved` never transitions true → false"** — the recommendation engine is pure and cannot test it |
| WOM adapter | A score plateau or decrease emits nothing. **Owns §16.2's "absent WOM evidence never advances freshness"** |
| Practice proxies | Tests per accepted signal; explicit negative tests for every rejected signal in §7.6 |
| Combat threshold | Tests that one attack or <10s does not refresh |
| Roadmap blending | Convex-combination bounds and no double-counting (§9.3) |
| Refresher grouping | Urgency = max + capped bonus, never sum |
| Hysteresis | Boundary test at exactly `1.10 ×` — displacement requires strictly more (§9.9) |
| Price resolution | Each fallback layer; confidence from trade age, not fetch age |
| Estimation | Unit tests over synthetic method tables |
| Sync API | Schema validation, auth rejection, version-mismatch 409, payload rejects unsummarized telemetry |
| Migrations | Alembic upgrade/downgrade round-trip on a seeded database |

---

# 17. Future Features

* Multiple characters in the UI (schema already supports it — §6.1)
* Collection Log integration
* Bank progression and gear planner
* Money-making recommendations, feeding `cost_decay` with real income rates
* Quest routing
* Inventory planner
* LMS analytics
* Fight journal, replay analysis, video review integration

---

# 18. Decision Log

### D1 — Self-attested milestone decay
> Self-attested milestones do not expire. Execution milestones carry freshness metadata and may become stale. Staleness generates refreshers or reduces readiness confidence, but **never** sets a milestone unachieved.

*Rationale:* automatic reversion would cause recommendations to move backward after a break. §6.6, §6.9, §9.8.

### D2 — Item price source
> Live prices for relevant items, cached with a configurable TTL, with a static fallback hint per item. Price provenance and age contribute to estimate confidence. Only items referenced by the active roadmap and candidate set are fetched.

*Rationale:* GP cost is a ranking factor, so stale prices reorder output; scoped fetching avoids the "item database" non-goal. §6.8, §7.5, §8.3, §8.4.

### D3 — Multi-roadmap scoring
> Multiple active roadmaps merge into one normalized effective capability-weight map. The maximum across roadmaps is **not** used.

*Rationale:* a max rule lets each candidate be interpreted under whichever roadmap flatters it most, rendering selection weights meaningless. Convex combination also eliminates double-counting as a side effect. §4.3, §9.3.

### D4 — Default scoring weights
> Retain the current weights as provisional v1 defaults. Tune weights, τ and κ against a golden corpus using invariant, pairwise-ranking and stability tests. Optimize for pairwise agreement, not exact ordering.

*Rationale:* no principled way to solve for weights before realistic scenarios exist. The design owes a definition of tuning success, not the answer. §9.4, §9.6, §9.7, §16.

### D5 — Plugin distribution
> Side-loading is the only supported path for v1. Plugin Hub submission is triggered by external adoption and a stable sync contract; it is not an architectural requirement.

*Rationale:* review latency would tax exactly the iteration early development needs most. §13.

### D6 — Derived practice proxies
> Practice proxies refresh `last_practiced_at` only from affirmative evidence of relevant PvP participation. RuneLite-observed LMS matches and sustained Wilderness player combat are high-confidence; positive WOM LMS progression is a medium-confidence fallback. Proxies never set a milestone achieved and never infer mastery from equipment, prayer changes, Wilderness presence, or login activity. The plugin emits summarized `PracticeEvent` records and collects no opponent identities or detailed combat telemetry.

*Rationale:* keeps manual entry near zero without letting participation masquerade as competence. §6.7, §7.6, §12.1.

### D7 — κ presets
> Retain κ = 8M / 20M / 50M as provisional v1 values. Present them as "strongly / normally / barely deprioritize expensive upgrades" rather than exposing κ terminology. Tune with the scoring weights against the golden corpus. Do not infer spending tolerance from bank value or cash holdings.

*Rationale:* bank value is not disposable budget, and a three-way preference is more useful and far less annoying than asking for a number. §9.6.

### D8 — Post-v1 staleness semantics
> Execution-milestone staleness never becomes a hard blocker, including for advanced capabilities. Capability state represents objective requirement satisfaction; readiness confidence represents freshness of execution evidence. Advanced capabilities may declare a recommended readiness threshold, allowing the app to discourage immediate use and recommend refreshers without revoking progress. **Objective unknowns produce an unknown capability state rather than an unlocked capability with low confidence.**

*Rationale:* hard-blocking would undo the `status`/`readiness` separation the design deliberately introduced. The unknown-vs-stale refinement removes a real logical inconsistency: *"Unlocked: yes / Confidence: low because ownership is unknown"* was never coherent. Implemented as the `unlocked: bool` → `status: unlocked | locked | unknown` schema change, propagated through three-valued evaluation. §4.4, §6.9, §9.1, §9.2.

### D9 — Refresher candidate volume
> Refreshers are grouped by practice domain. At most one appears in the primary recommendation list; additional stale domains appear in a separate practice-freshness view. Grouped refresher value uses the highest member value plus a small capped breadth bonus, never the sum.

*Rationale:* five separate "refresh X" entries are accurate but poor coaching, and unbounded grouping would let stale checkboxes crowd out objective progression. §9.8, §10.4.

### D10 — Price-feed attribution
> Use the OSRS Wiki real-time prices API. Every request carries a configurable descriptive User-Agent identifying application, version, purpose and an optional public contact. No fixed numeric rate limit is published, but clients must avoid disruptive volume. The app uses a 12-hour cache, exponential backoff, `Retry-After`, and static fallback values. **Price confidence is based on the underlying trade timestamp as well as cache age.** Acquisition recommendations prefer the latest credible high price.

*Rationale:* `fetched_at` alone cannot distinguish a fresh retrieval of stale market data — the same class of error as `ContainerScan`. §6.8, §7.5, §8.3, §8.4.

### D11 — Candidate schema and factor derivation
> Candidates are authored with `kind`, `advances`, `requires`, `completion` and `grants_facts`. Every scoring factor is **derived** from those fields; none is authored directly. `pvp_value` blends the capability map first and then takes the **maximum** over `advances`, never the sum. `proximity` generalizes beyond skill training as the `unlock_fraction` of the `completion` predicate. A candidate whose gate evaluates `unknown` is unknown, not blocked.

*Rationale:* through v0.4 the `Candidate` was named as one of the four core nouns (§4), given a content directory (§10.1) and used by every term in the scoring function (§9.4) — but never defined. The gap was invisible because each individual section read as complete; only assembling an implementation order exposed that nothing could populate the type. Two sub-decisions were forced by the omission. Order of operations: blending the capability map before taking the maximum, versus taking a maximum per roadmap and blending after, gives different answers for multi-capability candidates because `max` and convex combination do not commute — the blend-first form is the one consistent with §9.3's worked table. Maximum over sum: summation would let a candidate advancing four capabilities weakly outrank one advancing a single capability strongly, making breadth a substitute for relevance — the same failure D9 rejected for refresher groups. Forbidding authored factors keeps §10.8's boundary intact: content declares *what a thing is*, never *how important the engine should consider it*. §9.3, §9.4, §10.6.

### D12 — Sync contract freeze point
> `contracts/sync_payload.schema.json` is written before the plugin, but marked provisional and **not frozen until a real RuneLite snapshot has validated against it**. Reconciliation happens once, early, before plugin implementation proper. After that, changes require a `payload_version` bump.

*Rationale:* the schema is the Java↔Python seam and needs a single owner, so it must be written first. But quest identity, the varbit-to-unlock-key mapping, diary and combat-achievement shape, and whether a *complete* bank scan is detectable at all are facts about the RuneLite API that cannot be settled from the app side — they would be guessed, and the guesses would be wrong. Declaring the contract frozen before that discovery would also contradict D5's own reasoning: side-loading was chosen precisely for the "freedom to evolve the payload contract aggressively" because "early development will churn it". A short reconciliation step converts that churn from an ongoing tax into a single scheduled event. §12.1, §12.2, §13.

---

# 19. Deferred Decisions

Consciously postponed, with the trigger that would reopen each. None blocks implementation.

| Deferred | Reopens when |
|---|---|
| Budget-derived κ (`κ = max(floor, budget × multiplier)`) | Disposable budget — not bank value — can be established reliably; likely an optional advanced setting |
| Exact GP budget entry | A user asks for finer control than the three-way preference |
| Plugin Hub submission | The §13.1 stage-3 gate is met |
| Direct hiscores integration | WOM proves unreliable in practice |
| Additional practice domains beyond the six in §7.6 | A milestone needs evidence none of the six can supply |

---

# 20. Specification Gap Closure Log

Twenty-one gaps (A1–A21) were found in v0.4 by walking the document section-by-section against
a proposed implementation order — the first time it was read as something to *execute* rather
than to *agree with*. A22 was found in v0.5 by implementing §10.7. Each is closed above; this
table exists so a reader of an earlier version can find where each change landed.

The gaps cluster into four kinds, and the pattern is worth noting for future revisions:

* **Named but never defined** (A1) — the largest single gap. `Candidate` had a role in four
  sections and a definition in none.
* **Defined for the common case only** (A3–A7, A10, A11) — rules that read as complete because
  the awkward third value, the missing threshold, or the undefined term never came up in the
  worked example.
* **Contract with no sink** (A12, A13, A17, A19) — a field specified on one side of a boundary
  with nothing on the other side to receive it.
* **Rule without a referent** (A20, A22) — a constraint stated over a set the document never
  provides a place to populate. Both were found by writing the thing that had to satisfy the
  rule, which is the only reliable way to find this kind.

| # | Gap in v0.4 | Closed in |
|---|---|---|
| A1 | `Candidate` had no schema despite being a core noun with a content directory | §10.6, D11 |
| A2 | `pvp_value` derivation undefined for multi-capability candidates; §9.3's formula and worked table implied different orders of operation | §9.3, §10.6, D11 |
| A3 | `unlock_fraction` denominator unspecified | §6.9, §9.1 |
| A4 | `readiness_confidence: medium` depended on an undefined threshold and an undefined term ("contributing", "aged") | §6.9, §9.7 |
| A5 | `unlock: available` and `quest: in_progress` had no evaluation rule | §6.3, §9.1 |
| A6 | `combat_level` and `quest_points` leaves had no `unknown` rule | §9.1 |
| A7 | The `milestone` leaf's `unknown` condition was unrepresentable — `achieved: bool` cannot distinguish "declined" from "never asked" | §4.5, §6.6, §9.1 |
| A8 | Refreshers had no hours, so `effort_decay` scored them perfectly and would have defeated §9.8's list policy | §10.4 |
| A9 | `recommended_now` compared `high\|medium\|low` with `>=` but no ordering was defined | §6.9 |
| A10 | `recommended_now_reason` had no generation rule | §6.9 |
| A11 | `warnings` had no content specification | §6.9 |
| A12 | Spellbook, diaries and combat achievements were plugin-provided with no table and no leaf type | §6.3, §7.1 |
| A13 | Active roadmap selection had no persistence | §6.12 |
| A14 | "Rejects unknown **major** versions" — `payload_version` is an integer and has no major component | §12.2 |
| A15 | Hysteresis "10% higher" was ambiguous between raw and log score, which differ | §9.9 |
| A16 | §11 rule 2 requires a token on all `/api/*`, which would break a liveness check | §11 |
| A17 | §11.3 requires a `SyncEvent` for unauthenticated writes, but §6.11's `player_id` was not nullable | §6.11 |
| A18 | `Milestone.freshness` was described as materialized but was not a column | §6.6 |
| A19 | `ItemPrice.selected_*` columns had no specified writer | §6.8 |
| A20 | §14's layout omitted the shared domain types and a tools directory | §14 |
| A21 | Python 3.13 pinned without need | §14.1 |
| A22 | §10.7 requires referential integrity for quest and skill ids, but §10.1 gave neither a content directory to be declared in; §10.4's refresher templates likewise had no directory | §10.1 |
