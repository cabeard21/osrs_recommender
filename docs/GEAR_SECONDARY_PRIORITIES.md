# Gear Optimizer secondary priorities

The shared optimizer accepts `secondary_priority`, defaulting to `default` (the existing inventory/cost/action/identity ordering). The configuration dropdown also offers Balanced defence, Magic & ranged defence, individual Stab/Slash/Crush/Ranged/Magic defence, Prayer bonus, Melee strength bonus, Ranged strength bonus, Magic damage bonus and Accuracy. All options remain available for one to four roles.

Magic & ranged defence (`magic_ranged_defence`) is the equal average of the magic and ranged equipment defence bonuses. Negative bonuses are preserved; melee defence bonuses do not contribute. It describes equipment bonuses, not damage reduction. Multi uses the existing normalized active-time weights across scored roles.

Weighted ordinary-attack DPS remains the primary objective. The initially selected DPS solution maximizes the priority only when modeled DPS compares exactly equal under the existing float ordering; there is no tolerance or rounded-DPS comparison. Remaining ties use the existing ordering. Candidate retention and partial beams use the selected priority after their DPS estimate, while preserving the existing Fast/Thorough work limits and complete legality checks. Bounded search does not guarantee the best secondary value, or a global DPS optimum.

Metrics come from Python equipment bonuses and combat evaluation. Balanced defence is the arithmetic mean of the five equipment defence bonuses, not a survival estimate. Individual defence, prayer, melee/ranged strength and magic damage use their corresponding equipment bonuses; magic damage is measured in percentage points. Accuracy is the evaluator's hit probability against each role's configured target. Across scored roles, metrics use the same normalized active-time weights as primary DPS; unscored utility roles contribute nothing. Results show the selected priority and measured value separately from DPS (`null` for Default, which has no single numeric metric).

The normalized scenario, its fingerprint, result provenance and every solution carry the selected priority. Switching it makes accepted results outdated and prevents incompatible result/trial comparisons. Omitted and explicit Default requests normalize identically. Combat formulas and catalog eligibility rules remain unchanged.

Focused regression entry points are `tests/gear/test_secondary_priorities.py`, `tests/api/test_gear_secondary_priorities.py` and `frontend/gear/src/tests/secondary-priorities.test.tsx`.


## Best-found tradeoff frontiers

Selecting a named secondary also runs a separately bounded search for nondominated DPS/secondary tradeoffs. A solution dominates another when both objectives are at least as large and one is strictly larger. Equal objective pairs retain existing inventory/cost/action/identity ordering. Comparisons use unrounded model values. Default secondary does not run this extra phase.

`max_dps_loss_pct` is a finite number from 0 to 100, default 10. Each swap limit and the unrestricted result has its own baseline and frontier; percentage loss uses that group's highest DPS found across both phases. A zero DPS baseline has no defined percentage loss. Balanced defence remains an equipment-bonus average, not a survival estimate.

The response adds `result.secondary_frontiers`: groups with `swap_limit` (null for unrestricted), `baseline_dps`, `sampled`, and `points`. Each point contains a stable `id`, the full validated `solution`, `dps_loss`, nullable `dps_loss_pct`, and `secondary_gain`. At most 64 displayed points preserve endpoints and evenly sample the sorted frontier. Every returned point includes normal item provenance. Historical responses without frontier fields remain readable.

The chart and accessible table default to highest DPS. Selecting a point changes displayed gear, combat options, purchases, and joint transitions together. Changing the maximum DPS loss is a scenario change requiring another optimization. Named-secondary frontiers carry `frontier_policy` in response provenance and scenario fingerprints. Fast permits 100,000 extra expansions; Thorough permits 300,000 plus one shared 2,000-assignment frontier substitution budget, separate from existing DPS refinement. Diagnostics report actual work and exhaustion.

Search retains secondary diversity in candidates, branches, and beams, and validates complete solutions with existing legality and resource constraints. Legal combat-option variants participate when option selection is enabled. These remain best-found frontiers: candidate/beam truncation and work limits can omit useful alternatives. Absence of a point does not establish infeasibility or global dominance.

Manual single-role evaluations accept optional `baseline_combat_options` and `proposed_combat_options`, keyed by role ID, so selected stance/spell variants retain their modeled performance. Options must match an eligible configuration for that side's weapon and the original scenario's combat-option filters; fixed scenarios retain their fixed configuration. Equipment changes that invalidate the selected option produce an invalid evaluation rather than silently changing combat configuration.


## Frozen local benchmark evidence

Measured on Windows on 2026-10-28 with `tools.gear_search_quality_fixture.load_case`,
using the redacted `gear_search_quality_account.json` fixture, its frozen account,
catalog, prices and time. Each row is one run, with Python `tracemalloc` enabled.
Times include allocation tracing overhead and are not production latency estimates;
peak MiB is traced Python allocation memory, not process RSS. No Pi acceptance or
live deployment is implied. Default selects no secondary; Fast/Thorough select
balanced defence with the default 10% DPS-loss range. These comparisons include the
existing secondary ordering as well as the new frontier phase.

| Case | Mode | Seconds | Peak MiB | Highest DPS | Returned points | Added expansions | Frontier assignments |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| owned_slash | Default | 3.052 | 15.08 | 2.642031 | 0 | 0 | 0 |
| owned_slash | Fast | 11.618 | 26.66 | 2.670866 | 30 | 18,086 / 100,000 | 0 |
| owned_slash | Thorough | 24.710 | 31.72 | 2.670866 | 60 | 18,086 / 300,000 | 2,000 / 2,000 |
| joint_four | Default | 20.884 | 37.97 | 2.710306 | 0 | 0 | 0 |
| joint_four | Fast | 33.024 | 53.87 | 2.765004 | 9 | 43,257 / 100,000 | 0 |
| joint_four | Thorough | 56.583 | 60.15 | 2.785961 | 28 | 43,257 / 300,000 | 2,000 / 2,000 |

Returned point counts sum all swap-limit groups plus unrestricted and can include
repeated equipment across groups. Neither Fast run exhausted its extra expansion
budget; both Thorough runs exhausted the separate frontier substitution budget.
The highest-DPS incumbent was preserved or improved in these cases. This is focused
local evidence, not proof of global frontier completeness or a general latency SLA.

Focused backend verification: 71 tests passed across frontier, secondary priorities,
optimizer and exact evaluation. Changed frontier/evaluation modules reached 94.80%
combined coverage (frontier 96%, evaluation 93%) under an 80% gate. The tests include
omitted defensive candidates, joint swap feasibility, stance tradeoffs, shared
Thorough work limits and legal-option enforcement in manual comparisons.
