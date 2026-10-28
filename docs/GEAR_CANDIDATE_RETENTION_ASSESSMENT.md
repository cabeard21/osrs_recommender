# Gear Candidate Retention Assessment

## Finding and decision

The existing candidate cap demonstrably loses complementary strength equipment.
Marginal scaffold DPS ties are not dominance: two individually ineffective `+3`
strength additions can cross a full-loadout max-hit breakpoint. Expanding pools,
numeric Pareto retention, diversity retention, shared-role retention, and exact
finalist refinement all recover the small counterexample in this assessment.

**Recommend a separate, narrowly scoped additive refinement milestone, not a
production pool-policy replacement.** Keep every baseline incumbent at every
action limit, evaluate additional complete loadouts, and accept only valid
improvements under the existing final solution ordering. This preserves baseline
answer quality by construction. Discovery of better combinations remains
heuristic. No production search policy or cutover is implemented here.

The account boundary remains the Phase 1 local development account: accepted
observations from October 19, 2026, evaluated at `2026-10-19T22:05:44Z`, with the
current Phase 1 reviewed metadata. It is not today's live account or Pi state.
The checkout already contains the Phase 1 catalog/audit work and unrelated edits;
this assessment preserves them.

Publication note: this assessment and its research infrastructure accompany the
targeted-refinement commit. The earlier detailed account audit, Phase 1 report,
catalog/importer changes, authored overlay and Phase 1-specific tests remain
separate local work. Exact account measurements require the recorded Phase 1
input hashes. Historical validation counts include that work; the generic
reproduction command below omits its unpublished test module. Synthetic cases
remain independently reproducible from the refinement commit.

## Reproductions and search-stage analysis

### Candidate breakpoint

At level 70 accurate slash, weapon `100` has zero bonuses. Heads `1..11` have
zero bonuses; head `12` adds `+3` melee strength; cape `20` adds another `+3`.
All are owned, requirements-complete, and ordinary-model supported. Each head
ties standalone scaffold DPS at `1.6069145326618806`.

The unchanged head pool is `[None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]`.
The bounded answer hits **8**, with DPS `1.6069145326618806`; full enumeration
includes head `12` plus cape `20`, hits **9**, and reaches
`1.7980070716811314` DPS. The absolute gap is `0.19109253901925083`.
The `breakpoint` fixture enumerates all 26 supported complete assignments.

The stronger `double_breakpoint` fixture has 12 heads and 12 capes. Heads
`1..11` and capes `21..31` are neutral; head `12` and cape `32` each add `+3`.
Both useful IDs are omitted. Either single replacement still hits 8; their pair
hits 9. Enumeration covers 169 supported assignments. This directly exercises
pair evaluation without assuming that a profitable sequence of single edits
exists.

### Five observed IDs

The fresh read-only account audit reproduces exactly five distinct observed
physical IDs and eight eligible item/role omissions:

| Physical ID | Item | Eligible roles omitting it |
| --- | --- | --- |
| 3755 | Farseer helm | ranged |
| 6326 | Snakeskin bandana | magic |
| 10589 | Granite helm | ranged, magic |
| 10828 | Helm of Neitiznot | slash, crush |
| 13385 | Xerician hat | slash, crush |

There are 13 eligible heads plus empty before retention. The production pool has
12 options. Pool omission establishes neither a combat-model blocker nor a lost
account optimum. These are separate single-role requests, not one five-role
request. The stab scenario lacks a supported weapon scaffold; its truncation
flag is not evidence of lost supported stab equipment.

### Where complementary choices disappear

1. **Pools:** `_Search.candidate_pools()` interleaves cheapest items and per-role
   scaffold-DPS rankings, prefixes explicit locks, then takes 11 concrete IDs plus
   empty (or more when required by locks). Equal cost/DPS resolves by physical ID.
   The best score across scaffolds does not describe every surrounding loadout.
2. **Role/common beams:** exact partial weighted DPS sorts first, then cost.
   All-melee ties prefer greater melee strength before IDs; mixed roles do not
   have this tie protection. Width is 128. This later preference cannot recover
   an ID already absent from its pool.
3. **Joint branches and beam:** each role receives empty, its top two marginal
   choices, and one weighted common choice, except where locked. Retaining an ID
   does not ensure branching on it. Width is 16, ranked by summed marginal values,
   union size, cost, and stable identity rather than exact complete encounter DPS.
4. **Tuple combination and node limit:** constrained searches run separately for
   each action limit and unrestricted mode. Role/common/joint/tuple expansion
   share the million-node budget; extra early work can deprive later stages.
