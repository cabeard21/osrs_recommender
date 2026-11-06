# Gear browser API — Milestone 4

The architecture authority remains [the redesign plan](GEAR_OPTIMIZER_REDESIGN_PLAN.md).
This document describes account/item reads, real single/joint optimization, and
exact fixed-loadout comparisons.

## Fast and Thorough search modes

`POST /ui-api/gear/optimizations` accepts optional `optimization_mode`, strictly
`"fast"` (default) or `"thorough"`. This is separate from equipment access `mode`
(`owned`, `usable`, `future`). Omitted and explicit Fast run the unchanged baseline;
Thorough opts into existing complete-assignment local refinement with a limit of
2,000 additional assignments. Targeted head refinement is not enabled. Both return
bounded `best_found` results, including when the refinement limit is reached.

The normalized `scenario` includes `optimization_mode`. Both response and `result`
include `optimization_mode` and server-owned `work_budget_policy`:

```json
{"policy":"local-refinement-v1","complete_assignment_limit":2000,"targeted_head_refinement":false}
```

Fast uses `policy: "baseline-v1"` and `complete_assignment_limit: 0`. These limits
describe additional local-refinement work, not total baseline search nodes. Clients
cannot override this policy. `scenario_fingerprint` hashes the normalized scenario
and effective policy together; fixed `/evaluations` uses the same identity so manual
trials against accepted Thorough results remain compatible. Account, catalog,
model, assumptions and price provenance retain their existing fields and checks.

Thorough retains `result.search.local_refinement`, including `triggered`, `reason`,
`assignment_attempts`, `valid_assignments`, `work_budget_exhausted`, objective and
tie replacement counts, elapsed duration, and preserved `baseline.curve_solutions`
and `baseline.unrestricted`. Baseline curve solutions correspond by action-limit
index. Actual score, acquisition GP, actions and inventory deltas must compare the
chosen result to its matching preserved baseline; replacement counts are not DPS
deltas or request progress. Equal-DPS ordering changes must not be labeled damage
improvements. Cap exhaustion is successful bounded termination, not search failure.

Existing browser callers without a mode and existing NiceGUI/Python/MCP callers
retain Fast behavior. The MCP `optimize_gear` operation accepts optional per-role
combat filters and returns the selected option with each loadout; no new tool is needed.
`GearService.optimize` exposes a Python-only `local_refinement=False` keyword used
by the browser adapter. Busy rejection, worker-thread execution, cooperative
cancellation and pre/post snapshot checks retain their existing behavior. No queue,
job persistence or background storage is added. Progress telemetry is described
under the optimization progress endpoint below.

See [optimization mode acceptance](GEAR_OPTIMIZATION_MODES.md) for deployment limits.

## Combat Options

Each ordinary role may include `combat_options` with explicit `attack_types`,
`stances`, and `spells` allowlists. Omission preserves the prior fixed
`style`/`stance`/`spell` behavior. An empty array remains empty and yields no
configuration when that dimension is required. The browser sends all account
eligible options by default and retains explicit exclusions across account syncs.
`GET /ui-api/gear/context` exposes current availability; `optimize_gear` returns
`combat_option` per selected loadout.

Melee and ranged legality uses reviewed weapon `attack_profiles`. Ranged
light/standard/heavy follows the scorer's ammunition category. Standard spell
eligibility uses account Magic level. The standard spellbook is available by
default when sync omits its optional unlock row; an explicit locked or unknown
`spellbook_standard` observation remains authoritative.
The snapshot does not track which spellbook is active at the moment of attack.
Rune holdings, ammunition quantities, and powered-staff charges are reported
separately as unknown when the required data is unavailable.

Magic weapon autocast requires reviewed `spell_compatibility` metadata. Powered
attacks additionally require a reviewed attack name, fixed base maximum hit, and
stance list. Current real catalog weapons do not supply these magic fields, so
magic weapon autocast and powered attacks remain unsupported until reviewed
metadata and level-scaling formulas are added. Unarmed standard casting is
available when its account requirements are observed. Special attacks are outside
this ordinary-attack model.

## Automatic discipline selection (Single)

