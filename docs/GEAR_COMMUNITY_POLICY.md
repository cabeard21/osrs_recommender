# Community equipment eligibility

The personal React Gear interface explicitly defaults to `community_best_effort`.
Its policy selector can restore `verified_only`. Legacy Python/service/MCP calls
that omit a policy retain verified-only eligibility. Optimization and fixed-loadout
evaluation use the same policy and existing legality/combat calculations.

Best-effort results distinguish **community-assumed** items from verified items.
For classified ordinary equipment, satisfied known requirements are accepted while
unresolved quest/unlock gates are explicitly assumed absent. This is a hobby-use
eligibility policy, not proof that every equip gate is known. Missing requirement
maps on normal tradeable ordinary items are assumed to mean no equip requirements;
this assumption is shown on the item. Known unmet or unknown skill requirements
still prevent use.
Authored skill/quest gates, explicitly unknown authored gates, and explicit mechanic
blockers take precedence over community data.

Only positively classified exact physical IDs can bypass the generic
`Offensive effects have not been validated.` marker. The original catalog retains
that marker. Known conditional mechanics are excluded; their ordinary damage is
not approximated by treating their effects as zero. Physical statistics, slots,
weapon/ammunition compatibility and combat formulas remain authoritative.
Ownership, exclusions, locks, budgets and supply/inventory constraints still apply.
An unowned item needs supported tradeability and a usable price; an unknown price
does not make it a free purchase.

Policy and classification provenance participate in result identity. The source
and evidence are recorded in `content/equipment/community.json`. This is a small
deterministic classification sidecar, not another approval/review workflow.

## Current ordinary-item policy

The `ordinary-v3` sidecar has no item-name category allowlist. Normal tradeable
equipment can qualify by default even when its equip requirement field is absent,
null, or empty. Populated maps must still pass validation, and authored metadata
takes precedence. Independent physical evidence, valid player-equippable forms,
weapon compatibility, and checks for indicated conditional mechanics still apply.
Generic effects markers are cleared for qualifying community items; explicit
unsupported mechanics remain blocked.

The regenerated sidecar contains 798 qualifying physical IDs (673 noncosmetic,
125 cosmetic), including Seers ring `6731` and Warrior ring `6735`. Archers ring
`6733` and Berserker ring `6737` retain their existing authored approvals. Steel
ring `30895` retains its exception for harmless enchanted examine text; other
items no longer need a name/category exception. `verified_only` retains its
reviewed-only rules. Eligibility does not guarantee selection by the optimizer.

## Initial coverage and remaining exceptions (ordinary-v1)

The preimplementation estimate was 241 additional IDs. Requiring existing
independent physical profiles and compatibility reduced this to **194 qualifying
IDs**: 119 noncosmetic forms and 75 trimmed/gilded variants, representing **137
distinct physical combat profiles** and 55 weapon IDs. Name/category matching alone
never qualifies an item: it also needs a populated valid requirements map, exact
identity, normal player-equippable GE source flags, a single ordinary physical
capture, matching physical statistics/slot, and existing weapon/ammunition
compatibility. Names/examine text also exclude indicated conditional mechanics.
This is a conservative community-data classification, not exhaustive effects proof.

With synthetic level-99 skills and completed quests, gates-and-model support rises
from **210 to 404 IDs**. This is a catalog upper bound, not an ownership or purchase
claim. No physical statistics or reviewed approvals were changed.

The sidecar records one exclusion reason per remaining exact ID: 3,423 lack valid
requirements, 803 have uncertain source form/acquisition flags, 148 have unresolved
variants/mechanics, 113 have slot disagreements, 31 lack weapon compatibility,
12 lack ammunition compatibility, and 401 fall outside the narrow ordinary
categories. Another 293 preserve authored metadata. Fifteen indicate conditional
mechanics and two are explicit special-attack exceptions: Rune thrownaxe `805`
(Chainhit) and Rune claws `3101` (Impale). These counts are mutually exclusive
classification reasons; they are not additional automatic approval candidates.
Charged/degrading/set/location-dependent equipment remains excluded. Existing
reviewed skill/quest gates remain binding even where community data disagrees.

