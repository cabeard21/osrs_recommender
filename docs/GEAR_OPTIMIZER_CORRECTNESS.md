# Gear optimizer correctness investigation — 2026-10-19

The refreshed development snapshot reproduces the supplied original loadout and every
reported combat result. Its actual melee strength bonus is **+65**, not +10. The +10
field belongs to ranged strength from the equipped iron arrows. Both the original
service result and the existing running Gear page explicitly contained melee strength
65. There is no evidence of lost Rune scimitar/helmet bonuses in this reproduction;
the dense presentation made the two fields unnecessarily easy to confuse.

The investigation did establish two separate correctness problems: an owned imbued
ring form was excluded by incomplete variant handling, and partial-loadout DPS ties
could discard strength needed for a later max-hit breakpoint. Targeted fixes now find
**3.0363738994067186 DPS**, up **7.3660%**, for **0 GP** additional purchases.

## Frozen inputs and provenance

Only the refreshed local `tracker.db` was read. A SQLite online backup was made through
a `mode=ro` source connection into ignored local investigation artifacts. Its integrity
check returned `ok`. Subsequent evaluations used that isolated copy. No production
database was opened or modified, and no stale acceptance result was used.

- Snapshot fingerprint: `961a4cca3db25372d4ab5ea7d9c03922f11caeed4bd833da048d9763f147b145`.
- Evaluation time for both numerical runs: `2026-10-19T22:58:27.649697+00:00`.
- Attack 59, Strength 59, Defence 56, Hitpoints 56, Prayer 46, Ranged 45, Magic 49;
  combat level 72, members, 240 quest points.
- Completed relevant quests: Monkey Madness I, Dragon Slayer I, The Fremennik Trials,
  The Fremennik Isles, Horror from the Deep, Death Plateau, Troll Stronghold,
  Animal Magnetism. Recipe for Disaster is `in_progress`.
- Equipment access: `usable` (observed owned or purchasable); **additional** budget
  0 GP. Every selected item in both runs has a positive accepted observation.
- One melee role, slash, **accurate**, weight 1. No boosts or prayers, future skill or
  quest overrides, assumed acquired items, or equipment locks.
- Generic target: Defence 1, Magic 1, all defensive bonuses zero; no special mechanics,
  elemental weakness or damage cap. The resulting melee defence roll is 640.
- Reserve 12 supply slots; curve maximum 8 actions. A single role has no transitions.

| Accepted RuneLite scan | UTC timestamp | Age at frozen evaluation |
| --- | --- | --- |
| Bank | 2026-10-19 21:57:11 | 61 minutes 17 seconds |
| Equipment | 2026-10-19 22:05:41 | 52 minutes 47 seconds |
| Inventory | 2026-10-19 22:05:41 | 52 minutes 47 seconds |

Last account sync was 22:05:44 UTC. The relevant bank sightings, including torso,
Fury, and ring 26770, are positive quantities observed at 21:57:13 UTC, after the
accepted bank scan. These are dated observations, not guarantees of present ownership.

The bundled statistics source is the Wiki calculator equipment export at commit
[`89c3e25b344aea90d0189746e4b5f73dde0f0383`](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json).
The catalog SHA-256 is
`df16ae83df6462b2607934f53e244ea8993d671849b9ff5ab485ea1342f03850`.
No numerical source statistics were changed.

## Strength pipeline and independent verification

| Stage | Finding |
| --- | --- |
| Source/import | Rune scimitar strength 44, Neitiznot 3, strength amulet 10, bracelet 6, rune boots 2 are present and imported correctly. |
| Serialized definitions | `catalog.json` and frozen Pydantic definitions preserve separate attack, strength and defence fields. Round-trip regressions cover them. |
| Identification | Original selected physical IDs resolve correctly. The separate ring-form omission is described below. Ownership aliases do not copy item statistics. |
| Aggregation | Original strength is `44 + 3 + 10 + 6 + 2 = 65`; slash attack is `45 + 7 = 52`. Mapping and sequence inputs agree. |
| Combat inputs | Accurate stance gives effective Attack 70 and Strength 67. Actual aggregated strength is used in the damage formula. |
| Display | Original running page showed `melee strength: 65; ranged strength: 10`. Added distinct signed strength-bonus labels to make the distinction explicit. |

