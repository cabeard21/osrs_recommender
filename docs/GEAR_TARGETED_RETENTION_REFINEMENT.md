# Targeted Candidate Retention Refinement

## Outcome and milestone boundary

Implemented an additive omitted-head refinement for one ordinary melee role.
It recovers both established strength breakpoints while preserving the original
optimizer's final ordering at every action limit. Discovery remains bounded:
results continue to say `best_found`, not globally optimal.

The Python API is explicitly opt-in:

```python
optimize(snapshot, request, catalog, content, prices, now,
         targeted_head_refinement=True)
```

The new keyword is keyword-only and defaults to `False`. Existing positional
arguments remain compatible. It is absent from `OptimizationRequest` and from
service, UI, HTTP and MCP routing. Normal calls retain their original response
shape. No production enablement, deployment, catalog change, combat-formula
change, commit or push is part of this milestone. Existing unrelated worktree
changes were preserved.

The account evidence uses the same snapshot and as-of prices as the retention
assessment, evaluated at `2026-10-19T22:05:44+00:00`. It is historical local
development evidence, not current live account or Pi acceptance.

Publication boundary: the earlier detailed account audit, Phase 1 report,
catalog/importer changes and authored Phase 1 overlay remain a separate local
milestone. They are not included in the refinement commit. The exact account
benchmark numbers below require those matching Phase 1 inputs; a clean checkout
with different catalog hashes may produce different account results. Synthetic
fixtures and the offline benchmark infrastructure are included. The historical
171-test regression count includes the local Phase 1-specific test module;
the generic reproduction command below omits that unpublished module.

## Trigger, algorithm and result preservation

`tracker/gear/targeted_retention.py` runs after existing ammunition refinement
and before curve, alternatives and item-fact assembly. It requires:

- Exactly one positive-weight ordinary `stab`, `slash` or `crush` role, without
  transitions, ordered roles, looping or a parent role.
- No global or role head lock, including an explicit empty-head lock.
- At least one eligible concrete head absent from the original head pool.
  This directly establishes relevant head truncation; the global truncation
  flag alone does not trigger refinement.
- A supported completed baseline incumbent.

Owned, usable and future modes reuse the original projected snapshot and access
facts. Eligibility is not reinterpreted. Exclusions, requirements, acquisition
prices, ownership and assumed physical IDs retain their existing meanings.

Distinct original curve and unrestricted winners become frozen seeds, sorted
by concrete equipment identity. For each seed and omitted head, trials include
the head alone and the head paired with one unlocked cape, neck, body, legs,
hands, feet or ring slot. Companion choices include empty and **all eligible
physical items**, including alternatives omitted from their candidate pools.
The seed's unchanged companion choice is skipped. Pair trials do not depend on
a beneficial single substitution.

The scheduler cycles through seed/head queues and, within each queue, through
singleton and companion-slot groups. Each active group yields one assignment
per turn. Heads and item alternatives use stable numeric ID ordering; companion
groups use the slot order above. Empty is the first companion alternative.
Exhausted groups are removed. Global equipment-identity deduplication occurs
before counting work.

The maximum is **2,000 distinct complete assignments**, independent of explored
nodes. A private helper parameter can reduce this limit for tests but cannot
raise it. Exhaustion means another distinct assignment remains after the cap;
finishing exactly at the cap is not exhaustion. Cancellation is checked at entry,
during eligibility/group preparation, scheduling and duplicate handling, before
validation and before return. It raises the existing
`ValueError("optimization_cancelled")`.

Every trial goes through `_Search.solution(assignment, None)`, which validates
complete equipment and recalculates exact combat, locks, access, purchase union,
cost, inventory and action facts. No trial is repaired or followed by ammunition
refinement. Only its head and explicitly selected companion slot can change.
Original search pools, beams, pruning, ordering, scoring and million-node budget
are unchanged; refinement never calls `search.tick()`.

A valid trial is offered to unrestricted mode and each compatible curve point.
It replaces an incumbent only when the existing `_solution_key` is strictly
smaller: weighted DPS first, then inventory peak, cost, total transition actions
and stable loadout serialization. Original incumbents remain available in
`search.targeted_head_refinement.baseline`, with `curve_solutions` and
`unrestricted` snapshots. Their referenced item facts remain in the response.
Final selected solution, alternatives, purchases, relative performance and
suggested action limit are assembled from the resulting winners.

