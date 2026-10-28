# metal_chainbodies equipment review

Discovery is not approval. Exact physical IDs only.

| ID | Item | Classification | Decision | Wear/acquisition | Source | Reason |
|---|---|---|---|---|---|---|
| 1101 | Iron chainbody | ordinary | approved | {"skill": {"defence": 1}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15320142) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. Black Knights' Fortress, King's Ransom and While Guthix Sleeps are uses, not equip requirements. |
| 1103 | Bronze chainbody | ordinary | approved | {"skill": {"defence": 1}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15320183) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. |
| 1105 | Steel chainbody | ordinary | approved | {"skill": {"defence": 5}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15182585) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. |
| 1107 | Black chainbody | ordinary | approved | {"skill": {"defence": 10}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15182608) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. |
| 1109 | Mithril chainbody | ordinary | approved | {"skill": {"defence": 20}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15320194) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. |
| 1111 | Adamant chainbody | ordinary | approved | {"skill": {"defence": 30}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15182714) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. Song of the Elves is an item use, not an equip requirement. |
| 1113 | Rune chainbody | ordinary | approved | {"skill": {"defence": 40}} / tradeable | [pinned source](https://oldschool.runescape.wiki/w/Special:PermanentLink/15182848) | Exact unornamented physical ID; explicit Defence wear gate; static armour bonuses only. No quest wear gate; crafting and quest-use facts excluded. |
| 3140 | Dragon chainbody | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Dragon chainbody needs its own wear/acquisition review; no metal-tier inheritance. |
| 6615 | White chainbody | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | White chainbody needs independent wear and acquisition review; no black-equipment inheritance. |
| 12414 | Dragon chainbody (g) | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Gold dragon form needs independent exact-ID variant and wear review. |
| 20149 | Gilded chainbody | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Gilded physical identity needs source-backed variant review; no rune alias approval. |
| 22616 | Vesta's chainbody (Deadman Mode) | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Deadman form: suspected mode restrictions or conditional mechanics; manual source/effect review required. |
| 27831 | Vesta's chainbody (bh) | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Bounty Hunter form: suspected mode restrictions or conditional mechanics; manual source/effect review required. |
| 27842 | Corrupted vesta's chainbody (bh) | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Corrupted Bounty Hunter form: suspected restrictions or conditional mechanics; manual source/effect review required. |
| 28065 | Dragon chainbody (cr) | manual_review_exception | rejected | unknown / unknown | [pinned source](https://github.com/weirdgloop/osrs-dps-calc/blob/89c3e25b344aea90d0189746e4b5f73dde0f0383/cdn/json/equipment.json) | Crater form needs independent exact-ID mechanics and wear review. |

Proposed effect clearances: [1101, 1103, 1105, 1107, 1109, 1111, 1113]
Approved effect clearances: [1101, 1103, 1105, 1107, 1109, 1111, 1113]

Catalog-wide coverage (not account ownership or search selection):

| Measure | Before | After |
|---|---:|---:|
| Physical IDs | 5,435 | 5,435 |
| Complete requirements | 266 | 273 |
| Effects cleared | 198 | 205 |
| Both metadata gates satisfied | 187 | 194 |

Validation: 49 bulk/capture tests passed, with 94% combined tool coverage;
44 requirement tests passed; 342 selected catalog/evaluator/optimizer regression
checks passed (the historical digest check passed separately after its update).
The original historical digest is retained by restoring only these seven IDs'
approved metadata inside that assertion. All physical fields still participate.
Content validation and scoped Ruff checks pass. Comparing the catalog to the
pre-batch Git revision finds only seven `unsupported_effects` changes, with
identical physical ID sets and no physical-stat changes. Approved and applied
manifests are byte-identical. Reapplication is byte-identical and partial-approval
tests verify that every unapproved row remains unchanged.