Independently, original max hit is `floor((320 + 67 × (65 + 64)) / 640) = 14`.
The strength product is 8643. Attack roll is `70 × (52 + 64) = 8120`, and target
defence roll is `(1 + 9) × 64 = 640`. Accuracy is `1 − 642 / 16242`.

The actual, unmodified pinned Wiki calculator was executed through a separate temporary
harness, including its equipment aggregation and `PlayerVsNPCCalc`. It agrees with
both the original and final melee calculations:

| Metric | Original | Corrected optimizer | Pinned Wiki, corrected setup |
| --- | ---: | ---: | ---: |
| Slash attack bonus | 52 | 62 | 62 |
| Melee strength bonus | 65 | 75 | 75 |
| Effective Strength | 67 | 67 | 67 |
| Attack roll | 8120 | 8820 | 8820 |
| Defence roll | 640 | 640 | 640 |
| Accuracy | 0.9604728481714074 | 0.9636095680761818 | 0.9636095680761818 |
| Max hit | 14 | 15 | 15 |
| Attack interval, seconds | 2.4 | 2.4 | 2.4 |
| DPS | 2.8280589418380333 | 3.0363738994067186 | 3.0363738994067186 |
| Additional purchases | 0 GP | 0 GP | Account/budget enforced locally |

Final strength is `44 + 3 + 8 + 4 + 6 + 2 + 8 = 75`. The strength product is 9313;
`floor((320 + 9313) / 640) = 15`. Fury adds 10 slash, so attack roll is `70 × 126`.
The ordinary accurate-hit distribution transforms a rolled zero to one: final
conditional expected damage is `121 / 16`, and DPS is
`(1 − 642 / 17642) × (121 / 16) / 2.4`. Using max-hit/2 alone would be incorrect.
See the pinned [strength and attack calculations](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/src/lib/PlayerVsNPCCalc.ts)
and [rounding/accuracy rules](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/src/lib/BaseCalc.ts).

