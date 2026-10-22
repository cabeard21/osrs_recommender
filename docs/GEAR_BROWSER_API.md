# Gear browser API — Milestone 2

The architecture authority remains [the redesign plan](GEAR_OPTIMIZER_REDESIGN_PLAN.md).
This document describes the implemented read-only contract. Live optimization and
manual equipment evaluation are unavailable.

## Access and lifecycle

The existing FastAPI application serves these routes **inside the private dashboard
network boundary**. They deliberately do not inherit `/api/*` bearer authentication.
The existing Settings bind policy remains in force. `/api/sync` still requires a valid
bearer token; React receives no token. The MCP sidecar does not register these routes.

Routes precede NiceGUI's root mount. NiceGUI and the browser API share an app-scoped
`GearService`; account reads use `AccountService` and prices use `DatabaseGearPrices`.
No endpoint refreshes external prices, writes account observations, or runs optimization.
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

The only supported eventual optimization objective is weighted DPS. Its `available`
flag is false during this milestone, with an explicit reason. Encounter presets and
spell metadata describe the existing model; exposing them does not execute a solve.

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

Unknown item IDs return 404; invalid query/path input returns 422 (`invalid_request`).
Unexpected failures return 500 (`gear_unavailable`) with a generic message and server
logging. The route-specific handler leaves existing `/api/*` behavior intact.

Server DTOs validate equipment definitions, ownership facts, requirements, price fields,
and response structure. `/openapi.json` exposes their schemas. The HTTP adapter checks
identity, slot assignments, required structures and quote types before storing context.
A failed or malformed response cannot select the fixture adapter.

## React modes

`/gear-next/` defaults to live account mode. `?mode=fixture` explicitly selects the
existing deterministic adapter and visibly labels all demonstration data. Mode changes
reload the application; draft storage keys distinguish fixture and live account IDs.
Live mode never calls the fixture optimizer/evaluator. Fixture workflows remain available
in both Single and Multi workspaces. Current live equipment has no calculated metrics.

Context refreshes on focus and every 30 seconds while visible, and has a manual refresh
button. Errors have retry guidance; previously loaded observations retain their dates.
All eleven live slots remain selectable during missing, partial and ambiguous scans.
The inspector supports candidate inspection, missing metadata, physical name/ID search,
pagination, eligibility, ownership timestamps, prices/provenance, and unsupported effects.