An ordinary role may supply `allowed_disciplines`, a nonempty, unique subset of
`["melee", "ranged", "magic"]`. Its presence enables Auto and requires explicit
`combat_options`. Auto accepts exactly one ordinary role; multiple roles and
utility configurations are rejected. Omitting the field preserves manual behavior.
For Auto, the retained fixed `style`, `stance`, and `spell` fields do not restrict
selection. Empty combat-option allowlists remain empty rather than becoming defaults.

The shared Python optimizer runs each permitted discipline sequentially against
the same frozen account, target, prices, catalog, assumptions, and evaluation time.
Each receives the full Fast or Thorough allowance. The existing busy guard spans
the complete operation, and cancellation stops the operation rather than returning
a partial comparison. Unexpected branch errors propagate.

Every returned solution loadout identifies its resolved `discipline` alongside
`combat_option`. `result.discipline_comparison` contains one row per permitted
discipline with `discipline`, `status`, `score`, `purchase_cost_gp`, and `reasons`.
A missing feasible result is a bounded-search outcome, not proof of infeasibility.
The selected result uses the existing DPS-first ordering and deterministic ties.
Curve normalization and secondary-frontier DPS losses use the combined winner;
secondary candidate archives are merged before loss filtering and display sampling.
Slot alternatives describe substitutions within the winning discipline.

`result.search.discipline_selection` records `policy: "full-per-discipline-v1"`,
`branch_count`, and per-discipline `branches` diagnostics. The effective policy and
allowlist participate in scenario identity. Considering all three disciplines can
take roughly three manual searches; results remain `best_found`.
The response `work_budget_policy` also identifies `budget_scope: "per_discipline"`
and `discipline_count` (one for manual requests). Its assignment limit applies to
each branch, not to the sum of all branches.

Fixed-loadout evaluations retain Auto scenario identity. Without a pinned combat
option they choose the best legal option across permitted disciplines for each
fixed loadout. Pinned options must satisfy the discipline allowlist, account,
equipment, and combat-option filters. Baseline equipment observations must still
be complete and unambiguous.

## Access and lifecycle

The existing FastAPI application serves these routes **inside the private dashboard
network boundary**. They deliberately do not inherit `/api/*` bearer authentication.
The existing Settings bind policy remains in force. `/api/sync` still requires a valid
bearer token; React receives no token. The MCP sidecar does not register these routes.

Routes precede NiceGUI's root mount. NiceGUI and the browser API share an app-scoped
`GearService`; account reads use `AccountService` and prices use `DatabaseGearPrices`.
No endpoint refreshes external prices or writes account observations. Optimization
and evaluation return their results directly; computation runs in a worker thread.
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
price inputs. JSON is the existing domain `OptimizationRequest`, supporting one through
four roles. React Single submits one ordinary role; Multi submits two through four
configurations in one joint search. Fixed-loadout comparisons remain Single-only.

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
Unsupported mechanics, prayers, boosts, special scoring and objective fields are
rejected. Names do not confer verified boss mechanics. Multiple configurations may
use the same combat discipline with distinct IDs, targets, stances and weights.

### Joint roles and directed topology

Each role retains its own `target`, `weight` and `locks`. Weights are finite values
from 0 through 1,000,000; at least one ordinary role must have positive active time.
The domain normalizes ordinary-role weights into `result.active_time_shares`.

Optional advanced `style: "special"` roles require an ordinary `parent_role` and an
explicit role weapon lock. They are **unscored utility configurations**, not scored
special attacks. They consume acquisitions, inventory and equipment actions, return
null combat metrics and have no active-time share. They count toward the four-role limit.

Topology uses the existing domain fields:

| Field | Meaning |
| --- | --- |
| `base_role` | Configured role initially equipped; defaults to the first role |
| `transitions` | Up to 16 explicit directed `[from_role, to_role]` edges |
| `ordered_roles` | Up to 100 ordered phase references, including repeated roles |
| `loop` | Add the final-to-first edge for ordered phases |
| `max_swaps` | Maximum equipment **actions per required directed transition**, 0–12 |

Choose explicit edges or ordered phases, never both. With neither, the optimizer
uses base↔ordinary-role round trips. Utility roles receive their existing parent
round trips unless included in ordered phases. Repeated required edges and ordered
self-steps are normalized by the existing backend; no all-pairs topology is added.
Malformed references, conflicting locks/exclusions and unsupported role inputs return
422 with editable paths such as `roles.2.spell`, `transitions.1.0`, or `ordered_roles.3`.

