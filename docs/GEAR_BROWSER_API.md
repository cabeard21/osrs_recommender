# Gear browser API — Milestone 3

The architecture authority remains [the redesign plan](GEAR_OPTIMIZER_REDESIGN_PLAN.md).
This document describes account/item reads and real single-style optimization.
Arbitrary manual equipment evaluation and live multi-style optimization remain unavailable.

## Access and lifecycle

The existing FastAPI application serves these routes **inside the private dashboard
network boundary**. They deliberately do not inherit `/api/*` bearer authentication.
The existing Settings bind policy remains in force. `/api/sync` still requires a valid
bearer token; React receives no token. The MCP sidecar does not register these routes.

Routes precede NiceGUI's root mount. NiceGUI and the browser API share an app-scoped
`GearService`; account reads use `AccountService` and prices use `DatabaseGearPrices`.
No endpoint refreshes external prices or writes account observations. Milestone 3 adds
the synchronous-response optimization POST described below; computation runs in a worker thread.
Successful and handled error responses specify `Cache-Control: no-store`.

The selected player is the first player ID, matching the existing dashboard. An empty
database is supported. An account configured in Settings without a sync retains its
identity and unknown observations; it does not receive sample skills or equipment.

## GET /ui-api/gear/context

Returns `ContextResponse` (`api_version: "gear-ui-v1"`).

| Field | Meaning |
| --- | --- |
| `evaluated_at` | UTC projection time, not an observation timestamp |
| `account` | `AccountSnapshot.summary()` plus `snapshot_id`, or null if no account exists |
| `container_scans` | `bank`, `inventory`, `equipment`: timestamp/source/age note, or null |
| `current_equipment` | Conservative equipment projection described below |
| `items` | Full physical-item facts for mapped equipment candidates, including ambiguous candidates |
| `capabilities` | Slots, access modes, spell definitions, existing encounter presets, combat disciplines, role/action limits, objective availability |
| `catalog_version` | Loaded physical catalog revision |
| `model_version` | Existing ordinary-attack model identifier, `normal-attacks-v1` |
| `price_revision` | Deterministic fingerprint of cached price records |

`account` preserves username, player ID, skills with source/time/XP, quests and quest
observations, unlocks, quest points, combat level, membership, last sync, and the existing
missing-data policy. `snapshot_id` is the immutable account fingerprint; it includes
item/container observations, not just the summary.

The supported optimization objective is ordinary-attack DPS (`weighted_dps` in the
existing domain vocabulary), with `available: true` for single-style requests. Other
objectives remain unavailable. Encounter presets and spell metadata describe the
existing model; a target name does not imply complete encounter simulation.

### Equipment projection

`current_equipment` contains:

```typescript
{
  status: "observed" | "partial" | "unknown";
  scanned_at: string | null;
  equipment: Partial<Record<Slot, number>>;
  slots: Record<Slot, {
    status: "observed" | "empty" | "unknown" | "ambiguous";
    item_id: number | null;
    candidate_item_ids: number[];
  }>;
  observations: {
    item_id: number;
    quantity: number;
    observed_at: string;
    source: string;
  }[];
  unmapped_item_ids: number[];
  warnings: string[];
}
```

Slots use backend names, including **`ammunition`**. The React adapter maps this to
its existing visual slot name `ammo`; no slot/ownership/requirement inference occurs
in JavaScript.

Sync aggregates item IDs by container and does not preserve actual slot indices.
Only accepted positive observations with known physical catalog slots are candidates.
Superseded observations do not contribute. A unique candidate can be projected into
its catalog slot; multiple candidates leave that slot ambiguous. Impossible quantities
for nonstackable items and a two-handed weapon/offhand conflict also remain ambiguous.
Candidate IDs are retained for inspection, without selecting a winner.

Missing scans produce overall `unknown`, while individually supported positive
sightings can still be inspected. Missing slots do not become empty. With a scan and
complete physical mapping, absent slots are `empty`. Unmapped IDs make the projection
`partial` and keep unresolved slots unknown. A complete scan with no positive sightings
can represent observed empty equipment. Old scans retain their dates and age notes;
no new age-based eligibility or ownership rule is introduced.

## GET /ui-api/gear/items

Searches physical equipment, including items with incomplete requirements/effects.

| Query | Default | Validation |
| --- | --- | --- |
| `q` | empty | Case-insensitive name substring or exact numeric ID; max 200 characters |
| `slot` | absent | Catalog slot, including `ammunition` |
| `style` | absent | `melee`, `ranged`, `magic`; existing catalog weapon filtering |
| `ownership` | absent | `owned`, `unowned`, `unknown` |
| `wear_status` | absent | `satisfied`, `unsatisfied`, `unknown` |
| `acquisition` | absent | `tradeable`, `untradeable`, `unknown` |
| `offset` | 0 | Integer >= 0 |
| `limit` | 50 | Integer 1–200 |