This proves baseline nonregression under that ordering by induction over
accepted trials. It does **not** prove discovery optimality or preserve every
unscored bonus. Equal-DPS changes can be accepted by later ordering fields.
Relative percentages can change when the unrestricted denominator improves.

### Diagnostics

Enabled calls add `search.targeted_head_refinement`:

| Field | Meaning |
| --- | --- |
| `triggered`, `reason` | Trigger or skip decision |
| `eligible_omitted_item_ids` | Eligible heads absent from the baseline pool |
| `inspected_item_ids` | Heads actually used in evaluated trials |
| `assignment_attempts`, `valid_assignments` | Distinct exact checks and successful validations |
| `improvements_accepted` | Trial assignments accepted by at least one incumbent |
| `incumbent_replacements` | Total curve/unrestricted replacements; one trial can replace several |
| `work_budget`, `work_budget_exhausted` | Maximum distinct checks and remaining-work indicator |
| `duration_seconds` | Helper runtime, including preparation and baseline snapshot copying |
| `performance_cache_misses` | New performance cache entries created during the helper |
| `baseline` | Recoverable original accepted incumbents |

Reasons are `eligible_omitted_heads`, `unsupported_scenario`, `head_locked`,
`no_eligible_omitted_heads`, and `no_supported_baseline`. Skipped calls attempt
zero assignments and retain original result fields apart from added telemetry.
Timing is observational and does not affect scheduling or acceptance.

## Correctness and benchmark evidence

### Independent fixtures

The existing fourteen exhaustive catalogs contain 590 supported joint
assignments and 38 action-limit curve points. Baseline, targeted and broad
refinement give 42 benchmark cells. Every cell receives one warm-up and five
timed repetitions. Semantic response hashes agree across repetitions. Only the
two explicitly named elapsed-time fields are excluded from determinism hashes;
counts, identities, decisions and solution facts remain included.

Targeted refinement triggers on the two breakpoint fixtures and matches their
independent exhaustive maximum at every curve point and unrestricted mode.
The other twelve fixtures retain their original result fields and run zero
targeted assignments. Their multi-role cases verify rejection compatibility,
not multi-role refinement support. Every feasible tiny benchmark result passes
independent solution validation.

Both breakpoints use level-70 accurate slash, a zero-bonus weapon `100`, and
heads `1..12`; head `12` supplies `+3` melee strength and is omitted by the
baseline pool. In the single case, cape `20` supplies another `+3`. In the
double case, capes `21..32` are present and useful cape `32` is also omitted.
Either single change in the double case still hits 8; the coordinated pair hits
9. All baseline heads tie in scaffold DPS, so a marginal tie is not dominance.

| Fixture / strategy | Max hit | DPS | Full median ms | Refinement median ms | Extra assignments | Explored nodes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Single / baseline | 8 | 1.606914532662 | 5.299 | 0 | 0 | 414 |
| Single / targeted | 9 | 1.798007071681 | 5.461 | 0.220 | 2 | 414 |
| Single / broad | 9 | 1.798007071681 | 7.142 | 1.788 | 25 | 414 |
| Double / baseline | 8 | 1.606914532662 | 24.576 | 0 | 0 | 2,110 |
| Double / targeted | 9 | 1.798007071681 | 26.178 | 1.133 | 13 | 2,110 |
| Double / broad | 9 | 1.798007071681 | 35.075 | 10.384 | 168 | 2,110 |

All targeted breakpoint trials are valid; each fixture accepts one improving
assignment and finishes without exhausting the cap. The absolute DPS recovery
is `0.19109253901925083`. Uncached performance evaluations, unlike assignment counts,
also include normal response alternatives and scaffolds.

Additional tests compare exhaustive outcomes for purchases costing 40 GP for
head `12` and 60 GP for cape `32`, with budgets 99, 100 and 101 GP. The pair is
accepted only when affordable; purchases retain both distinct physical IDs.
Future fixtures exercise explicit skill and quest assumptions and an unowned
assumed head without creating a purchase or changing the account snapshot.

### Frozen account

The original five observed omitted IDs remain reproducible: `3755`, `6326`,
`10589`, `10828`, and `13385`. Only omitted heads `10828` and `13385` are relevant
to supported targeted Slash/Crush refinement. Stab has no supported baseline;
ranged and magic are outside this milestone.

Each timing cell below is **full median ms / refinement-only median ms**.
"Broad" is the existing broader experimental `refinement` strategy, whose search
behavior remains unchanged.