5. **Existing refinement:** ammunition sharing revalidates a small finalist set.
   It does not introduce omitted head/cape strength alternatives.

The research wrapper records baseline/experimental pools, marginals, per-stage
node ranges, role/common survivors, joint survivors, and joint branch options.
It does not instrument each internal beam eviction; absence from a final stage
alone is not assigned to a specific intermediate eviction. Tests independently
show that widening the role beam to 10,000 cannot recover the omitted head,
whereas retaining it with a width-one all-melee beam recovers the breakpoint.

## Experiments and correctness boundaries

The standalone runner patches a research `_Search` subclass only within its own
serial CLI process and restores the class and optional beam-width override even
on failure. No application import, extension point, or public schema was added.
Baseline output, excluding added research diagnostics, is tested equal to a
direct unmodified optimizer call.

| Strategy | Exact experimental definition | Guarantee boundary |
| --- | --- | --- |
| `baseline` | Production pools, beams, ordering and limits | Existing bounded `best_found` |
| `all` | All eligible IDs plus empty; unchanged later search | Removes pool truncation only |
| `pareto` | Strict nondominance over every bonus field and negative singleton purchase cost within equal slot/speed/styles/profiles/handedness/ammo/effect signature; keep all exact-equal IDs and locks | Conditional numeric comparison, not an end-to-end search proof |
| `diversity` | Baseline pool union numeric frontier, in stable ID order | Preserves strength/accuracy/magic tradeoffs; larger bounded search can still regress |
| `shared` | Baseline pool union frontier over all role scaffold DPS values and negative cost; exact ties keep all IDs | Protects some shared alternatives; scaffold vectors still hide breakpoints |
| `refinement` | Original baseline followed by up to 2,000 distinct exact complete joint assignments: singles, two-slot edits, coordinated same-slot role assignments | Baseline final ordering cannot worsen; discovery is bounded |

Frontiers are not truncated back to 12. All experiment variants retain explicit
locks, empty options and physical identities. The numeric frontier includes
attack, both strength types, magic damage, every defence bonus and prayer; no
weighted bonus desirability score is introduced.

Numeric IDs are categorical, not coordinates to minimize. Collapsing identical
physical items into one ownership/acquisition identity is invalid. The
`identity_equal` fixture locks two otherwise equal heads into different roles:
the true purchase union costs 200 GP and requires two equipment actions. The
strict Pareto experiment deliberately keeps both equal IDs and both locks.
This is an identity-collapse counterexample, not a falsely attributed failure of
that implemented Pareto strategy.

A proof of cross-ID discard would need a globally applicable substitution that
preserves compatibility, locks, all role performance, purchase union cost and
directed inventory/action feasibility. Stat superiority in one role or a lower
singleton price alone does not establish those conditions. This assessment
does not disprove every carefully conditioned global Pareto substitution, nor
does passing these fixtures establish such a theorem.

The exhaustive reference uses full-catalog Cartesian enumeration, independent
lock/union/budget/score calculations, and an independent all-carried-item action
state graph ordered by shortest actions and minimum peak inventory. It reuses
access facts and exact combat evaluation, so independence concerns search and
constraint aggregation, not a second implementation of combat formulas.
Reported paths are separately replayed: a valid production shortest path can
have a different peak from the oracle's minimum-peak shortest path. Physical
winner equality is not required when final tie serializations differ.

### Joint roles and constraints

Joint quality is weighted complete-role DPS subject to one distinct physical-ID
purchase union and every configured transition. Shared equipment can save both
GP and actions even when individually weaker. Capacity includes transient hand
displacement, not only endpoint inventories. Zero-weight ordinary roles and
unscored special roles still constrain equipment, purchases and transitions.

All candidate experiments run through the production complete-loadout validator.
The tiny-suite runner additionally checks each feasible curve point and
unrestricted solution with the independent validator, including exact role
performance, locks/access, purchases, score, capacity and replayed paths.

Additive refinement retains the original incumbent separately at every action
limit and for unrestricted mode. By induction, accepting only a strictly better
existing solution key cannot worsen that key. This is a baseline-quality
guarantee, not optimality. It does not guarantee unchanged per-role DPS,
defence/prayer, purchases or actions when higher weighted DPS is accepted within
the original limits. Relative percentages may decrease when the unrestricted
denominator improves. These distinctions must remain visible in any future UI.

