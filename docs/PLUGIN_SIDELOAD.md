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