| Account role | Baseline | Targeted | Broad | Explored nodes, all three |
| --- | ---: | ---: | ---: | ---: |
| Stab | 318.55 / 0 | 321.51 / 0.029 | 320.51 / 0.066 | 596 |
| Slash | 709.26 / 0 | 736.43 / 14.056 | 1,106.68 / 399.319 | 14,740 |
| Crush | 712.31 / 0 | 727.97 / 14.032 | 1,124.69 / 408.213 | 15,412 |
| Ranged | 710.36 / 0 | 713.57 / 0.087 | 1,075.56 / 421.049 | 13,852 |
| Magic | 813.40 / 0 | 806.03 / 0.088 | 1,282.39 / 467.826 | 16,468 |

Targeted refinement evaluates 78 valid assignments per supported role, inspects
both omitted heads and completes without exhaustion. It creates 78 new
performance-cache entries per role. Broad refinement performs 2,000 checks in
each supported account scenario and reaches its experimental cap.

There is **no account DPS or max-hit gain** from either refinement:

| Role | Selected DPS, all three | Max hit |
| --- | ---: | ---: |
| Slash | 3.459484774723177 | 17 |
| Crush | 2.0028343237661734 | 10 |
| Ranged | 2.269539708519421 | 11 |
| Magic | 1.324090634558809 | 8 |

All selected costs are zero. Stab has no feasible result found, not a newly
proven realistic-catalog infeasibility result. Targeted Slash accepts no change.
Targeted Crush accepts three equal-DPS ordering improvements, producing 30
incumbent replacements across nine curve points and unrestricted mode.
Its final trial changes head `3751` to `10828` and feet `21643` to `1061`.
Max hit and accuracy stay equal; melee strength drops from 32 to 29, stab defence
from 172 to 157, and prayer rises from 8 to 11. These are existing serialization
tie-break choices, not DPS gains or Pareto improvements. The original setup
remains recoverable. No extra defence preference was added to final scoring.

Relative to measured baseline medians, targeted full runtime rises about 3.8%
for Slash and 2.2% for Crush, versus about 56.0% and 57.9% for broad refinement.
The helper itself takes about 14 ms. Full-run differences also include changed
normal alternatives/cache behavior and measurement variation; they are not
equal to helper time. The account run takes 69.56 seconds and tiny run 3.01
seconds, excluding process startup. Raw individual samples and min/max values
are retained in the artifacts. Measurements use Python 3.12.10 on Windows;
they are descriptive, not service latency or Pi guarantees.

Baseline account responses, excluding existing research metadata, exactly match
the previous assessment's frozen benchmark outputs. Baseline snapshots and
ordering are checked at every account curve point. All 120 feasible account
curve/unrestricted outputs across the three strategies pass independent exact
validation.

### Frozen identities and reproduction

| Input | SHA-256 / identity |
| --- | --- |
| Snapshot | `88aa8d3d8f6e9986c8e3d6b91fdc54622659986ee1cf58baf5117d4567039fc4` |
| As-of prices | `da403267078d0fc1495e18fd6696e68a1fb127f9b1544d0ad0c5cdf4cb6409de` |
| Catalog | `3a8e2651ad4c7d44c02238cbd7d7dcbb3186df446c75ca60d48ecfee3cd9d19c` |
| Source DB | `50bd3ca819861989b031f366f75d6e1959e2a366a8db45271fc65887b69321f8` |
| Source WAL | `9879381315cc8b1d320e62d7f4d0de4507a561c3207d71698824b4eabdbe51ab` |
| Frozen SQLite image | `2d74d48d1a30b9b95c0d180e4d346ab0295d242521c222fe444e2d24e7c4c9ef` |
| Optimizer integration | `9eadbf807ed3006e69957d5985efbb3dd5cefdece158a26fac3a5c736a54791f` |
| Targeted helper | `ad131e78b04f63be33466bcb43a84df39a8cd0f002f5fb36f7cc5a0994697f15` |

WAL and frozen-image hashes differ from the earlier assessment while the source
database hash, logical account and as-of prices are identical. The capture checks
source hashes before and after read-only, WAL-aware copying. Both final benchmark artifacts share
identical source hashes, verified again against the completed implementation.
Raw account artifacts remain private under ignored `.tmp` paths.

```powershell
.venv/Scripts/python.exe -m tools.assess_gear_retention --tiny --strategy baseline --strategy targeted --strategy refinement --repeats 5 --output .tmp/gear-targeted-retention/tiny-final.json
.venv/Scripts/python.exe -m tools.assess_gear_retention --database tracker.db --player-id 1 --at 2026-10-19T22:05:44+00:00 --strategy baseline --strategy targeted --strategy refinement --repeats 5 --output .tmp/gear-targeted-retention/account-final.json
```

