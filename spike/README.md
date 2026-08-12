# `spike/` — throwaway code, deleted at the end of Step 8.5

Nothing in this directory ships. Plan step 8.5's last task is *"delete the spike code"*, and its
exit criteria require `plugin/` to still be empty when the step closes — Step 12a builds the real
plugin there, against the **frozen** contract this spike exists to freeze.

## What `snapshot-spike` does

Press a hotkey in RuneLite; it writes one snapshot of the logged-in account to `~/snapshot.json`.
No auth, no HTTP, no practice detection, no retry.

The file has two halves:

- the **schema half** — a best-effort attempt at `contracts/sync_payload.schema.json`, so the
  Python side can validate it directly;
- **`raw`** — everything the schema half had to guess at or discard. This is the material for
  `docs/CONTRACT_RECONCILIATION.md`.

## Running it

Requires JDK 11+ (Temurin 17 is what this machine has) and network access to
`https://repo.runelite.net`. Gradle itself is vendored — use the wrapper, don't install Gradle.

```bash
cd spike/snapshot-spike
./gradlew build          # or gradlew.bat on Windows
./gradlew runClient      # launches RuneLite in developer mode with the spike loaded
```

`runClient` starts a normal RuneLite client. Nothing is copied into
`~/.runelite/sideloaded-plugins` — real side-loading is Step 12's human gate, not this one.

Then, in the client:

1. Log in to the account you want the contract reconciled against.
2. **Open your bank and close it.** This matters more than it looks: the bank item container
   does not exist until the bank has been opened, and the spike stamps the bank's
   `container_scans` entry with the *close* time, not the capture time (§4.5 — observation time
   is not truth). Skip this and the snapshot legitimately carries no bank scan, which is the
   `unknown` case of §6.5, not the empty case.
3. Press **Ctrl+Shift+S** (rebindable under the plugin's config).
4. A game message confirms the write and states whether a bank scan was emitted. Failures are
   reported in chat and logged — the spike never fails silently.

The client is pinned to **RuneLite 1.12.35**, matching `~/.runelite/repository2` on this
machine. If your client auto-updates past that, bump `runeLiteVersion` in `build.gradle`.

## Findings already banked, before any capture

These came out of writing the spike and belong in the reconciliation doc:

- **`net.runelite.api.Varbits` and `VarPlayer` are deprecated** in 1.12.35, superseded by
  `net.runelite.api.gameval.VarbitID` / `VarPlayerID`. The spike deliberately keeps the
  deprecated classes: their constants are *named* (`DIARY_WILDERNESS_HARD`,
  `COMBAT_ACHIEVEMENT_TIER_MASTER`), which is what makes reflective enumeration of the diary and
  CA sets possible. Step 12a has to decide whether to depend on a deprecated surface or
  hand-transcribe ids from `gameval`.
- **The active spellbook is not the unlocked spellbook.** The spike reads `Varbits.SPELLBOOK`,
  which says which book is *currently* open. The schema's `unlock` semantics want "Ancients are
  available to you" — a different fact. Emitted as `spellbook_<active>: unlocked` and flagged
  here so the diff catches it.
- **Quest identity is unresolved by design.** The spike emits a slug of the RuneLite enum
  constant as `quest_id` and records the enum name, numeric id and display name in
  `raw.quests[]`. Pick the identity from that evidence; `content/` currently authors its own
  quest ids and the two have to be reconciled deliberately.
- **`xp` is never null from the client.** RuneLite reports 0 for an untrained skill, not −1, so
  G5's "−1 normalizes to null" rule has nothing to do at this boundary — it belongs to the
  hiscores/WOM adapters (§7.3). Whether an untrained skill should transmit `xp: 0` or be omitted
  is a live question.
