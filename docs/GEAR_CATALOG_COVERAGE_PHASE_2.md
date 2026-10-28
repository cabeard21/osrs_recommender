# Gear Catalog Coverage Expansion — Phase 2

## Result and scope

Phase 2 independently reviews **13 concrete physical IDs** in three batches: the observed Phase 1 queue first, then purchasable ordinary variants. Seven of those IDs are observed in this frozen account; six are additional supported purchase/ownership possibilities, not newly invented account observations. All thirteen pass reviewed wear rules and ordinary outgoing-combat checks. Observed-equipment support rises from **69/229 (30.1%) to 76/229 (33.2%)**. Combat-relevant coverage rises from **69/174 (39.7%) to 76/174 (43.7%)** under the fixed definition below.

This is the local development account's October 19, 2026 observation snapshot, evaluated at `2026-10-19T22:05:44Z`, with item metadata reviewed October 27, 2026. It is not a current live-account claim or a historical catalog replay. See [Phase 1](GEAR_CATALOG_COVERAGE_PHASE_1.md), the [equipment audit](GEAR_EQUIPMENT_COVERAGE_AUDIT.md), and [targeted retention refinement](GEAR_TARGETED_RETENTION_REFINEMENT.md).

No search pruning, candidate/node limits, combat formulas, account observations, pricing policy or production routing changed. `targeted_head_refinement` stays opt-in and disabled in service/UI/MCP paths. No deployment, production cutover, Pi access, commit or push was performed.

## Coverage definition and batch results

The total denominator is the same 229 accepted observed catalog-equipment IDs used by the original audit. The 500 unclassified bank/inventory IDs are not silently treated as non-equipment or equipment.

**Combat-relevant** means an accepted observed catalog-equipment ID with at least one strictly positive numeric ordinary combat bonus: attack, defence, melee/ranged strength, magic damage or prayer. Membership is fixed from the Phase 2 baseline, before any approvals, and listed below. This deliberately includes defensive and utility items that have combat stats; it excludes all-zero and negative-only rows. It does not claim that conditional effects or defensive survival are modeled. The numerator in both measures is the audit's `fully_supported` flag: satisfied wear facts plus ordinary model support, independently of candidate retention and final selection.

| Stage | New reviewed IDs | Observed supported / 229 | Combat relevant / 174 | Incomplete wear metadata | Effect/model blockers | Distinct omitted IDs / item-role omissions |
| --- | --- | --- | --- | --- | --- | --- |
| before | — | 69 (30.1%) | 69 (39.7%) | 158 | 159 | 5 / 8 |
| batch1 | 33101, 3105, 23413 | 71 (31.0%) | 71 (40.8%) | 157 | 157 | 5 / 8 |
| batch2 | 19994, 21736, 7398, 7399, 23249 | 76 (33.2%) | 76 (43.7%) | 152 | 152 | 5 / 8 |
| batch3 | 7400, 4101, 4103, 4111, 4113 | 76 (33.2%) | 76 (43.7%) | 152 | 152 | 5 / 8 |

Incomplete wear metadata and effect blockers overlap. Batch 3 supplies useful alternative physical forms without changing observed coverage; approving unowned variants is not counted as account coverage growth.

Fixed combat-relevant denominator (174 IDs):

```text
35, 89, 426, 428, 577, 589, 616, 772, 806, 843, 853, 857, 861, 863, 868, 882, 884, 886, 890, 975, 1017, 1019, 1021, 1033, 1035, 1059, 1061, 1063, 1065, 1077, 1079, 1097, 1099, 1125, 1127, 1133, 1135, 1163, 1165, 1169, 1201, 1203, 1205, 1207, 1265, 1267, 1269, 1271, 1275, 1293, 1333, 1349, 1353, 1359, 1381, 1387, 1405, 1409, 1495, 1540, 1580, 1704, 1724, 1725, 1727, 1731, 2402, 2579, 2655, 2659, 2866, 2883, 2890, 2952, 2963, 3097, 3105, 3175, 3202, 3335, 3749, 3751, 3753, 3755, 3785, 3841, 4089, 4091, 4093, 4097, 4131, 4156, 4298, 4300, 4302, 4304, 4308, 4310, 4315, 4502, 4551, 4567, 4587, 4599, 4600, 4798, 4827, 5016, 5574, 6133, 6326, 6328, 6585, 6720, 6746, 6773, 6809, 7398, 7399, 7457, 7458, 7459, 7668, 7917, 7918, 8880, 8882, 9006, 9185, 9731, 9733, 10446, 10491, 10498, 10551, 10564, 10581, 10589, 10822, 10824, 10826, 10828, 10836, 10837, 10838, 10839, 11061, 11126, 11136, 12610, 12612, 13104, 13108, 13112, 13117, 13121, 13125, 13129, 13137, 13141, 13385, 13387, 13389, 19994, 20226, 21643, 21646, 21736, 21760, 23249, 26770, 29084, 30895, 33101
```