```json
{
  "roles": [
    {"id": "melee", "style": "slash", "stance": "accurate", "weight": 1},
    {"id": "range", "style": "ranged", "stance": "rapid", "weight": 3}
  ],
  "base_role": "melee", "ordered_roles": ["melee", "range", "melee"],
  "loop": false, "mode": "usable", "budget_gp": 100000,
  "max_swaps": 4, "reserved_supply_slots": 12,
  "expected_snapshot_id": "<current account fingerprint>"
}
```

Access modes preserve domain semantics: `owned` uses observed owned equipment;
`usable` also permits eligible, priced purchases within the additional integer GP
budget; `future` additionally permits explicit hypothetical assumptions. Skill/quest
keys and concrete acquired IDs are validated. Overrides never write observations.
Requirements remain enforced in every mode. Unknown prices cannot fund purchases.

The optional strict boolean `include_untradeables` defaults to false. In `usable`
and `future` modes it also permits unowned untradeable equipment whose wear
requirements are satisfied under the request's normal account/assumption rules.
It has no effect in `owned` mode. Supported-effect policy, exclusions, locks,
physical compatibility, and all other constraints still apply. Unknown acquisition
types remain unavailable. This toggle changes search eligibility, not account
observations, and does not claim that obtaining an item is quick or free.

Selected unowned untradeables are hypothetical upgrades to obtain, separately
reported as `unowned_untradeable_item_ids` on complete solutions and fixed
evaluations. They contribute no GE purchase rows or purchase GP, including when
ownership is unknown. Already-owned untradeables need no acquisition entry.
The UI labels these items separately from **What to buy**. The flag participates
in scenario and assumptions fingerprints; historical responses without these
fields retain the default false/empty semantics. Tradeable purchases continue to
require usable prices and obey the additional GP budget. Older saved results remain
readable but require a rerun before fixed comparisons under the new provenance.

Optional `excluded_item_ids` contains up to 500 concrete physical IDs. The default
is empty. Unknown IDs and overlap with any global or role lock are rejected with
structured field errors. Exclusions apply to candidate preparation, every search
path, final validation, curve/unrestricted results, and contextual alternatives.
Physical variants retain separate identities. An assumed acquisition does not
override an exclusion.

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
| `baseline` | Single observed baseline; unavailable with an explicit explanation for joint scenarios |

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

### Joint solutions and curve selection

`result.curve` contains only computed points: `swap_limit`, `status`, nullable
`solution`, and nullable `relative_performance`. `selected_solution` corresponds to
the submitted action limit. `unrestricted` is the **best found without the swap-action
limit**; account, budget, inventory and model constraints still apply. It is neither
a global optimum nor an unconstrained reference. Missing solutions remain explicit.

Each solution preserves Python `score` (weighted aggregate DPS), role-keyed `loadouts`
with complete `CombatPerformance`, purchase union and `purchase_cost_gp`, and:

| Field | Meaning |
| --- | --- |
| `carried_item_ids`, `distinct_items` | Complete distinct physical equipment union, **including equipped items** |
| `gear_inventory_slots` | Equipment outside active slots in the submitted base role |
| `max_gear_inventory_slots` | Maximum occupancy across roles and transient transition states |
| `reserved_supply_slots` | Reserved capacity, without supply-consumption simulation |
| `remaining_supply_slots` | Total capacity available for supplies at peak gear occupancy |
| `remaining_inventory_slots` | Capacity remaining after peak gear and reserved supplies |
| `maximum_actions` | Largest equipment-action count across required transitions |
| `transitions` | Exact directed backend transition plans |

Each transition contains `from_role`, `to_role`, `changed_slots`, `action_count`,
`max_gear_inventory_slots`, and ordered `actions`. Each action preserves `operation`
(`equip`/`unequip`), physical `slot`, `item_id`, `automatically_removed` IDs and resulting
`gear_inventory_slots`. Automatic hand displacement does not add extra actions.

Changed equipment slots, equipment actions, gear inventory slots and unique required
items are different quantities. Shared markers use exact physical-ID intersections;
inventory outside a role is the required union minus that role's equipped IDs.
The browser does not calculate combat metrics, infer transition sequences or synthesize
intermediate curve points. Curve/view/role selection requires no new optimization.

