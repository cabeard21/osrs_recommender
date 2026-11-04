# Gear Optimizer tradeoff metrics

The configuration offers a **Tradeoff metric** alongside DPS: Balanced defence, Magic & ranged defence, individual Stab/Slash/Crush/Ranged/Magic defence, Prayer bonus, Melee/Ranged strength, Magic damage bonus, and Accuracy. **None — DPS only** retains the ordinary DPS search. Existing API identifiers (`secondary_priority`, `secondary_value`, `secondary_frontiers`) remain compatible.

Magic & ranged defence is the minimum of magic and ranged equipment defence bonuses in each complete loadout. Balanced defence is the arithmetic mean of all five defence bonuses. These describe equipment bonuses, not damage reduction or survivability. Negative bonuses remain negative. Multi averages per-loadout metric values using normalized active-time role weights; unscored utility roles do not contribute.

## Player defensive rolls

Seven additional tradeoff metrics use player defence rolls: Balanced defence roll, Magic & ranged defence roll, and individual Stab/Slash/Crush/Ranged/Magic defence rolls. Existing equipment-bonus metrics retain their meanings.

Rolls use freshly boosted Defence and Magic levels, complete equipment defence bonuses and the selected legal combat stance. Defensive and longrange stances add 3 effective levels; controlled adds 1. Physical effective defence is `Defence + stance + 8`. Magic effective defence is `floor(7 * Magic / 10) + floor(3 * Defence / 10) + stance + 8`, with the contributions truncated separately. Each usable roll is `max(0, effective_defence * (equipment_defence_bonus + 64))`. These rules follow the [OSRS Wiki calculator player-defence implementation](https://github.com/weirdgloop/osrs-dps-calc/blob/main/src/lib/NPCVsPlayerCalc.ts).

The UI displays all roll values in thousands with two decimal places (for example, `12.34k`). Frontier roll gains show both the absolute increase and the percentage increase relative to the highest-DPS point in the same swap-limit group, using unrounded values. A zero baseline shows percentage unavailable. These percentages describe roll increases, not damage reduction.

Balanced averages the five rolls. Magic & ranged takes the lower of those two rolls within each complete role loadout, before Multi applies normalized active-time weights. Individual metrics use the corresponding roll. Utility roles remain unscored. Required unknown levels make the requested roll metric unavailable rather than being treated as zero.

Potion search retains Defence boosts for roll metrics and Magic boosts when magic defence contributes, even for melee or ranged outgoing attacks. Fixed combat settings and legal-option filters are respected. Larger rolls resist ordinary attack accuracy; they are not damage reduction or survival percentages. No incoming enemy attacks, prayers, boost decay, drinking downtime, supply endurance or encounter survival are simulated. Divine potion HP costs remain separate disclosures.

New results expose optional `player_defence_rolls` alongside combat performance; the existing singular `defence_roll` continues to describe the enemy defence used for outgoing accuracy. Historical results without player rolls remain readable and require a fresh optimization to measure a new roll metric.

## Best-found tradeoff frontiers

Named metrics produce nondominated DPS/metric alternatives for every swap limit and unrestricted results. Both objectives must be at least as high, with one strictly higher, for dominance. Comparisons use unrounded values and existing resource/identity tie-breakers. Highest DPS favors metric on equal damage; highest metric favors DPS on equal metric.

The ordinary DPS search is preserved. A separate metric-first lane reserves one quarter of frontier equipment expansions, alongside diverse exploration for intermediate alternatives. Metric lane candidates and beams retain complementary defence components. Existing shared-assignment, combat-option and refinement allowances remain bounded. Search diagnostics report lane work and exhaustion. Neither endpoints nor intermediate points are guaranteed global optima.

The browser submits `max_dps_loss_pct=100` for new runs, including restored drafts, and has no DPS-loss input. Existing API callers may still explicitly supply finite caps from 0 to 100 (default 10); historical responses retain their original caps. New browser requests also expose full running-cost and ammunition-comparison ranges. Changing the metric requires a fresh optimization.

Charts plot actual DPS against the metric. Highest DPS is initially selected; both endpoint buttons select complete solutions, including equipment, combat options, purchases, potions and joint transitions. A single point can represent both endpoints. DPS loss and metric gain remain explanatory table values; a zero baseline has no defined percentage loss. Sampled published groups contain at most 64 points and preserve endpoints.

Auto discipline and potion orchestration merge complete child archives before final sampling. IDs remain unique and swap-cap scoped. The `tradeoff-frontier-v2` policy and `metric_lane_equipment_fraction=0.25` participate in provenance and scenario fingerprints. Old capped results remain historical and require rerunning to obtain the expanded range.

Manual comparisons preserve selected combat options and validate equipment, budget, eligibility, inventory, locks and transitions through the existing evaluator.

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