The response contains `api_version`, `snapshot_id` (null without an account),
`catalog_version`, `items`, `total`, `offset`, `limit`, and nullable `next_offset`.
Ordering is deterministic by canonical physical name and numeric ID. Filters/search
precede pagination. These are inspectable catalog rows, not ranked alternatives.

## GET /ui-api/gear/items/{item_id}

Returns `ItemResponse` for that **exact physical numeric ID**, or 404. It never
substitutes a curated alias or resolves a variant to its primary ownership ID.

| Field | Meaning |
| --- | --- |
| `item_id`, `numeric_item_id` | Same concrete physical ID |
| `name`, `slot`, `equipment` | Canonical catalog identity and complete `EquipmentDefinition`, including bonuses, speed, styles, requirements and compatibility metadata |
| `wear` | Existing requirement evaluator result, unmet/unknown reasons, and `requirements_complete` flag |
| `ownership` | Existing `observed_ownership` projection with accepted sightings and container scans |
| `acquisition` | `tradeable`, `untradeable`, or `unknown` |
| `acquisition_descriptions` | Authored acquisition descriptions for the concrete primary ID, where available |
| `price` | Selected acquisition estimate and raw cached provenance below |
| `limitations` | Unsupported effects from the physical definition |
| `catalog_version` | Loaded physical catalog revision |

Incomplete requirement coverage remains `unknown`, even when the reviewed subset is
satisfied. Unknown skills/quests retain their evaluator reasons. Physical variants
preserve their numeric identity and existing reviewed eligibility overlays.

### Ownership and historical limits

`ownership` retains `status`, `quantity`, `meaning`, `sightings`, and `container_scans`
from the existing Python observation logic. Sightings distinguish equipment, bank,
and inventory, with quantities, sources and observation times. Asynchronous quantities
are not summed. No accepted positive sighting plus complete scan coverage yields
`unowned` meaning **not observed in the accepted scans**, not guaranteed absence today.
Incomplete scan coverage yields `unknown`.

Every sighting is a previous observation. There is no complete item ownership ledger:
sync replaces superseded container membership and snapshots omit superseded rows.
Historical ownership after a sighting disappears is unavailable. The API/UI explicitly
preserve that limitation rather than inventing a historical ownership category or
reclassifying dated sightings as current possession.

### Prices

`price` includes:

- `amount_gp` (nullable), `layer`, `selection_reason`.
- `selected_trade_at`, `fetched_at`, `source`, `provider` (nullable).
- `confidence` (`low`, `medium`, `high`, or null), `policy` (nullable).
- Raw `high_price_gp`, `low_price_gp`, `high_trade_at`, `low_trade_at` (nullable).

Selection uses the existing `resolve_price` policy. A row's source and the selected
number's layer remain distinct. Cached fetch time never substitutes for trade time.
An authored fallback is explicitly `static_hint`, without market provider/trade data;
it is not represented as a fresh GE price. Missing prices remain null, never zero.
Untradeable and unknown-tradeability items are labeled explicitly. There are no price
network calls from these GET endpoints.

## Errors and validation

Handled errors use:

```json
{"error":{"code":"item_not_found","message":"Physical item metadata unavailable"}}
```

Unknown item IDs return 404; invalid query/path/scenario input returns 422 (`invalid_request`).
Unexpected failures return 500 (`gear_unavailable`) with a generic message and server
logging. The route-specific handler leaves existing `/api/*` behavior intact.

Server DTOs validate equipment definitions, ownership facts, requirements, price fields,
and response structure. `/openapi.json` exposes their schemas. The HTTP adapter checks
identity, slot assignments, required structures and quote types before storing context.
A failed or malformed response cannot select the fixture adapter.

## POST /ui-api/gear/optimizations

Runs the existing `GearService.optimize` against frozen account, catalog and cached
price inputs. JSON is the existing domain `OptimizationRequest`, restricted to exactly
one ordinary-attack role. There is no public arbitrary-loadout evaluation endpoint.

```json
{
  "roles": [{
    "id": "role-1", "style": "slash", "stance": "accurate",
    "spell": "fire_strike", "weight": 1,
    "target": {"name": "Custom ordinary-attack target", "defence_level": 1},
    "locks": {}
  }],
  "mode": "usable", "budget_gp": 0,
  "reserved_supply_slots": 12, "max_swaps": 8,
  "skill_overrides": {}, "quest_overrides": {}, "assumed_item_ids": [],
  "expected_snapshot_id": "<current account fingerprint>"
}
```

Role styles are `stab`, `slash`, `crush`, `ranged`, or `magic`. Stances and standard
spells must be supported by the model. Targets reuse `CombatTarget`, including Magic
level, defence bonuses, ranged subtype bonuses and supported elemental weaknesses.
Unsupported mechanics, prayers, boosts, special scoring, objective/exclusion fields
and multi-role transitions are rejected. Names do not confer verified boss mechanics.

Access modes preserve domain semantics: `owned` uses observed owned equipment;
`usable` also permits eligible, priced purchases within the additional integer GP
budget; `future` additionally permits explicit hypothetical assumptions. Skill/quest
keys and concrete acquired IDs are validated. Overrides never write observations.
Requirements remain enforced in every mode. Unknown prices cannot fund purchases.

