# OSRS Account Companion architecture

## Product boundary

The application owns observed account facts and deterministic evaluation. ChatGPT uses
those facts to help a player decide what to do. The server does not rank all possible
actions or assign a universal utility score.

```text
RuneLite / imported account observations
                 |
          AccountSnapshot
                 |
    deterministic domain services
       Quest Cape       Gear
                 |
        MCP and factual dashboard
                 |
              ChatGPT
```

`AccountSnapshot` is the shared account-state boundary. It records when facts were
observed, including distinct bank, inventory, and equipment scan times. An item called
"unowned" was not seen in the latest accepted scans; a later acquisition remains
possible. Missing observations and stale observations must not become confident current
claims.

## Surviving domains

- **Account:** authenticated RuneLite synchronization, imported skill state, quests,
  unlocks, item sightings and container scans, sync audit, and cached raw price facts.
- **Quest Cape:** catalog and requirement checks, goal status, available actions, and
  read-only hypothetical quest or skill action evaluation.
- **Gear:** account-aware equipment optimization, factual candidate filtering, item
  details, ownership and requirement reporting, and price resolution with provenance.
  Existing curated progression and hypothetical item-change operations remain
  compatibility adapters; an item-change result does not establish joint loadout validity.

The private MCP sidecar exposes `get_account_summary`, `get_goal_status`,
`get_available_actions`, `evaluate_action`, `get_gear_progression`,
`get_gear_candidates`, `get_item_details`, `evaluate_gear_change`, and `optimize_gear`
at exact `/mcp`.
The dashboard presents account, sync, goal, Gear, skill, unlock, and settings facts. Its
Gear view uses `GearService`, the same domain service as MCP. The RuneLite sync API
reports synchronization results, not recommendation counts.

## Deliberate limits

ChatGPT decides which available action or upgrade makes sense for a player's goals.
The server does not choose a universally best action, keep recommendation rankings,
score every goal or gear option, implement a generic goal DSL, or duplicate conversational
planning. The current authored goal is Quest Cape; additional goals require separate
product work.

Hypothetical operations never write an account snapshot. Missing price, requirement,
ownership, or compatibility information stays explicit. `player.gp_sensitivity` is a
stored historical preference; current Account, Quest Cape, Gear, and price operations do
not apply it.

## Operations and compatibility

### Equipment optimizer

Deployment intent: gear optimization runs on the development computer, not on the
resource-constrained Raspberry Pi. The Pi remains the authoritative source of account
observations and cached prices for desktop Gear, as described in
[Desktop Gear using live Pi data](DEPLOYMENT.md#desktop-gear-using-live-pi-data).

`tracker.gear` owns one deterministic calculation boundary shared by the dashboard
and MCP. The optimizer consumes a frozen account snapshot, reviewed equipment metadata,
cached price observations, explicit role/target constraints, and evaluation time. It
does not fetch prices, persist recommendations, or change synchronized account facts.
Hypothetical skills, quests and acquisition assumptions apply only to that request.

Eligibility, observed ownership, usable physical form and purchasability are separate
facts. Existing shared requirement evaluation remains authoritative. Ownership aliases
do not establish equivalent bonuses, charges or readiness. Unknown prices are not zero,
and sightings from different container times are not independent copies of an item.

The offensive objective is a declared weighted active-time DPS proxy, not a universal
gear score or predicted encounter completion time. Combat results expose intermediate
rolls and supported-mechanic limitations. Unimplemented effects and target mechanics
block numeric ranking rather than silently contributing zero or being ignored.

Joint search constrains explicit directed transitions. A swap limit counts equipment
actions: equipping an item costs one, explicit unequipping costs one, and automatic
hand-slot removal adds no action. Changed slots and carried equipment are reported
separately. Every returned action sequence must respect the 28-slot inventory and
reserved supplies. Buying one item reused across roles is one purchase.

Bounded search returns the best solution found under the supported model. Candidate
truncation, search limits and infeasibility scope must remain visible; beam exhaustion
does not prove no solution exists. Curve points share frozen non-swap assumptions and
reuse incumbents, with normalization against the corresponding unrestricted baseline.
Computed results are ephemeral and CPU work runs outside the UI event loop.

### Encounter templates and validation boundary

`tracker.gear.encounters` contains two versioned conveniences that convert to ordinary
custom requests: an illustrative Dagannoth Kings cycle and a Zulrah form comparison.
They introduce no encounter framework, measured phase durations, or new account state.
Their target statistics are pinned to Wiki calculator revision
`89c3e25b344aea90d0189746e4b5f73dde0f0383`. The Zulrah form order is explicitly **not**
a published rotation; equal role weights are user-editable modeling assumptions.

The supported subset includes matching standard-spell elemental weakness: earth 35%
for the Kings and fire 50% for Zulrah. Accuracy and maximum-hit adjustments use explicit
integer rounding, checked against independent intermediate calculations. Zulrah attacks
whose modeled maximum hit exceeds 50 remain unsupported: its above-cap damage reroll
distribution is not approximated. Individual unsupported equipment still blocks scoring.
Target defence bonuses use a dedicated model, not equipment attack/defence fields.
Respawns, movement, survival, Jad phases, venom, snakelings and supply endurance remain
outside these templates. Do not market them as full boss simulation.

Compatibility tool retirement is separate from the dashboard replacement. Preserve
existing factual MCP meanings during migration; remove ladder-only operations only
with replacement parity, a documented contract change, and matching MCP instructions,
readiness and container-smoke updates. Historical database migrations stay intact.

The app accepts version 1 RuneLite sync payloads. Its optional `practice_events` field
remains schema-validated for deployed clients, but ingestion ignores it; new plugin
builds omit it. This boundary shim can be removed when v1 support ends. No practice
domain, view, or persistence is required by current services.

The app and MCP sidecar have separate listeners. The MCP listener exposes only exact
`/mcp`, uses a configured player, and has no dashboard or sync route. Local MCP tests,
an existing tunnel connection, and a live ChatGPT conversation are separate acceptance
checks. See [deployment](DEPLOYMENT.md) for launch and backup procedures.
