# Building and running the RuneLite plugin

Side-loading from a local build is **the only supported distribution path for v1** (SDD §13, D5).
Plugin Hub submission is explicitly out of scope and must not touch the critical path.

## Prerequisites

| Need | Notes |
|---|---|
| JDK 11+ | Temurin 17 works. Set `JAVA_HOME`. |
| Network | `https://repo.runelite.net` for the client jars, Maven Central for the rest. |
| Gradle | **Not required.** The wrapper is vendored — always use `./gradlew` (`gradlew.bat`). |

## Build

```bash
cd plugin
./gradlew build          # compiles, generates SyncPayloadFields, runs all tests
```

The build generates `SyncPayloadFields` from `contracts/sync_payload.schema.json`. If you rename a
property in the contract, the plugin stops compiling — that is deliberate (§12.1).

## Run

```bash
./gradlew runClient
```

This launches RuneLite with the plugin loaded and `--developer-mode`. Assertions are enabled
for our plugin, the `RuneLite` developer-mode startup check, and `ExternalPluginManager`
(whose `loadBuiltin` requires them), rather than globally. RuneLite's built-in plugins retain
normal-launcher assertion settings: a built-in `AssertionError` can escape the event bus and
freeze the game loop while audio keeps playing.
Before launch, Gradle checks RuneLite's published release in its Maven repository and warns if
`plugin/build.gradle` is pinned to a different version. The check leaves the pin unchanged so the
collector and payload contract can be reviewed before an update. If the check is unavailable,
the pinned client still launches; `--offline` skips the check.

The version check only compares release numbers; it does not check client stability.
`runClient` uses a separate RuneLite runtime dependency graph so contract-test libraries cannot
replace the client's logging dependencies. `./gradlew verifyRunClientRuntime` checks that logging
works, assertions are scoped correctly, and test-only libraries are absent; `build` runs this
check too.

If the client freezes or closes shortly after startup, retain the `runClient` console output and check
`~/.runelite/logs/client.log`. The normal launcher uses its bundled Java runtime while Gradle
uses your configured JDK, so matching client versions can still behave differently.

> **You cannot side-load into a launcher-started client, and this is by design.** Verified against
> `client-1.12.39`:
>
> ```
> developerMode = options.has("developer-mode") && RuneLiteProperties.getLauncherVersion() == null
> ```
>
> The RuneLite launcher always sets `runelite.launcher.version`, so a launcher-started client forces
> developer mode **off** — and `PluginManager.loadSideLoadPlugins()` returns immediately without it.
> Copying a jar into `~/.runelite/sideloaded-plugins` and launching through the Jagex Launcher does
> nothing at all, and adding `--developer-mode` as a launcher client argument does not help either:
> the launcher-version check defeats it. `./gradlew runClient` is the way to run this plugin.

### If you use a Jagex account

The dev client cannot log in with a Jagex account directly — that is the launcher's job. Borrow its
credentials once:

1. `<RuneLite install>\RuneLite.exe --configure` — set **Client arguments** to
   `--insecure-write-credentials`. The launcher persists this to `~/.runelite/settings.json`.
2. Launch RuneLite from the Jagex Launcher as usual and log in. The client writes
   `credentials.properties` (look in `~/.runelite/`; the path is overridable with
   `-Drunelite.credentials.path`).
3. Close that client and run `./gradlew runClient`. It picks up the dumped credentials.
4. When you are done, **clear the client argument and delete `credentials.properties`.** It holds
   live access and refresh tokens for your account — treat it exactly like a password. It is
   gitignored as a backstop, but deleting it is the actual fix.

The flag is named `insecure` for a reason. It is a development detour, not a setup step.

## Configure

In the plugin's settings panel:

| Setting | Value |
|---|---|
| Server URL | `http://127.0.0.1:8502` — must match `bind_address`/`port` in your `config.yaml` |
| API token | the `api_token` from `config.yaml` |
| Sync on login | on by default |
| Practice detection | on by default (§7.6) |

§11.1 rejects `0.0.0.0` and §11.5 is explicit that there is no public deployment story: point this
at a loopback or Tailscale address, never a forwarded port.

## Version compatibility — §13.1 stage 1

Stage 1 of the §13.1 ladder is *"local checkout, Gradle build, side-load, **manually matched
app/plugin versions**"*. Three numbers have to stay in step:

| Number | Where | Today |
|---|---|---|
| RuneLite client | `plugin/build.gradle` → `runeLiteVersion` | `1.13.1` |
| Payload contract | `AccountSnapshot.PAYLOAD_VERSION` and `tracker/api/sync.py` → `SUPPORTED_PAYLOAD_VERSIONS` | `1` |
| Contract findings | `docs/CONTRACT_RECONCILIATION.md` | captured against 1.12.35; recheck on 1.13.1 |

The 1.13.1 plugin build and tests pass. The developer-mode launcher rule was checked against
1.12.39 source. The live-account collector findings in `CONTRACT_RECONCILIATION.md` have not
yet been recaptured on 1.13.1; verify a fresh sync before relying on them for this release.

**If your client auto-updates past 1.13.1**, bump `runeLiteVersion` and re-read the reconciliation
doc rather than just changing the number. Its four rulings are facts about a specific client build —
particularly that `getItemContainer` returns null and containers must come from
`ItemContainerChanged`. A client update is exactly when that could change, for better or worse.

**If the payload shape changes**, §12.2 requires a `payload_version` bump on both sides in the same
change. The server answers 409 to a version it does not know, and the plugin surfaces that as a
rejection rather than retrying — see `HttpTrackerSyncClient`.

## What the plugin sends

Only what `contracts/sync_payload.schema.json` declares. `additionalProperties: false` on every
object makes §7.6's collection boundary a contract rather than a convention (G8), and
`PayloadKeySetAuditTest` walks the serialized payload to prove no undeclared key rides along.

Practice events carry exactly four fields — domain, start, end, evidence type. No opponent names, no
chat, no prayer selections, no fight-time inventories, no tick-by-tick location. That is the whole
vocabulary, and it is enforced in three places: the detector's shape, the schema, and the audit test.

## Enhanced PvP Status Bars — Phase 1

The optional bars run locally in the existing **OSRS Tracker** plugin, with no server connection
required. They do not send HP, eating information, opponents, or diagnostics to the backend.
Disable RuneLite's built-in **Status Bars**, then enable **Enhanced Status Bars** in OSRS Tracker.
When both are active, enhanced bars are suppressed and the sidebar displays a separate warning;
existing account-sync status remains visible. No built-in settings are changed.

| Settings section | Defaults and behavior |
|---|---|
| Enhanced Status Bars | Bars **off**; numerical counters and icons **on**. |
| Hitpoints Scaling | Automatic **on**; manual override **off**, value **99**. |
| Eating Thresholds | Master and all three markers **on**; Shark **20/yellow**, double eat **35/cyan**, triple eat **56/purple**. |
| HP Diagnostics | **Off**; finite local log snapshots on scaling/state changes, never continuous current-HP logging. |

Automatic scaling recognizes LMS from RuneLite's existing LMS overlay widget. Pete K detection
requires the instance-adjusted player position to be in template region **11100**, plane **0**,
and a loaded combat-form Pete NPC with ID **16579–16586** or **16588–16597**. Detection does not
require an attack to be active and is re-evaluated from current state. Missing combat forms,
leaving the arena, and logout remove detection; no maximum is carried into the next account.
The user confirmed that **Penultimate and Ultimate** fights normalize player maximum HP to 99.
Other tutorials and unknown NPC forms are not assigned 99 automatically.

Maximum resolution order is recognized activity (automatic enabled), enabled manual override,
then real account HP. Disable automatic scaling to force the manual value. Manual maximum and
nominal healing settings accept 1–255, with runtime checks for imported/invalid configuration.
Current HP text retains actual HP even above the maximum; fill clamps to zero/full. Unavailable
maximums do not render a misleading full HP bar. Prayer is calculated separately, and no Pete
HP rule or manual HP value changes its maximum.

Markers describe **full nominal healing efficiency**, not a recommended combat eating time.
For maximum M and configured healing H, the threshold is M−H and the line lies H/M down from
the drawable top. At maximum 99, default thresholds are **79, 64, 43**. At maximum 54 they are
**34, 19**, with the 56-healing line omitted. Values at or outside the usable range are omitted.
Preset names are examples: configure totals for your consumables, level, and mode. Coincident
pixel rows retain their threshold and display split colors. Icons and numerical values draw
above the markers.