Refinement currently scans original seeds in stable order: role singles and
pairs precede coordinated assignments. Its 2,000-attempt cap can starve later
roles, seeds, or coordinated edits. It is a feasibility experiment, not the
recommended final scheduling policy. Additional refinement evaluations do not
consume or masquerade as production explored nodes.

## Exhaustive benchmark results

Fourteen small catalogs produce 590 joint assignments after per-role support
filtering and 38 action-limit curve points. Six strategies give 84 benchmark
cells. Every cell receives one warm-up and five timed runs; full deterministic
response hashes, including diagnostics, agree across repetitions.

Every experimental strategy matches all oracle feasible curve scores and
unrestricted scores in this suite. Baseline matches all except the two
breakpoints. All feasible outputs pass independent validation. Observed
purchase unions, costs, maximum actions and capacity peaks also match the oracle
at every feasible curve point, including the baseline breakpoint answers.
This finite result is not a general guarantee for the experimental strategies.

| Fixture | Supported joint assignments | Main boundary exercised |
| --- | ---: | --- |
| `breakpoint` | 26 | One omitted complementary strength item |
| `double_breakpoint` | 169 | Both complementary items omitted; singles do not raise max hit |
| `joint_shared` | 16 | One-action shared head vs two-action specialist heads |
| `budget_union` | 16 | Shared 100 GP purchase vs two 80 GP specialist purchases over budget |
| `identity_lock` | 4 | Role lock and one-action shared identity |
| `exclusion_empty` | 1 | Explicit empty head lock and excluded physical ID |
| `hands` | 1 | Two-handed to one-handed-plus-shield, directional actions, capacity two |
| `hands_capacity` | 1 | Same request with capacity one; exhaustive infeasibility |
| `ranged_magic` | 16 | Ranged accuracy/strength vs magic accuracy/damage, role weight two |
| `roles_3` | 64 | Three-role looping transitions and zero-weight ordinary role |
| `roles_4` | 256 | Four-role looping transitions and zero-weight ordinary role |
| `special` | 16 | Locked unscored utility role and parent transitions |
| `identity_equal` | 1 | Equal stats, distinct locked IDs, 200 GP union, two actions |
| `ammunition` | 3 | Arrow/bolt compatibility and shared ammunition |

For example, `joint_shared` reaches `2.086126452568111` DPS at one action and
`2.2788286394843773` at two. Under the 100 GP `budget_union` constraint, both
curve points instead reach `2.086126452568111` with the shared purchase.
The `hands` fixture becomes feasible at two actions with peak inventory two;
the capacity-one version has no valid assignment. These tiny infeasibility
conclusions are exhaustive; real-catalog bounded failures are not.

### Breakpoint time and work

Times below are Windows medians in milliseconds. "Evaluations" counts uncached
performance requests, not merely explored nodes; it includes scaffold work.
Special-role cache entries in other fixtures are unscored, so these counters
must not be interpreted as independent combat-model invocations in every case.
Refinement complete-assignment checks are reported separately, including checks
that reuse cached performance.

| Strategy | Single breakpoint ms / nodes / evaluations | Double breakpoint ms / nodes / evaluations | Extra full assignments, single / double |
| --- | --- | --- | --- |
| baseline | 5.03 / 414 / 27 | 24.70 / 2,110 / 148 | 0 / 0 |
| all | 5.40 / 448 / 28 | 25.93 / 2,162 / 171 | 0 / 0 |
| pareto | 2.00 / 74 / 17 | 2.83 / 74 / 28 | 0 / 0 |
| diversity | 5.85 / 448 / 28 | 25.94 / 2,162 / 171 | 0 / 0 |
| shared | 5.65 / 448 / 28 | 25.75 / 2,162 / 171 | 0 / 0 |
| refinement | 6.81 / 414 / 28 | 34.58 / 2,110 / 171 | 25 / 168 |

Both baseline answers hit 8; every other answer hits 9. Pareto removes the
strictly inferior neutral equipment in these cases. Shared retention also
recovers them because all scaffold-DPS ties survive its frontier, including the
useful items. This success does not demonstrate general breakpoint awareness.
The four-role fixture's refinement median is 81.4 ms versus 39.5 ms baseline,
with 256 extra assignment checks and no score improvement; coordinated search
has a visible cost even on small inputs.

## Frozen-account benchmark results

The final account run covers another 30 cells with one warm-up and five timed
runs each. Account and tiny runs have identical source fingerprints. They take
124.47 and 4.98 seconds respectively, excluding process startup; the final
measurement workload fits comfortably inside the selected 15-minute budget.
Measurements are serial, Python 3.12 on Windows, descriptive rather than latency
guarantees. No Pi or multi-user performance is inferred.

