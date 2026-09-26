# Milestone 2: account-aware gear facts

Milestone 2 extends the private Account Companion MCP sidecar described in the
[Milestone 1 implementation](Refactor_Milestone1_Implementation.md). The path is:

```text
RuneLite observations → AccountSnapshot → GearService
    + curated item catalog/ladders + cached prices → four read-only MCP tools
    → ChatGPT planning and tradeoff reasoning
```

The new gear service consumes one coherent account snapshot and supplied price rows. It
does not call weighted scoring, roadmap ranking, recommendation history, or the older
advisor. The existing `/gear` dashboard still selects its highest wearable/obtainable
progression rung, and the older advisor's `get_gear_setup` still describes that computed
setup. Neither selection is returned as an objective recommendation by the new MCP tools.

## What the facts mean

The item catalog contains hand-curated, style/slot progression ladders. `tier` and the
returned order are **authored guide order**. They do not measure combat bonuses, DPS,
universal best-in-slot status, value per GP, or coverage of every OSRS item. An MCP
candidate is a catalog rung that passes the requested *factual* filters. ChatGPT decides
whether it is worth pursuing for the player's activity and other goals.
`get_item_details` also accepts a known catalog item outside these ladders and marks it
with `curated_progression_member: false`; an unknown identifier returns an error.

Ownership is a dated observation. A recognized base or variant ID with a valid positive
sighting yields `owned`. If no sighting survives and bank, inventory, and equipment each
have an accepted scan, `unowned` means **not observed in the latest accepted scans**.
Otherwise it is `unknown`. The three scans can have different times and can all be old;
neither `owned` nor `unowned` guarantees live state. Each item returns `sightings` and
`container_scans` with per-container time and source. An equipment sighting establishes
equipment-container membership, **not** the exact occupied equipment slot. The item's
`slot` is authored catalog data.

The snapshot fingerprint now hashes canonical item sightings and container scans, even
when those collections are empty. This changes `snapshot_id` values from Milestone 1
for otherwise identical accounts; consumers must obtain a fresh ID after upgrading.
The compact `get_account_summary` response does not list the bank or equipment catalog.

`wear.status` is `satisfied`, `unsatisfied`, or `unknown`. `wear.requirements` retains
the evaluated requirement tree even when satisfied, while `wear.unmet` explains known
blockers and unsupported or unknown requirement leaves; `gate_unknown` marks a wear gate
that has not been authored. A missing price is `null`, not zero. For tradeable items,
`price` includes the selected amount, resolution layer/reason, confidence and policy,
selected trade time, cache fetch time, and provider when available. Confidence follows
the existing price resolver's selected trade timestamp. A cached or fallback figure is
an estimate, not an executable quote. Untradeable items are not GE purchases. The price
refresh scope includes primary numeric IDs for authored tradeable ladder items, including
items absent from the old recommendation candidates. Price updates do not change the
account `snapshot_id`.

## MCP contracts

The private sidecar now exposes these four tools alongside the four Quest Cape/account
tools. Each call acquires a fresh snapshot and returns `snapshot_id` and `last_sync_at`.
Compare IDs across a multi-call analysis and restart discovery if the account changed.
The response also includes each container's scan time and source, even on an empty page.
`last_sync_at` does not make older individual sightings or scans current.

| Tool | Request | Result |
|---|---|---|
| `get_gear_progression` | Required `style` (`melee`, `ranged`, `magic`); optional `slot`, `offset`, `limit` | Authored rung page with ownership, wear, acquisition, and price facts; no selected setup |
| `get_gear_candidates` | Same, plus optional `ownership`, `wear_status`, `acquisition` | Factual-filtered rung page; no utility or price ranking |
| `get_item_details` | Exactly one of `content_id` or `numeric_item_id` | Matching catalog memberships and account-aware facts; numeric IDs can return multiple entries with `ambiguous: true` |
| `evaluate_gear_change` | `style`, 1–5 `changes` with `{slot, content_id}`, optional `expected_snapshot_id` | Individual proposal facts and a conditional purchase subtotal; no mutation or loadout validation |

List tools default to `offset=0`, `limit=50`, with a maximum limit of 100. `total`
counts the matching catalog entries before pagination; `next_offset` is `null` at the
end. Results follow stable authored slot/tier/content-ID order. Narrow by style/slot or
follow `next_offset` rather than treating the first page as complete. Filters include
unknown states only when omitted or explicitly selected.

For `evaluate_gear_change`, each content ID must be an authored rung for the requested
style and slot. The service rejects duplicate slots and duplicate representations of a
physical item supported by catalog IDs. This checks **only catalog-supported conflicts**.
Every successful response states `joint_loadout_validity: "not_evaluated"`, including
limitations for two-handed/offhand and ammunition compatibility. Success does not confirm
that the pieces work together. Exact replaced items, combat-stat/DPS deltas, and
activity suitability are also not calculated.