The familiar HP-left/Prayer-right anchors support fixed, resizable classic, and resizable modern
interfaces. Bars are hidden without a valid logged-in player or required viewport widget.
Restoration previews, combat auto-hide, extra appearance options, and combat analytics are deferred.

### Startup, shutdown, and diagnostics

Existing startup creates the sidebar and HTTP sync client. Login arms the delayed login sync,
game ticks trigger it, snapshots are built on the client thread, and HTTP work runs on the executor.
Those account-sync paths remain separate from enhanced bars. Overlay registration is reconciled
on startup and configuration/profile/plugin changes; disable and shutdown remove it. Registration
is idempotent, and callbacks from an earlier lifecycle cannot re-register a stopped overlay.

To investigate an unrecognized tutorial, temporarily enable local diagnostics and capture before
entry, each exercise, damage/healing, exit, and logout. Record current and real HP, confirmed
exercise maximum, provenance, instance-adjusted region/plane, recognized NPC IDs, and visible
interfaces. Use RuneLite developer tools for candidate varp values if needed. Share only relevant
log snippets; diagnostics remain local. Automatic Pete detection is source-backed and uses public
RuneLite 1.13.1 APIs, but **live-game acceptance remains pending**.

### Build and live acceptance

Use the existing workflow from the `plugin` directory (PowerShell):

```powershell
.\gradlew.bat build --no-daemon
.\gradlew.bat runClient
```

The build includes plugin tests and `verifyRunClientRuntime`; the RuneLite pin, side-load identity,
launcher assertions, and isolated runtime graph are unchanged. No Plugin Hub release is provided.

1. Disable built-in Status Bars and enable enhanced bars; verify ordinary 54/54 and damaged HP.
2. Enter LMS and verify 54/99 and 99/99 scaling; leave and confirm real account maximum returns.
3. Enter both Pete Penultimate and Ultimate fights; verify 99 maximum during attack pauses and
   NPC form switches, then verify reset on exit and logout/login.
4. Test an unsupported tutorial with manual 99 fallback; disable automatic scaling to force manual.
5. Verify default marker thresholds, configurable healing/colors, individual switches, overlapping
   positions, and actual HP text during overhealing. Confirm Prayer remains independent.
6. Test fixed, resizable classic, and resizable modern interfaces; confirm readability while resizing.
7. Reload/profile-switch and confirm settings persist without duplicate overlays. Test with the
   backend unavailable. Enable built-in bars to check warning/suppression, then disable it to resume.
8. Disable enhanced bars and stop/restart the plugin; confirm clean removal and existing sync operation.

Do not treat unit tests or offscreen rendering as live-game acceptance.

### Source investigation and attribution