The following counts and account results describe the original `ordinary-v1`
measurement and are historical, rather than current catalog totals.

## Measured account improvement

Measured against the local **19 October 2026, 22:05:44 UTC historical account
snapshot**, not the current live account. Both policies use the same frozen DB
image `91211f300401fa35b0808e1f8975fda6c28f7925240d1a1fe27bf2e7c51636e7`.

| Coverage before candidate truncation | Verified only | Community best effort |
| --- | ---: | ---: |
| Satisfied gates and supported ordinary model | 155 | 327 |
| Owned usable physical IDs | 78 | 82 |
| Unowned supported IDs with usable cached purchase price | 2 | 2 |
| Supported unowned tradeable IDs lacking price | 62 | 230 |

The actual account gains **172 gate/model-supported IDs**, but **four actually
usable owned items** after acquisition constraints: Rune knife `868`, Steel dagger
`1207`, Steel axe `1353`, and Rune axe `1359`. The other 168 newly supported items
are not observed owned and have no usable historical purchase price, so remain
unavailable. **Zero new purchases** qualify from this snapshot's two available
as-of price records; unknown prices remain unknown.

Representative single-role results against the same Defence/Magic 100 target:

| Scenario | Verified DPS | Community DPS | Median runtime, seconds |
| --- | ---: | ---: | --- |
| Owned melee (slash) | 2.43474 | 2.43474 | 1.129 → 1.178 |
| Owned ranged (rapid) | 2.08416 | 2.61181 | 1.162 → 1.316 |
| Owned magic | 1.60189 | 1.60189 | 1.562 → 1.464 |
| 50m usable melee | 2.43474 | 2.43474 | 1.457 → 1.312 |
| 50m usable ranged | 2.09543 | 2.63415 | 1.224 → 1.253 |
| 50m usable magic | 1.60189 | 1.60189 | 1.361 → 1.533 |

Ranged gains 25.3% owned DPS (25.7% with available purchases) by using the newly
available Rune knife and an existing offhand. Melee and magic retain the same
selected setups. These are ordinary attacks with unchanged formulas; special
utility, survival and sustained ammunition costs are not new modeled features.
Summed retained candidate-pool sizes rise 87→89 owned and 90→92 usable; explored
nodes rise by about 1,000–1,600. Two local timing repetitions show roughly
1.1–1.6 seconds per search, with normal timing noise. The candidate/beam limits
and search algorithm were not expanded or rebuilt.

The historical Phase 1 digest failure is separately resolved: all 23 pre-existing
approved bulk changes are explicitly allowed, while the original historical
digest is preserved. See `GEAR_REBOXED_REQUIREMENTS.md` for the verified cause.

## Reproduce the account comparison

The classification records physical-catalog, requirement-sidecar and independent
physical-capture SHA-256 values. Generation verifies the capture against the
physical manifest; the loader ignores classification with changed catalog or
requirements bytes.
Refresh requirements first using `GEAR_REBOXED_REQUIREMENTS.md`, then regenerate
the classification from the pinned source and physical capture:

```powershell
.\.venv\Scripts\python.exe -m tools.build_community_equipment `
  --source .tmp/osrsreboxed/items-complete.json `
  --capture .tmp/gear-reference/cdn/json/equipment.json
```

The capture must match the existing physical manifest. Regeneration writes the
community sidecar only; it does not change physical data or authored overlays.

```powershell
.\.venv\Scripts\python.exe -m tools.measure_community_gear `
  --database tracker.db --player-id 1 --at 2026-10-19T22:05:44Z `
  --repeats 2 --output .tmp/community-gear-measurement.json
```

The tool freezes a WAL-aware, read-only in-memory database image and uses the same
account, evaluation time, prices and requests for both policies. Raw output contains
private exact owned IDs and stays in ignored `.tmp/`. It reports physical IDs before
candidate truncation, actual owned and priced purchase coverage, a separately labeled
synthetic level-99 catalog upper bound, and distinct combat signatures so cosmetic
variants do not count as distinct combat improvements. Representative single-role
melee/ranged/magic cases use a Defence/Magic 100 target, both owned-only and a 50m GP
purchase budget. Timings describe this local bounded search, not a global optimum
or current live account acceptance.