Before publishing the curve, Python applies bounded performance-neutral ammunition
sharing to found finalists. It only tries already-required ammunition IDs or empty,
preserves locks, utility equipment, exact ordinary-role attack metrics and defensive/
prayer bonuses, and revalidates complete purchase/transition/inventory semantics.
Improvements can populate lower-action curve points. Search diagnostics include
`ammunition_refinement` assignment/improvement counts; bounded-search caveats remain.

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

## POST /ui-api/gear/evaluations

Evaluates fixed baseline and proposed equipment without running candidate search.
The baseline here is a supplied configuration, usually the accepted optimized
result; it is distinct from the observed current-equipment baseline above.

```json
{
  "scenario": {
    "roles": [{"id": "role-1", "style": "slash", "stance": "accurate"}],
    "mode": "usable", "budget_gp": 100000,
    "expected_snapshot_id": "<current account fingerprint>"
  },
  "baseline_loadouts": {"role-1": {"weapon": 1333}},
  "proposed_loadouts": {"role-1": {"weapon": 1331}}
}
```

`scenario` is the same domain request shape returned by optimization, including
its locks, exclusions, target, access mode and assumptions. Exactly one ordinary
role is supported, and both loadout maps must contain exactly that role ID.
Equipment keys are physical slots, including `ammunition`; values are strict
positive physical IDs. Omitted slots are empty. A proposal is never repaired by
removing a shield, selecting ammunition, or substituting another item.

The response contains `api_version`, `evaluated_at`, normalized `scenario`,
`scenario_fingerprint`, `snapshot_id`, `catalog_version`, `model_version`,
`assumptions_fingerprint`, `price_revision`, physical `items`, `baseline`,
`proposed`, and nullable `deltas`.

Each fixed evaluation contains:

| Field | Meaning |
| --- | --- |
| `status` | `valid`, `invalid`, or `unsupported` |
| `equipment` | Exact submitted physical slot assignments |
| `performance` | Existing Python `CombatPerformance` when valid; otherwise null |
| `reasons` | Structured `{path, message}` explanations |
| `purchase_cost_gp` | Additional purchase estimate, or null when prices are unavailable |
| `purchases` | Distinct `{item_id, cost_gp, conditional}` purchase requirements |
| `assumed_item_ids` | Explicit hypothetical acquisitions used by this configuration |

Both configurations share one frozen snapshot, hypothetical projection, catalog,
price set and time. Requirements, ownership/access, locks, exclusions, budget and
supported combat constraints apply to both. Owned equipment does not require a
purchase quote; unknown ownership remains a conditional purchase. Assumed
acquisitions require future mode and never modify observations.

When both sides are valid and supported, `deltas` contains signed **proposed minus
baseline** `dps`, `max_hit`, `accuracy`, `attack_interval` (seconds), and
`purchase_cost_gp`, plus `equipment_changes` (`slot`, `baseline_item_id`,
`proposed_item_id`), `added_purchase_ids`, and `removed_purchase_ids`.
Purchase differences are additional acquisition costs, with no assumed resale
proceeds or per-item damage attribution. Both sides are recalculated together;
stored optimization metrics are not used as a stale subtraction baseline.

Malformed shapes, slots, role keys, unknown IDs and contradictory scenario
constraints return 422 `invalid_request` with field paths. Recognized equipment
that violates configuration constraints returns 200 with an invalid/unsupported
status and no performance or comparison deltas. A successful HTTP response alone
does not imply a valid trial.

Evaluation retains optimization's same-origin checks (403), pre/post account
fingerprint checks (409), non-cacheable responses, generic unexpected errors
(500), worker execution and service concurrency guard (`optimizer_busy`, 503).
Disconnected/cancelled evaluations signal cooperative cancellation
(`evaluation_cancelled`, 499); a browser abort does not forcibly stop a thread.

## React modes

`/gear-next/` defaults to live account mode. `?mode=fixture` explicitly selects the
existing deterministic adapter and visibly labels all demonstration data. Mode changes
reload the application; draft storage keys distinguish fixture and live account IDs.
Live mode never calls the fixture optimizer/evaluator. Fixture workflows remain available
in both Single and Multi workspaces. Live single-style results, valid baselines and
manual trials use Python POSTs. Live Multi submits one joint request and presents its
selected computed curve solution in both comparison and switching views.