Global and role `locks` use physical slot names: absent key means optimize, `null`
means force empty, and a positive numeric ID means force that exact item. Conflicting
locks, wrong slots, unknown IDs and two-handed/offhand conflicts are rejected. Inventory
reservations retain the existing 0–28 range. `max_swaps` retains its domain wire name;
single-role results have no equipment transitions. No search limits or scoring changed.

### Response

`OptimizationResponse` is exposed in OpenAPI:

| Field | Meaning |
| --- | --- |
| `api_version` | `gear-ui-v1` |
| `evaluated_at` | Frozen calculation time |
| `scenario` | Server-normalized domain request, including role target and snapshot |
| `scenario_fingerprint` | SHA-256 of normalized serialized scenario |
| `price_revision` | Fingerprint of the frozen cached price inputs |
| `result` | Existing domain output preserved, including selected/unrestricted solutions, curve, alternatives, assumptions, facts and diagnostics |
| `items` | Typed concrete `ItemResponse` rows for referenced and baseline equipment, with complete price provenance |
| `baseline` | `{status, equipment, performance, reasons}` for this single role |

`result.selected_solution` is null when no feasible configuration was found. Otherwise
its role-keyed `loadouts` contain concrete slot assignments and `CombatPerformance`:
`dps`, `max_hit`, `accuracy`, `attack_interval` (seconds), rolls, equipment bonuses,
supported flag and limitations. Missing equipment keys are empty selected slots.
Unsupported metrics remain null; they are not synthetic zeros. The browser only
formats Python numbers. Acquisition retains distinct purchases, conditional ownership
flags, purchase subtotal, assumed acquisitions, and concrete shared-item semantics.

The result's `snapshot_id`, `catalog_version`, `model_version`, `evaluated_at`,
assumptions fingerprint and search diagnostics remain available. Search output is
**best found**, with candidate truncation and termination reasons; it is not a proof
of global optimality or infeasibility. No prayer/potion, survival, special-attack,
boss-completion or encounter-duration metrics are supplied.

### Exact current-equipment baseline

Only a complete, unambiguous equipment projection with supported metadata and
requirements is evaluated. `baseline.status: "available"` includes the same Python
combat model's performance against the submitted role, target and hypothetical skill/
quest assumptions. Optimization locks, purchase budget and acquisition restrictions
do not disqualify observed equipment. Slot identity and combat legality reuse the
shared `tracker.gear.evaluation` foundation also called by the optimizer.

Missing scans, ambiguous slots, unmapped IDs, unknown requirements or unsupported
combat produce `status: "unavailable"`, `performance: null` and explicit reasons.
Known equipment remains identified without treating unresolved slots as empty. An
unavailable baseline does not prevent optimization.

### Execution and errors

Account/price reads and CPU work run outside the FastAPI event loop. The app-scoped
service's nonblocking lock rejects overlapping searches. No result/job persistence or
external queue is introduced. A fresh account read after the worker completes must
match the submitted snapshot before any result is returned.

| Status | Code / behavior |
| --- | --- |
| 200 | Completed search, including a null selected solution |
| 403 | `origin_rejected` for cross-origin browser POSTs |
| 409 | `snapshot_changed` or `account_unavailable`; refresh and rerun |
| 422 | `invalid_request`; `error.fields` contains `{path, message}` entries |
| 499 | `optimization_cancelled` when a disconnected request is observed |
| 503 | `optimizer_busy`; retry after the active search finishes |
| 500 | Generic `gear_unavailable`; details logged server-side |

Same-origin browser POSTs are required; Vite's documented proxy preserves the browser
Host/Origin pair. Non-browser calls without Origin retain the private network boundary.
There is no permissive CORS configuration or sync-token delivery to JavaScript.

Disconnects and request-task cancellation signal a thread-safe cancellation event to
the existing cooperative optimizer callback. HTTP abort does not kill a Python thread.
Cancellation can wait until the optimizer reaches a supported checkpoint, including
after candidate preparation; the lock remains held until the search exits. The client
also aborts obsolete requests and rejects superseded generations. Progress is
indeterminate, with no percentage-complete claim.

## React modes

`/gear-next/` defaults to live account mode. `?mode=fixture` explicitly selects the
existing deterministic adapter and visibly labels all demonstration data. Mode changes
reload the application; draft storage keys distinguish fixture and live account IDs.
Live mode never calls the fixture optimizer/evaluator. Fixture workflows remain available
in both Single and Multi workspaces. Live single-style results and valid baselines use
the Python POST; live Multi, manual replacements and exclusions remain unavailable.

Context refreshes on focus and every 30 seconds while visible, and has a manual refresh
button. Errors have retry guidance; previously loaded observations retain their dates.
All eleven live slots remain selectable during missing, partial and ambiguous scans.
The inspector supports candidate inspection, missing metadata, physical name/ID search,
pagination, eligibility, ownership timestamps, prices/provenance, and unsupported effects.
