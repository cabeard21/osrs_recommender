# Milestone 3 legacy dependency inventory

This is the pre-deletion inventory for the Account Companion retirement. `KEEP` means a
current factual Account, Quest Cape, Gear, sync, or observability contract uses it.
`MIGRATE` means the factual part must move off a legacy dependency before deletion.
`DELETE` means its remaining purpose is the retired recommendation product. Existing
Alembic revisions remain as historical migration records; a new forward revision removes
obsolete schema only after runtime consumers are gone.

| Area | KEEP | MIGRATE | DELETE |
| --- | --- | --- | --- |
| Account and goals | `tracker/accounts/*`, `tracker/quest_cape/*`, `content/quest_cape/catalog.json`, skill/quest/item requirements and observed account facts | Move the four three-valued helpers used by `accounts/requirements.py` out of `progression/tri.py` | Progression capability engine and evaluator after old UI consumers leave |
| Gear and prices | `GearService`, authored ladders, `DatabaseGearPrices`, raw cached market prices, `resolve_price` and its provenance output | Dashboard `/gear` from `gear.setup`/`PlayerState` to the same `GearService` calls as MCP; price refresh from roadmap scope to authored tradeable Gear IDs | Old gear setup projection, roadmap price scope, persisted selected-price writes |
| Recommendation domain | Factual skill, ownership, account-mode, and price types; `GpSensitivity` stored user preference | Narrow `domain/types.py` and `Content` to factual records | `tracker/recommendations/*`, candidate/consequence/ranking types, estimator and tuning behavior used only by recommendation generation |
| Sync and app | RuneLite validation and merge, WOM import, single-flight price refresh, account audit, HTTP 202, app/MCP startup | Replace `sync/pipeline.py` recommendation run with factual merge and price refresh; remove scoring-profile dependency at both startups | Capability recomputation, recommendation writes/history, guidance and in-app advisor construction |
| Persistence | Player, skill snapshots, unlocks, quest state, item sightings, container scans, raw item prices, sync events, database infrastructure | Split raw price cache writes from derived selected-price writes; replace old `PlayerState` projection consumers | Recommendation snapshots/entries, capability states, active roadmap, guidance notes, advisor messages/conversations, practice events and milestones, and exclusive queries/serialization |
| Dashboard and commands | Factual account, sync, skills, unlocks, settings, and Gear visibility; migration/validation and current MCP launch commands | Root/goal and `/gear` presentation from factual services; keep `gp_sensitivity` editable with a no-current-effect label | Recommendation, advisor, capabilities, roadmap, practice, and recommendation-history views; tuner/candidate-generation commands |
| MCP | The eight Account, Quest Cape, and Gear tools, exact `/mcp` route, read-only hypothetical evaluations | Sidecar content loading without scoring profile | No current tool handler uses weighted recommendation classes; remove indirect startup loading of scoring content |
| Content and tests | Factual items, skills, quests and Quest Cape catalog; focused Account/Quest/Gear/sync/MCP/interface/migration tests | Narrow content loader, validator, and fixtures; retain one v1 `practice_events` boundary test | Scoring profile; candidate, capability, roadmap, refresher, practice, and training-method corpora; golden scenarios/loader and exclusive ranking/tuning/roadmap/PvP tests |
| Documentation | Current account, goal, gear, sync, MCP, and deployment contracts | Rewrite README/architecture/content/runbook descriptions around factual services | Current-tense descriptions of deleted scoring, golden corpus, roadmap, practice, and in-app advisor behavior |

## Sensitive field classification before migration

`player.gp_sensitivity` is **KEEP**. Before retirement, the scorer used it; settings and
the old `PlayerState` projection read it. `GearService`, `DatabaseGearPrices`, `AccountService`,
`QuestCapeService`, and the MCP handlers do not read it. It remains stored and editable
as a user preference, with clear UI wording that current factual tools do not use it.

The `item_price` columns `item_id`, `high_price_gp`, `high_trade_at`, `low_price_gp`,
`low_trade_at`, `provider`, `fetched_at`, and `source` are **KEEP** raw observations and
provenance. `selected_price_gp`, `selection_policy`, and `selection_reason` are **DELETE**
persisted outputs of the old selection run. Before retirement,
`tracker/db/persist_prices.py` wrote them and the old dashboard/advisor read them.
Gear reads the raw columns and calls
`resolve_price` at evaluation time. Its returned selection reason/policy and confidence
are factual, current output and must remain.

## Sync compatibility and deletion order

The v1 JSON schema continues accepting and validating optional `practice_events` from
deployed RuneLite builds. The ingestion boundary ignores it and new plugin builds omit it.
No practice domain writer, table, or UI remains. Remove production consumers first,
then legacy implementation and tests, then create the forward schema migration. Preserve
all unrelated working-tree files throughout.