Context refreshes on focus and every 30 seconds while visible, and has a manual refresh
button. Errors have retry guidance; previously loaded observations retain their dates.
All eleven live slots remain selectable during missing, partial and ambiguous scans.
The inspector supports candidate inspection, missing metadata, physical name/ID search,
pagination, eligibility, ownership timestamps, prices/provenance, and unsupported effects.
Single accepted results retain contextual alternatives for their submitted surrounding
equipment. Manual previews change one slot and leave accepted results and drafts
untouched. Revert discards the trial; lock/exclude updates the draft and marks the
accepted result outdated until reoptimization. Trial generations and abort signals
prevent stale responses from publishing. Account, catalog, model and price changes
invalidate dependent trials. Results and evaluations are never persisted.

Multi inspection reuses physical facts, ownership, requirements and prices. Global
and role-specific lock edits and global exclusions modify only the draft and mark
accepted results outdated. Single-role contextual alternatives and manual trial DPS
comparisons are unavailable for Multi. `/evaluations` independently rejects joint
scenarios; it never evaluates only the first role as a joint comparison.

## NPC target catalog

`GET /ui-api/gear/targets?q=<name-or-id>&offset=0&limit=20` searches the bundled
NPC catalog. The response contains `catalog_revision`, `items`, `total`, `offset`,
and `limit`. Entries retain separate `key`, `npc_id`, `name`, `variant`,
`combat_level`, `support_status`, and `reasons` fields. Exact name/ID matches rank
before prefixes and substrings; pagination uses a stable order.

`GET /ui-api/gear/targets/{key}` adds the mapped `target` and source reference.
`target` can be null when required statistics are missing. Support statuses are
`supported`, `unsupported`, and `not_reviewed` (unknown attributes only);
all remain inspectable, but only supported
ordinary-attack targets can be optimized. Complete ordinary profiles are supported
by default without individual review. Mechanical attributes, missing statistics,
and known NPC-specific rules can block scoring with explicit reasons;
ordinary classification tags do not automatically block a target. This is a
static ordinary-attack calculation, not a full encounter simulation.
Targets carry signed integer `flat_armour` (default `0`, range -10000 to 10000).
Accurate melee and ranged hits first raise rolled zeroes to one, then subtract
armour and clamp damage at zero; negative armour adds damage. Misses remain zero
and magic ignores flat armour. Catalog armour cannot be overridden while retaining
the NPC selection; custom targets can set it explicitly.
Blood Moon, Blue Moon and Eclipse Moon Regular support ordinary attacks only;
curses, healing, survival and encounter downtime are excluded. Eclipse Moon Clone
remains unsupported because its phase changes accuracy, timing and hit behavior.
Reviewed usable forms of dual macuahuitl, Torag's hammers, glacial temotli and
sulphur blades apply armour separately to each hit. Dual macuahuitl's second hit
requires the first accuracy check to succeed. Set effects and special attacks
remain excluded. Torag's degradation cost is unavailable until reviewed.
Performance `hitsplats` reports each hit's marginal accuracy and maximum damage;
`max_hit` is maximum total damage per attack after armour (including zero), while
`accuracy` remains the first hit's accuracy.
Elemental weaknesses and separate light,
standard, and heavy ranged defence values feed the existing Python evaluator.

Roles optionally submit `target_selection: {key, catalog_revision}` alongside
their effective `target`. Numeric stat overrides retain the selected NPC identity
and are visibly marked Modified. Server-owned damage caps and unsupported-mechanic
restrictions cannot be removed through edits. Both optimization and exact
evaluation resolve selections on the server; stale catalog revisions and removed
keys require explicit reselection rather than silently adopting changed stats.
Custom targets remain explicit manual snapshots without catalog identity.

Single and each Multi role use independent selections. Draft storage v3 preserves
selection identity and effective values, while v1/v2 drafts migrate as manual
targets without name-based identity inference. Results retain the submitted
selection and scenario fingerprints include it. Changing target identity, data
revision, or overrides invalidates comparisons with a previous result.

The catalog is bundled under `content/npcs` and needs no runtime network access or
database migration. Its manifest pins the upstream commit, exact payload SHA-256,
import timestamp, and attribution. To refresh, replace the source payload from an
explicit upstream commit, regenerate the manifest checksum, review capability
classifications against the changed records, and run the focused catalog/API and
picker/browser tests before shipping both files together. Existing selections
must be refreshed explicitly after the catalog revision changes. Raid scaling,
defence-reduction settings, and new encounter mechanics are outside this release.