All individual item bonuses and raw full-loadout fields agree with that export. There
is one deliberate semantic distinction: the repository reports the iron arrow's raw
ranged strength +10 in a melee loadout; the Wiki's
[active aggregation](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/src/lib/Equipment.ts#L279-L333)
excludes unused ammunition and returns active ranged strength 0 with a scimitar.
Neither value affects melee strength or any melee combat result.

## Recommendation and alternative audit

Every item below is present in the physical catalog. Eligibility, candidate-pool
retention, main-beam evaluation and post-selection full-loadout substitutions were
checked separately; they are not interchangeable claims.

| Equipment | Refreshed-account explanation |
| --- | --- |
| Rune scimitar 1333 | Owned, wear requirements satisfied, retained and evaluated. Best supported, budget-feasible slash weapon in this search. |
| Combat bracelet 11126 | Owned and eligible. Replacing it with owned ordinary gloves drops original DPS to 2.6229165496627167: a genuine offensive benefit. |
| Blue wizard robe 577 | Owned and eligible. Originally an offensive tie with torso at the max-14 breakpoint; stable ID/serialization ordering favored it. Replaced by torso in the corrected combination. |
| Zamorak monk bottom 1033 | Owned and eligible. Same melee DPS as eligible owned rune platelegs; has different prayer/magic-defence trade-offs. Remains a tie-selected item. |
| Explorer's ring 1 13125 | Owned and eligible; originally chosen among zero-melee-offence rings while the owned imbued variant was incorrectly unavailable. Replaced after correction. |
| Fighter torso 10551 | Owned, Defence requirement satisfied, retained. Its original full-loadout substitution was evaluated post-selection: strength 69, max 14, exactly tied DPS. It was omitted from the displayed top five by equal-score ID ordering, not missing from the catalog or removed by pool truncation. |
| Amulet of fury 6585 | Owned, eligible, retained and evaluated. Its +10 accuracy and +8 strength win in the corrected combined setup even though the strength amulet alone gives +10 strength. |
| Berserker ring (i) 26770 | Positively observed in bank. Previously unknown requirements/unsupported because only primary 11773 was reviewed. Now explicitly recognized as an equivalent physical form, retaining ID 26770 and its own ownership. |
| Primary imbued ring 11773 / form 25264 | Neither positively observed. Ownership of 26770 does not fabricate ownership of these forms. |
| Barrows gloves 7462 | Unobserved in accepted scans; Recipe for Disaster remains in progress. Excluded by requirements and ownership, not truncation. |
| Sulphur blades 29084 | Owned and catalog-present, but reviewed wear gates are absent and multi-hit offensive mechanics unsupported. Removing the incompatible shield does not make their DPS supported. No new mechanics added. |
| Dragon scimitar 4587 | Owned and Monkey Madness I complete, but Attack 59 fails 60. Excluded before search. |
| Rune platebody 1127 / platelegs 1079 | Owned, eligible, retained, and evaluated as complete substitutions; original DPS ties. Higher physical defence does not establish higher DPS. |
| Rune defender | Catalog-present but unobserved, with unknown reviewed gates and unsupported marker. |
| Dragon defender 12954 | Unobserved, and Defence 56 fails 60. |
| Berserker ring 6737 | Unobserved; cached acquisition quote 3,441,565 GP exceeds additional budget 0. This does not describe the owned imbued form. |
| Climbing boots 3105 | Owned, but reviewed gates and combat support are missing. Kept excluded rather than assuming eligibility. |

The final setup changes exactly three slots: **Amulet of fury, Fighter torso,
Berserker ring (i) 26770**. The other eight items match the supplied recommendation.
All eleven final items are positively observed, wear-satisfied and in their candidate
pools. Fury, torso and ring are each bank quantity 1 at 21:57:13 UTC.

The final audit tested all 83 request-eligible catalog items, including those outside
the retained pools: 36 feasible changed-item substitutions and 10 feasible empty-slot
removals. None improves final DPS. This is a one-slot local check, not an exhaustive
proof over combinations.

## Targeted fixes and the distinction between ties and improvements

1. **Reviewed equivalent forms:** The pinned Wiki
   [alias dataset](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment_aliases.json)
   explicitly maps 25264 and 26770 to 11773. The loader now allows these two reviewed
   forms to share authored wear gates and ordinary-effects review only after every
   physical field except ID/review marker matches. Authored variant membership is
   required for gate inheritance. Own IDs/statistics are preserved; source drift
   raises an error and ambiguous source markers remain unsupported.
2. **Breakpoint-aware tie retention:** In an all-melee partial beam, exact DPS and
   cost ties now retain greater melee strength before arbitrary item IDs. This keeps
   tied partial setups that can cross a damage threshold with later equipment. DPS
   remains the first comparison, and the final solution score is unchanged. No
   weighted recommendation framework was introduced.
3. **Presentation:** Distinct `Melee strength bonus: +…` and `Ranged strength bonus:
   +…` labels clarify the existing result; there is no Gear-tab redesign.

Ring alone takes original strength 65 to 73 and still hits 14. Torso alone takes it
to 69 and still hits 14. Together they reach 77 and hit 15. After the variant fix alone,
the old beam still returned only 2.8372948393354243 DPS by discarding individually tied
helmet/boot strength. The small pruning correction retains those combinations and
finds the final Fury setup at 3.0363738994067186. These are offensive improvements;
choosing rune legs instead of monk bottoms is an offensive tie.

For a defensive secondary preference, a conservative proposal is: preserve exact DPS
priority and existing inventory/cost/action priorities; among exact ties, discard
defensively dominated setups (no worse in all five defence bonuses and prayer, better
in at least one), then use stable item IDs for incomparable setups. During partial
pruning, only apply this after preserving offensive potential, so defensive preference
cannot discard strength needed for a later breakpoint. This favors improvements without
inventing numerical weights or assuming the target's defensive stats describe its
incoming attacks. Torso/robes or rune/monk legs can trade physical defence against
magic defence/prayer, so no universal defensive winner should be claimed. This broader
defensive policy is proposed, not implemented in this correctness patch.

## External choice comparison and remaining limits

[OSRS Best in Slot](https://www.osrsbestinslot.com/best-in-slot-gear/) exposes levels,
style, a total setup price cap, locks and selected unlock filters. Its public controls
cannot express the same positively observed owned-item set, full quest snapshot and
zero **additional** purchase budget. An equivalent unrestricted recommendation
comparison was therefore unavailable. No external recommended loadout was treated as
account eligibility evidence or a numerical oracle.

Search remains `best_found`, not proven globally optimal. The final run explored
15,076 nodes versus 14,820 before; both terminated `bounded_search_complete` with
candidate truncation true. Eligible catalog items rose 82 to 83. Pool truncation
removed only Adamant full helm 1161, leather body 1129, leather cowl 1167 (all unowned
and unaffordable at budget 0), and the owned Xerician hat 13385. None of the notable
alternatives above was removed by candidate-pool truncation. Beam pruning is a
separate limitation, and the tie correction does not eliminate all possible
complementarity failures, particularly across different styles.

Other unreviewed equipment/gates remain excluded. Sulphur blades and other exceptional
attacks, prayers, boosts, special attacks/set effects, movement, survival, supplies and
combat downtime remain unsupported or outside this ordinary-attack objective. Cached
prices and observations retain their dates. Inactive-ammunition raw/active totals
differ as documented above.

## Verification and retained evidence

Regression coverage includes known source bonuses, import field mapping, serialization,
physical-ID isolation, complete-loadout sums, independent original/final damage math,
ring-form ownership and gates, source drift/ambiguity rejection, multi-slot max-hit
breakpoints, preservation of genuine DPS improvements, and rendered strength labels.
The new label and variant/breakpoint regressions were observed failing before fixes.

Focused checks: **110 tests passed**, with **93.33% gear coverage**; the existing
rendered optimizer browser journey also passed. Ruff lint/format, mypy over the
changed runtime modules and regression files, and `git diff --check` passed. Review
found and resolved a NiceGUI unit-test client-isolation issue. The final result
component was independently rendered with the actual corrected output and its two
strength labels and selected items were verified in headless Chromium.
The complete Gear-page optimization was then verified against the frozen database
through a temporary loopback server using read-only database access and no scheduler:
the final rendered DPS, selected items, +75 melee and +10 raw ranged labels all passed.
That full-account UI run took 33.62 seconds. A diagnostic trace identified repeated
snapshot fingerprint serialization in the existing cancellation callback; its overhead
was not changed as part of these correctness fixes.

Local, ignored evidence remains available in this workspace:

- [Frozen request](../.tmp/gear-correctness/request.json) and
  [account summary](../.tmp/gear-correctness/snapshot.json).
- [Original result](../.tmp/gear-correctness/before.json),
  [variant-only intermediate](../.tmp/gear-correctness/variant-only.json),
  [final result](../.tmp/gear-correctness/final-after.json).
- [Original alternative audit](../.tmp/gear-correctness/candidate-audit.json) and
  [final eligibility/substitution evidence](../.tmp/gear-correctness/final-candidate-summary.json).
- [Original live page text](../.tmp/gear-correctness/live-before.txt).
- [Corrected full Gear-page text](../.tmp/gear-correctness/ui-final-full.txt) and
  [headless rendered capture](../.tmp/gear-correctness/ui-final-full.png).
- Actual pinned calculator [original execution](../.tmp/gear-reference/reference-result.json),
  [final execution](../.tmp/gear-reference/reference-final-result.json) and
  [separate harness](../.tmp/gear-reference/reference.ts).

No commit, push, deployment, production write or new combat feature was performed.
