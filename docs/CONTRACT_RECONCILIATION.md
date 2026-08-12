# Contract reconciliation — `sync_payload.schema.json` v1

**Status: FROZEN, 2026-08-11.** Reconciled against real snapshots from **RuneLite 1.12.35**,
captured by the Step 8.5 spike on a live account (combat 63, 96 quest points). The redacted
capture is committed at `tests/contracts/fixtures/real_snapshot.json` and asserted by
`tests/contracts/test_real_snapshot.py`.

**The shape did not change, so `payload_version` stays `1`** and
`SUPPORTED_PAYLOAD_VERSIONS = {1}` in `tracker/api/sync.py` is unchanged. The real payload
validated against the provisional schema with **zero errors**. That is a stronger result than
the plan expected — §13 chose side-loading precisely because it assumed the contract would
churn — and it means the churn budget was spent on *semantics* rather than structure.

| Capture | What it settled |
|---|---|
| 24 skills, incl. `sailing` at level 1 / 0 xp | `xp` is never negative from the client (G5) |
| 211 quests, every one with a readable state | Quest identity; `unknown` is not needed from this source |
| 48 diary + 6 CA varbits | A12's `diary_*` / `ca_*` prefixes work |
| 216 observed items, 3 container scans | The §6.5 ownership trichotomy is representable |

---

## The four questions the plan said only a real client could answer

### 1. Quest identity — **ruled: slug of the RuneLite `Quest` enum constant**

RuneLite offers three identities per quest: the enum constant (`DESERT_TREASURE_I`), a numeric
`getId()` (27), and a display name (`Desert Treasure I`). The spike emitted all three into its
`raw` block so the choice could be made from evidence.

**The evidence chose it.** `content/` independently authors `quest: desert_treasure_i` and
`quest: lunar_diplomacy`; lowercasing the enum constant and replacing non-alphanumerics yields
*exactly* those strings. Two ids, authored months apart on opposite sides of the seam, agreeing
without coordination is the strongest signal available here.

Rejected: **numeric ids**, because they have gaps (0, 1, 3, 4 — id 2 is absent) and would make
content unreadable; **display names**, because they carry apostrophes and punctuation
(`Alfred Grimhand's Barcrawl`, `Romeo & Juliet`, `Between a Rock...`) that no `content_key`
pattern admits, and would need a lossy transform anyway.

Two consequences Step 12b inherits:

- **Recipe for Disaster is both a quest and ten sub-quests.** The parent
  (`recipe_for_disaster`, `in_progress`) and its ten children
  (`recipe_for_disaster_another_cooks_quest`, …) are separate entries with independent states.
  Content that wants "RFD complete" must name the parent; content that wants a specific subquest
  gate must name the child. Both are available; neither is derived from the other.
- **Quest ids are stable against renames only as far as the enum is.** A RuneLite enum rename
  silently changes a `quest_id`. That is a schema-invisible break, and the reason the fixture
  test exists.

### 2. Varbit → unlock key mapping — **partially ruled; the gap is Step 12b's**

Diaries and CAs work exactly as A12 assumed: `Varbits.DIARY_*` and
`Varbits.COMBAT_ACHIEVEMENT_TIER_*` enumerate reflectively, and `value > 0` reads as `unlocked`.
The capture shows `diary_ardougne_easy: unlocked` with the other 47 locked, matching the account.

**But the unlock keys `content/` actually needs are not being collected at all.** Content
references `ancient_magicks`, `rigour`, `protect_item` and `spellbook_lunar`; the spike emits
only `spellbook_*`, `diary_*` and `ca_*`. Step 12b must author the varbit mapping for the
prayer and spellbook unlocks. **This is a collection gap, not a contract gap** — the schema
already carries arbitrary `content_key` unlock rows, so no version bump is implied.

### 3. Spellbook — **the spike's reading is wrong, and the schema must not inherit it**