Use `python tools/import_npcs.py --source <monsters.json> --revision <commit-sha>`
to refresh the bundled catalog. The importer preserves the existing manifest's
known mechanic exceptions and their provenance. A fresh output directory must
first receive a copy of the bundled manifest; importing without an exception
registry fails before writing either file.

### Browsing Auto disciplines

Single Auto results open on **Auto overall**. Tabs for each searched discipline expose its best-found loadout and its own secondary tradeoff frontier, including disciplines dominated in the combined frontier. Default priority shows each discipline's best DPS loadout; select a named secondary priority to explore tradeoffs. Discipline DPS loss is measured from that discipline's best DPS under the same swap limit. Frontiers remain bounded best-found results and may be sampled to 64 points, preserving endpoints.

The additive `result.discipline_results` list retains each searched discipline's status, reasons, selected solution, secondary frontiers, search diagnostics, limitations, and contextual alternatives. Existing overall fields retain their meaning. Switching tabs does not run another search or change the overall Auto winner.

## Arrow running cost

`POST /ui-api/gear/ammo-comparisons` accepts `scenario`, a fixed `loadout`
(slot to physical item ID), and a resolved `combat_option` (`attack_type:
"standard"` for ordinary bows). It freezes the bow, target, stance and other
gear, then enumerates supported compatible arrows and Ava devices plus the
current cape and an empty cape slot. Account access, locks, exclusions and
purchase budget remain enforced by exact evaluation.

The response preserves evaluation identity fields, `cost_model_version`,
`limitations`, and `points`. Each point contains `ammo_id`, `ammo_name`,
`cape_id`, `cape_name`, `dps`, `attack_interval`, `recovery_rate`,
`arrows_lost_per_hour`, `gp_per_hour`, `gp_per_damage`, `price`, `current`,
`frontier`, and string `reasons`. Null costs indicate unknown recovery or price;
invalid equipment has null performance. All combinations remain inspectable.

Rates assume continuous ordinary attacks and no ground pickup. Owned arrows
still incur replacement cost. Ava recovery is reviewed by exact cape ID and
body interference: attractor 60%, accumulator 72%, assembler 80%. Body armour
outside the reviewed interference metadata yields unknown recovery rather than
an assumed saving. Purchase cost is separate from arrow running cost. Special
weapons, quivers, skillcapes and ammunition beyond current combat support are
not granted additional mechanics by this endpoint.

Armour recovery metadata covers ordinary ranged bodies and their reviewed
variants, common cloth bodies, and the Wiki's metallic interference exceptions.
This does not change the separate combat support or account access requirements.

Price-cache maintenance runs on the authoritative Pi service, not the desktop.
Empty market results and static hints no longer satisfy the market-cache TTL;
the next scheduled refresh retries them. Deploy the Python cache fix to the Pi
through the normal application update; no migration or configuration change is
needed. All seven supported ordinary arrows are already in the price refresh
scope. Restart desktop Gear after updating its armour comparison code.

# Combat potion assumptions

Scenarios accept `potions` with `mode` (`disabled`, `optimize`, or `fixed`),
`allowed_ids` (catalog family IDs), and `selected_ids` (an exact setup for fixed
evaluation). Omitted policies default to disabled. Gear context exposes
`potion_catalog`; use its IDs rather than inventing item forms.

Optimization compares compatible potion setups alongside gear. One setup applies
to every Multi role. Potions are assumed available regardless of observed ownership.
Their boosts affect combat and spell-level checks, while equipment requirements
continue to use base account levels (or future-mode base-level assumptions).

Solutions carry their exact potion setup, base and boosted levels, and cost per
application. Prices use the frozen market snapshot; unavailable prices remain
unknown. Potion application costs are separate from gear acquisition budgets and
ammo/rune/charge GP/hour and GP/damage. A fixed comparison must retain the selected
setup rather than silently optimizing potions again.

DPS is a fresh-boost snapshot. Decay, duration advantages, drinking downtime,
healing costs, survival, and supply endurance are not modeled. Divine HP costs are
disclosed. Boosted Defence is informational and does not alter equipment-bonus
secondary objectives. Potions do not count as equipment swaps or automatically
change reserved supply slots.