Use fresh output filenames; existing files are rejected. The runner records
requests, catalogs, source fingerprints, full responses, deterministic semantic
hashes, full-run timings and refinement-only timing arrays. Tiny results include
exhaustive comparisons and independent validation. Its scoped research class
patch remains serial and confined to the CLI process; the actual targeted
optimizer implementation uses no global monkeypatch.

## Verification, limitations and next steps

Tests were written before implementation: initial integration failures identified
the missing opt-in keyword, core tests identified the missing module, and harness
tests exposed elapsed-time nondeterminism before timing normalization existed.
Focused tests cover trigger rejection, exact locks/exclusions/access, budget and
purchase identity, future assumptions, no unnamed slot changes, cancellation,
round-robin fairness, deduplication, cap boundaries, baseline recovery and
determinism. CLI subprocess tests exercise baseline, targeted and broad modes.

The independent oracle now supports existing future projections and assumed-ID
purchase semantics. It also checks purchase-row facts and reported global
action/inventory aggregates against replayed paths, while allowing different
valid shortest paths with different inventory peaks.

Final focused verification passes **297 tests in two separate lanes**:
126 milestone/infrastructure tests and 171 existing gear regressions. The new
helper has **100% branch-aware coverage**; the five measured modules together
have **92.67%** coverage (optimizer integration, helper and three research tools).
The default-cap stress test generates more than 4,200 possible assignments,
evaluates exactly 2,000 distinct trials, visits both heads and cape/ring/feet
groups, and preserves inputs, pools, nodes and baseline snapshots.

Scoped Ruff lint and formatting checks pass for ten files, and mypy passes for
five source modules. Whitespace and ignored-private-artifact checks pass.
Independent read-only implementation/report review found no high or medium
correctness issue. One mixed invocation reported 18 missing gear-fixture setup
errors; both final separate lanes pass without changing fixture configuration.
Browser or live deployment acceptance is not claimed.

Publication verification additionally passes 222 focused tests against an export
of the 18 staged files plus their tracked prerequisites, using the original
published catalog rather than local Phase 1 edits: 142 research/audit tests and
80 optimizer regressions. The byte-sensitive catalog is checked using its exact
staged blob bytes. Scoped lint/type checks include the offline audit helpers;
the dependency audit finds no known vulnerabilities in auditable packages
(two local packages are unavailable on PyPI). Detailed account reports, private
benchmark artifacts and local Phase 1 metadata remain outside this commit.

```powershell
.venv/Scripts/python.exe -m pytest tests/gear/test_targeted_retention.py tests/gear/test_targeted_retention_integration.py tests/test_assess_gear_retention.py tests/test_gear_retention_oracle.py tests/test_gear_retention_strategies.py -q --cov=tracker.gear.optimizer --cov=tracker.gear.targeted_retention --cov=tools.assess_gear_retention --cov=tools.gear_retention_oracle --cov=tools.gear_retention_strategies --cov-branch --cov-fail-under=80 --basetemp .tmp/targeted-milestone-verify
.venv/Scripts/python.exe -m pytest tests/gear/test_optimizer.py tests/gear/test_coverage_audit.py tests/gear/test_ammunition_sharing.py tests/gear/test_transitions.py tests/gear/test_evaluation.py tests/gear/test_optimizer_service.py tests/gear/test_optimizer_facts.py tests/gear/test_optimizer_fingerprint.py -q --no-cov --basetemp .tmp/targeted-existing-verify
```

The 2,000 cap bounds validations, not wall-clock duration or all preparation
work. If queues outnumber available attempts, some cannot be visited. Seed-only
one/two-slot neighborhoods cannot discover every three-slot or weapon-dependent
combination. Multi-role sharing, equipment transitions and inventory pressure
are deliberately not refined; ordinary single-role solutions have no between-role
actions and carry their equipped union, so those constraints are largely vacuous
here. Existing transition regressions remain necessary compatibility evidence.

Keep the feature disabled in production routing. The narrow algorithm delivers
the synthetic correctness recovery with substantially less work than broad
refinement, but this audited account supplies no practical DPS benefit. Review
representative additional single-role cases and latency before any separate
enablement decision. Do not broaden slots, roles or the budget based on this
milestone, and do not infer global realistic-catalog optimality.