## Independently reviewed item facts

| ID / pinned item evidence | Slot | Observed | Wear rule | Acquisition |
| --- | --- | --- | --- | --- |
| 33101 [Mooleta](https://oldschool.runescape.wiki/w/Special:PermanentLink/15279216) | shield | yes | None; no quest wear gate | Untradeable; post-quest Brutus drop |
| 3105 [Climbing boots](https://oldschool.runescape.wiki/w/Special:PermanentLink/15359845) | feet | yes | Death Plateau complete; no skill gate | Tradeable; Tenzing after Death Plateau / player trade |
| 23413 [Climbing boots (g)](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324095) | feet | no | Death Plateau complete; no skill gate | Tradeable; medium clues / player trade |
| 19994 [Ranger gloves](https://oldschool.runescape.wiki/w/Special:PermanentLink/15325124) | hands | yes | Ranged 40; no Defence/quest gate | Tradeable; elite clues / player trade |
| 21736 [Granite gloves](https://oldschool.runescape.wiki/w/Special:PermanentLink/15365323) | hands | yes | Defence 50 AND Strength 50; no quest gate | Tradeable; Grotesque Guardians drop / player trade |
| 7398 [Enchanted robe](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324863) | legs | yes | Magic 40 AND Defence 20; no quest gate | Tradeable; hard clues / player trade |
| 7399 [Enchanted top](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324862) | body | yes | Magic 40 AND Defence 20; no quest gate | Tradeable; hard clues / player trade |
| 23249 [Rangers' tights](https://oldschool.runescape.wiki/w/Special:PermanentLink/15325123) | legs | yes | Ranged 40; no Defence/quest gate | Tradeable; elite clues / player trade |
| 7400 [Enchanted hat](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324861) | head | no | Magic 40 AND Defence 20; no quest gate | Tradeable; hard clues / player trade |
| 4101 [Mystic robe top (dark)](https://oldschool.runescape.wiki/w/Special:PermanentLink/15322453) | body | no | Magic 40 AND Defence 20; no quest gate | Tradeable; monster drops / player trade |
| 4103 [Mystic robe bottom (dark)](https://oldschool.runescape.wiki/w/Special:PermanentLink/15322426) | legs | no | Magic 40 AND Defence 20; no quest gate | Tradeable; monster drops / player trade |
| 4111 [Mystic robe top (light)](https://oldschool.runescape.wiki/w/Special:PermanentLink/15250408) | body | no | Magic 40 AND Defence 20; no quest gate | Tradeable; monster drops / player trade |
| 4113 [Mystic robe bottom (light)](https://oldschool.runescape.wiki/w/Special:PermanentLink/15250409) | legs | no | Magic 40 AND Defence 20; no quest gate | Tradeable; monster drops / player trade |

Each exact item page was read independently, including its wear prose, infobox, bonus table and effects/usage sections. The thirteen item-page revisions establish identity, tradeability, wear rules and ordinary bonuses. [Mystic robes revision 15374725](https://oldschool.runescape.wiki/w/Special:PermanentLink/15374725) separately corroborates player trade and dark/light monster-drop acquisition; source locations are acquisition facts, not added wear gates.

Both Climbing boots pages explicitly require Death Plateau completion, even for traded pairs. The gilded page's `quest=No` infobox is not evidence of ungated wear. Mooleta has no wear requirements; its post-quest drop does not impose that quest on an already-owned item. Granite gloves require both Strength and Defence; neither the Slayer level needed to farm the boss nor a general boss kill count is authored as a universal wear requirement. Special account prestige/acquisition restrictions are not invented as universal ordinary combat gates.

Twelve tradeable rows use the existing live-price policy, a 30-day freshness window and no fallback GP value. Existing pricing labels older available records `cached`; Phase 2 preserves that policy rather than claiming every stale record is unavailable. Missing exact-ID prices block unsupported purchases, and unknown ownership is not converted into ownership. Synthetic purchase tests use a 100-GP quote only to test budget boundaries; it is not a market price claim. Mooleta reuses its existing untradeable authored entry, has no purchasable price, and remains unavailable for an unowned ordinary purchase request.

## Ordinary statistics, compatibility and effects

Every one of the fourteen numeric bonus fields, the exact ID, slot and tradeability was checked against the pinned Wiki item page and the independent source-shaped calculator row. Statistics and compatibility remain exactly equal to the pre-Phase-2 normalized catalog. The only physical-catalog changes are thirteen removals of the generic `Offensive effects have not been validated.` marker, for explicitly reviewed IDs only. No ambiguous or specialized blocker is cleared.

Vectors are **stab, slash, crush, magic, ranged**. All thirteen have ranged strength 0, magic damage 0%, prayer 0, are not two-handed and are not ammunition or weapons. Their own attack-style/profile/ammunition compatibility lists remain empty; their bonuses apply to a compatible ordinary main-hand attack. Their normalized nonweapon speed floor remains 1 and does not determine the main-hand attack interval.

| ID | Attack vector | Defence vector | Melee strength |
| --- | --- | --- | --- |
| 33101 | 5, 7, 7, -1, -1 | 4, 8, 8, -2, -1 | 1 |
| 3105 | 0, 0, 0, 0, 0 | 0, 2, 2, 0, 0 | 2 |
| 23413 | 0, 0, 0, 0, 0 | 0, 2, 2, 0, 0 | 2 |
| 19994 | 0, 0, 0, -10, 11 | 1, 2, 1, 2, 0 | 0 |
| 21736 | 5, 5, 9, -3, -1 | 8, 8, 8, -3, 5 | 7 |
| 7398 | 0, 0, 0, 15, 0 | 0, 0, 0, 15, 0 | 0 |
| 7399 | 0, 0, 0, 20, 0 | 0, 0, 0, 20, 0 | 0 |
| 23249 | 0, 0, 0, -10, 15 | 0, 0, 0, 0, 0 | 0 |
| 7400 | 0, 0, 0, 4, 0 | 0, 0, 0, 4, 0 | 0 |
| 4101 | 0, 0, 0, 20, 0 | 0, 0, 0, 20, 0 | 0 |
| 4103 | 0, 0, 0, 15, 0 | 0, 0, 0, 15, 0 | 0 |
| 4111 | 0, 0, 0, 20, 0 | 0, 0, 0, 20, 0 | 0 |
| 4113 | 0, 0, 0, 15, 0 | 0, 0, 0, 15, 0 | 0 |

Mooleta occupies shield: one-handed melee/casting compatibility follows the existing slot validator, and a two-handed bow with Mooleta remains invalid. Armour pieces occupy their exact slots without weapon or ammunition exemptions. Blue/dark/light robes and plain/gold boots keep distinct IDs, ownership, quotes and requirement entries; physical equality does not create an ownership alias or general requirement inheritance.

The reviewed pages describe no conditional outgoing proc, target multiplier or set damage bonus for these thirteen pieces. Climbing utility, storage, clues, appearance, and Granite gloves' cactus protection during The Feud are outside ordinary attack damage and do not change it. A full Enchanted set has no invented set multiplier: the arithmetic regression at Magic 70 checks staff/top/robe/hat magic bonus 49, attack roll 9153, max hit 8 and a three-second interval against independent ordinary arithmetic.

## Retention and optimizer effects

Eligible support, retained slot pools and final selection are measured separately. All five default requests remain independent, owned-only ordinary roles with the original candidate limits, beam widths and pruning. The observed omission list remains the same eight item-role pairs across all batches:

- Farseer helm `3755`: ranged.
- Snakeskin bandana `6326`: magic.
- Granite helm `10589`: ranged and magic.
- Helm of neitiznot `10828`: slash and crush.
- Xerician hat `13385`: slash and crush.

These are five distinct supported IDs omitted in at least one role. No Phase 2 reviewed observed ID is omitted by initial slot retention. Later beam survival is not measured; absence from the final loadout is not proof of a retention failure. Candidate truncation remains true, and optimizer quality remains `best_found`.

Incremental retained slot-pool membership changes, compared with the immediately preceding batch (all other role/slot pools are unchanged):

| Stage | Role | Slot | Added IDs | Removed IDs |
| --- | --- | --- | --- | --- |
| batch1 | stab | feet | 3105 | none |
| batch1 | slash | feet | 3105 | none |
| batch1 | crush | feet | 3105 | none |
| batch1 | ranged | feet | 3105 | none |
| batch1 | magic | feet | 3105 | none |
| batch2 | stab | body | 7399 | none |
| batch2 | stab | hands | 19994, 21736 | none |
| batch2 | stab | legs | 7398, 23249 | none |
| batch2 | slash | body | 7399 | none |
| batch2 | slash | hands | 19994, 21736 | none |
| batch2 | slash | legs | 7398, 23249 | none |
| batch2 | crush | body | 7399 | none |
| batch2 | crush | hands | 19994, 21736 | none |
| batch2 | crush | legs | 7398, 23249 | none |
| batch2 | ranged | body | 7399 | none |
| batch2 | ranged | hands | 19994, 21736 | none |
| batch2 | ranged | legs | 7398, 23249 | none |
| batch2 | magic | body | 7399 | none |
| batch2 | magic | hands | 19994, 21736 | none |
| batch2 | magic | legs | 7398, 23249 | none |

Batch 3 has no observed pool changes. Mooleta was already access-eligible in the shield pool before this phase, but its unreviewed-effect marker prevented supported ordinary evaluation; Phase 2 clears only that independently reviewed blocker.

| Stage | Role | Selected DPS | Change from baseline | Explored nodes |
| --- | --- | --- | --- | --- |
| before | stab | unavailable | — | 596 |
| before | slash | 3.459484774723 | +0.000000000000 | 14740 |
| before | crush | 2.002834323766 | +0.000000000000 | 15412 |
| before | ranged | 2.269539708519 | +0.000000000000 | 13852 |
| before | magic | 1.324090634559 | +0.000000000000 | 16468 |
| batch1 | stab | unavailable | — | 596 |
| batch1 | slash | 3.460843748528 | +0.001358973805 | 15332 |
| batch1 | crush | 2.012249232604 | +0.009414908838 | 16172 |
| batch1 | ranged | 2.269539708519 | +0.000000000000 | 14132 |
| batch1 | magic | 1.324090634559 | +0.000000000000 | 16724 |
| batch2 | stab | unavailable | — | 596 |
| batch2 | slash | 3.460843748528 | +0.001358973805 | 16612 |
| batch2 | crush | 2.014670251253 | +0.011835927487 | 17452 |
| batch2 | ranged | 2.272454840548 | +0.002915132028 | 15412 |
| batch2 | magic | 1.324090634559 | +0.000000000000 | 18004 |
| batch3 | stab | unavailable | — | 596 |
| batch3 | slash | 3.460843748528 | +0.001358973805 | 16612 |
| batch3 | crush | 2.014670251253 | +0.011835927487 | 17452 |
| batch3 | ranged | 2.272454840548 | +0.002915132028 | 15412 |
| batch3 | magic | 1.324090634559 | +0.000000000000 | 18004 |

Selected concrete equipment by stage (unchanged rows deliberately retained for traceability):

| Stage | Role | Equipment (slot=ID) |
| --- | --- | --- |
| before | stab | none |
| before | slash | body=10551, cape=1019, feet=21643, hands=11126, head=3753, legs=1033, neck=6585, ring=26770, shield=1201, weapon=4587 |
| before | crush | body=10551, cape=1019, feet=21643, hands=11126, head=3751, legs=1033, neck=6585, ring=26770, shield=1201 |
| before | ranged | ammunition=890, body=1135, cape=10498, feet=6328, hands=1065, head=3749, legs=1099, neck=1704, ring=13125, weapon=861 |
| before | magic | ammunition=20226, body=4091, cape=13121, feet=2579, hands=11126, head=3755, legs=4093, neck=1704, ring=13125, shield=12612, weapon=1381 |
| batch1 | stab | none |
| batch1 | slash | body=10551, cape=1019, feet=21643, hands=11126, head=3751, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| batch1 | crush | body=10551, cape=1019, feet=21643, hands=11126, head=3751, legs=1033, neck=6585, ring=26770, shield=33101 |
| batch1 | ranged | ammunition=890, body=1135, cape=10498, feet=6328, hands=1065, head=3749, legs=1099, neck=1704, ring=13125, weapon=861 |
| batch1 | magic | ammunition=20226, body=4091, cape=13121, feet=2579, hands=11126, head=3755, legs=4093, neck=1704, ring=13125, shield=12612, weapon=1381 |
| batch2 | stab | none |
| batch2 | slash | body=10551, cape=1019, feet=21643, hands=11126, head=3751, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| batch2 | crush | body=10551, cape=1019, feet=21643, hands=21736, head=3751, legs=1033, neck=6585, ring=26770, shield=33101 |
| batch2 | ranged | ammunition=890, body=1135, cape=10498, feet=6328, hands=19994, head=3749, legs=23249, neck=1704, ring=13125, weapon=861 |
| batch2 | magic | body=4091, cape=13121, feet=2579, hands=11126, head=3755, legs=4093, neck=1704, ring=13125, shield=12612, weapon=1381 |
| batch3 | stab | none |
| batch3 | slash | body=10551, cape=1019, feet=21643, hands=11126, head=3751, legs=1033, neck=6585, ring=26770, shield=33101, weapon=4587 |
| batch3 | crush | body=10551, cape=1019, feet=21643, hands=21736, head=3751, legs=1033, neck=6585, ring=26770, shield=33101 |
| batch3 | ranged | ammunition=890, body=1135, cape=10498, feet=6328, hands=19994, head=3749, legs=23249, neck=1704, ring=13125, weapon=861 |
| batch3 | magic | body=4091, cape=13121, feet=2579, hands=11126, head=3755, legs=4093, neck=1704, ring=13125, shield=12612, weapon=1381 |

Stab remains unavailable because this frozen account has no complete supported accurate-stab scaffold under the existing weapon profiles; this was already true before Phase 2. Slash and crush can now select Mooleta; Granite gloves add a later crush improvement. Ranger gloves and Rangers' tights improve ranged accuracy. Magic retains its DPS and blue mystic body/legs; its equal-DPS selection change removes ammunition `20226`, while the approved Enchanted pieces remain eligible alternatives. Batch 3 is unowned in this snapshot and changes no selected owned-only solution. No purchase is charged for these observed owned solutions.

## Runtime observations

Each row is one untimed warmup followed by three deterministic full optimizations on the same immutable account, requests, as-of prices and stage metadata. Values are Windows local medians in seconds, not Pi latency guarantees or a controlled performance benchmark. Final timing stages ran serially after the focused test processes finished; host load and scheduling still affect timing. The single frozen database image is shared by the final stage replay; every response within each stage matches its reference hash.

| Role | before | batch1 | batch2 | batch3 |
| --- | --- | --- | --- | --- |
| stab | 0.8500 | 0.8748 | 0.8265 | 0.3490 |
| slash | 2.0997 | 1.7052 | 1.9057 | 0.9506 |
| crush | 1.7763 | 1.6880 | 1.7842 | 0.9264 |
| ranged | 1.6249 | 1.6847 | 1.5171 | 0.9279 |
| magic | 1.8478 | 1.7920 | 1.0508 | 1.0010 |

Per-stage retained pool sizes, all timing samples, node counts, response hashes, full selected solutions and alternative output are retained in the private measurement artifacts. Larger supported pools increase explored work; no candidate cap was raised to compensate. Batch 2 and Batch 3 have identical explored-node counts and owned selections, yet noticeably different timings: these samples do not establish a catalog-caused speedup or latency regression.

## Validation and provenance

Tests were added before metadata: initial RED produced 66 failures and 17 passes. Batch 1 GREEN: 26 passes; Phase 1/catalog regressions: 94 passes. Batch 2 RED: 25 failures, then combined batch 1–2 GREEN: 51 passes; bonus/evaluation/catalog regressions: 125 passes. Batch 3 RED: 25 failures and three passes, then all Phase 2 checks: 83 passes. A further independent arithmetic anchor brings the final Phase 2 test count to 84.

Content validation caught two authored-schema mistakes during development: `all` was corrected to `all_of`, and acquisition-route prose was moved out of the tradeable-only metadata fields into comments/report text. Final content validation passes; no validator was weakened. Final measurements replay each captured stage with schema-valid immutable authored views, asserting complete equality with captured physical definitions and every existing baseline authored-item hash. The original per-batch audit artifacts are retained separately; no tracked file or account state was restored for replay.

Final focused gear suite: **310 passed**, **95.00% branch-aware coverage** of catalog/fact loading. Final content/ladder suite: **81 passed**. Audit/measurement tool checks: **38 passed**. Scoped Ruff lint/format and whitespace checks: **passed**. Independent read-only code review found no correctness issue. Browser, live-client, Pi and production acceptance are not claimed.

Commands (explicit temporary directories avoid unrelated legacy test caches):

```powershell
.venv/Scripts/python.exe -m pytest tests/gear/test_catalog_coverage_phase2.py tests/gear/test_catalog_coverage_phase1.py tests/gear/test_catalog.py tests/gear/test_bonus_pipeline.py tests/gear/test_optimizer_facts.py tests/gear/test_optimizer.py tests/gear/test_evaluation.py tests/gear/test_exclusions.py tests/gear/test_ammunition_sharing.py tests/gear/test_coverage_audit.py tests/gear/test_targeted_retention_integration.py -q --cov=tracker.gear.catalog --cov=tracker.gear.facts --cov-branch --cov-fail-under=80 --basetemp .tmp/phase2-final-corrected
.venv/Scripts/python.exe -m pytest tests/content tests/tools/test_gear_ladders.py -q --no-cov --basetemp .tmp/phase2-content-fixed
.venv/Scripts/python.exe -m pytest tests/test_measure_gear_coverage.py tests/test_audit_gear_equipment.py -q --no-cov --basetemp .tmp/phase2-audit-tools
.venv/Scripts/python.exe -m tools.measure_gear_coverage --database tracker.db --player-id 1 --at 2026-10-19T22:05:44Z --output-dir .tmp/gear-coverage-phase2/recheck --repeats 3
```

A before/after comparison requires a saved same-snapshot baseline. The existing `compare_measurements` drift checks remain unchanged: account, database, time, requests, price policy/prices and pipeline/harness sources must match. Its legacy allowlist is Phase 1 only, so its `unexpected_*` fields intentionally list Phase 2 approvals. The Phase 2 report check independently constrains every changed physical/authored ID to the thirteen reviewed IDs, verifies all physical stats/compatibility unchanged, and verifies no existing authored definition changed. It does not suppress the legacy warning or widen runtime eligibility.

The physical fixture is extracted from the complete pinned calculator export at revision `89c3e25b344aea90d0189746e4b5f73dde0f0383`, [equipment.json](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json), with capture SHA-256 `96022a4a1764cc9d7d3d0a73f9434563e5f727e7c7f85eb1a79ab791dd4d678d`. Fetching the pinned bytes for validation reproduced that checksum. The manifest preserves the original revision/retrieval/capture attribution and licensing; only its catalog checksum and review note change. Full upstream rows are kept independently of normalized runtime metadata in `tests/fixtures/gear_coverage_phase2_source.json`, with item-page revisions, revision timestamps and UTF-8 content hashes. Attribution: OSRS Wiki and Weird Gloop contributors; calculator export GPL-3.0, Wiki-derived material CC BY-NC-SA 3.0.

| Item ID | Pinned Wiki revision | UTF-8 revision-content SHA-256 |
| --- | --- | --- |
| 33101 | 15279216 | `6d8df83ece61bf9de0c377bf802ee4add0767c4f178e80f45dca68bbeac3a1d1` |
| 3105 | 15359845 | `74e4cd8c69d78f45dce6cad79ed03d2ea20a835f17ccdafec1a4d466a4a5efa7` |
| 23413 | 15324095 | `62cf366ce2cb8e9e1bb5458a6357d103d4b9d587c6e9c095de79499c11bfc235` |
| 19994 | 15325124 | `5238a9571ddcc8a5a706fda42531430ea2a44965210220b817ea40e24b4d219f` |
| 21736 | 15365323 | `8d7e468bef62441a3f82da7243297eb524ea797a08893cba1cc31c1c9fde6475` |
| 7398 | 15324863 | `e9fc99e97ad1ecd065f160c73d32097ea759af8ff866047d9ddb4fb91f378858` |
| 7399 | 15324862 | `6be281c7c9f340888017328564480802cf2d790378febd88763d4469d53d3a6a` |
| 23249 | 15325123 | `df1eecc31226e97c78a99d5af0807a67706b1ba9feecf61fbf32833ebc8e88d5` |
| 7400 | 15324861 | `abcf63821bb6c1c66b69aa3fcc7f3fb56bf9c4495ca11edbefc33205604c6621` |
| 4101 | 15322453 | `dc6208ac944ac7b19f585edc46898a701613bf76dd5d9653eb17b1911925079f` |
| 4103 | 15322426 | `b52112539a0acc729009c38b5a7d5d15f7e410e4bff40c1ac6f006a179799b84` |
| 4111 | 15250408 | `d0fc564a1cc286e65c81a8ec903f9a060e99e997ff252653456427905a6bb62d` |
| 4113 | 15250409 | `ecb077066b32afe0b53573d07c8a4006cb750f89b5e06338b9857d96be71862f` |

Additional reviewed pages: Mystic robes revision `15374725` for trade/drop acquisition, and [Spiked boots revision 15359847](https://oldschool.runescape.wiki/w/Special:PermanentLink/15359847) for the explicitly rejected equip restriction. Raw API captures are private working evidence in `.tmp/gear-coverage-phase2/sources/`; permanent revision links and fixture checksums remain in the repository.

Frozen account fingerprint: `88aa8d3d8f6e9986c8e3d6b91fdc54622659986ee1cf58baf5117d4567039fc4`. Frozen database-image SHA-256: `2d74d48d1a30b9b95c0d180e4d346ab0295d242521c222fe444e2d24e7c4c9ef`. Original database/WAL byte preservation is verified in `.tmp/gear-coverage-phase2/source-preservation.json`; account identity/scan anchors, observations and accepted state were never rewritten.

Final replay evidence: `.tmp/gear-coverage-phase2/verified/{before,batch1,batch2,batch3}/{audit.json,audit.md,measurement.json}` and `summary.json`. Each stage uses the exact initial physical definitions, with only its approved authored subset. These ignored private artifacts contain detailed account evidence and are not a runtime input. The Phase 1 preservation digest excludes only the explicit Phase 2 list; its replacement digest was captured before Phase 2 edits, and all remaining IDs plus the unreviewed-variant checks are still protected.

## Deferred mechanics and next priorities

- **Spiked boots `3107` remain blocked.** Matching +2 strength/defence does not authorize them as a Climbing boots alias: the pinned page restricts equipping to the Ice Path segment of Desert Treasure I. The model has no such location/quest-stage context.
- **Other mystic/ornament forms remain blocked** unless previously reviewed: dusk robe top/bottom `23050/23053`, ornament top `26533`, other gloves/boots/hats are not implicitly approved from colour or name similarity.
- **Effect-dependent weapons remain blocked**, including Keris, Darklight, Gadderhammer, charged/Iban variants and other conditional mechanics from the Phase 1 queue. This phase does not implement target-specific multipliers, specials, charges, reflection, set procs or incoming-survival scoring.
- **Rune crossbow `9185` remains correctly ineligible** at the frozen account's Ranged 60 against its reviewed Ranged 61 wear rule. Missing pricing is not substituted for the real skill blocker.
- Next source-review priorities are observed ordinary Fremennik armour such as Spined body `6133`, followed by other useful purchasable exact variants. RFD glove subquests, diary items and miniquest/location equipment need independently representable gates before approval. Prioritize account combat utility rather than cosmetic percentage growth.
- The retained head omissions remain visible research evidence, not authorization to broaden retention or enable refinement. Any production cutover requires a separate requested milestone.

Phase 2 ends here. Production cutover has not begun.
