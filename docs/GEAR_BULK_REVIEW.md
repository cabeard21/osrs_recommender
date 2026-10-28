# Bulk equipment review

Run these maintenance tools from the repository root with the project's Python
environment. Runtime still reads `catalog.json` and `content/items/`; the review
files are offline evidence, not another runtime item database.

## Propose, review, validate, apply

```powershell
python -m tools.bulk_review_gear coverage
python -m tools.bulk_review_gear propose --family content/equipment/reviews/families/metal_chainbodies.json --manifest proposed.json --report review.md
```

By default, discovery skips items with both complete wear metadata and cleared
effects. `--include-reviewed` includes those exact IDs for inspection. The
committed original proposal is under `content/equipment/reviews/proposed/`.
Proposals never change eligibility.

Copy the proposal to an approved manifest. Read the table, exact IDs, physical
fields, proposed overlay, pinned references, and source page text. For each
accepted entry set `decision` to `approved` and provide a nonempty `review_reason`.
Put exactly those IDs in `approved_effect_clearance` after independently checking
their outgoing combat mechanics. Leave other decisions pending or rejected.
Do not change generated fields to override validation. Missing gates, conditional
mechanics, or ambiguous variants need another source review, not a manifest edit.

```powershell
python -m tools.bulk_review_gear validate --family content/equipment/reviews/families/metal_chainbodies.json --manifest content/equipment/reviews/approved/metal_chainbodies.json
python -m tools.bulk_review_gear apply --family content/equipment/reviews/families/metal_chainbodies.json --manifest content/equipment/reviews/approved/metal_chainbodies.json
python -m tools.bulk_review_gear coverage
```

`validate` writes nothing. `apply` validates all output first, then writes the
approved exact-ID overlays, effect clearances, catalog checksum, and maintenance
review registry. Reapplying the same manifest is byte-identical. Existing applied
batches cannot be expanded in place: use another family/batch ID. Existing
overlays, aliases, or generated authored-ID collisions cause rejection.

The importer reuses applied review fingerprints, rejecting changed physical
statistics rather than silently carrying an approval into a new source capture.
It does not introduce ownership aliases. Bonus values, slots, attack profiles,
ammunition compatibility, and every other physical field remain unchanged.

## Add another family without tool changes

1. Copy a family JSON to a new file with a unique `id`, `name_pattern`, and
   `slots`. These select candidates only. Start with `items: {}`.
2. Capture evidence explicitly:

   ```powershell
   python -m tools.capture_bulk_gear --family next-family.json --output content/equipment/reviews/sources/next-family.json
   ```

   This checks the existing pinned Weird Gloop capture checksum and fetches Wiki
   pages, preserving revision IDs, timestamps, full wikitext, page hashes, licenses,
   and physical export rows. Missing pages or ambiguous/multi-form infoboxes are
   not matched to an ID. Network/API failures do not write a partial output.
   Captures are maintenance-time only. Reuse committed evidence offline thereafter;
   another live capture may select newer Wiki revisions and needs fresh review.
3. Set `source_file` to that repository-relative path and `source_sha256` to the
   file's SHA-256. Keep evidence files under version control with LF endings.
4. Define conservative `wear_patterns`: each rule has a known `skill` and a regex
   with a named `(?P<level>...)` group matching an explicit wear statement.
   `quest_patterns` have `quest` and `pattern`; use only positive wear restrictions.
   `ungated_pattern` is allowed only for an explicit statement of no wear gates.
   Crafting levels, quest uses, shop access and drops are not wear requirements.
5. Add exact numeric ID keys to `items` for source-reviewed ordinary candidates,
   each with `classification: ordinary`, `mechanics: ordinary`, and a substantive
   `review_reason`. Requirements and acquisition can be extracted from the pinned
   page using the grammar and infobox. Unrecognised wear prose stays an exception.
   Optional `wear_evidence` excerpts and `requires`/`acquisition` transcriptions
   must match the captured source and grammar. The first family retains these
   explicit excerpts to make the review readily inspectable.
6. A `verified_variant` additionally needs `variant_of` and an independently
   captured reference export row with equal physical data apart from ID/name.
   It still gets its own requirement overlay and exact-ID effect approval.
   No runtime identity is merged. Put unresolved IDs in `exceptions` with a short
   reason; omitted IDs always remain exceptions. Conditional-mechanics keywords
   are an advisory extra blocker, never proof that an item is ordinary.
7. Generate a proposal and review the exact-ID table before validation/application.

The tool trusts reviewed family grammar and pinned evidence files as local
maintenance inputs; it is not a signed approval service or a general Wiki prose
interpreter. Keep grammar narrow. Unsupported requirements/effects fail closed.
Input revisions, capture bytes, physical fields, and authored content are checked
again at validation. A changed baseline needs a fresh proposal/review. Authored
fingerprints normalise platform line endings and paths.

Use one writer at a time. Ordinary replacement failures restore original bytes.
A process kill or power loss during replacement can leave a mismatched
catalog/checksum pair; restore the reviewed files from version control together
before retrying. No database, UI, search, formula, or deployment changes are involved.

## First applied batch

The seven plain metal chainbodies add seven supported physical IDs. See
[the exact-ID review and exception report](GEAR_BULK_CHAINBODIES_REVIEW.md).
Catalog-wide coverage changes from 187 to 194 metadata-supported IDs out of
5,435. Complete requirements change from 266 to 273; cleared effects from 198
to 205. These are catalog metadata counts, not account ownership or optimization
selection counts. Every unapproved physical row remains byte-for-byte equivalent
as a JSON value; only the seven approved effect flags change.
