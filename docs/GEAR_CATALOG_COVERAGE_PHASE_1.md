# Gear Catalog Coverage Expansion — Phase 1

## Result and account boundaries

All **16 reviewed physical IDs** now pass their independently verified wear requirements and ordinary outgoing-combat model checks in the frozen account audit. Fully supported observed equipment increased from **53 to 69 of 229 IDs** (23.1% to 30.1%). Incomplete requirements decreased from **174 to 158**; effect-review/model blockers decreased from **172 to 159**. These categories overlap.

This is the local development account's **October 19, 2026** accepted observation snapshot, evaluated at `2026-10-19T22:05:44Z`, against metadata reviewed on **October 27, 2026**. It is not a live-account statement or a reconstruction of historical catalog versions. The original [equipment coverage audit](GEAR_EQUIPMENT_COVERAGE_AUDIT.md) remains the baseline reference.

The larger candidate set exposes the existing head-slot retention cap: **five otherwise eligible observed IDs are omitted in at least one tested role**, representing eight item/role omissions. They remain supported in other tested roles. Support, slot-pool retention, and final optimized selection are separate measurements. Later beam survival is not measured, and results remain `best_found`.

No combat formulas or mechanics, global eligibility gates, search limits/pruning, synchronization, observations, schema, production `/gear`, or deployment configuration were changed. No Pi access, cutover, commit, or push occurred.

## Review queue and completed batches

The queue starts with observed combat equipment: first the three items with effects already cleared; then ordinary black armour, shield and bow; then observed mage/Fremennik pieces; then independently checked granite armour. Cosmetic and quest utility items were not selected to raise the percentage. All sixteen are exact primary IDs, without new ownership aliases or progression ladder tiers.

| Stage | New physical IDs | Supported | Incomplete requirements | Effect blockers | Distinct IDs omitted in eligible roles |
| --- | --- | --- | --- | --- | --- |
| Baseline | — | 53 | 174 | 172 | 0 |
| Batch 1 | 882, 886, 1387 | 56 | 171 | 172 | 0 |
| Batch 2 | 1077, 1125, 1165, 1201, 857 | 61 | 166 | 167 | 0 |
| Batch 3 | 1017, 2579, 3753, 3755 | 65 | 162 | 163 | 3 |
| Batch 4 | 6809, 10564, 10589, 21643 | 69 | 158 | 159 | 5 |

Tests were written before metadata: initial RED found 77 failures; batch-specific RED runs confirmed the remaining changes. Completed-batch checks passed before the next batch. Original catalog/requirement checks passed after Batch 1; broader bonus/evaluator/ammunition checks passed after Batch 2; quest/bonus checks passed after Batch 3; final combined-scope checks passed after Batch 4.

## Approved facts and source evidence

Each row below identifies the concrete physical form, independently reviewed wear rule, and permanent item-page revision. All sixteen pages explicitly identify tradeable equipment; the overlay selects existing live pricing with a 30-day policy and no invented fallback price. All are available by player/GE trade. Crafting, clue/drop acquisition, shop access and quest usage are separate from wear requirements.