An owned proposal contributes zero purchase GP. An unowned tradeable proposal contributes
its known selected price. Unknown ownership, unknown acquisition, missing required price,
or an unowned untradeable item makes `purchase_subtotal_gp` null and populates
`subtotal_unknown_reasons`; the service does not mislabel a partial amount as the total.
Each proposed item reports `purchase_status` as `necessary`, `unnecessary`, `unknown`,
or `not_applicable` to a GE purchase. A necessary purchase may still have an unknown price.
No sale proceeds from presumed replaced gear are inferred. `expected_snapshot_id` detects
account changes and returns `snapshot_changed` instead of evaluating against a different
account observation.

### Fixture-shaped examples

These values illustrate the wire shape; they are **not** the user's account state or
live market prices. A test fixture has an item `bow`, numeric ID `20`, and a bank scan
on September 20 with no inventory or equipment scan:

```json
{"style":"ranged","slot":"weapon","offset":0,"limit":1}
```

Example `get_gear_progression` response (one-item page):

```json
{
  "snapshot_id": "fixture-snapshot-id", "last_sync_at": null,
  "container_scans": {
    "bank": {"scanned_at": "2026-09-20T00:00:00+00:00", "source": "runelite"},
    "inventory": null, "equipment": null
  },
  "style": "ranged", "slot": "weapon", "total": 1,
  "offset": 0, "limit": 1, "next_offset": null,
  "items": [{
    "content_id": "bow", "name": "Fixture bow", "numeric_item_id": 20,
    "variant_item_ids": [], "curated_progression_member": true,
    "style": "ranged", "slot": "weapon", "tier": 1,
    "ownership": {
      "status": "unknown", "meaning": "incomplete container scan coverage",
      "observed_containers": [], "sightings": [],
      "container_scans": {
        "bank": {"scanned_at": "2026-09-20T00:00:00+00:00", "source": "runelite"},
        "inventory": null, "equipment": null
      }
    },
    "wear": {"status": "satisfied", "gate_unknown": false,
             "requirements": null, "unmet": []},
    "acquisition": "tradeable", "acquired_from": null,
    "price": {
      "amount_gp": null, "layer": "unknown", "selection_reason": "no price available",
      "confidence": 0, "policy": "acquisition_cost", "selected_trade_at": null,
      "fetched_at": null, "provider": null
    }
  }]
}
```

Example `evaluate_gear_change` request and a response excerpt for the same fixture
(`items[0]` is the complete item fact above and is omitted only for brevity):

```json
{"style":"ranged","changes":[{"slot":"weapon","content_id":"bow"}],"expected_snapshot_id":"fixture-snapshot-id"}
```

```json
{
  "snapshot_id": "fixture-snapshot-id", "last_sync_at": null, "style": "ranged",
  "purchase_subtotal_gp": null,
  "subtotal_unknown_reasons": ["unknown_ownership"],
  "joint_loadout_validity": "not_evaluated",
  "limitations": [
    "Joint loadout validity is not evaluated, including two-handed/offhand and ammunition compatibility.",
    "Exact replaced items and combat stat or DPS deltas are unavailable from current observations and catalog."
  ]
}
```

The actual response includes `items` with the full object from the first response plus
`purchase_status: "unknown"` for this fixture.
For item drill-down,
`get_item_details({"numeric_item_id":20})` returns a `query` object, an `ambiguous`
boolean, and all matching entries in `items`. Use a returned `content_id` when a numeric
ID belongs to more than one style or catalog entry.

## Local acceptance checklist

1. Start the existing local database and RuneLite sync as in the Milestone 1 runbook.
   After observing the relevant bank, inventory, and equipment containers, note each
   scan time; refresh the account before relying on older observations.
2. Configure the private sidecar for the intended existing player and run `make run-mcp`
   from the repository. Follow the [desktop configuration and tunnel steps](Refactor_Milestone1_Implementation.md)
   for environment variables and the existing Secure MCP Tunnel. Do not expose the MCP
   listener publicly.
3. From the local MCP client, confirm `tools/list` contains the four gear names above
   plus the four existing tools. Call `get_gear_progression` with `{"style":"ranged"}`;
   inspect `snapshot_id`, `last_sync_at`, individual scan times, and `next_offset`.
4. Call `get_gear_candidates` with a factual filter, drill into a returned `content_id`
   using `get_item_details`, then evaluate that ID with its authored `slot` and the
   captured `expected_snapshot_id`. Confirm `joint_loadout_validity` is
   `not_evaluated` even on success. An intentionally stale ID should yield
   `snapshot_changed`.
5. In ChatGPT through the existing tunnel, ask about a ranged purchase alongside Quest
   Cape progress and a stated budget. Confirm it distinguishes tool facts from its own
   recommendation, qualifies dated ownership and prices, and does not claim measured
   combat deltas or a valid combined loadout. Confirm `/gear` still shows its existing
   dashboard progression view.

These are **manual acceptance steps**, not a claim that live RuneLite, tunnel, or ChatGPT
checks have been performed by automated tests.