`Varbits.SPELLBOOK` reports the **currently active** spellbook (0 standard / 1 ancient /
2 lunar / 3 arceuus). The capture emitted `spellbook_standard: unlocked`.

That is a different fact from the one `unlock` means. Content authors `unlock: spellbook_lunar`
to ask *"can this player use Lunars?"*; a player with Lunars unlocked but Standard open would
answer **no** under the spike's rule — and would flip to yes merely by changing altar. An
`unlock` whose value changes when the player walks somewhere is not an unlock.

**Ruling:** `spellbook_*` unlock rows mean *available to the player*, derived from the quest
that grants the book (Lunar Diplomacy → `spellbook_lunar`, Desert Treasure I →
`spellbook_ancient`), never from the active-book varbit. If the active book is ever wanted, it
needs a distinct key prefix and a distinct name — it is not this fact.

### 4. Is a complete container scan detectable? — **yes, on change; no, on silence**

This one took four captures and inverted twice, so the mechanics are recorded exactly.

- `client.getItemContainer(93 | 94 | 95)` returned **null** for inventory, equipment and bank on
  a `LOGGED_IN` client whose bank had just been closed. The gameval ids are correct and match
  the deprecated enum's (`INV=93`, `WORN=94`, `BANK=95`).
- `client.getItemContainers()` — the whole hash table — enumerated **zero** entries at the same
  moment. So it is not an id problem; that entire lookup surface reads empty from a plugin's
  vantage point in this version.
- `ItemContainerChanged` works. It carries the container and its id directly, and every capture
  that touched a container got it: bank on open (215 items), inventory and equipment on change.

**The rule is change, not emptiness.** The decisive capture emptied the inventory (withdraw an
item, equip it) and the inventory *still* fired — producing a `container_scans` row with **no**
`observed_items`. That is §6.5's "looked, found nothing", and it is representable. A container
that is never touched in a session stays silent, and the payload then honestly carries no scan
for it — which the app reads as `unknown`, which is correct.

**Step 12b's constraint, stated plainly:** the collector cannot force a read. An account that
logs in with an empty inventory and never touches it produces no inventory evidence at all. The
bank widget's open/close edges do fire independently (recorded in the spike's
`raw.bank_widget_edges`) and are the natural pairing for the bank; equivalent triggers for
inventory and equipment do not exist and must not be faked. **Emitting a scan the client never
witnessed is the one failure mode that silently destroys the unknown-state design** — it turns
"never looked" into "owns nothing", which is D8's bug wearing a different hat.

---

## Findings that need no contract change

- **`net.runelite.api.Varbits` and `VarPlayer` are deprecated** in 1.12.35, superseded by
  `gameval.VarbitID` / `VarPlayerID`. Only the deprecated classes carry *named* constants, which
  is what makes reflective enumeration of the 48 diary and 6 CA varbits possible. Step 12a
  chooses: depend on a deprecated surface, or hand-transcribe ids and own the drift.
- **`xp` is never `null` from the plugin.** The client reports `0` for an untrained skill
  (`sailing`: level 1, 0 xp), never `-1`. G5's "-1 normalizes to null" rule therefore belongs
  entirely to the hiscores/WOM adapters (§7.3); nothing normalizes at this boundary.
- **New skills appear without warning.** `sailing` is in the enum and in the payload. Content
  and the projection must tolerate a skill key they do not know rather than reject the payload —
  the schema's open `content_key` already does.
- **Bank placeholders were zero on this account** but the collector skips `quantity < 1` slots
  regardless, since the schema requires `quantity >= 1`. Placeholder-heavy banks are untested.
- **Combat achievement tiers all read `locked`** on this account, so the `> 0` threshold for CA
  varbits is *unverified against a positive case*. Recorded rather than claimed.

## What this cost

Four captures. The first three failed usefully: null containers (twice, ruling out the id and
the fallback scan) and then an empty-container silence that only made sense once the account's
inventory state was known. The spike's `raw` block — quest triples, varbit values, container
event ids and times — is what turned each failure into a ruling instead of a guess.