Every strategy returns the same selected DPS and max hit in each supported
single-role scenario; every selected purchase cost is zero. None reaches the
million-node limit. Stab returns no feasible solution found with every strategy;
the absence of a supported scaffold is independently known, while its generic
bounded-search status is not a global infeasibility proof.

| Role | Selected DPS, all strategies | Max hit |
| --- | ---: | ---: |
| slash | 3.459484774723177 | 17 |
| crush | 2.0028343237661734 | 10 |
| ranged | 2.269539708519421 | 11 |
| magic | 1.324090634558809 | 8 |

Each timing/work cell is **median milliseconds / explored nodes**:

| Role | baseline | all | pareto | diversity | shared | refinement |
| --- | --- | --- | --- | --- | --- | --- |
| stab | 314.5 / 596 | 313.1 / 596 | 314.5 / 432 | 316.5 / 596 | 318.7 / 596 | 309.5 / 596 |
| slash | 692.3 / 14,740 | 705.9 / 14,964 | 580.7 / 10,208 | 704.1 / 14,852 | 705.5 / 14,740 | 1,134.4 / 14,740 |
| crush | 723.5 / 15,412 | 747.9 / 15,748 | 584.4 / 10,768 | 706.2 / 15,580 | 714.1 / 15,748 | 1,111.4 / 15,412 |
| ranged | 719.9 / 13,852 | 740.6 / 13,928 | 610.4 / 10,028 | 711.2 / 13,928 | 755.0 / 13,852 | 1,076.5 / 13,852 |
| magic | 795.9 / 16,468 | 800.2 / 16,980 | 668.1 / 12,208 | 812.0 / 16,980 | 793.4 / 16,468 | 1,273.1 / 16,468 |

Pareto reduces supported-role nodes by approximately 26–31% and median time by
15–19%, with unchanged selected DPS. This is an empirical efficiency result,
not proof that its bounded search always preserves the baseline answer.
Its head pool has ten options; all-pool retention has fourteen versus the
baseline's twelve. The diversity/shared variants have role-dependent sizes.

Refinement reaches its 2,000-assignment cap in each supported account scenario,
adds approximately 50–64% median runtime, and improves no selected score.
Performance-cache misses rise from 5,866 to 7,782 for slash; 6,206 to 8,122 for
crush; 5,961 to 7,830 for ranged; and 7,043 to 8,920 for magic. Production explored
nodes deliberately remain unchanged; these extra assignment checks and cache
misses prevent a misleading claim of zero additional work. Stab has no finalist
to refine and performs zero refinement assignments.

All raw minima, maxima, five individual timing samples, node counts and cache
misses for every strategy are retained in the JSON artifacts. No strategy cell
timed out or was omitted. No broad random-catalog sweep, realistic joint-account
optimality oracle, or worst-case latency bound was attempted under this budget.

### Fingerprints

These are the final run's SHA-256 identities; full file fingerprints are in both
JSON artifacts:

| Input | SHA-256 / identity |
| --- | --- |
| Frozen SQLite image | `2f4d717ce66ba97011b32c0160ea0dfafd74d9445100a23b915d8996d4d40496` |
| Source database | `50bd3ca819861989b031f366f75d6e1959e2a366a8db45271fc65887b69321f8` |
| Source WAL | `75e7bd44e095634e5d5dee6da78b528492c2d2ed52dcbdd0f0217d908906ecbc` |
| Account fingerprint | `88aa8d3d8f6e9986c8e3d6b91fdc54622659986ee1cf58baf5117d4567039fc4` |
| As-of prices | `da403267078d0fc1495e18fd6696e68a1fb127f9b1544d0ad0c5cdf4cb6409de` |
| Normalized catalog | `3a8e2651ad4c7d44c02238cbd7d7dcbb3186df446c75ca60d48ecfee3cd9d19c` |
| Unchanged production optimizer | `1e3fccc3f655c02213178622e420a4a2737a711a6bced9f13de4dff18c937313` |
| Research runner | `8d3e489e56275aedce72befe44564e56d57ca8492d13e4287e42012524e4ac92` |
| Reference oracle | `abb2325699fb48a9d2f53a0a38eb919a4536cec0582bf1cc85b34bb6c035bf59` |
| Experimental strategies | `1a3459c1e6b1f4a3ab18d0754e6f44c8bab3db374f7da0c04f699cda07937e95` |

## Recommended next implementation, without cutover