Potion optimization collapses equivalent boost vectors using only skills scored
by the configured roles. Single Auto enumerates profiles separately for each
permitted discipline, then schedules the concrete jobs in the same worker pool.
For example, nine melee profiles and two each for ranged and magic require 13
searches, rather than 36 combinations each repeating all three disciplines. Combined
potions remain eligible when cheaper, even if they also boost an unscored skill.
For melee, Defence and Ranged boosts do not create additional searches.
Base equipment facts are shared across profiles; boost-dependent candidate
rankings and performance caches remain independent. Individually unaffordable
equipment is removed before candidate ranking and attack-scaffold evaluation;
owned, assumed and budget-exempt items retain their existing cost treatment.
The full catalog facts remain available for validation and explanations.
Desktop uses its existing
bounded worker pool for potion branches, with serial fallback when no pool is
configured. This does not move optimization onto the Pi.

Clients may attach a fresh UUID `progress_id` query parameter to optimization
POSTs, then poll `GET /optimizations/progress?progress_id=<uuid>`. The response
contains the matching attempt's progress or null; previous attempts are never
substituted. Progress is reported for every run type (Single, Multi, Auto and potion
search) and contains:

- `phase` / `label`: the current stage id and its human label.
- `fraction`: overall 0–1 completion. It never decreases within one attempt and only
  reaches 1 when the run finishes.
- `stages`: the ordered stage plan (`preparation`, `candidate_ranking`, `gear_search`,
  `refinement`, `frontiers` when a frontier runs, `merge` when several searches run),
  each with `status` (`complete` | `active` | `pending`) and `fraction`.
- `lanes` and `lane_counts` (only when there are several independent searches, e.g.
  Auto disciplines × potion profiles): rows with `label`, `status` (`complete` |
  `running` | `pending`), `stage`, `stage_label` and `fraction`. Every row is sent for
  up to 12 searches; above that only running rows are sent. `lane_counts` always
  gives `{complete, running, pending}`. Browsers show these rows instead of the stage
  checklist, because parallel searches are in different stages at once.
- `completed` / `total`: finished and total independent searches (`total` is 0 for a
  single search). `eta_seconds`: estimated seconds left, or null while not credible.
- `elapsed_seconds` and `scenario_fingerprint`.

In-stage fractions come from deterministic search counters: equipment slots, beam
segments, finalists scored, refinement assignments and frontier node budgets. Spawned
desktop workers publish them through lock-free shared-memory slots. Stage durations
come first from searches already finished in the same run, then from per-shape
history learned in memory (reset on restart), then from defaults. They weight the
stages and smooth progress between counter updates. The ETA is the remaining search
work divided across the worker pool. Progress is
telemetry only and never changes search order, budgets or results. Browsers poll every
400 ms.
Result search diagnostics include potion preparation, branch and merge timings.
`search.timings_seconds.total` measures the enclosing optimizer run: Auto reports
branch and merge wall time, and potion optimization also reports preparation.
Parallel branch wall time includes overlap; it is not the sum of worker times.
The winning profile's phases are no longer presented as the entire run's phases.
Every concrete potion profile retains its discipline, selected potion IDs and
complete search diagnostics under `search.potion_selection.profiles`.

Both frontier passes report `timings_seconds`. Secondary frontier phases cover
pool preparation, metric and diverse equipment lanes, assignments, combat
variants, ammunition cleanup, finalist refinement and publication. Running-cost
timings include preparation and final publication around its exploration;
`running_cost_frontier.exploration.timings_seconds` retains the nested phases.
These timers are observational, outside scenario identity and search budgets.
Polling is observational and does not alter the request's search effort or
cancel an active job.

Secondary frontier insertion retains ranked archives incrementally and shares
updates across identical action-cap archives. Elemental attack scoring collapses
equivalent tier/stance/weakness outcomes while retaining the original spell tie
winner. Full spell choices remain available to resource-cost frontier searches.
These optimizations preserve the configured search limits.
Equipment-bonus metric lanes reuse DPS option winners because their secondary
value is constant across attacks and prayers for fixed equipment and discipline.
Their equipment beams still rank the selected bonus first. Accuracy, player
defence-roll and running-cost metric lanes retain independent option winners.
