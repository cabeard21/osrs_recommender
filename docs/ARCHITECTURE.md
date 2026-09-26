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
- **Gear:** curated progression ladders, factual candidate filtering, item details,
  ownership and requirement reporting, on-demand price resolution with provenance, and
  read-only hypothetical gear changes. A gear-change result does not establish joint
  loadout validity unless that was actually evaluated.

The private MCP sidecar exposes `get_account_summary`, `get_goal_status`,
`get_available_actions`, `evaluate_action`, `get_gear_progression`,
`get_gear_candidates`, `get_item_details`, and `evaluate_gear_change` at exact `/mcp`.
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

The app accepts version 1 RuneLite sync payloads. Its optional `practice_events` field
remains schema-validated for deployed clients, but ingestion ignores it; new plugin
builds omit it. This boundary shim can be removed when v1 support ends. No practice
domain, view, or persistence is required by current services.

The app and MCP sidecar have separate listeners. The MCP listener exposes only exact
`/mcp`, uses a configured player, and has no dashboard or sync route. Local MCP tests,
an existing tunnel connection, and a live ChatGPT conversation are separate acceptance
checks. See [deployment](DEPLOYMENT.md) for launch and backup procedures.