## Validation

Targeted validation passed: 161 backend/service/API tests, 249 catalog/import/
classification/regression tests, 112 affected frontend tests, and one desktop
Chromium policy roundtrip. The policy module and classifier each have 100% focused
coverage; classifier plus generator coverage is 98%. Production frontend build,
scoped Ruff, whitespace checks and focused backend type checks passed. The suites
overlap; their counts are not a unique combined total. No deployment was performed.

## Purchase-price discovery fix (2026-10-28)

The price client already supported bulk Wiki `/latest`, but sync discovered only
authored primary tradeable IDs. It omitted all 194 community additions. Sync now
unions the existing authored scope with supported, explicitly tradeable physical
IDs from a freshly loaded community projection. Each refresh reloads classification
evidence, including its existing source-hash checks. Explicit effects and unknown or
false tradeability cannot enter through this additional scope. Discovery is independent
of one account's levels or ownership; evaluation still enforces those facts.

Equipment refresh explicitly requests bulk mode even if only one new ID lacks a
cached quote. Existing retry, cache TTL, manual throttle, persistence, timestamps,
provenance and acquisition-price selection remain unchanged. All-fresh automatic
refreshes still make no request. Account-only sync does not require catalog loading.
No UI, combat, search or catalog approval behavior changed.

A price-only call to the existing `run_pipeline` refreshed the configured local
database at **2026-10-28 06:06:36 UTC**, without WOM import or account writes. The
account fingerprint remained identical; its latest accepted sync is still
**2026-10-19 22:05:44 UTC**. Prices are evaluated at refresh time, rather than being
incorrectly filtered back to the old account observation date. Refresh scope: 441
IDs; 437 price rows written. Private exact-ID evidence and before/after optimizer
results are retained locally in ignored `.tmp/community-price-refresh.json`.

| Account-supported equipment | Verified | Community |
|---|---:|---:|
| Owned | 78 | 82 |
| Unowned and tradeable | 64 | 232 |
| Usable purchase quote before refresh | 44 | 44 |
| Usable purchase quote after refresh | 64 | 232 |
| Individually affordable purchases at 1M GP | 59 | 217 |
| Individually affordable purchases at 5M GP | 63 | 227 |
| Individually affordable purchases at 50M GP | 64 | 232 |
| Missing or unusably stale purchase quotes after refresh | 0 | 0 |

Budget rows count unowned physical IDs whose individual existing acquisition cost
fits the budget, before scenario compatibility and candidate truncation; they do
not claim that all those items can be bought together. Adding owned items gives
137/141/142 available IDs for Verified and 299/309/314 for Community at those budgets.
All accepted account purchase quotes also have recent trades; none require the
existing stale-trade cached fallback. The previous historical report's 230 missing
quotes used prices available at the October 19 observation time; this run started
with 188 missing community quotes at current evaluation time and resolved all 188.

Four IDs in the broader retained authored discovery scope have no cached quote:
23971 Crystal helm, 23975 Crystal body, 23979 Crystal legs and 27624 Ancient sceptre.
They do not pass this account's supported-equipment filter. They remain unknown,
with no guessed price, ID substitution or free-purchase assumption.

Representative unchanged 50M GP, zero-swap, single-role scenarios against Defence/
Magic 100: both policies retain melee **2.47005 DPS** and ranged **2.79552 DPS**.
Verified magic stays **1.60819 DPS**; Community magic rises to **1.63840 DPS**
(1.88%), purchasing Infinity top (6916), gloves (6922), bottoms (6924), plus existing
supported Infinity boots (6920), for **5,278,273 GP** total. These are bounded-search
results on the stored account, not new combat formulas or live account acceptance.
Melee/ranged selected IDs remain unchanged; market refresh updates purchase costs.

Focused validation: 115 sync/pricing/staleness/support regression tests passed
(91% pipeline coverage), followed by all eight pipeline tests after adding the
account-only catalog-independence regression. Ruff and whitespace checks passed.
The three changed source modules pass mypy with dependency traversal suppressed;
normal traversal reports an existing unrelated `no-any-return` in
`tracker/gear/priorities.py:48`, which this pricing change leaves untouched.