Do not promote any tested pool replacement as the default. Numeric Pareto is
promising for reducing work, but needs a separate conditional-substitution proof
and adversarial bounded-search tests. Larger pools alone also leave joint
branching and budget competition unresolved.

The next implementation should be an **additive omitted-head refinement for a
single ordinary melee role**, triggered only when that head pool is truncated.
Keep baseline candidate limits, beams and ordering. Inspect eligible omitted
heads as single replacements and pair each with alternatives in one other
unlocked non-weapon/non-shield/non-ammunition slot. Use full eligible slot
choices, not just retained candidates; pair combinations must be evaluated even
when neither single substitution improves DPS. Protect all global/role locks and
exclusions. Keep every baseline curve/unrestricted incumbent and accept changes
only after full validation and the existing final solution comparison.

Use a separately reported deterministic cap of 2,000 complete assignments,
deduplicate assignments, and round-robin singleton and slot-pair groups so early
groups cannot exhaust all work. Report attempts, improvements and cap exhaustion;
continue returning `best_found`. The cap is an experimental starting point, not
a measured service-level guarantee. Cancellation must apply throughout.

Leave multi-role refinement, weapon/ammunition changes, and generalized frontier
pruning to later independently reviewed milestones. The joint experiments here
establish the required union/transition invariants, not comprehensive coverage of
realistic joint catalogs. Before any future cutover, require the two breakpoint
fixtures, no-worse baseline objective at every curve point, constraint replay,
determinism/cancellation tests and a fresh latency review. Account-wide blanket
refinement is not justified by this snapshot's benefit/cost measurements.

## Reproduction and validation

Final focused verification: **57 research tests pass**, with **93.08%
branch-aware combined research coverage**, plus **159 existing optimizer,
retention, ammunition, transition and evaluation tests**. Scoped Ruff lint,
format checks, mypy and whitespace checks pass. Tests were written before the
new harness and before the paired-omission fixture; their initial RED runs failed
for the missing implementation/fixture. Disposable SQLite integration and a
real subprocess CLI invocation cover the command's end-to-end workflow.

Repeated frozen runs are deterministic across all 114 final benchmark cells.
Reversed catalog insertion order is additionally checked for every strategy on
the breakpoint fixture. Tests cover patch restoration on failure, explicit node
exhaustion, refinement caps, role-beam ablation, invalid CLI inputs, existing
output protection, source preservation, and independent validator rejection of
malformed solutions. Independent read-only correctness/security review found
no material unresolved issue. The validator is not a universal schema verifier;
the separate fixture comparisons cover the global reported action/capacity
aggregates for these cases.

From the repository root, using fresh output filenames:

```powershell
.venv/Scripts/python.exe -m tools.assess_gear_retention --tiny --repeats 5 --output .tmp/gear-candidate-retention/tiny-final.json
.venv/Scripts/python.exe -m tools.assess_gear_retention --database tracker.db --player-id 1 --at 2026-10-19T22:05:44+00:00 --repeats 5 --output .tmp/gear-candidate-retention/account-final.json
.venv/Scripts/python.exe -m pytest tests/test_assess_gear_retention.py tests/test_gear_retention_oracle.py tests/test_gear_retention_strategies.py -q --cov=tools.assess_gear_retention --cov=tools.gear_retention_oracle --cov=tools.gear_retention_strategies --cov-branch --cov-fail-under=80
.venv/Scripts/python.exe -m pytest tests/gear/test_optimizer.py tests/gear/test_coverage_audit.py tests/gear/test_ammunition_sharing.py tests/gear/test_transitions.py tests/gear/test_evaluation.py -q --no-cov
```

The raw JSON includes exact requests, catalog definitions, source fingerprints,
oracle curves, full optimizer responses, stage diagnostics and all timings.
`--case` and `--strategy` may repeat to select smaller experiments. Existing
output files are rejected. Account artifacts remain ignored and private.
The source database is opened read-only and copied WAL-aware into query-only
memory. Database/WAL hashes are checked around capture. Account/prices are
captured once and reused, with as-of filtering at the fixed evaluation time.
Source hashes are checked again after measurements to reject code/content drift.

The research-only files are `tools/assess_gear_retention.py`,
`tools/gear_retention_oracle.py`, `tools/gear_retention_strategies.py` and their
three corresponding test modules. The two earlier coverage reports are inputs
and remain unchanged. No combat formula, production optimizer, deployment,
database schema, catalog, synchronization or frontend edit is part of this work.

No realistic-catalog global optimum, Pi performance, live account behavior,
browser acceptance, production cutover, commit or push is claimed.
