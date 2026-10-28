# OSRSReboxed bulk requirements

This import report describes verified-only eligibility. The optional community
policy now enables suitable ordinary equipment under explicit assumptions; see
[community policy and measured coverage](GEAR_COMMUNITY_POLICY.md).

The community dataset is useful for bulk **partial skill gates**, but does not
justify automatically declaring wear requirements complete. The small importer
now supplies those skill gates without replacing physical equipment data,
approved overlays, combat calculations, or effect blockers. No new review
framework was added. These are catalog-wide counts for the current working tree,
including its existing manual expansion overlays; they are not account eligibility counts.

## Source and exact-ID comparison

Downloaded the entire 16,923-record
[items-complete.json](https://raw.githubusercontent.com/DayV-git/osrsreboxed-db/4b3ac03c6a5b1df8ce56bc2bad83813b382a913d/docs/items-complete.json),
pinned to commit `4b3ac03c6a5b1df8ce56bc2bad83813b382a913d`.
SHA-256: `a7ff79b5811b3999464f0a4a3e03d827a9926520db425b2d9d506ce0b221a6a3`.
Repository license: GPL v3; the accompanying upstream license is retained in
`content/equipment/OSRSREBOXED_LICENSE.txt`. Source attribution and hash are in the
generated sidecar. The complete downloaded source is cached locally under
`.tmp/osrsreboxed/items-complete.json`; it is not a second physical catalog.

| Catalog comparison | IDs |
| --- | ---: |
| Physical catalog | 5,435 |
| Exact IDs present in source | 5,430 (99.91%) |
| Populated `equipment.requirements` maps | 1,968 |
| Valid maps usable with our registry | 1,932 |
| Rejected maps with unregistered Sailing skill | 35 |
| Rejected source record flagged incomplete | 1 |
| `requirements: null` | 2,856 |
| Matching ID, no equipment record | 606 |
| No matching ID | 5 |
| Equipment record with missing requirements key | 0 |
| Explicit empty requirements object | 0 |

All 1,932 accepted maps contain skill gates; 22 also contain `combat`, mapped to
our existing combat-level leaf. No names, aliases, noted/unnoted transformations,
or presumed variant equivalence are used for matching. The 606 records without
equipment data include alternate/degraded forms; they remain unknown rather than
inheriting another physical ID's gates.

Of 289 IDs with existing complete reviewed overlays, 196 have exactly matching
conjunctive skill maps, 17 differ, and 76 have no comparable source map. This is
agreement of skill minima, not proof that quest/unlock requirements agree.
The importer preserves all 289, including reviewed unrestricted items.

## Before and after

| Coverage measure | Before | After |
| --- | ---: | ---: |
| Items with a nonempty requirement tree | 231 | 1,950 |
| Complete reviewed wear gates (including unrestricted) | 289 | 289 |
| Incomplete wear gates | 5,146 | 5,146 |
| Items retaining special-effect blockers | 5,214 | 5,214 |
| Complete gates and no effect blocker | 210 | 210 |
| Items needing gate and/or effect review | 5,225 | 5,225 |

**1,719 currently blocked items gain partial requirements; zero become newly
rankable.** Of these, 1,714 also retain effect blockers. The five with clear effects
are bolts `9140–9144`; their wear gates still remain incomplete. There are 5,135
items with both incomplete gates and effect blockers, so these categories overlap.
The 5,146 gate exceptions require confirmation of quest/unlock/other gate
completeness, not necessarily a quest requirement on each item.

## Why null, empty and ungated cannot be equated

Raw absent equipment, absent key, `null`, `{}`, and populated maps are structurally
distinguishable, and the importer keeps those states separate in its report.
But this source has **no reliable explicit-ungated marker**. In particular:

- Leather gloves `1059`, Climbing boots `3105`, and Barrows gloves `7462` all use
  `null`, despite differing existing reviewed requirements.
- Rune platebody `1127` gives only Defence 40; Dragon scimitar `4587` gives only
  Attack 60. Both have `quest_item: false`, while our reviewed overlays retain
  their equip quest gates. `quest_item` is therefore not a gate-completeness flag.
- `incomplete: false` does not certify complete equip gates. It appears on the
  above records too.

Empty objects, if encountered on a future update, are likewise skipped rather
than interpreted as approved unrestricted equipment. Populated skill maps cannot
prove the absence of quest gates. Consequently this dataset can replace manual
transcription of ordinary skill levels, but cannot by itself replace the remaining
gate/effect decisions or safely unlock thousands of catalog items.

## Remaining exceptions

All affected exact IDs, classifications, disagreements and remaining blocker lists
are in `content/equipment/requirements-report.json`. It is a generated audit, not
an approval queue or another source of physical statistics.

The five unmatched beta IDs are `25493, 25494, 25495, 25496, 25497`.
The incomplete source record is Keris partisan of amascut `30891`.
The 35 rejected maps include max cape/hood variants and Sailing capes/hoods:
`13337, 13338, 20760, 20764, 24135, 21898, 21900, 24134, 13329, 13330,
13335, 13336, 24234, 21784, 21786, 24232, 21776, 21778, 24233, 21780,
21782, 24133, 21285, 21282, 13342, 13281, 24855, 24857, 31290, 31288,
31292, 13331, 13332, 13333, 13334`.
Whole maps are skipped rather than silently dropping the unknown Sailing gate;
the local skill registry remains authoritative.

The 17 disagreements below are recorded, not resolved in favor of either source.
`none` means our complete reviewed overlay has no skill gate; it is not a missing
overlay. Some ammunition differences may describe weapon-use rather than equip
gates, which is another reason not to automatically replace reviewed metadata.

| Physical ID / item | Reviewed skills | Source skills |
| --- | --- | --- |
| 890 Adamant arrow | none | Ranged 30 |
| 21326 Amethyst arrow | none | Ranged 50 |
| 11828 Armadyl chestplate | none | Defence 70, Ranged 70 |
| 11802 Armadyl godsword | none | Attack 75 |
| 11832 Bandos chestplate | none | Defence 65 |
| 21643 Granite boots | Defence 50, Strength 50 | Defence 50 |
| 10380 Guthix chaps | Ranged 70 | Defence 40, Ranged 70 |
| 21791 Imbued Saradomin cape | Magic 75 | Magic 50 |
| 27238 Masori body (f) | Ranged 80, Defence 30 | Ranged 80, Defence 80 |
| 27241 Masori chaps (f) | Ranged 80, Defence 30 | Ranged 80, Defence 80 |
| 27235 Masori mask (f) | Ranged 80, Defence 30 | Ranged 80, Defence 80 |
| 888 Mithril arrow | none | Ranged 20 |
| 21944 Ruby dragon bolts (e) | none | Ranged 64 |
| 892 Rune arrow | none | Ranged 40 |
| 1133 Studded body | Ranged 20 | Defence 20, Ranged 20 |
| 20997 Twisted bow | Ranged 85 | Ranged 75 |
| 27690 Voidwaker | none | Attack 75 |

## Refresh mechanism

Download `docs/items-complete.json` from a pinned upstream commit, then run:

```powershell
.\.venv\Scripts\python.exe -m tools.import_reboxed_requirements `
  --source .tmp/osrsreboxed/items-complete.json `
  --commit 4b3ac03c6a5b1df8ce56bc2bad83813b382a913d `
  --output content/equipment/requirements.json `
  --report content/equipment/requirements-report.json
```

The import is deterministic and offline. It reads the existing physical catalog,
validates exact IDs, registered skill keys and integer levels (rejecting booleans),
and writes only a requirements sidecar and report. The pinned commit is supplied
by the operator; the SHA-256 records the actual local bytes. There is no automatic
network refresh or claim that the importer authenticates a supplied file's origin.

The loader uses a sidecar map only when the physical ID has no authored overlay.
Existing overlays win even when explicitly unrestricted or marked unknown. All
source-only trees retain `requirements_complete=False`; special effects,
acquisition, tradeability, content IDs and physical fields remain unchanged.
An unregistered skill in a reduced/custom content registry makes the entire map
unavailable. The catalog revision incorporates the sidecar bytes so cached
calculations cannot mistake a metadata refresh for unchanged input.

To inspect the reviewed-only baseline, use
`load_catalog(content, use_requirements_source=False)`. To stop using community
partial gates, remove the generated `requirements.json`; original overlays and
physical catalog remain sufficient to load the catalog.

Focused tests cover state distinctions, malformed records, integer/skill checks,
combat gates, deterministic CLI output, output-path protection, overlay precedence,
and preservation of every existing catalog definition except new partial trees.
The historical Phase 1 nonbatch digest drift was traced to legitimate existing
bulk approvals, not physical-statistics or requirements-import changes. Compared
with `HEAD`, exactly 23 physical rows changed, all solely by clearing the generic
effect marker: seven chainbodies, three full helms, eight kiteshields, three
platebodies and two platelegs. Their applied manifests and pinned-source tests
independently cover identity, physical statistics, wear gates and effects.
The historical test restored only the seven chainbody overlays. It now restores
the approved metadata for all 23 explicitly listed IDs to reconstruct its old
baseline; no physical field is removed from the digest. This reproduces the
**original** expected SHA-256
`e6872e89c7e99f756e1ff03fec15c492ce65201954c0c1ba8b4f3ac699d085fc`
without changing its expected value. Community requirements stay disabled for
this historical baseline check.
Verification of this correction: all 189 Phase 1, bulk-expansion and bulk-review
tests passed; formatting and lint checks passed for the changed test file.
Original importer validation: 131 tests passed, 97% coverage across the importer and
requirement parser, with lint, formatting and focused type checks passing. The
earlier larger run including Phase 1 had 220 passes and that one historical digest failure
before the final additional malformed-record state test was added.