PvP Performance Tracker explicitly recognizes Pete, rather than merely inferring tutorial activity
from player-like combat. [`PeteKayer.isArena/isPete/canTrack`](https://github.com/Matsyir/pvp-performance-tracker/blob/3e8c5bac7f3c6357fe6b9ca79428f2f954465ec7/src/main/java/matsyir/pvpperformancetracker/utils/PeteKayer.java)
provides the region/plane and combat-form ID evidence. Its
[`PvpPerformanceTrackerPlugin`](https://github.com/Matsyir/pvp-performance-tracker/blob/3e8c5bac7f3c6357fe6b9ca79428f2f954465ec7/src/main/java/matsyir/pvpperformancetracker/PvpPerformanceTrackerPlugin.java)
creates candidate encounters from interactions between the local player and supported actors.
[`FightPerformance.checkForAttackAnimations/fightStarted`](https://github.com/Matsyir/pvp-performance-tracker/blob/3e8c5bac7f3c6357fe6b9ca79428f2f954465ec7/src/main/java/matsyir/pvpperformancetracker/controllers/FightPerformance.java)
starts recorded encounters after a recognized attack; arena exit, NPC despawn, or inactivity ends
them. Its local-player skill handling does **not** establish player maximum HP. The 99 maximum
for these two fights comes from the user's confirmation. No encounter tracking or combat statistics
code is included here.

Rendering and widget anchors are adapted from RuneLite 1.13.1
[`StatusBarsOverlay`](https://github.com/runelite/runelite/blob/runelite-parent-1.13.1/runelite-client/src/main/java/net/runelite/client/plugins/statusbars/StatusBarsOverlay.java)
and [`BarRenderer`](https://github.com/runelite/runelite/blob/runelite-parent-1.13.1/runelite-client/src/main/java/net/runelite/client/plugins/statusbars/BarRenderer.java).
Their BSD copyright and license notices are retained in adapted source. Binary distribution must
include the applicable notice reproduced below, as well as any retained notices in those files.

```text
Copyright (c) 2018, Jos <Malevolentdev@gmail.com>
Copyright (c) 2019, Jos <Malevolentdev@gmail.com>
Copyright (c) 2019, Rheon <https://github.com/Rheon-D>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### Phase 1 implementation report - 2026-10-08

Branch: `feat/enhanced-pvp-status-bars-phase1`. Changes are local; no commit, push, or deployment
was performed. RuneLite remains pinned to 1.13.1 and Java source/target compatibility remains 11.

Changed files, grouped by responsibility:

- `plugin/src/main/java/com/osrstracker/plugin/statusbars/`: `EffectiveMaxHealthResolver`,
  `HealthResolution`, `PeteFightDetector`, `EatingThresholds`, `HpScalingDiagnostics`,
  `EnhancedStatusBarsOverlay`, `StatusBarRenderer`, and `StatusBarsViewport`.
- Existing integration: `TrackerConfig.java`, `TrackerPlugin.java`, and `TrackerPanel.java`.
  The shared lifecycle lock serializes registration and shutdown; sidebar warnings do not replace
  account synchronization status. Configuration stays in RuneLite's existing `osrstracker` group.
- Tests: new `EnhancedBarsLifecycleTest` plus `HealthCalculationsTest`, `PeteFightDetectorTest`,
  `HpScalingDiagnosticsTest`, `StatusBarRendererTest`, and `EnhancedStatusBarsOverlayTest`.
  `RuneLiteRuntimeCheck.java` now also rejects a leaked Mockito library.
- `plugin/build.gradle`: test-only Mockito 4.11.0 and JaCoCo 0.8.12, with coverage verification
  restricted to the new status-bars package. This document contains setup, source findings,
  attribution, acceptance steps, and the implementation report.

Automated verification:

- Test-first runs demonstrated missing feature implementations; subsequent regression tests
  exposed null-player Prayer drawing, an in-flight shutdown/registration race, and a one-pixel
  marker/fill rounding difference. Their fixes passed the corresponding regression tests.
- Final `gradlew.bat build jacocoTestReport --no-daemon` passed using a temporary verification-only
  Gradle init script to direct the existing serializer's fixture output to
  `plugin/build/verification-fixtures/plugin_sample.json` instead of the tracked fixture.
- **76 tests passed**, with zero failures, errors, or skips: **43 existing tests and 33 new tests**.
- New-package coverage: **216/222 lines (97.30%)** and **196/214 branches (91.59%)**.
  The build enforced the 80% line/branch coverage gate.
- `verifyRunClientRuntime` passed: working Logback, scoped assertions, and no JUnit, contract-test,
  or Mockito libraries on the developer-client runtime classpath. `git diff --check` passed.
- Code/security review found an in-flight lifecycle race; it was corrected and re-reviewed with
  no remaining actionable findings. Deprecation warnings concern public pinned RuneLite APIs;
  no client upgrade or private API use was introduced.

The build produced `plugin/build/libs/osrs-tracker-plugin.jar`; launch it through the existing
`gradlew.bat runClient` workflow rather than changing installation methods. Test and coverage
reports are under `plugin/build/reports/tests/test/` and `plugin/build/reports/jacoco/test/`.

Confirmed automatically: scaling precedence, normal/LMS/Pete/manual calculations, all supplied
threshold examples, source-backed Pete arena/form predicates, instance-coordinate conversion,
form switches/absence, zero/unknown/boosted HP handling, exact marker/fill rounding across supported
maxima and both drawable heights, four viewport anchors, independent Prayer rendering, backend
independence, and idempotent registration/removal including shutdown races.

Unverified live behavior: actual LMS/Pete entry and exit, newly loaded/changed tutorial NPC forms,
client scaling/DPI and resizing, profile persistence in a running client, and live account sync.
Source inspection establishes activity signals and the user supplied the two fights' 99 maximum;
offscreen tests do not establish live-game acceptance. Complete the checklist above before calling
that gate passed. Unknown tutorial forms and other exercises still require manual scaling. Restoration
previews, combat auto-hide, and combat analytics remain outside Phase 1.