| ID | Physical identity / item source | Slot | Wear requirements | Acquisition information |
| --- | --- | --- | --- | --- |
| 882 | [Bronze arrow](https://oldschool.runescape.wiki/w/Special:PermanentLink/15182782) | ammunition | Ranged 1 skill floor; no additional gate | Archery shops / trade |
| 886 | [Steel arrow](https://oldschool.runescape.wiki/w/Special:PermanentLink/15182875) | ammunition | Ranged 5 | Archery shops / trade |
| 1387 | [Staff of fire](https://oldschool.runescape.wiki/w/Special:PermanentLink/15351469) | weapon | Explicitly ungated basic elemental staff | Staff shops / trade |
| 1077 | [Black platelegs](https://oldschool.runescape.wiki/w/Special:PermanentLink/15211048) | legs | Defence 10 | Armour shops / trade |
| 1125 | [Black platebody](https://oldschool.runescape.wiki/w/Special:PermanentLink/15322398) | body | Defence 10 | Armour shops / trade |
| 1165 | [Black full helm](https://oldschool.runescape.wiki/w/Special:PermanentLink/15183647) | head | Defence 10 | Shop / clue reward / trade |
| 1201 | [Rune kiteshield](https://oldschool.runescape.wiki/w/Special:PermanentLink/15320217) | shield | Defence 40 | Smithing / drops / trade |
| 857 | [Yew shortbow](https://oldschool.runescape.wiki/w/Special:PermanentLink/15183551) | weapon | Ranged 40 | Fletching / trade |
| 1017 | [Wizard hat](https://oldschool.runescape.wiki/w/Special:PermanentLink/15183735) | head | No wear requirements (wizard robe family, exact hat checked) | Betty / dark wizards / trade |
| 2579 | [Wizard boots](https://oldschool.runescape.wiki/w/Special:PermanentLink/15324172) | feet | Magic 20 | Medium clues / trade |
| 3753 | [Warrior helm](https://oldschool.runescape.wiki/w/Special:PermanentLink/15183261) | head | Defence 45 AND The Fremennik Trials complete | Skulgrimen / rewards / trade |
| 3755 | [Farseer helm](https://oldschool.runescape.wiki/w/Special:PermanentLink/15318286) | head | Defence 45 AND The Fremennik Trials complete | Skulgrimen / drops / trade |
| 6809 | [Granite legs](https://oldschool.runescape.wiki/w/Special:PermanentLink/15183056) | legs | Defence 50 AND Strength 50 | Skeletal Wyverns / trade |
| 10564 | [Granite body](https://oldschool.runescape.wiki/w/Special:PermanentLink/15379148) | body | Defence 50 AND Strength 50 | Penance Queen-gated reward shop / trade |
| 10589 | [Granite helm](https://oldschool.runescape.wiki/w/Special:PermanentLink/15183055) | head | Defence 50 AND Strength 50 | Terror dogs / rewards / trade |
| 21643 | [Granite boots](https://oldschool.runescape.wiki/w/Special:PermanentLink/15184787) | feet | Defence 50 AND Strength 50 | Fossil Island wyverns / trade |

Requirement corroboration: [Arrows, revision 15367680](https://oldschool.runescape.wiki/w/Special:PermanentLink/15367680) labels its Ranged requirement column and distinguishes ordinary from seeking arrows; [Elemental staff, revision 15351475](https://oldschool.runescape.wiki/w/Special:PermanentLink/15351475) explicitly states basic staves are ungated; [Wizard robes, revision 15327965](https://oldschool.runescape.wiki/w/Special:PermanentLink/15327965) establishes ungated wizard attire, with the exact hat identity/bonuses checked independently. Wizard boots' own page overrides any broad reading of that family text: **Magic 20 is required**.

The black pieces' use in King's Ransom/Heroes' Quest does not impose those quests as wear gates. The Fremennik helms' prose explicitly imposes quest completion despite their item infobox saying `quest=No`. Granite body's Penance Queen condition applies to buying it from Commander Connad; Slayer levels needed to obtain other granite drops are not wear gates. Every granite piece independently states both skill requirements.

### Ordinary bonuses and compatibility

Statistics remain the existing pinned calculator export at revision `89c3e25b344aea90d0189746e4b5f73dde0f0383`, [equipment.json](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json). The retained full capture SHA-256 is `96022a4a1764cc9d7d3d0a73f9434563e5f727e7c7f85eb1a79ab791dd4d678d`. Source-shaped test fixtures are extracted from that capture rather than generated from the normalized catalog. Independent review also compared all sixteen current Wiki bonus infoboxes with these pinned inputs and found no drift.

Vectors below are ordered **stab, slash, crush, magic, ranged**. Other columns distinguish melee strength, ranged strength, magic damage percent, and prayer.

| ID | Attack vector | Defence vector | Melee strength | Ranged strength | Magic damage % | Prayer |
| --- | --- | --- | --- | --- | --- | --- |
| 882 | 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0 | 0 | 7 | 0.0 | 0 |
| 886 | 0, 0, 0, 0, 0 | 0, 0, 0, 0, 0 | 0 | 16 | 0.0 | 0 |
| 1387 | 3, -1, 9, 10, 0 | 2, 3, 1, 10, 0 | 6 | 0 | 0.0 | 0 |
| 1077 | 0, 0, 0, -21, -11 | 21, 20, 19, -4, 20 | 0 | 0 | 0.0 | 0 |
| 1125 | 0, 0, 0, -30, -15 | 41, 40, 30, -6, 40 | 0 | 0 | 0.0 | 0 |
| 1165 | 0, 0, 0, -6, -3 | 12, 13, 10, -1, 12 | 0 | 0 | 0.0 | 0 |
| 1201 | 0, 0, 0, -8, -3 | 44, 48, 46, -1, 46 | 0 | 0 | 0.0 | 0 |
| 857 | 0, 0, 0, 0, 47 | 0, 0, 0, 0, 0 | 0 | 0 | 0.0 | 0 |
| 1017 | 0, 0, 0, 2, 0 | 0, 0, 0, 2, 0 | 0 | 0 | 0.0 | 0 |
| 2579 | 0, 0, 0, 4, 0 | 0, 0, 0, 4, 0 | 0 | 0 | 0.0 | 0 |
| 3753 | 0, 5, 0, -5, -5 | 31, 33, 29, 0, 30 | 0 | 0 | 0.0 | 0 |
| 3755 | -5, -5, -5, 6, -5 | 8, 10, 12, 6, 0 | 0 | 0 | 0.0 | 0 |
| 6809 | 0, 0, 0, -31, -18 | 43, 45, 41, -4, 68 | 0 | 0 | 0.0 | 0 |
| 10564 | 0, 0, 0, -22, -5 | 87, 84, 79, -6, 97 | 0 | 0 | 0.0 | 0 |
| 10589 | 0, 0, 0, -9, -7 | 31, 33, 29, -1, 39 | 0 | 0 | 0.0 | 0 |
| 21643 | 0, 0, 0, -3, -1 | 15, 16, 17, 0, 8 | 3 | 0 | 0.0 | 0 |

Yew shortbow is a **two-handed**, four-tick ordinary bow, with accurate/rapid/longrange profiles. It now explicitly accepts ordinary unpoisoned arrow IDs `882, 884, 886, 888, 890, 892`. Its previous empty compatibility list would have bypassed ammunition validation, ignored arrow strength and selected light rather than standard ranged defence. Adding the reviewed compatibility facts uses the existing formula correctly; no formula changed. Poisoned, seeking, fire, broad, amethyst, dragon, unstrung and minigame forms receive no approval or identity inheritance.

Staff of fire is **one-handed**, five ticks, with crush accurate/aggressive/defensive attacks and existing supported standard casting. Aggressive magic casting remains rejected; spell-level checks remain active. The ordinary arrow IDs occupy ammunition and have no independent weapon stances. The remaining armour and ammunition entries are non-weapon, non-two-handed equipment. Non-weapon normalized speed values are serialization placeholders, not attack timing claims. Profiles are corroborated by [Wiki CombatStyles, revision 15379028](https://oldschool.runescape.wiki/w/Special:PermanentLink/15379028).

Full-page mechanics review found no conditional outgoing damage, accuracy, charge, degradation, or set mechanic requiring new model work for these approved ordinary scenarios. Staff of fire supplies fire runes and has a fiery attribute affecting **incoming PvP pearl-bolt damage**. Granite boots protect against Karuulm ground heat. Those real properties are documented rather than claimed modeled: this optimizer does not score incoming PvP damage, environmental hazards, rune budgets, supply endurance, or special utility. Neither changes the supported ordinary outgoing calculation. The other approved pieces have no identified special outgoing modifier.

### Observed role eligibility and retention

Every approved ID is owned, wear-eligible, and fully supported in at least one tested role. The table measures initial role eligibility directly. Retention is reported only for initially eligible roles; mere presence in a pool does not imply model compatibility. Stab has no compatible accurate weapon scaffold in this account, so it remains unavailable. A bow's reported magic compatibility reflects the existing manual standard-spell evaluator; it does not claim bow autocasting.

| ID | Initially eligible roles | Eligible roles omitted from pool |
| --- | --- | --- |
| 882 | slash, crush, ranged, magic | None |
| 886 | slash, crush, ranged, magic | None |
| 1387 | crush, magic | None |
| 1077 | slash, crush, ranged, magic | None |
| 1125 | slash, crush, ranged, magic | None |
| 1165 | slash, crush, ranged, magic | None |
| 1201 | slash, crush, ranged, magic | None |
| 857 | ranged, magic | None |
| 1017 | slash, crush, ranged, magic | None |
| 2579 | slash, crush, ranged, magic | None |
| 3753 | slash, crush, ranged, magic | None |
| 3755 | slash, crush, ranged, magic | ranged |
| 6809 | slash, crush, ranged, magic | None |
| 10564 | slash, crush, ranged, magic | None |
| 10589 | slash, crush, ranged, magic | ranged, magic |
| 21643 | slash, crush, ranged, magic | None |

## Coverage and optimizer behavior

### Observed-account coverage

| Measure | Before | After |
| --- | --- | --- |
| confirmed_equipment_ids | 229 | 229 |
| fully_supported | 53 | 69 |
| incomplete_requirements | 174 | 158 |
| effect_review_or_model_limitations | 172 | 159 |
| eligible_items_omitted_during_retention | 0 | 5 |
| unclassified_ids | 500 | 500 |
| valid_items_excluded_by_scenario | 0 | 0 |
| physical_variants_requiring_review | 0 | 0 |

The confirmed-equipment denominator stays 229. The other 500 observed bank/inventory IDs remain unclassified; they are neither assumed non-equipment nor unowned. Missing/stale accepted-scan counts remain zero. The narrow existing variant-review signal remains zero; this does not approve unreviewed physical variants.

The remaining 160 unsupported equipment IDs comprise **158 incomplete requirement reviews** (all also carrying generic effect-review markers), **Rune crossbow 9185** with a correctly unmet Ranged 61 requirement against account Ranged 60, and **Mooleta 33101** with complete wear metadata but its unchanged generic effect-review marker. No generic flag is evidence that an actual special mechanic exists. The complete remaining-item list is below.

### Catalog-wide review coverage

| Measure | Before | After |
| --- | --- | --- |
| physical_items | 5435 | 5435 |
| requirements_complete | 231 | 247 |
| incomplete_requirements | 5204 | 5188 |
| effects_clear | 162 | 175 |
| effect_review_or_model_limitations | 5273 | 5260 |
| requirements_complete_and_effects_clear | 148 | 164 |
| acquisition_unknown | 5209 | 5193 |
| missing_tradeable_prices | 128 | 144 |

Sixteen exact-ID overlays are added; thirteen physical generic effect markers are cleared. Bronze arrow, Steel arrow and Staff of fire already had physical effect clearance. The normalized definitions of all **5,419 non-batch IDs** and all existing authored item entries remain unchanged. All 5,435 physical IDs and ordinary statistics are unchanged. The test fixture is not a runtime database; the existing catalog remains the only physical statistics source.

All sixteen newly tradeable-reviewed items lack both as-of quotes and raw cached quotes in this local database. As-of missing tradeable prices therefore rise from 128 to 144 catalog-wide, and from 45 to 61 observed tradeable IDs. This exposes previously unknown acquisition metadata; it does not remove prices. All sixteen are already owned, so these gaps do not block owned mode. The 83 non-owned catalog acquisition-price gaps remain 83. Purchasable-mode tests use explicit synthetic valid/stale/missing quotes and preserve existing conditional-price behavior; no historical market value is invented.

### Candidate pools and search results

Each default role now has 70 access-eligible catalog items, up from 54. Access includes the still model-blocked Mooleta and is not synonymous with combat support. Scaffold counts change as follows.

| Role | Scaffolds before | Scaffolds after | Explored nodes before | Explored nodes after |
| --- | --- | --- | --- | --- |
| stab | 0 | 0 | 310 | 596 |
| slash | 2 | 2 | 12114 | 14740 |
| crush | 2 | 3 | 12114 | 15412 |
| ranged | 6 | 16 | 11270 | 13852 |
| magic | 8 | 10 | 13194 | 16468 |

| Slot | Pool size before (includes empty) | Pool size after |
| --- | --- | --- |
| ammunition | 5 | 7 |
| body | 8 | 10 |
| cape | 4 | 4 |
| feet | 6 | 8 |
| hands | 5 | 5 |
| head | 9 | 12 |
| legs | 7 | 9 |
| neck | 6 | 6 |
| ring | 3 | 3 |
| shield | 4 | 5 |
| weapon | 8 | 10 |

Only head pools reach the existing 12-option cap. They contain 13 eligible physical head IDs plus the empty option before retention; two heads per supported role are omitted. Candidate truncation changes from false to true in every default scenario, including the scaffold-less stab sweep. The distinct eligible observed omissions are:

| Physical ID | Item | Roles omitted |
| --- | --- | --- |
| 3755 | Farseer helm | ranged |
| 6326 | Snakeskin bandana | magic |
| 10589 | Granite helm | ranged, magic |
| 10828 | Helm of Neitiznot | slash, crush |
| 13385 | Xerician hat | slash, crush |

The deterministic `test_expanded_ordinary_heads_expose_repeatable_retention_without_policy_changes` uses thirteen real ordinary head IDs, an owned Rune scimitar, synthetic level-70 combat skills, and completed relevant Fremennik quests. It repeats the audit, verifies two eligible heads omitted from the 12-option pool, and independently evaluates both omitted heads in legal ordinary loadouts. This demonstrates retention, not a lost global optimum. The prior audit's synthetic max-hit 8-versus-9 counterexample remains passing. Any remedy remains a separate search milestone requiring dominance/exhaustive-fixture proof and explicit policy review; no widths, heuristics or pruning were changed.

The full optimizer's selected score changes below are observations, not the proof of item support. Exact scaffold evaluations and pre-search gates provide that proof.

| Role | Selected ordinary DPS before | Selected ordinary DPS after |
| --- | --- | --- |
| stab | No feasible solution found | No feasible solution found |
| slash | 3.455926666 | 3.459484775 |
| crush | 2.002834324 | 2.002834324 |
| ranged | 2.269539709 | 2.269539709 |
| magic | 1.323106065 | 1.324090635 |

Slash selects newly reviewed Warrior helm, Rune kiteshield and Granite boots; magic selects Farseer helm and Wizard boots. Crush's score and ranged's selected loadout/score stay unchanged. More supported choices can be useful alternatives without changing the selected loadout. All selected account solutions have zero acquisition cost and preserve `best_found` labeling.

### Performance observations

Measurements use one warm-up followed by five timed full optimizations per role on the same frozen image and final harness. Times exclude database/catalog loading and audit construction. Every repeated response within each version is deterministic. These short Windows measurements are descriptive, with normal scheduling noise; they establish neither Pi behavior nor a runtime guarantee.

| Role | Before median seconds | After median seconds | After min–max seconds | Median change |
| --- | --- | --- | --- | --- |
| stab | 0.2656 | 0.3129 | 0.2665–0.3171 | +17.8% |
| slash | 0.5992 | 0.6564 | 0.6535–0.7039 | +9.5% |
| crush | 0.5887 | 0.6614 | 0.6580–0.6675 | +12.3% |
| ranged | 0.6003 | 0.6855 | 0.6515–0.7056 | +14.2% |
| magic | 0.6442 | 0.7618 | 0.7306–0.7799 | +18.3% |

## Reviewed behavior deferred and Phase 2 queue

These items remain unchanged and unavailable. Source inspection informs the next queue; it is not catalog approval.

| Observed ID / item | Review evidence | Disposition / next dependency |
| --- | --- | --- |
| 33101 | [Mooleta revision 15279216](https://oldschool.runescape.wiki/w/Special:PermanentLink/15279216): ungated untradeable ordinary off-hand, no identified outgoing special modifier | Highest-value small follow-up: complete exact-ID effect approval and dedicated tests. Deferred at the agreed 16-item batch boundary, not because a new mechanic was identified. |
| 3105 | [Climbing boots revision 15359845](https://oldschool.runescape.wiki/w/Special:PermanentLink/15359845): Death Plateau completion is a wear gate | Next ordinary equipment review; validate quest-state boundaries and distinct spiked/ornamental forms. No metadata approval in this phase. |
| 1409 | [Iban’s staff revision 15379987](https://oldschool.runescape.wiki/w/Special:PermanentLink/15379987): Attack 50/Magic 50, Iban Blast | Dedicated spell/charges/physical-form capability review; Iban Blast is absent from the current standard-spell model. Remains blocked. |
| 10581 | [Keris revision 15254686](https://oldschool.runescape.wiki/w/Special:PermanentLink/15254686): conditional target damage and proc | New target-attribute and damage-distribution model work with independent reference cases; retain effect blocker. |
| 2550 | [Ring of recoil revision 15358794](https://oldschool.runescape.wiki/w/Special:PermanentLink/15358794): reflected damage and finite recoil capacity | Incoming-attack and charge/endurance model dependency; retain effect blocker. |

Phase 2 should first finish Mooleta and common observed ordinary pieces such as Climbing boots, Ranger gloves `19994`, Granite gloves `21736`, and the Enchanted top/legs `7399`/`7398`, with independent requirements and effect review for each. Useful untradeables and observed heraldic/god physical forms such as `2655`/`2659` follow after exact identity/equivalence checks; no name-based inheritance. Common unobserved upgrades follow observed coverage. Genuine conditional mechanics form separate milestones. The demonstrated head retention issue belongs to a separate reviewed search-correctness project, not a prerequisite for representing ordinary items accurately.

## Reproduction, provenance, and changed files

Run the existing audit or the new measurement command from the repository root:

```powershell
.venv/Scripts/python.exe -m tools.audit_gear_equipment --database tracker.db --player-id 1 --at 2026-10-19T22:05:44Z --output-dir .tmp/gear-coverage-phase1/recheck
.venv/Scripts/python.exe -m tools.measure_gear_coverage --database tracker.db --player-id 1 --at 2026-10-19T22:05:44Z --output-dir .tmp/gear-coverage-phase1/recheck-measured --compare .tmp/gear-coverage-phase1/before/measurement.json
```

The optional comparison requires a retained baseline measurement from the same snapshot, database image, time, requests, as-of prices, pipeline, and harness. It rejects mismatches and reports changes outside the sixteen-ID allowlist. Without that baseline, omit `--compare` to reproduce current coverage/timing. Output directories receive `audit.json`, `audit.md`, and `measurement.json`; private working artifacts stay ignored. The original audit remains unchanged. Full local evidence is retained in `.tmp/gear-coverage-phase1/{before,batch1,batch2,batch3,after}`.

Before editing, the full normalized catalog, authored definitions, source catalog/manifest, audit, and database/WAL hashes were captured. After finalizing measurement drift checks, baseline timings were repeated using those exact pre-edit definitions and original authored entries in immutable in-memory objects. Assertions proved their equality with the original capture; no tracked files or observations were restored or rewritten. Both final timing sets use the same harness bytes. The current catalog is not misrepresented as the original one.

The source SQLite file is opened `mode=ro`, copied WAL-aware into a query-only in-memory image, and account/prices are read from that image. Source database and WAL SHA-256 values match before/after. All three accepted scan anchors and snapshot identity are preserved. Future-fetched cache rows/trade legs remain excluded from historical pricing; raw-cache diagnostics are labeled separately. Metadata review sources may postdate the account snapshot.

| Identity | Value |
| --- | --- |
| Git revision (dirty checkout; not a release) | e9b652bbef20f24656b3ee2cc6e3a482bf9399a4 |
| Snapshot fingerprint | 88aa8d3d8f6e9986c8e3d6b91fdc54622659986ee1cf58baf5117d4567039fc4 |
| Frozen database image SHA-256 | 50bd3ca819861989b031f366f75d6e1959e2a366a8db45271fc65887b69321f8 |
| Physical catalog SHA-256 before | df16ae83df6462b2607934f53e244ea8993d671849b9ff5ab485ea1342f03850 |
| Physical catalog SHA-256 after | 3a8e2651ad4c7d44c02238cbd7d7dcbb3186df446c75ca60d48ecfee3cd9d19c |
| Authored content SHA-256 before | 0fe4e07b79b6a6709b8c0e163b8993338d764ce728aba3f191d5c217995d7c52 |
| Authored content SHA-256 after | aad4e00e475928df7e7046b82b1892843d7f8a5d1770326d583ad7ef7692ffcc |
| Measurement harness SHA-256 | e9a5ecb48e90d283ac773641fb56c26c97a545270903b5d672464ebb1cd215d4 |

| Changed file | Purpose |
| --- | --- |
| content/items/gear_coverage_phase1.yaml | Sixteen exact-ID requirements/acquisition overlays with source revision comments; no tiers or aliases |
| tools/import_equipment.py | Explicit approved-ID effects review and Yew arrow compatibility |
| content/equipment/catalog.json | Thirteen generic marker removals and Yew compatibility only |
| content/equipment/manifest.json | Updated checksum and separate review note; original capture provenance preserved |
| tests/fixtures/gear_coverage_phase1_source.json | Sixteen source-shaped independent test inputs; attribution/license retained |
| tests/gear/test_catalog_coverage_phase1.py | Boundary, unknown, quest, stats, purchase, identity, exact evaluator, full optimizer, and retention diagnostics |
| tools/measure_gear_coverage.py | Read-only repeated measurement/comparison CLI |
| tests/test_measure_gear_coverage.py | Unit, disposable-database integration, and subprocess CLI acceptance |
| docs/GEAR_CATALOG_COVERAGE_PHASE_1.md | This report and evidence |

Existing audit utilities/report/fixture were already present from the prior audit and are reused without modification. Pre-existing frontend, plugin, and contract-fixture edits remain untouched. No second physical runtime database or application API/schema was added.

## Test results and acceptance

Final focused verification: **313 tests passed** across separate Gear/audit/measurement and content/ladder invocations. The new measurement module has **98.73% branch-aware coverage**. Its tests include disposable SQLite integration, source-file preservation, missing-database failure, overwrite protection, malformed comparisons, drift rejection and subprocess CLI end-to-end acceptance. The new metadata suite contributes **91 passing cases**.

An initial mixed-directory pytest invocation reported 295 passes and 18 fixture-discovery errors (`make_content` unavailable). Rerunning Gear and content scopes separately loads the correct existing directory fixtures and passes the same 313 collected cases; no production or shared test-infrastructure workaround was introduced.

Scoped Ruff lint/format checks and mypy pass. Regenerating the physical catalog from the pinned source with the updated importer produces byte-identical catalog bytes. Parsed before/after checks confirm the exact thirteen marker changes and Yew-only compatibility change; non-batch normalized definitions have an unchanged digest. Independent correctness/security review found no material unresolved issues. Browser/live/Pi acceptance is not claimed because no UI/deployment workflow changed.

Focused reproduction commands:

```powershell
.venv/Scripts/python.exe -m pytest tests/gear/test_catalog_coverage_phase1.py tests/gear/test_catalog.py tests/gear/test_bonus_pipeline.py tests/gear/test_optimizer_facts.py tests/gear/test_optimizer.py tests/gear/test_evaluation.py tests/gear/test_exclusions.py tests/gear/test_ammunition_sharing.py tests/gear/test_coverage_audit.py tests/test_audit_gear_equipment.py tests/test_measure_gear_coverage.py -q --cov=tools.measure_gear_coverage --cov-branch --cov-fail-under=80
.venv/Scripts/python.exe -m pytest tests/content tests/tools/test_gear_ladders.py -q
.venv/Scripts/python.exe -m pytest tests/gear/test_catalog_coverage_phase1.py -k expanded_ordinary_heads -q
```

## Source revision fingerprints

Raw Wiki revision content was captured through the public revisions API on October 27, 2026. The following SHA-256 values hash UTF-8 revision content, before local newline translation. Permanent revision links above and the pinned physical export make the review traceable without depending on ignored captures. No source implementation was copied into runtime code.

| Source title | Revision | Revision timestamp | UTF-8 content SHA-256 |
| --- | --- | --- | --- |
| Arrows | 15367680 | 2026-10-07T13:31:40Z | c5d6e9fa6267095f5a17992bd4355bad4a04ca2146c514f09e58b0acef3a5f6f |
| Black full helm | 15183647 | 2026-04-22T02:56:03Z | 4d4d020a40928e32b1be3638cb3bb0e8d045fdf01d511d828aabce42584c498a |
| Black platebody | 15322398 | 2026-08-27T21:39:34Z | 69d06da4ce90855dc279d16afc6a52301c00f2ef194078d5c1021b16a980cbc9 |
| Black platelegs | 15211048 | 2026-05-14T19:59:40Z | efa267a39c098efa6dc8b7d0f44e105b2f1d573aa4a9c0f3b8c7e14e8540dc80 |
| Bronze arrow | 15182782 | 2026-04-22T02:48:15Z | 1ecc77df1336aa4feb2061fa2daef4b98a2c519b5491ddb52d9bd7c9cef65e50 |
| Climbing boots | 15359845 | 2026-10-01T18:47:57Z | 74e4cd8c69d78f45dce6cad79ed03d2ea20a835f17ccdafec1a4d466a4a5efa7 |
| Elemental staff | 15351475 | 2026-09-20T00:18:59Z | 1e65f17690fb094f07804c2fab4d55d4f73e251f47b37c5fcca0d17a5f16831b |
| Farseer helm | 15318286 | 2026-08-24T21:43:06Z | 834cd5ceddf98168e8c54cb0861b4f8ab7adf312b9ccf19555c0f0b47c099990 |
| Granite body | 15379148 | 2026-10-22T07:23:56Z | 381085275db1266fe43fdfa45af7c4a46ca08a8c5fbbcd3431c660de268f9e94 |
| Granite boots | 15184787 | 2026-04-22T03:07:03Z | 7878ece853db7c3c4767b0c5e39be67c2eaa7fde359f7f8167a39cf576ed0cc2 |
| Granite helm | 15183055 | 2026-04-22T02:50:40Z | c3c0cae25674b6f21788231256ee3a12c51d946fa3bedd26e4fc6c8bc9e1882b |
| Granite legs | 15183056 | 2026-04-22T02:50:41Z | 63b5711adf38104de7e23cf74bf08bb5c03061ce48c8a52244944c2ebfc42c3d |
| Iban's staff | 15379987 | 2026-10-23T08:45:43Z | 3ad8624aa8214f80a1a797f3ab50460f3390f9f8e02dfdaa4bec41c1048b1243 |
| Keris | 15254686 | 2026-07-05T23:53:44Z | d26b3f649e5c9b704dea135190bd56f0d9fc12ea876b52a46a56fb8173a02a68 |
| Module:CombatStyles | 15379028 | 2026-10-22T02:25:28Z | 3d766f35c1a0c66a1902d6cb0cb6fb0af081c171223b29bf30b29a6b226539a8 |
| Mooleta | 15279216 | 2026-07-29T05:35:14Z | 6d8df83ece61bf9de0c377bf802ee4add0767c4f178e80f45dca68bbeac3a1d1 |
| Rada's blessing 1 | 15240314 | 2026-06-26T20:37:40Z | d88cf320a484155234a5866a81b0de97b829f428f93f5d3169beb894bf1ac9b3 |
| Ring of recoil | 15358794 | 2026-09-30T10:19:44Z | 5ddd276d9ed02f0fc0578f8e4ab889562b16982bf569afbe3daf73bf6bda79a2 |
| Rune kiteshield | 15320217 | 2026-08-25T22:51:03Z | 27b6a51d0a695fcc8b19ad514a49a42ad36632108ad20d804392011c4098fd0e |
| Staff of fire | 15351469 | 2026-09-20T00:17:07Z | cc98f6fe415ab82dfd11a8e5c0e127c5ee99e3573bed3e9734ba10ff645026b2 |
| Steel arrow | 15182875 | 2026-04-22T02:49:09Z | 9f24dbfea12bc965932ea365804456347e7e07f7a4851176f59bc12d004b71f6 |
| Template:CombatStyles | 13942863 | 2020-11-23T17:57:36Z | b93bbe0a048767a7563a75de6d1c9ee2e6767ea8853103d0d0c053c511eb4834 |
| Warrior helm | 15183261 | 2026-04-22T02:52:32Z | 8f5de0cd70b595f6e397d576fb8354c949beaa66e72d3b20d29b46372deec9bf |
| Wizard boots | 15324172 | 2026-08-28T23:57:22Z | f7b088463ae4335c963dd3e9fbd3aad20880cc2d77ffaa3470c1d528d351b5d5 |
| Wizard hat | 15183735 | 2026-04-22T02:56:49Z | 555f70842a52b724ef2cad1616023e4afbe278a47359ab18d6eae9b1c1e66fd8 |
| Wizard robes | 15327965 | 2026-09-02T01:36:56Z | 721ec209c3d018e6092e817ca9b62760a89350aa229d402472562b46bdaa61cd |
| Yew shortbow | 15183551 | 2026-04-22T02:55:14Z | f68d15d4b325d302e23a97d2522634e22cb4c586a7b484c6e4f4b3d91c43d426 |

## Remaining observed equipment blockers

This appendix lists all 160 confirmed equipment IDs still unavailable in the five audit sweeps. All are observed owned; acquisition prices cannot be their primary blocker in owned mode. `requirements incomplete` preserves unknown wear eligibility, and `generic effect review` preserves unresolved modeling review. It does not assert a special effect. Additional per-role scaffold, retention, pricing and observation details remain in the reproduced item-level audit output. The other 500 observed IDs remain unclassified.

| Physical ID | Canonical name | Primary reason and secondary review limitation |
| --- | --- | --- |
| 35 | Excalibur | Requirements incomplete; generic effect review |
| 89 | Boots of lightness | Requirements incomplete; generic effect review |
| 284 | Plague jacket | Requirements incomplete; generic effect review |
| 285 | Plague trousers | Requirements incomplete; generic effect review |
| 426 | Priest gown (top) | Requirements incomplete; generic effect review |
| 428 | Priest gown (bottom) | Requirements incomplete; generic effect review |
| 552 | Ghostspeak amulet | Requirements incomplete; generic effect review |
| 589 | Gnome amulet | Requirements incomplete; generic effect review |
| 616 | Beads of the Dead | Requirements incomplete; generic effect review |
| 772 | Dramen staff | Requirements incomplete; generic effect review |
| 806 | Bronze dart | Requirements incomplete; generic effect review |
| 863 | Iron knife | Requirements incomplete; generic effect review |
| 868 | Rune knife | Requirements incomplete; generic effect review |
| 975 | Machete | Requirements incomplete; generic effect review |
| 1005 | White apron | Requirements incomplete; generic effect review |
| 1021 | Blue cape | Requirements incomplete; generic effect review |
| 1035 | Zamorak monk top | Requirements incomplete; generic effect review |
| 1203 | Iron dagger | Requirements incomplete; generic effect review |
| 1205 | Bronze dagger | Requirements incomplete; generic effect review |
| 1207 | Steel dagger | Requirements incomplete; generic effect review |
| 1265 | Bronze pickaxe | Requirements incomplete; generic effect review |
| 1267 | Iron pickaxe | Requirements incomplete; generic effect review |
| 1269 | Steel pickaxe | Requirements incomplete; generic effect review |
| 1271 | Adamant pickaxe | Requirements incomplete; generic effect review |
| 1275 | Rune pickaxe | Requirements incomplete; generic effect review |
| 1293 | Iron longsword | Requirements incomplete; generic effect review |
| 1349 | Iron axe | Requirements incomplete; generic effect review |
| 1353 | Steel axe | Requirements incomplete; generic effect review |
| 1359 | Rune axe | Requirements incomplete; generic effect review |
| 1405 | Mystic air staff | Requirements incomplete; generic effect review |
| 1409 | Iban's staff | Requirements incomplete; generic effect review |
| 1495 | Klank's gauntlets | Requirements incomplete; generic effect review |
| 1506 | Gas mask | Requirements incomplete; generic effect review |
| 1540 | Anti-dragon shield | Requirements incomplete; generic effect review |
| 1580 | Ice gloves | Requirements incomplete; generic effect review |
| 1635 | Gold ring | Requirements incomplete; generic effect review |
| 1724 | Unholy symbol | Requirements incomplete; generic effect review |
| 2402 | Silverlight | Requirements incomplete; generic effect review |
| 2550 | Ring of recoil | Requirements incomplete; generic effect review |
| 2558 | Ring of dueling | Requirements incomplete; generic effect review |
| 2570 | Ring of life | Requirements incomplete; generic effect review |
| 2655 | Zamorak platelegs | Requirements incomplete; generic effect review |
| 2659 | Zamorak kiteshield | Requirements incomplete; generic effect review |
| 2866 | Ogre arrow | Requirements incomplete; generic effect review |
| 2883 | Ogre bow | Requirements incomplete; generic effect review |
| 2890 | Elemental shield | Requirements incomplete; generic effect review |
| 2952 | Wolfbane | Requirements incomplete; generic effect review |
| 2963 | Silver sickle (b) | Requirements incomplete; generic effect review |
| 2978 | Chompy bird hat (ogre bowman) | Requirements incomplete; generic effect review |
| 3097 | Steel claws | Requirements incomplete; generic effect review |
| 3105 | Climbing boots | Requirements incomplete; generic effect review |
| 3175 | Rune spear | Requirements incomplete; generic effect review |
| 3202 | Rune halberd | Requirements incomplete; generic effect review |
| 3335 | Broken bark snelm | Requirements incomplete; generic effect review |
| 3689 | Lyre | Requirements incomplete; generic effect review |
| 3785 | Fremennik purple cloak | Requirements incomplete; generic effect review |
| 3841 | Damaged book (Zamorak) | Requirements incomplete; generic effect review |
| 3855 | Games necklace | Requirements incomplete; generic effect review |
| 4021 | M'speak amulet | Requirements incomplete; generic effect review |
| 4024 | Ninja monkey greegree (small) | Requirements incomplete; generic effect review |
| 4026 | Gorilla greegree | Requirements incomplete; generic effect review |
| 4029 | Zombie monkey greegree (small) | Requirements incomplete; generic effect review |
| 4031 | Karamjan monkey greegree | Requirements incomplete; generic effect review |
| 4035 | 10th squad sigil | Requirements incomplete; generic effect review |
| 4084 | Sled | Requirements incomplete; generic effect review |
| 4156 | Mirror shield | Requirements incomplete; generic effect review |
| 4166 | Earmuffs | Requirements incomplete; generic effect review |
| 4298 | Ham shirt | Requirements incomplete; generic effect review |
| 4300 | Ham robe | Requirements incomplete; generic effect review |
| 4302 | Ham hood | Requirements incomplete; generic effect review |
| 4304 | Ham cloak | Requirements incomplete; generic effect review |
| 4306 | Ham logo | Requirements incomplete; generic effect review |
| 4308 | Ham gloves | Requirements incomplete; generic effect review |
| 4310 | Ham boots | Requirements incomplete; generic effect review |
| 4315 | Team-1 cape | Requirements incomplete; generic effect review |
| 4502 | Bearhead | Requirements incomplete; generic effect review |
| 4551 | Spiny helmet | Requirements incomplete; generic effect review |
| 4567 | Gold helmet | Requirements incomplete; generic effect review |
| 4599 | Oak blackjack | Requirements incomplete; generic effect review |
| 4600 | Willow blackjack | Requirements incomplete; generic effect review |
| 4677 | Catspeak amulet | Requirements incomplete; generic effect review |
| 4798 | Adamant brutal | Requirements incomplete; generic effect review |
| 4827 | Comp ogre bow | Requirements incomplete; generic effect review |
| 5016 | Bone spear | Requirements incomplete; generic effect review |
| 5527 | Air tiara | Requirements incomplete; generic effect review |
| 5529 | Mind tiara | Requirements incomplete; generic effect review |
| 5531 | Water tiara | Requirements incomplete; generic effect review |
| 5535 | Earth tiara | Requirements incomplete; generic effect review |
| 5537 | Fire tiara | Requirements incomplete; generic effect review |
| 5543 | Chaos tiara | Requirements incomplete; generic effect review |
| 5574 | Initiate sallet | Requirements incomplete; generic effect review |
| 6133 | Spined body | Requirements incomplete; generic effect review |
| 6465 | Ring of Charos | Requirements incomplete; generic effect review |
| 6665 | Mudskipper hat | Requirements incomplete; generic effect review |
| 6707 | Camulet | Requirements incomplete; generic effect review |
| 6720 | Slayer gloves | Requirements incomplete; generic effect review |
| 6746 | Darklight | Requirements incomplete; generic effect review |
| 6773 | Rat pole | Requirements incomplete; generic effect review |
| 6786 | Robe of Elidinis (top) | Requirements incomplete; generic effect review |
| 6787 | Robe of Elidinis (bottom) | Requirements incomplete; generic effect review |
| 6885 | Progress hat | Requirements incomplete; generic effect review |
| 7053 | Bug lantern | Requirements incomplete; generic effect review |
| 7398 | Enchanted robe | Requirements incomplete; generic effect review |
| 7399 | Enchanted top | Requirements incomplete; generic effect review |
| 7457 | Black gloves | Requirements incomplete; generic effect review |
| 7458 | Mithril gloves | Requirements incomplete; generic effect review |
| 7459 | Adamant gloves | Requirements incomplete; generic effect review |
| 7534 | Fishbowl helmet | Requirements incomplete; generic effect review |
| 7535 | Diving apparatus | Requirements incomplete; generic effect review |
| 7668 | Gadderhammer | Requirements incomplete; generic effect review |
| 7917 | Ram skull helm | Requirements incomplete; generic effect review |
| 7918 | Bonesack | Requirements incomplete; generic effect review |
| 9185 | Rune crossbow | Unmet Ranged 61 (snapshot Ranged 60); reviewed metadata retained |
| 9731 | Mind shield | Requirements incomplete; generic effect review |
| 9733 | Mind helmet | Requirements incomplete; generic effect review |
| 9944 | Bomber jacket | Requirements incomplete; generic effect review |
| 9945 | Bomber cap | Requirements incomplete; generic effect review |
| 10446 | Saradomin cloak | Requirements incomplete; generic effect review |
| 10491 | Blessed axe | Requirements incomplete; generic effect review |
| 10581 | Keris | Requirements incomplete; generic effect review |
| 10822 | Yak-hide armour (top) | Requirements incomplete; generic effect review |
| 10824 | Yak-hide armour (legs) | Requirements incomplete; generic effect review |
| 10826 | Neitiznot shield | Requirements incomplete; generic effect review |
| 10836 | Silly jester hat | Requirements incomplete; generic effect review |
| 10837 | Silly jester top | Requirements incomplete; generic effect review |
| 10838 | Silly jester tights | Requirements incomplete; generic effect review |
| 10839 | Silly jester boots | Requirements incomplete; generic effect review |
| 11061 | Ancient mace | Requirements incomplete; generic effect review |
| 11136 | Karamja gloves 1 | Requirements incomplete; generic effect review |
| 11855 | Graceful top | Requirements incomplete; generic effect review |
| 11859 | Graceful gloves | Requirements incomplete; generic effect review |
| 11968 | Skills necklace | Requirements incomplete; generic effect review |
| 11986 | Ring of wealth | Requirements incomplete; generic effect review |
| 13104 | Varrock armour 1 | Requirements incomplete; generic effect review |
| 13108 | Wilderness sword 1 | Requirements incomplete; generic effect review |
| 13112 | Morytania legs 1 | Requirements incomplete; generic effect review |
| 13117 | Falador shield 1 | Requirements incomplete; generic effect review |
| 13129 | Fremennik sea boots 1 | Requirements incomplete; generic effect review |
| 13133 | Desert amulet 1 | Requirements incomplete; generic effect review |
| 13137 | Kandarin headgear 1 | Requirements incomplete; generic effect review |
| 13141 | Western banner 1 | Requirements incomplete; generic effect review |
| 19994 | Ranger gloves | Requirements incomplete; generic effect review |
| 21153 | Necklace of passage | Requirements incomplete; generic effect review |
| 21166 | Burning amulet | Requirements incomplete; generic effect review |
| 21169 | Burning amulet | Requirements incomplete; generic effect review |
| 21180 | Flamtaer bracelet | Requirements incomplete; generic effect review |
| 21646 | Granite longsword | Requirements incomplete; generic effect review |
| 21736 | Granite gloves | Requirements incomplete; generic effect review |
| 21760 | Kharedst's memoirs | Requirements incomplete; generic effect review |
| 22941 | Rada's blessing 1 | Requirements incomplete; generic effect review |
| 23249 | Rangers' tights | Requirements incomplete; generic effect review |
| 24942 | Reinforced goggles | Requirements incomplete; generic effect review |
| 29084 | Sulphur blades | Requirements incomplete; generic effect review |
| 30895 | Steel ring | Requirements incomplete; generic effect review |
| 31736 | Storm cruiser's hat | Requirements incomplete; generic effect review |
| 31738 | Storm cruiser's coat | Requirements incomplete; generic effect review |
| 31740 | Storm cruiser's trousers | Requirements incomplete; generic effect review |
| 31742 | Storm cruiser's shoes | Requirements incomplete; generic effect review |
| 33101 | Mooleta | Generic effect review; requirements complete/satisfied; deferred ordinary off-hand review |
| 33104 | Cowbell amulet | Requirements incomplete; generic effect review |
