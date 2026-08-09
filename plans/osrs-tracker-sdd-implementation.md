# Blueprint — OSRS PvP Progression Tracker (SDD v0.4 implementation)

| | |
|---|---|
| **Objective** | Implement `docs/SDD.md` v0.4 end to end |
| **Generated** | 2026-08-04 · revised after adversarial review |
| **Mode** | Direct mode → git mode after Step 1 (`git init -b main` is a Step 1 task; no remote, no `gh`) |
| **Steps** | 15 numbered, 24 executable units (several steps split into sub-steps) |
| **Repo root** | `/mnt/linux-fast/Repo/osrs_recommender` |
| **Status** | In progress — **1**, **2a**, **2b**, **2c**, **2.5**, **3a**, **3b**, **4**, **5**, **6**, **7** complete and merged to `main` (2026-08-06); **8a**, **8b**, **8c** and **9** merged 2026-08-09; 979 tests. The app runs: a live authenticated `POST /api/sync` merges, refreshes and returns ranked recommendations. Next: **10** (UI), with **13** unblocked and parallel; **8.5** is blocked on the user gate below.

> **Step 9 deviation, deliberate.** Tasks 3 and 4 name `tracker/progression/persist.py` and
> `tracker/recommendations/persist.py`. Both packages sit inside §16.1's purity boundary,
> which Step 4 enforces by AST — a persist module there cannot both obey it and write a row,
> and Step 9's own exit criteria require that test to keep passing. The two modules therefore
> ship as `tracker/db/persist_engine_output.py` and `tracker/db/persist_prices.py`. Seven candidate amendments are open — see the note under §20. |

> **Read this first if you are a fresh agent.** Every step is self-contained: it restates the
> design context it needs. You do **not** need to read prior steps or the whole SDD to execute
> one — but you **must** read the SDD sections each step cites. The SDD is the specification;
> this plan is only the construction order.
>
> **Sub-steps (e.g. `2a`, `2b`) share their parent step's context brief.** Read the parent
> brief, then your sub-step's tasks. Nothing else.
>
> **The SDD is now v0.5** and the 21 gaps this plan found are closed in it (SDD §20). Where
> this plan and the SDD disagree, **the SDD wins** — read
> [the amendments table](#sdd-amendments--ratified-in-v05) for what changed and why.

---

## Design summary

The SDD describes a locally hosted, single-user (multi-character-capable) web app answering
*"what should I work on next to become a better Wilderness PKer?"*. Four nouns carry the
design: **Fact**, **Capability**, **Candidate**, **Roadmap**.

Three architectural facts drive the step decomposition:

1. **§16.1 mandates a pure recommendation function.**
   ```python
   def recommend(state: PlayerState, selection: RoadmapSelection,
                 content: Content, profile: ScoringProfile) -> list[Recommendation]
   ```
   The engine never touches the database. This is the biggest lever for parallelism: once
   the domain types exist (Step 2a), the engine stack (4 → 5 → 6), the persistence stack
   (3a → 3b), and the integration clients (7) proceed independently, joining only at Step 9.

2. **`contracts/sync_payload.schema.json` is the Java↔Python seam (§12.1)** — but it is
   *provisional* until a real RuneLite snapshot validates it (Step 8.5). See M5 in the
   review log: the SDD chose side-loading precisely so the contract could churn (§13), so
   freezing it before any plugin code exists would contradict the design's own rationale.

3. **The three status layers (§4.4) are the design's crown jewels.** `status` (objective) →
   `readiness_confidence` (freshness) → `recommended_now` (coaching). Information flows
   strictly downward. Collapsing any two reintroduces the exact bugs D1 and D8 removed.

### Non-negotiable global invariants

Must hold after **every** unit. A unit that breaks one is not complete.

| # | Invariant | Source | Owning step (tests live here) |
|---|---|---|---|
| G1 | `Milestone.achieved` never transitions `true → false` from time alone | §6.6, D1 | **8c** |
| G2 | Freshness never influences `CapabilityState.status` | §9.2, D8 | **4** |
| G3 | An `unknown` requirement leaf never becomes `unlocked` | §9.1, D8 | **4** |
| G4 | A lower-precedence source never decreases a stored fact | §7.4 | **8b** |
| G5 | Hiscores/WOM `-1` normalizes to `NULL` at the adapter boundary — never `0` | §6.2 | **7** |
| G6 | Absent WOM evidence never accelerates staleness | §7.6 | **7** |
| G7 | Practice proxies never set `achieved = true`, never infer competence from participation | §7.6, D6 | **8c** |
| G8 | The plugin transmits only summarized practice events | §7.6, §12.1 | **8a** (schema) + **12c** (detector) |
| G9 | No game content lives in Python or Java code | §10.7 | **2c** |
| G10 | At most one refresher in the primary recommendation list | §9.8, D9 | **6** |

### Step dependency graph

```
1 Foundation
└── 2 Domain types + content layer ································· [strongest]
    │   2a types + requirement AST → 2b loader + validator → 2c seed corpus
    ├── 2.5 Candidate schema + candidate corpus ····················· [strongest]
    │
    ├── 3 Persistence      3a models + Alembic → 3b repository + projection
    │   └── 8 Sync         8a contract + auth + API
    │                      └── 8b merge + precedence
    │                          └── 8c freshness service
    │                              └── 8.5 plugin spike + contract reconciliation
    │                                  └── 12 RuneLite plugin
    │                                      12a skeleton + sync client
    │                                      └── 12b collectors
    │                                          └── 12c practice detector
    ├── 4 Evaluator + progression engine ···························· [strongest]
    │   └── 5 Estimation
    │       └── 6 Recommendation engine (also needs 2.5) ············ [strongest]
    │           └── 13 Golden corpus + tuning ······················· [strongest]
    └── 7 Integrations (prices + WOM) — returns DTOs, persists nothing

9 Orchestration      needs 3b, 6, 7, 8c
└── 10 UI · status surfaces
    └── 11 UI · recommendations, freshness, settings, history
```

**Note the Step 7 decoupling.** The review observed that Step 7 only depended on Step 3
because the clients wrote rows directly. Making the clients return DTOs — with persistence
owned by Step 9's pipeline — drops that dependency and puts 7 in the widest parallel window.
This also mirrors the §16.1 purity philosophy one layer out.

### Critical paths

| Path | Units | Notes |
|---|---|---|
| **To a working web app** | 1 → 2a → 2b → 2c → 3a → 3b → 8a → 8b → 8c → 9 → 10 → 11 | 12 units — this is what "usable" costs |
| **To full v1 incl. plugin** | …→ 8c → 8.5 → 12a → 12b → 12c | 15 units — the longest chain |
| Engine chain | 1 → 2a → 2b → 2c → 4 → 5 → 6 → 13 | 8 units — finishes early, off the critical path |

The original plan claimed a single 8-step critical path; the review correctly showed that
counting nodes without weighting by size understates the persistence/sync chain. Both chains
above are real; the engine chain is the one that finishes first.

### Parallel execution windows

| Window | Concurrent units | Shared-file risk |
|---|---|---|
| After **2c** | **2.5** ∥ **3a** ∥ **4** ∥ **7** | none — `content/candidates/` vs `tracker/db/` vs `tracker/progression/` vs `tracker/integrations/` |
| After **3b** | **8a** ∥ (engine chain continues) | none |
| After **6** | **13** ∥ (9 → 10 → 11) | `content/scoring/profile.yaml` — **Step 13 owns it**; 9–11 read only |
| After **8.5** | **12a→12b→12c** ∥ (9 → 10 → 11) | `contracts/sync_payload.schema.json` — frozen at 8.5; Step 12 read-only |

**Conflict rules.**
1. If two parallel units need to edit the same file, the earlier-numbered unit owns it; the
   later waits.
2. `pyproject.toml` and `Makefile` are **append-only** for parallel units — add your target
   or dependency at the end of its section; never reorder or reformat.
3. Never concurrently edit `contracts/sync_payload.schema.json` or
   `content/scoring/profile.yaml`.
4. A unit's tests live under `tests/<its own area>/`. Never write into another unit's test
   directory.

### Model tier assignment

| Tier | Units | Why |
|---|---|---|
| **Strongest** (Opus) | 2a, 2b, 2.5, 4, 6, 13 | Requirement grammar, Kleene three-valued logic, candidate-to-capability projection, scoring/blending/hysteresis math, weight tuning. A subtle error here is invisible until it silently corrupts every recommendation. |
| Default (Sonnet) | 1, 2c, 3a, 3b, 5, 7, 8a, 8b, 8c, 8.5, 9, 10, 11, 12a, 12b, 12c | Schema translation, HTTP clients, CRUD, UI, plugin plumbing — mechanical against a clear spec. |

### Per-unit workflow

Step 1 initializes git. From 2a onward:

```bash
git checkout -b step-<id>-<slug>
# ... implement ...
make lint && make typecheck && make test && make validate-content
git add -A && git commit -m "step <id>: <summary>"
git checkout main && git merge --no-ff step-<id>-<slug>
```

Rollback: `git checkout main && git branch -D step-<id>-<slug>`. Units creating Alembic
migrations additionally run `alembic downgrade -1` first if the migration was applied.

---

## SDD amendments — ✅ ratified in v0.5

**These are no longer plan decisions. All 21 were folded into `docs/SDD.md` v0.5 on
2026-08-04** and are traced in the SDD's own §20 gap-closure log. The table below is retained
as a reading aid: it names the defect each amendment fixed, which is context the SDD's final
text deliberately does not carry.

**Where the plan and the SDD disagree, the SDD wins.** Two things moved during ratification:
the `Candidate` schema landed at **§10.6** (not §10.8, which is now the "no logic in code"
principle), and validation renumbered from §10.6 to **§10.7**.

Also added in v0.5, beyond the 21: **§4.5 "Observation time is not truth"**, which names the
recurring pattern behind A7, `ContainerScan` (§6.5) and the price trade timestamp (D10), and
**D11 / D12** in the decision log.

| # | Gap in v0.4 | Resolution | Landed in |
|---|---|---|---|
| **A1** | **`Candidate` had no schema.** One of the four core nouns (§4), with a content directory (§10.1), driving every scoring factor (§9.4) — but no section defined its fields. | Full schema plus derivations for `pvp_value`, `leverage`, `proximity`, `completed`, `blocked`. | **§10.6**, D11 |
| **A2** | `pvp_value` derivation for a candidate advancing several capabilities is undefined. §9.3's worked table blends per-roadmap values; §9.3's formula blends per-capability weights. These commute only for single-capability candidates. | **Blend the capability map first (§9.3), then** `pvp_value = max_c (effective_weight(c) × advances(c))`. Maximum, never sum — consistent with §9.8's rule for refreshers. Verified: reproduces §9.3's 0.90 and 0.375. | §9.3 |
| **A3** | `unlock_fraction` denominator unspecified. | `satisfied_leaves / total_leaves`. Unknown leaves sit in the denominator but are never credited. §6.9 says "share of requirement leaves satisfied"; §9.1 constrains only the numerator. | §6.9 |
| **A4** | `readiness_confidence: medium` triggers on "a contributing observation is aged" — no threshold, and "contributing" is undefined. | **Contributing** = leaves reached by the transitive requirement walk that evaluated `satisfied`. **Aged** = `now − ContainerScan.scanned_at > observation_aged_days`, default **14**, stored in `profile.yaml` so it is content (§10.7). | §6.9 |
| **A5** | `Unlock.state = available` and `QuestState.status = in_progress` have no evaluation rule. | Both evaluate **`unsatisfied`**, not satisfied. "Available" means purchasable, not owned — an agent will get this wrong by default. | §9.1 |
| **A6** | `combat_level` and `quest_points` leaves have no unknown rule. | `unknown` when the `Player` row has never been synced (`last_sync_at IS NULL`). | §9.1 |
| **A7** | The `milestone` leaf's unknown condition ("self-attested and never prompted") is unrepresentable — `Milestone.achieved` is a bool. | Add `attested: Tri` to `PlayerState`'s milestone entries, projected from `attested_at IS NULL`. Identical in kind to the `ContainerScan` fix (§6.5). | §6.6, §9.1 |
| **A8** | Refreshers have no hours or GP, so `effort_decay` and `cost_decay` are undefined for them. Defaulting hours to 0 gives `effort_decay = 1.0` and makes every refresher maximally attractive — directly threatening G10. | Add `suggested_session_hours` (float) to the refresher schema; `gp_cost: 0` is correct and explicit. | §10.4 |
| **A9** | `recommended_now = … >= capability.recommended_readiness` requires an ordering on a `high\|medium\|low` enum; none is defined. | `Confidence` is an `IntEnum`: `LOW=0 < MEDIUM=1 < HIGH=2`. | §6.9 |
| **A10** | `recommended_now_reason` has no generation rule, yet §4.4's example shows derived prose. | Three cases: `status=unknown` → name the unknown leaf ("bank contents have never been observed"); `status=locked` → name the top blocker; confidence below bar → "complete a refresher session first". | §6.9 |
| **A11** | `CapabilityState.warnings` is "human-readable caveats" with no content spec. | Three generators: stale/very_stale contributing milestones; aged contributing observations; informational staleness note on `class: knowledge` milestones (§6.6 permits the note but forbids any readiness effect). | §6.9 |
| **A12** | Spellbook, diaries and combat achievements are plugin-provided (§7.1) but have no table (§6) and no leaf type (§10.2). | Fold into `Unlock` rows with reserved key prefixes: `spellbook_*`, `diary_*`, `ca_*`. No new table, no new leaf type. | §6.3, §7.1 |
| **A13** | Active roadmap selection has no persistence. `RecommendationSnapshot.roadmap_selection` records a *run*, not the live setting. | New table `ActiveRoadmap(player_id, roadmap_id, selection_weight)`; weights normalized on read, not on write. | **§6.12** (Migrations renumbered to §6.13) |
| **A14** | `payload_version` is an integer (§12.2) but §12.2 says "rejects unknown **major** versions" — an integer has no major component. | Server declares `SUPPORTED_PAYLOAD_VERSIONS = {1}`; anything outside → 409. | §12.2 |
| **A15** | Hysteresis "more than 10% higher" is ambiguous between raw and log score, which differ. | Raw scores: displace iff `challenger.score > 1.10 × incumbent.score`. | §9.9 |
| **A16** | §11 rule 2 says *all* `/api/*` requests require a bearer token, which would include a health endpoint. | Health lives at `GET /healthz`, **outside** the `/api` prefix. Auth attaches at router level to all of `/api`. | §11.2 |
| **A17** | §11.3 requires a `SyncEvent` on unauthenticated writes, but §6.11's `SyncEvent.player_id` is unsatisfiable for an unauthenticated caller. | `SyncEvent.player_id` nullable; add `remote_addr` and `reason` columns. | §6.11 |
| **A18** | §6.6 says `Milestone.freshness` is "materialized for query convenience" but nothing materializes it. | Add the column; Step 9's pipeline materializes it after the freshness service runs. | §6.6 |
| **A19** | `ItemPrice.selected_price_gp` / `selection_policy` / `selection_reason` (§6.8) have no writer. | Step 5 computes them purely; Step 9's pipeline persists them. | §6.8 |
| **A20** | §14's repository layout omits `tracker/domain/` (where `Tri` is defined) and `tools/`. | Add both. | §14 |
| **A21** | Python 3.13 specified (§14.1); machine has 3.12.4 and no `uv`. | **Decided: `Python 3.12+`, 3.13 preferred but not required.** Nothing in the design needs a 3.13-only feature; the real floor is Pydantic v2 and modern typing syntax. Step 1 targets 3.12. | §14.1 |

### Open amendment candidates — surfaced by implementation, not yet ratified

Found while building Steps 3b and 5. Each is recorded here rather than in the SDD because
each needs a decision, not a transcription. **The code currently ships a documented choice
for every one of them**, so nothing is blocked; ratifying changes what the docstring cites,
and in two cases would change behaviour.

| # | Gap | What the code does today | Decision needed |
|---|---|---|---|
| **A23?** | `Capability.grants` is authored and validated but **inert** — the SDD gives it no evaluation semantics, §10.7 only checks the referent exists, and no seed content uses it. It looks redundant with `requires: {capability: X}` read backwards. | Nothing reads it. | Give it semantics, or delete the field. |
| **A24?** | `ItemObservation`'s aggregation is unspecified. §6.5 defines `quantity` per container; §16.1's `PlayerState` is per item, and nothing says how they combine. | **Sum** across containers, containers unioned, `observed_at` the most recent. | Confirm sum. Nothing reads the magnitude yet (`_item` only tests `> 0`), which is why a wrong rule would be cheap to ship and expensive to find. |
| **A25?** | §7.4 ranks only 3 of the 6 `Source` members. `manual`, `derived` and `osrs_wiki_prices` have no precedence, so a user's manual correction tying a hiscores read resolves arbitrarily. | Unranked sources sort last, deterministically. | Should `manual` outrank every automated source? |
| **A26?** | §6.6's `achieved` invariant is assigned to the wrong layer. `models.py` says "whoever writes this table" enforces never-set-back-to-false, but §6.6's wording bars it *"by the passage of time"* — the freshness service, not a user fixing a mis-attestation. A repository writer cannot tell the two apart. | No guard in the writer; reasoning documented at `upsert_milestone`. | State that the guard belongs to Step 9's freshness pipeline. |
| **A27?** | §8.2's *"conservative default rate"* has no authored home. Every other tunable is content (§9.7's profile, §10.4's session hours); this one number is not. | `FALLBACK_XP_PER_HOUR = 15_000` in `methods.py`, with a test asserting it is slower than anything the corpus authors. | Move to a `fallback_xp_per_hour` field on `ScoringProfile`? |
| **A28?** | **Where §9.8's `group_urgency` enters the §9.4 score is undefined.** §9.8 derives the number in detail and §9.4 lists five factors; nothing joins them, so a refresher could be scored with urgency playing no part at all. | Spent as **`proximity`** — *"closer is better"* read on the decay clock rather than the progress clock. Ruled out folding it into `pvp_value`, because §9.3's worked table pins "Practice vengeance timing" at **0.375**, which is exactly `effective_weight(vengeance_pvp)` and leaves no room for an urgency multiplier. | Confirm `proximity`, or add a sixth factor with its own authored weight. |
| **A29?** | **§10.6's `leverage` is undefined for refreshers.** It counts capabilities whose `status` would flip to `unlocked`; a refresher grants no facts, so it scores 0 forever — which is not merely harsh but wrong, since restoring decayed practice is exactly what moves a capability from *"unlocked but not today"* back to *"recommended now"* (§4.4). | Refreshers count **`recommended_now` flips** — the readiness-layer twin of the status flip — measured against a state in which the session's members were practiced now, i.e. exactly what §9.8's *"mark session complete"* writes. Normalized against the same maximum as progression candidates so the two kinds stay comparable. | Confirm that a readiness flip and a status flip belong in one normalization. |

**One of the two "fixed in code" findings below is now closed.** `hours is None` has a stated
rule: §9.4's `effort_decay` charges `profile.unknown_effort_hours` (new §9.7 field, default
10 = τ, giving `exp(−1) ≈ 0.37`) rather than reading the absence as zero and handing an
unsizable quest a *perfect* effort mark. The GP half of the same gap needed no field — an
unknown cost is charged one **κ**, which `kappa_gp` already authors, for the same `exp(−1)`.
Both are content, per §10.8. **Candidate amendment: fold `unknown_effort_hours` into the
SDD's §9.7 profile listing.**

Two further findings needed no amendment and were **fixed in code**:

- **Every stored `datetime` was timezone-naive.** `Mapped[datetime]` rendered a plain
  `DateTime`; SQLite stores dates without an offset, so a value written aware read back
  naive and could not be subtracted from an aware `now` at all. Every §4.5 comparison —
  `now − scanned_at`, `now − last_practiced_at`, `now − high_trade_at` — crosses that
  boundary. Fixed with `tracker/db/types.py::UtcDateTime`, applied through
  `type_annotation_map` so future columns inherit it. `sa.DateTime(timezone=True)` is
  **not** the fix: on SQLite it is a silent no-op that absorbs the offset into the number.
- **`hours is None` had no stated meaning for §9.4's `effort_decay`.** A `quest:` candidate
  has no skill target and no item, so §8 can estimate neither time nor gp — but
  `exp(−hours/τ)` then scores it as effortless. This is A8's problem one candidate kind
  over; A8 closed it for refreshers by making `suggested_session_hours` mandatory, and
  quests have no equivalent. **Closed in Step 6** by the `unknown_effort_hours` profile
  field described above, rather than by letting the floor `ε` decide it by accident.

---

## Explicitly out of scope for v1

Listed so a later agent does not build them speculatively.

**§17 Future features — none of these:** multiple characters *in the UI* (the schema
supports it, §6.1, but the UI exposes one); Collection Log integration; bank progression /
gear planner; money-making recommendations; quest routing; inventory planner; LMS analytics;
fight journal, replay analysis, video review.

**§19 Deferred decisions — do not implement; each has a reopen trigger:**

| Deferred | Reopens when |
|---|---|
| Budget-derived κ | Disposable budget (not bank value) can be established reliably |
| Exact GP budget entry | A user asks for finer control than the three-way preference |
| Plugin Hub submission | The §13.1 stage-3 gate is met |
| Direct hiscores integration | WOM proves unreliable in practice (Step 7 ships a README only) |
| Practice domains beyond the six in §7.6 | A milestone needs evidence none of the six can supply |

**§13 Plugin Hub work must not touch the critical path** (D5). Stage 1 of the §13.1 ladder —
local checkout, Gradle build, side-load, manually matched versions — is the entire v1 scope.

---

# Step 1 — Foundation: repo skeleton, tooling, configuration

**Tier:** default · **Depends on:** — · **Unblocks:** 2a · **Size:** small

## Context brief

The repository contains only `docs/SDD.md` and this plan. No git, no Python package, no
tooling. Create the SDD §14 skeleton (plus the §A20 additions), the config layer (§11 bind
address, §7.5 integration config), and nothing else. No domain logic.

§14.1 specifies: **Python 3.12+** (3.13 preferred, not required — settled in v0.5), SQLite,
SQLAlchemy + Alembic, Pydantic v2, NiceGUI, Plotly, httpx, YAML. The machine has Python
3.12.4, no `uv`, no `gh`, no `gradle`; `pyenv` **is** present. Target 3.12; set
`requires-python = ">=3.12"`.

## Tasks

1. Install `uv` (or use the present `pyenv`). Then `git init -b main` — the default branch
   name is config-dependent and the rest of this plan assumes `main`. Commit `docs/SDD.md`
   v0.5 and this plan as the initial commit.
2. `.gitignore`: `__pycache__/`, `*.db`, `*.sqlite3`, `.venv/`, `.env`, `config.yaml`,
   `plugin/build/`, `.gradle/`.
3. Directory tree (each Python package with `__init__.py`):
   ```
   tracker/{domain,ui,api,db,migrations,sync,progression,freshness,recommendations,
            estimation,integrations/{wise_old_man,hiscores,prices},content,config}/
   tools/  plugin/  contracts/  content/  tests/{golden,contracts}/  docs/  plans/
   ```
   `tracker/domain/` and `tools/` are additions to §14 — record them in the SDD changelog
   (A20).
4. `pyproject.toml`. **Runtime:** `fastapi`, `uvicorn`, `nicegui`, `sqlalchemy`, `alembic`,
   `pydantic>=2`, `pydantic-settings`, `httpx`, `pyyaml`, `jsonschema`, `plotly`.
   **Dev:** `pytest`, `pytest-cov`, `pytest-playwright`, `nicegui[testing]`, `ruff`, `mypy`,
   `hypothesis`.
   > `pydantic-settings`, `uvicorn`, `jsonschema` and the NiceGUI test harness are each
   > hard-required by a later step. Omitting them makes `make install` succeed and Steps
   > 8/9/10 fail at import.
5. Tool config: ruff (lint + format); **mypy strict** over
   `tracker/{domain,content,freshness,progression,recommendations,estimation}` — the pure
   core, where strictness is what keeps three-valued logic from decaying into booleans;
   pytest with `--strict-markers`.
6. `tracker/config/settings.py` — `pydantic_settings.BaseSettings` over `config.yaml`:
   - `bind_address` — **no default**; validator rejects `0.0.0.0` outright (§11.1)
   - `port` (default `8502`), `api_token` (required, env `TRACKER_API_TOKEN`)
   - `database_url` (default `sqlite:///./tracker.db`)
   - `integrations.prices.{provider,base_url,user_agent,ttl_hours,manual_refresh_min_interval_seconds}`
   - `integrations.wise_old_man.{base_url,user_agent}`
   - `content_dir`, `scoring_profile_path`
7. `config.example.yaml` with the §7.5 block filled in; `config.yaml` gitignored.
8. `Makefile`. **Argument passing must work** — later steps run `make test ARGS=tests/x`:
   ```make
   ARGS ?=
   test:       ; pytest $(ARGS)
   test-cov:   ; pytest --cov=tracker --cov-report=term-missing $(ARGS)
   lint:       ; ruff check . && ruff format --check .
   format:     ; ruff format .
   typecheck:  ; mypy tracker
   validate-content: ; @echo "stub — implemented in step 2b"
   migrate:    ; @echo "stub — implemented in step 3a"
   run:        ; @echo "stub — implemented in step 9"
   ```
   > GNU make treats trailing bare words as *goals*, so `make test -- tests/x` fails with
   > exit 2. `ARGS=` is the working form.
9. `README.md` — one paragraph pointing at `docs/SDD.md` and this plan.
10. `tests/test_config.py` — settings load; `0.0.0.0` rejected; missing token rejected.
11. `tests/test_deps.py` — `import jsonschema, uvicorn, pydantic_settings; from nicegui import ui`.

## Verification

```bash
make install && make lint && make typecheck && make test
make test ARGS="tests/test_config.py -v"     # arg passing must work
python -c "from tracker.config.settings import Settings; print(Settings)"
git symbolic-ref --short HEAD                # must print: main
```

## Exit criteria

- [ ] `git symbolic-ref --short HEAD` prints `main` and an initial commit exists
- [ ] `make install`, `lint`, `format`, `typecheck`, `test` all succeed; `validate-content`,
      `migrate`, `run` are stubs that print and exit 0
- [ ] `make test ARGS="tests/test_config.py"` runs only that file
- [ ] `bind_address: 0.0.0.0` is rejected with a clear error; `api_token` is required
- [ ] `tests/test_deps.py` passes — every downstream headline import resolves
- [ ] `requires-python = ">=3.12"` and the venv runs 3.12.4 (A21, settled in SDD v0.5)

## Rollback

`rm -rf` everything except `docs/` and `plans/`.

---

# Step 2 — Domain types, content schema, loader, validator, seed corpus

**Tier:** ⚑ **strongest** (2a, 2b) / default (2c) · **Depends on:** 1
**Unblocks:** 2.5, 3a, 4, 7 · **Size:** large — split into 2a / 2b / 2c

## Context brief (shared by 2a, 2b, 2c)

The project's keystone. Produces the **content schema** (§10) and the **engine's input
types** (§16.1).

**Read before starting:** SDD §4, §6.3, §6.4, §6.6, §9.1, §10 (all), §16.1, plus amendments
A3–A12 above.

The requirement grammar (§10.2) is the core abstraction. Requirements need boolean
structure — *"Barrows gloves **or** rune gloves"* — which a flat list cannot express.

- **Leaf types:** `skill`, `unlock`, `quest`, `item`, `milestone`, `capability`,
  `combat_level`, `quest_points`
- **Combinators:** `all_of`, `any_of`, `not`, `at_least: {n, of: [...]}`

```yaml
id: ice_barrage
name: Ice Barrage
requires:
  all_of:
    - skill: {magic: 94}
    - unlock: ancient_magicks
    - any_of:
        - item: mystic_robe_top
        - item: ahrims_robetop
grants: [ice_barrage_nh]
pvp_value: 0.95
recommended_readiness: medium
```

> **YAML trap the SDD calls out (§10.2):** the space after the colon is mandatory.
> `magic:94` parses as the *string* `"magic:94"`, not a mapping. The v0.1 draft contained
> this bug twice. The validator must catch it.

Milestones carry two **orthogonal** attributes (§6.6): `kind` (`derived | self_attested` —
how measured) and `class` (`knowledge | execution | threshold` — how it ages). Only
`class: execution` milestones may declare `practiced_by` / `practice_group`.

Roadmaps are **weighted capability sets with no dependency graph of their own** (§4.2).

---

## Step 2a — Domain types and requirement AST

**Tier:** ⚑ strongest · **Unblocks:** 2b, 3a, 4, 7

### Tasks

1. `tracker/domain/types.py` — all frozen:
   - `Tri`: `SATISFIED | UNSATISFIED | UNKNOWN` — **never** `bool | None`
   - `Status`: `UNLOCKED | LOCKED | UNKNOWN`
   - `Confidence`: **`IntEnum`** `LOW=0 < MEDIUM=1 < HIGH=2` (A9 — `recommended_now` needs
     an ordering)
   - `Freshness`: `CURRENT | STALE | VERY_STALE`
   - `UnlockState`: `UNLOCKED | AVAILABLE | LOCKED | UNKNOWN` (§6.3 — the Unlocks UI renders
     four states)
   - `QuestStatus`: `NOT_STARTED | IN_PROGRESS | COMPLETE | UNKNOWN` (§6.4)
   - `Source`: `RUNELITE | WISE_OLD_MAN | HISCORES | OSRS_WIKI_PRICES | MANUAL | DERIVED`
   - `PracticeDomain`: the six of §7.6
   - `MilestoneState`: `achieved: bool`, **`attested: Tri`** (A7 — distinguishes "asked, said
     no" from "never asked"), `last_practiced_at`, `class_`, `value`
   - `PlayerState`: skills (**xp nullable**), unlocks, quests, observed items,
     **container scan timestamps**, milestones, `combat_level`, `quest_points`,
     `gp_sensitivity`, `last_sync_at` (A6)
   - `RoadmapSelection`, `Content`, `Recommendation`, `CapabilityView`, `Estimate`
2. `tracker/content/requirements.py` — the requirement AST as a discriminated union: leaves
   and combinators as separate model classes, with a validator parsing the YAML mapping
   form. **Reject string-typed leaf payloads** (the `magic:94` trap) with a message naming
   file and line.
3. Tests: `Confidence.HIGH > Confidence.MEDIUM`; `Tri` has no truthiness that could be
   mistaken for a bool (assert `bool(Tri.UNKNOWN)` is never relied on — prefer making the
   enum's members non-boolean-meaningful and testing exhaustive matching); AST round-trips
   every combinator; `skill: {magic:94}` (no space) is rejected.

### Exit criteria

- [ ] `grep -rn "Optional\[bool\]\|bool | None" tracker/domain/` returns nothing
- [ ] `Confidence` is an `IntEnum` with a tested ordering
- [ ] `PlayerState` carries container scan timestamps **and** `MilestoneState.attested` —
      without either, "not seen"/"never looked" and "said no"/"never asked" collapse (§6.5, A7)
- [ ] `UnlockState` and `QuestStatus` both exist with four states each
- [ ] `mypy --strict tracker/domain tracker/content` clean

---

## Step 2b — Loader and validator

**Tier:** ⚑ strongest · **Depends on:** 2a · **Unblocks:** 2c

### Tasks

1. `tracker/content/schema.py` — Pydantic v2 models: `Capability`, `Roadmap`,
   `TrainingMethod`, `Milestone`, `Item`, `RefresherTemplate`, `ScoringProfile`.
   (`Candidate` is Step 2.5.)
   `RefresherTemplate` gains **`suggested_session_hours: float`** (A8).
   `ScoringProfile` gains **`observation_aged_days: int = 14`** (A4).
2. `tracker/content/loader.py` — walk `content/`, parse, build `Content` with id→object indexes.
3. `tracker/content/validate.py` — **every** §10.6 assertion:
   - id uniqueness across the corpus
   - referential integrity for every capability / quest / item / skill / milestone id
   - every `grants` target is a declared capability
   - every `practiced_by` entry is a declared practice domain (§7.6)
   - every `practice_group` referenced by a refresher has ≥1 member with `class: execution`
   - **only** `class: execution` milestones declare `practiced_by` / `practice_group`
   - every item with `price_mode: live` has a numeric `item_id`
   - capability and requirement graphs are **acyclic** — report the cycle path, not a boolean
   - weights, `pvp_value`, roadmap capability weights ∈ `[0,1]`
   - κ presets satisfy §9.6: min `1_000_000`, max `250_000_000`, ordering `high < normal < low`
4. Wire `make validate-content` → `python -m tracker.content.validate`; non-zero exit on any
   failure, with file-and-line diagnostics.
5. `tests/content/corrupt/` — **ten** fixtures, one per rule above, each asserted to fail
   with the right message.

### Exit criteria

- [ ] `make validate-content` fails loudly on each of the ten corrupted fixtures
- [ ] Cycle detection reports the actual cycle path
- [ ] Every validator error names a file and, where the parser supplies it, a line

---

## Step 2c — Seed content corpus

**Tier:** default · **Depends on:** 2b · **Unblocks:** 2.5, 3a, 4, 7

### Tasks

1. Seed `content/` — small but *real*, enough for Steps 4–6 to be tested against something
   non-trivial:
   - **capabilities:** `ice_barrage_nh`, `deep_wildy_nh`, `budget_nh`, `anti_pk`
   - **roadmaps:** `main_nh`, `anti_pk`
   - **milestones — exactly nine:** the seven of §6.6's classification table
     (`first_wilderness_kill` `threshold`; `first_anti_pk` `threshold`;
     `successfully_freeze_log` `threshold`; `lms_wins_10` / `lms_wins_100` `threshold`
     derived; `teleblock_understanding` `knowledge`; `comfortable_4_way_switches`
     `execution`; `consistent_overhead_prayers` `execution`) — that is eight rows, since
     the two execution ones are also in §10.3 — **plus** `vengeance_timing` (`execution`,
     §10.3) **plus** a separate `freeze_logging_practice` (`execution`).
     > §6.6's blockquote **mandates** that last one: *"Where a `threshold` achievement also
     > has an ongoing practice component — freeze logging is the clear case — author a
     > **separate `execution` milestone** for the practice rather than making one row mean
     > both. This keeps `achieved` unambiguous."*
   - **training methods:** `magic_bursting` (§8.1) + a conservative default per skill
   - **items:** `voidwaker`, `armadyl_godsword`, `mystic_robe_top`, `ahrims_robetop` (§10.5)
   - **refresher:** `refresh_nh_fundamentals` (§10.4) with `suggested_session_hours`
   - `content/scoring/profile.yaml` exactly as §9.7 specifies, `tuned_against_corpus: null`,
     plus `observation_aged_days: 14`
2. `docs/CONTENT_AUTHORING.md` — how to add a capability/roadmap/milestone without touching
   code (the user-facing form of G9).
3. `tests/content/test_g9.py` — copy a new capability YAML into a temp corpus, load it, and
   assert it appears in `Content` with **zero** code changes. This is the mechanical test for
   G9 that the original plan asserted without one.

### Exit criteria

- [ ] `make validate-content` passes on the seed corpus
- [ ] Exactly nine milestones, with `freeze_logging_practice` separate from
      `successfully_freeze_log` (§6.6 blockquote)
- [ ] `tests/content/test_g9.py` proves new content needs no code change (G9)

## Rollback (all of Step 2)

`git branch -D` the sub-step branches. Nothing downstream exists yet.

---

# Step 2.5 — Candidate schema and candidate corpus

**Tier:** ⚑ **strongest** · **Depends on:** 2c · **Unblocks:** 6, 13 · **Size:** medium

> **Inserted after adversarial review**, because `Candidate` — one of the SDD's four core
> nouns (§4), with a content directory (§10.1), driving every scoring factor (§9.4) — had
> **no defined fields anywhere in v0.4**. Step 6 could not compute `pvp_value`, `leverage`,
> `proximity`, `completed` or `blocked`, and Step 13's scenarios referenced candidate ids
> nothing created.
>
> **This is now specified.** SDD **v0.5 §10.6** defines the schema and D11 records the
> reasoning. This step implements it — it no longer invents it.

## Context brief

**Read before starting:** SDD **§10.6** (the schema — authoritative), §4, §9.3, §9.4, §10.2,
§16.2, and **D11**.

A candidate is *"an action the player could take that changes facts"* (§4). The engine's job
is: *given current facts, which candidate most efficiently advances the capabilities this
roadmap weights most heavily?*

The schema, reproduced from §10.6 so this step reads cold:

```yaml
id: train_magic_87_to_94
name: Train Magic 87 → 94
kind: skill_training        # skill_training | acquisition | quest | unlock | practice
advances:                   # capability id → marginal contribution ∈ [0,1]
  ice_barrage_nh: 1.0
  deep_wildy_nh: 0.7
requires:                   # optional gate; same grammar as §10.2
  all_of:
    - unlock: ancient_magicks
completion:                 # predicate over facts; satisfied ⇒ candidate is complete
  skill: {magic: 94}
grants_facts:               # what changes on completion — drives `leverage`
  skill: {magic: 94}
```

**Derivations, per §10.6 and D11:**

| Factor | Derivation |
|---|---|
| `pvp_value` | Blend the capability map first (§9.3), **then** `max_c (effective_weight(c) × advances(c))`. **Maximum, never sum** — matches §9.8's rule for refreshers and reproduces §9.3's worked values (0.90 and 0.375). |
| `leverage` | Count capabilities whose `status` would flip to `unlocked` if `grants_facts` were applied, normalized by the maximum such count across the candidate set so the factor lands in `(0,1]`. |
| `proximity` | Skill training: `1 − remaining_xp / span_xp`. Everything else: the `completion` predicate's `unlock_fraction` (A3) — same machinery, works for any candidate kind. |
| `completed` | `completion` evaluates `satisfied`. §16.2: a completed candidate never ranks. |
| `blocked` | `requires` evaluates `unsatisfied` → `readiness` gate = 0, excluded and surfaced separately. `requires` evaluating **`unknown` is not blocked** — it surfaces as unknown, per G3. |

## Tasks

1. Add `Candidate` to `tracker/content/schema.py`; add `content/candidates/` to the loader
   and to all ten §10.6 validator rules (id uniqueness, referential integrity of `advances`
   targets, `advances` weights ∈ [0,1], acyclicity of any `requires` tree).
2. `tracker/domain/candidates.py` — the five derivations above as pure functions over
   `(candidate, state, content, effective_weights)`. No scoring here; Step 6 consumes these.
3. Seed `content/candidates/` with **at least** the six ids Step 13's scenarios name:
   `train_magic_87_to_94`, `buy_voidwaker`, `complete_desert_treasure_i`, `unlock_rigour`,
   `train_woodcutting`, `buy_high_risk_gear` — plus `train_strength_to_99` and
   `unlock_protect_item` for §16.2's pairwise judgments.
4. Add the three candidate rules to the §10.7 validator: every `advances` target is a declared
   capability with weight in `[0,1]`; every candidate declares a non-empty `completion`
   predicate; every refresher declares `suggested_session_hours`.
5. Tests: `pvp_value` reproduces §9.3's worked table exactly (0.90 for Train Magic, 0.375 for
   vengeance practice under `main_nh: 0.75, anti_pk: 0.25`); a multi-capability candidate
   takes the max, **not** the sum; `blocked` is false when `requires` is `unknown`;
   `completed` is true only when the predicate is `satisfied`.

## Verification

```bash
make validate-content && make test ARGS="tests/candidates -v" && make typecheck
```

## Exit criteria

- [ ] `Candidate` schema implemented exactly as SDD §10.6 specifies, and validated
- [ ] All five derivations implemented as pure functions with tests
- [ ] §9.3's worked table reproduced numerically
- [ ] A multi-capability candidate takes the maximum, never the sum (A2)
- [ ] An `unknown` gate does **not** mark a candidate blocked (G3)
- [ ] All eight candidate ids referenced by Step 13 exist in `content/candidates/`

## Rollback

`git branch -D step-2.5-candidates`.

---

# Step 3 — Persistence: models, migrations, projection

**Tier:** default · **Depends on:** 2c · **Unblocks:** 8a · **Size:** large — split 3a / 3b
· **Parallel with:** 2.5, 4, 7

## Context brief (shared by 3a, 3b)

**Read before starting:** SDD §6 (all), §7.4, §14, plus amendments A12, A13, A17, A18.

Translate §6 into SQLAlchemy models with **Alembic from the first commit** (§6.12 —
*"retrofitting migrations after the schema stabilizes is the expensive version of this
decision"*). Then project the DB into the `PlayerState` object from Step 2a. The engine never
queries the DB (§16.1); this projection is the only bridge.

Two subtleties that are easy to get wrong:

- **`SkillSnapshot.xp` is nullable and `NULL` means unranked, never `0`** (§6.2, G5).
- **`ContainerScan` is the staleness anchor** (§6.5). Without a row recording when a
  container was last seen *in full*, "no `ObservedItem` row" is ambiguous between "you don't
  own it" and "we've never looked":

  | Evidence | Ownership |
  |---|---|
  | Item seen in a scan | `satisfied` |
  | Not seen, but a scan covers the container | `unsatisfied` |
  | No scan of that container has ever occurred | `unknown` |

---

## Step 3a — Models, migrations, session

**Depends on:** 2c · **Unblocks:** 3b, 8a

### Tasks

1. `tracker/db/models.py` — every table in §6.1–§6.11, plus amendments:
   `Player`, `SkillSnapshot`, `Unlock`, `QuestState`, `ObservedItem`, `ContainerScan`,
   `Milestone`, `PracticeEvent`, `ItemPrice`, `CapabilityState`, `RecommendationSnapshot`,
   `RecommendationEntry`, `SyncEvent`, **`ActiveRoadmap(player_id, roadmap_id,
   selection_weight)`** (A13).
   - `SyncEvent.player_id` **nullable**, plus `remote_addr` and `reason` (A17 — an
     unauthenticated caller has no trusted identity, so the FK is otherwise unsatisfiable)
   - `Milestone.freshness` column (A18 — §6.6 calls it materialized)
   - Spellbook / diaries / combat achievements are `Unlock` rows with `spellbook_*`,
     `diary_*`, `ca_*` key prefixes — no new tables (A12)
   - Every fact-bearing table carries `source` and `observed_at`
2. `tracker/db/session.py` — engine/session factory; SQLite pragmas (`foreign_keys=ON`, WAL).
3. Alembic init at `tracker/migrations/`; `env.py` wired to the models metadata. Generate the
   initial revision and **hand-review it** — do not ship an unread autogenerate diff.
4. Indexes: `(player_id, skill)`, `(player_id, item_id, container)`, `(player_id, key)` on
   milestones and unlocks, `(player_id, domain, ended_at)` on `PracticeEvent`.
5. Wire `make migrate`.
6. Tests: `alembic upgrade head` → `downgrade base` → `upgrade head` round-trip on a seeded
   DB (§16.4); a `SyncEvent` row inserts with `player_id IS NULL`.

### Exit criteria

- [ ] Alembic round-trip passes on a database containing seeded rows
- [ ] `SyncEvent` accepts `player_id = NULL` with `remote_addr` and `reason` populated (A17)
- [ ] `ActiveRoadmap` exists (A13); `Milestone.freshness` exists (A18)
- [ ] `SkillSnapshot.xp` is nullable

---

## Step 3b — Repository and PlayerState projection

**Depends on:** 3a · **Unblocks:** 9

### Tasks

1. `tracker/db/repository.py` — thin read/write helpers per aggregate.
2. `tracker/db/projection.py` — **`build_player_state(session, player_id) -> PlayerState`**:
   - resolve item ownership three ways via `ContainerScan` (table in the shared brief)
   - unranked skills project as `None`, never `0`
   - `MilestoneState.attested` = `UNKNOWN` when `attested_at IS NULL`, else
     `SATISFIED`/`UNSATISFIED` per `achieved` (A7)
   - carry `last_practiced_at` and `last_sync_at` through (A6)
   - never invent a value for a fact with no observation
3. Tests: each of the three ownership cases; unranked skill → `None`; a never-prompted
   self-attested milestone projects `attested = UNKNOWN`.

### Exit criteria

- [ ] Ownership resolution has a test for each of the three cases
- [ ] `attested` distinguishes never-prompted from declined (A7)
- [ ] `build_player_state` is the sole entry point the pipeline uses to feed the engine —
      enforced by Step 4's import-boundary test, not asserted here

## Rollback (all of Step 3)

`alembic downgrade base`; delete `tracker.db`; `git branch -D` the sub-step branches.

---

# Step 4 — Three-valued evaluator and progression engine

**Tier:** ⚑ **strongest** · **Depends on:** 2c · **Unblocks:** 5 · **Size:** medium
· **Parallel with:** 2.5, 3a, 7

## Context brief

**Read before starting:** SDD §4.4, §6.5, §6.6 (freshness policy), §6.9, §9.1, §9.2, D8,
plus amendments A3–A7, A9, A10, A11.

The design's most load-bearing logic. Get it wrong and every recommendation is subtly wrong
forever.

**Three-valued requirement evaluation (§9.1).** Every leaf returns
`satisfied | unsatisfied | unknown`; combinators follow **Kleene three-valued logic**:

| Combinator | Result |
|---|---|
| `all_of` | `unsatisfied` if any child is unsatisfied; else `unknown` if any child is unknown; else `satisfied` |
| `any_of` | `satisfied` if any child is satisfied; else `unknown` if any child is unknown; else `unsatisfied` |
| `not` | swaps satisfied ↔ unsatisfied; `unknown` maps to `unknown` |
| `at_least: {n, of}` | `satisfied` if `count(satisfied) ≥ n`; `unsatisfied` if `count(satisfied) + count(unknown) < n`; else `unknown` |

> **The SDD's explicit warning (§9.1):** *"Implementations that reach for `if not satisfied`
> collapse unknown into false and reintroduce exactly the bug D8 removes."* Never branch on
> the truthiness of a `Tri`. Match exhaustively on all three arms.

**Complete leaf resolution table** (§9.1 plus amendments A5, A6, A7):

| Leaf | `satisfied` | `unsatisfied` | `unknown` |
|---|---|---|---|
| `skill` | level ≥ target | level < target | no snapshot from any source |
| `unlock` | `state = unlocked` | `state ∈ {available, locked}` — **`available` is not satisfied** (A5) | `state = unknown` |
| `quest` | `status = complete` | `status ∈ {not_started, in_progress}` (A5) | `status = unknown` |
| `item` | seen in a scan | scan covers the container, item absent | no `ContainerScan` ever covered it (§6.5) |
| `milestone` | `achieved` | attested and not achieved | self-attested and never prompted (`attested = UNKNOWN`, A7) |
| `capability` | child `status = unlocked` | child `status = locked` | child `status = unknown` |
| `combat_level` | ≥ target | < target | `last_sync_at IS NULL` (A6) |
| `quest_points` | ≥ target | < target | `last_sync_at IS NULL` (A6) |

**The three layers compute in strict order; information flows only downward (§9.2):**

```
requirement tree ──► status
                       └──► readiness_confidence   (only when status = unlocked)
                                └──► recommended_now
```

Freshness never flows upward into `status`. Unknown evidence never flows downward into
`readiness_confidence` — it stops at `status: unknown`.

**Freshness applies to `class: execution` milestones only** (§6.6): `<30d = current` ·
`30–90d = stale` · `>90d = very_stale`. Staleness never sets `achieved` false and is never a
hard blocker (D8).

**`readiness_confidence`** (only when `status = unlocked`). **Contributing** = the leaves
reached by the transitive requirement walk that evaluated `satisfied` (A4).

| Confidence | Condition |
|---|---|
| `high` | all contributing execution milestones `current`; all contributing positive observations fresh |
| `medium` | ≥1 contributing execution milestone `stale`, **or** a contributing observation aged (`now − scanned_at > profile.observation_aged_days`, default 14 — A4) |
| `low` | ≥1 contributing execution milestone `very_stale` |

**`recommended_now`** = `status == unlocked AND readiness_confidence >= capability.recommended_readiness`
(`Confidence` is an `IntEnum`, A9).

**`recommended_now_reason`** — three generators (A10): `status = unknown` → name the unknown
leaf (*"bank contents have never been observed"*); `status = locked` → name the top blocker;
confidence below bar → *"complete a refresher session first"*.

**`warnings`** — three generators (A11): stale/very_stale contributing milestones; aged
contributing observations; an informational staleness note for `class: knowledge` milestones,
which §6.6 permits *"but never affects readiness"*.

**`unlock_fraction`** = `satisfied_leaves / total_leaves` (A3). Unknown leaves sit in the
denominator, are never credited, and appear in `unknowns` — not `blockers`.

## Tasks

1. `tracker/progression/tri.py` — `Tri` combinators (`and_all`, `or_any`, `negate`,
   `at_least`) as explicit truth tables. Pure, no I/O.
2. `tracker/progression/evaluate.py` — `evaluate(requirement, state, content) -> EvalResult`
   returning `(Tri, blockers, unknowns, satisfied_leaves, total_leaves)`, implementing the
   full leaf table above. Memoize capability leaves; detect cycles at runtime as a defensive
   backstop even though 2b validates acyclicity statically.
3. `tracker/freshness/policy.py` — pure `freshness(last_practiced_at, now, milestone_class)`;
   returns `None` for non-execution classes.
4. `tracker/progression/engine.py` —
   `compute_capability_states(state, content, profile, now) -> dict[str, CapabilityView]`
   producing `status`, `unlock_fraction`, `blockers`, `unknowns`, `readiness_confidence`,
   `warnings`, `recommended_now`, `recommended_now_reason`.
5. `tests/progression/test_import_boundary.py` — assert no module under
   `tracker/{progression,recommendations,estimation,domain}/` imports `tracker.db`,
   `tracker.api`, `httpx` or `sqlalchemy`. Walk the AST; do not grep.
   > This test lives here, not in Step 3, because Step 3 and Step 4 run in parallel — at
   > Step 3's merge `tracker/progression/` may not exist and the assertion would pass
   > vacuously.
6. Tests — this step is test-heavy by design (§16.4):
   - **Full truth tables** for all four combinators across all three values, including
     short-circuit ordering (a definite `unsatisfied` in `all_of` beats sibling `unknown`s;
     a definite `satisfied` in `any_of` wins outright)
   - One test per row of the leaf table, **especially** `unlock: available → unsatisfied`
     and `quest: in_progress → unsatisfied`
   - Layering: a very_stale milestone changes `readiness_confidence` but leaves `status`
     byte-identical (**G2**)
   - An unknown item leaf yields `status: unknown` and `readiness_confidence = None` —
     **never** the incoherent pair *"Unlocked: yes / Confidence: low because ownership is
     unknown"* (**G3**, D8)
   - `blockers` and `unknowns` are disjoint and separately populated
   - `unlock_fraction` mixed case: 1 satisfied / 1 unsatisfied / 1 unknown → **0.33**, not
     0.50 (A3)
   - Each `recommended_now_reason` and `warnings` generator

## Verification

```bash
make test ARGS="tests/progression -v" && make typecheck
python - <<'PY'
import ast, pathlib, sys
bad = []
for p in pathlib.Path("tracker").rglob("*.py"):
    if p.parts[1] not in {"progression","recommendations","estimation","domain"}: continue
    for n in ast.walk(ast.parse(p.read_text())):
        if isinstance(n,(ast.Import,ast.ImportFrom)):
            mods = [a.name for a in n.names] if isinstance(n,ast.Import) else [n.module or ""]
            if any(m.startswith(("tracker.db","tracker.api","httpx","sqlalchemy")) for m in mods):
                bad.append(f"{p}: {mods}")
print("\n".join(bad) or "clean"); sys.exit(1 if bad else 0)
PY
```

## Exit criteria

- [ ] Every combinator has a complete 3ⁿ truth-table test
- [ ] Every row of the leaf resolution table has a test, including `available` and
      `in_progress` resolving to **unsatisfied**
- [ ] The AST import-boundary check above exits 0
- [ ] Freshness cannot reach `status` — proven by test, not inspection (G2)
- [ ] Unknown cannot reach `readiness_confidence` (G3)
- [ ] `unlock_fraction` mixed-case test asserts 0.33 (A3)

## Rollback

`git branch -D step-04-progression`.

---

# Step 5 — Estimation subsystem (time and GP)

**Tier:** default · **Depends on:** 4 · **Unblocks:** 6 · **Size:** medium

## Context brief

**Read before starting:** SDD §6.8, §8 (all), plus amendment A19.

The output line *"Train Magic 87 → 94, ~4.5 hours, ~1.8M gp"* needs a real estimator. This
is a subsystem, not a formula. It stays **pure**: prices are passed in as a resolved map,
never fetched here (Step 7 owns fetching, Step 9 owns persisting).

**Algorithm (§8.2):**
1. Compute remaining XP to target.
2. Partition into the level bands spanned.
3. For each band, select the highest-XP/hr method **whose requirements the player currently
   satisfies** — reuse Step 4's evaluator; the fast method is frequently gated behind the
   very content the recommender is trying to sequence.
4. Integrate hours and GP cost across bands.
5. If no available method covers a band, fall back to a conservative default rate and mark
   the band low-confidence.

**Price resolution is three-layer, first hit wins (§8.3):** `live → cached (within TTL) →
static content hint → unknown`. Within the live layer, acquisition cost is estimated
**conservatively**: `recent high → recent low → cached → static hint → unknown`.
`selection_reason` records which layer supplied the number, so the UI can explain any figure
it shows.

**Estimate confidence is three-valued (§8.4)** — two levels were insufficient, because a
cached price from yesterday is meaningfully better than a hand-authored fallback.

> **The subtle rule (§8.4, D10):** price confidence derives from the **trade timestamp**,
> not from `fetched_at`. *"Fetching today does not make a three-day-old trade fresh — this is
> the same defect as `ContainerScan` one layer out."*

| Age of the **selected trade** | Price confidence |
|---|---|
| < 24 hours | high |
| 1–7 days | medium |
| > 7 days | low |
| No trade data (static fallback / unknown) | low |

`estimate_confidence` = **minimum** of price confidence and training-method confidence (high
when every band has an authored available method; low when any band falls back).

## Tasks

1. `tracker/estimation/xp_table.py` — the OSRS XP curve for levels 1–99 as a constant.
   > This is game data in code, which brushes against G9. It is acceptable because the curve
   > is invariant arithmetic, not authored content — the §10.7 boundary is about content that
   > *changes* (quests, items, capabilities). Document the reasoning in a module docstring.
2. `tracker/estimation/methods.py` — band partitioning + method selection via Step 4's
   evaluator.
3. `tracker/estimation/prices.py` — pure
   `resolve_price(item, price_record, now, policy) -> (gp, selection_reason, confidence)`
   implementing the cascade and the acquisition selection order. Returns the values Step 9
   persists into `ItemPrice.selected_*` (A19).
4. `tracker/estimation/estimate.py` —
   `estimate(candidate, state, content, prices, now) -> Estimate(hours, gp, confidence, per_band_detail)`.
5. Tests over synthetic method tables (§16.4):
   - band partitioning across a method boundary (a method valid only 82–99)
   - a locked fast method is skipped in favour of a slower available one
   - a band with no method falls back and drags `estimate_confidence` to `low`
   - **each** price fallback layer, asserting the recorded `selection_reason`
   - **confidence from trade age, not fetch age**: a record fetched 1 minute ago whose trade
     is 5 days old yields `medium`, not `high` (D10)

## Verification

```bash
make test ARGS="tests/estimation -v" && make typecheck
```

## Exit criteria

- [ ] `tracker/estimation/` makes zero network calls and imports no HTTP client (covered by
      Step 4's AST boundary test)
- [ ] A test proves fresh-fetch-of-stale-trade yields the stale confidence (D10)
- [ ] `selection_reason` populated on every resolved price
- [ ] `estimate_confidence` is the minimum across both sub-confidences

## Rollback

`git branch -D step-05-estimation`.

---

# Step 6 — Recommendation engine

**Tier:** ⚑ **strongest** · **Depends on:** 5, 2.5 · **Unblocks:** 9, 13 · **Size:** large

## Context brief

**Read before starting:** SDD §9.3–§9.10, §10.4, §16.1, §16.2, D3, D9, plus amendments A1,
A2, A8, A15.

Implement the pure entry point mandated by §16.1:

```python
def recommend(state: PlayerState, selection: RoadmapSelection, content: Content,
              profile: ScoringProfile, incumbent: RecommendationSnapshot | None) -> list[Recommendation]
```

**Database access belongs to the caller.** Hysteresis needs the previous snapshot — it is a
parameter, never a query.

**Roadmap blending (§9.3, D3).** Normalize selection weights to sum to 1, then
`effective_weight(c) = Σ_r selection_weight(r) × roadmap_capability_weight(r, c)`. Because
selection weights sum to 1 and capability weights ∈ [0,1], this is a **convex combination** —
automatically in [0,1], no second normalization. A capability in two roadmaps **blends, never
accumulates**: `0.75(1.0) + 0.25(0.8) = 0.95`, never `1.8`. The maximum across roadmaps is
explicitly **not** used (D3 — a max rule lets each candidate be read under whichever roadmap
flatters it most, making selection weights meaningless).

Candidate factors come from Step 2.5's derivations (`pvp_value` blends the map first, then
takes the max over `advances` — A2).

**Scoring (§9.4)** — weighted geometric mean over factors normalized to `(0, 1]`:

| Factor | Definition | v1 weight |
|---|---|---|
| `readiness` | hard gate `{0,1}` — blocked candidates excluded and surfaced separately | gate |
| `pvp_value` | relevance under the blended weight map | 1.0 |
| `leverage` | normalized count of capabilities unblocked | 0.8 |
| `proximity` | `1 − (remaining / total)` | 0.6 |
| `effort_decay` | `exp(−hours / τ)`, τ = 10h | 0.7 |
| `cost_decay` | `exp(−gp / κ)`, κ from `gp_sensitivity` | 0.5 |

Every factor floored at **ε = 0.01**. κ presets: `high → 8M`, `normal → 20M`, `low → 50M`.

**Evaluate in log space (§9.5):** `ln(score) = Σ wᵢ · ln(fᵢ)`. Mathematically identical, but
each factor's contribution becomes an additive term in shared units. **Persist those
contributions in `RecommendationEntry.factors`,** and generate the "Why" line by reading off
the largest terms — never author the reason prose separately, or it drifts from the ranking.

**Refresher grouping (§9.8, D9).** Ungrouped refreshers give accurate but useless coaching
("Refresh 4-way switches / Refresh overhead prayers / Refresh DDing / …"). Milestones declare
a `practice_group`; when several members are stale, emit **one composite candidate**. Urgency
per milestone: `current → 0.00`; `stale (30–90d) → 0.40…0.70` linear in age; `very_stale
(>90d) → 0.70…1.00` linear to 270d, then clamped. Then:

```
breadth_bonus = min(0.10, 0.03 × (member_count − 1))
group_urgency = min(1.00, max(member_urgency) + breadth_bonus)
```

> **The inner cap is the whole point (§9.8):** without it a group of 20 stale milestones
> saturates at 1.0 on breadth alone. With it, a 5-member and a 20-member group both
> contribute at most +0.10, so urgency stays driven by *how stale the worst item is*.

Refresher `hours` comes from `suggested_session_hours` (A8) and `gp` is 0. **Do not default
hours to 0** — that gives `effort_decay = 1.0` and makes every refresher maximally
attractive, directly threatening G10.

**List policy:** at most one refresher in the primary list; a refresher may never be
top-ranked *solely* because many milestones were grouped; group size never multiplies
`pvp_value` — the candidate inherits the **maximum** relevant capability value, never the
sum; remaining stale groups go to the Practice freshness view.

**Anti-thrash hysteresis (§9.9, A15).** The incumbent top recommendation is displaced only
when `challenger.score > 1.10 × incumbent.score` (**raw** scores, not log), or the incumbent
becomes complete, or the incumbent becomes blocked.

## Tasks

1. `tracker/recommendations/blending.py` — the effective capability-weight map.
2. `tracker/recommendations/scoring.py` — log-space scorer returning the score **and** the
   per-factor log-contributions.
3. `tracker/recommendations/refreshers.py` — urgency curve, grouping, composite candidate
   synthesis from `practice_group` (§10.4), list-policy enforcement.
4. `tracker/recommendations/hysteresis.py` — pure `apply_hysteresis(ranked, incumbent)`.
5. `tracker/recommendations/reasons.py` — generate the "Why" line from the largest log
   contributions. No hand-authored prose.
6. `tracker/recommendations/engine.py` — `recommend()`, wiring 1–5 plus Step 4's capability
   states, Step 5's estimates and Step 2.5's candidate derivations.
7. **Engine-side §16.2 invariant tests — seven of the nine:**
   - a blocked candidate never appears in the actionable list
   - a completed candidate never ranks
   - of two otherwise identical candidates, the more expensive does not outrank the cheaper
   - of two otherwise identical candidates, the closer ranks higher
   - increasing a roadmap capability's weight never *lowers* a candidate that exclusively
     advances it
   - **no more than one refresher in the primary list** (G10)
   - **a refresher never outranks every progression candidate purely on group size**
   > The remaining two §16.2 invariants — G1 (`achieved` never flips from time alone) and
   > G6 (absent WOM evidence never advances freshness) — are **not** testable here.
   > `recommend()` is pure over `PlayerState`; it never mutates milestones and never sees
   > WOM. G1 belongs to Step 8c, G6 to Step 7. Do not stub them in.
8. **Regression test for the v0.1 defect (§9.4):** "Train Magic 87→94" outranks "Train Magic
   1→99" for a player at 87 Magic. The v0.1 formula multiplied by raw distance and time and
   therefore ranked *further and slower* as *better*.
9. Blending tests: property test that random selection/capability weights always yield a
   result in [0,1]; the 0.95-not-1.8 double-counting case; §9.3's worked table.
10. Hysteresis boundary test: a challenger at exactly `1.10 ×` does **not** displace; at
    `1.101 ×` it does (A15).
11. **Smoke corpus:** pull three of Step 13's scenarios forward and run them here.
    > Rationale: Step 13 is where gaps in the candidate model and refresher effort would
    > otherwise surface, forcing rework back through Steps 2.5 and 6. Three scenarios now
    > costs little and de-risks the whole engine chain.

## Verification

```bash
make test ARGS="tests/recommendations -v" && make typecheck
make test ARGS="tests/recommendations -k invariant -v"
```

## Exit criteria

- [ ] `recommend()` matches the §16.1 signature and takes `incumbent` as a parameter — it
      never queries a database (covered by Step 4's AST boundary test)
- [ ] **All seven engine-side** §16.2 invariant tests pass; G1/G6 are explicitly delegated
      to Steps 8c and 7 with a comment naming them
- [ ] Reason strings are generated from `factors`, never hand-written
- [ ] `factors` persists raw factor values **and** log-contributions (§6.10)
- [ ] Blending is convex — property test over random weights
- [ ] Hysteresis boundary tested at exactly 1.10× (A15)
- [ ] A refresher with `suggested_session_hours` unset fails validation rather than
      defaulting to 0 (A8)

## Rollback

`git branch -D step-06-recommendations`.

---

# Step 7 — Integrations: OSRS Wiki prices and Wise Old Man

**Tier:** default · **Depends on:** 2c · **Unblocks:** 9 · **Size:** medium
· **Parallel with:** 2.5, 3a, 4

## Context brief

**Read before starting:** SDD §7.2, §7.3, §7.5, §8.3, §11.6, D2, D10.

Two HTTP clients. **They return DTOs and persist nothing** — Step 9's pipeline owns writes.
This drops the dependency on Step 3 and mirrors the §16.1 purity philosophy one layer out.
Cache/TTL decisions read through an injected `PriceCacheReader` protocol.

**Wise Old Man (§7.2)** is the primary remote source — it already polls the hiscores, stores
history and exposes gains, covering both the "official hiscores" and "XP history" roles with
one integration, one parser and one rate-limit budget. Provides skills, total level, boss KC,
LMS score, XP history and gains. Requires a descriptive `User-Agent`; respect published rate
limits with backoff.

**Direct hiscores access is documented contingency only and is NOT built for v1 (§7.3).**
Create `tracker/integrations/hiscores/README.md` explaining this and stop.

**OSRS Wiki real-time prices (§7.5)** — `https://prices.runescape.wiki/api/v1/osrs`. The
provider asks automated clients for a descriptive `User-Agent` and notes that generic
identifiers (`python-requests`, `Python-urllib`, `Apache-HttpClient`, Java defaults, bare
`curl`) may be blocked. No fixed numeric rate limit is published, but it reserves the right
to limit clients whose sustained volume threatens service stability. Required behaviour:

* at most one refresh attempt per recommendation run
* no request at all while valid cached data exists
* retry schedule: immediate → 2s → 8s, then stop and fall back
* honour `Retry-After`; exponential backoff on `429` and `5xx`
* circuit breaker after repeated failures
* **no user-visible failure** when a cached or static fallback exists
* log response status and the provider's own timestamp
* manual refresh rate-limited to once per 60 seconds

**Fetch scope keeps this integration small (§8.3):** only items referenced by the **active
roadmap's** capabilities, candidates and training methods are fetched. Pulling the full item
economy would recreate the item database §3 rules out.

**Return both prices and their trade timestamps** (§6.8) — fetch time and trade time are
different facts, and Step 5's confidence derives from the latter.

> Verify the exact response shapes against the live APIs at implementation time rather than
> trusting this brief. Both providers' payload formats are outside this plan's authority.

## Tasks

1. `tracker/integrations/http.py` — shared httpx client factory applying the configured
   User-Agent, timeouts, retry schedule, `Retry-After` handling and a circuit breaker.
2. `tracker/integrations/prices/client.py` — `latest` fetch for a **scoped id set**;
   returns `PriceDTO(item_id, high_price_gp, high_trade_at, low_price_gp, low_trade_at,
   provider, fetched_at, source)`.
3. `tracker/integrations/prices/scope.py` — compute the referenced-item id set from the
   active roadmap's transitive content closure.
4. `tracker/integrations/prices/cache.py` — TTL policy (default 12h), manual-refresh
   throttle, `source` tagging (`live | cached | static_hint | unknown`), reading current
   state through the injected `PriceCacheReader`.
5. `tracker/integrations/wise_old_man/client.py` — player fetch + gains → `SkillDTO` list.
   **Normalize `-1` → `None` at this boundary (G5).**
6. `tracker/integrations/wise_old_man/practice.py` — emit a **medium**-confidence
   `PracticeEventDTO` when the LMS score *increases*. Evidence is positive-only: *"An LMS
   score increase proves recent activity; a lack of movement proves nothing."*
7. `tracker/integrations/hiscores/README.md` — contingency-only note; no code (§7.3).
8. `tracker/integrations/prices/attribution.py` — the §7.5 attribution constant for Step 11:
   *"Market prices provided by the OSRS Wiki real-time prices API and RuneLite contributors.
   Prices are estimates and may be stale for low-volume items."*
9. Tests with mocked transports:
   - no request issued while cache is valid
   - `429` + `Retry-After` honoured; circuit breaker opens after repeated failures
   - scoped fetch requests only referenced ids — an unreferenced id is never requested
   - `-1` normalizes to `None` in the DTO (**G5**)
   - **G6:** a WOM score *decrease* or *plateau* emits **no** event, and no code path in this
     module can decrease a freshness value. Add an explicit negative test named for G6.

## Verification

```bash
make test ARGS="tests/integrations -v" && make typecheck
grep -rn "python-requests\|Apache-HttpClient" tracker/integrations/   # must be empty
```

## Exit criteria

- [ ] Every outbound request carries the configured descriptive User-Agent
- [ ] Zero requests issued when cached data is within TTL
- [ ] Trade timestamps returned separately from `fetched_at` (D10)
- [ ] Fetch scope is roadmap-derived — a test asserts an unreferenced id is never requested
- [ ] **G5** and **G6** each have a named test in this step; G6 is §16.2's "absent WOM
      evidence never advances freshness" and this step owns it
- [ ] Clients return DTOs and import nothing from `tracker.db`
- [ ] Outbound requests carry only username (WOM) and item ids (prices) — practice events
      never leave the machine (§11.6)
- [ ] `tracker/integrations/hiscores/` contains documentation only

## Rollback

`git branch -D step-07-integrations`. No schema changes.

---

# Step 8 — Sync contract, API, merge, freshness service

**Tier:** default · **Depends on:** 3a · **Unblocks:** 8.5, 9 · **Size:** large
— split 8a / 8b / 8c

## Context brief (shared by 8a, 8b, 8c)

**Read before starting:** SDD §6.7, §6.11, §7.4, §7.6, §11, §12, D6, plus amendments A12,
A14, A16, A17.

**Security (§11).** v0.1 said both "localhost only" and "reachable from a phone via
Tailscale". These are incompatible: Tailscale reachability requires binding beyond loopback,
at which point *any device on the tailnet can POST to `/api/sync` and rewrite account state*.
"No public exposure" is a deployment property, not an access control. Therefore: explicit
bind address, never `0.0.0.0`; **all `/api/*` requests require a bearer token** regardless of
source address; unauthenticated writes rejected with 401 **and recorded as a `SyncEvent`**.

> Health lives at `GET /healthz`, **outside** `/api` (A16) — otherwise §11.2 and a public
> health check contradict each other. Auth attaches at **router** level so a future `/api/*`
> route inherits it by construction.

**Versioning (§12.2, A14).** The server declares `SUPPORTED_PAYLOAD_VERSIONS = {1}` and
rejects anything outside with **409**, recording the `SyncEvent`, rather than silently parsing
a subset of fields. *"Plugin and app will drift; the failure should be loud and diagnosable."*

**Merge precedence (§7.4).** Hiscores (and therefore WOM) only update on logout, so RuneLite
is nearly always fresher and the two *will* disagree during a session:
1. prefer the most recent `observed_at`
2. on ties, prefer `runelite > wise_old_man > hiscores`
3. **never allow a lower-precedence source to decrease a skill's stored XP** (G4)

**Freshness service (§6.7, §7.6).** Integrations write `PracticeEvent` rows; **the freshness
service maps events onto milestones**. Client-side detection logic never touches milestone
rows directly. The governing distinction:

```
achieved          = "The user has established this skill before."
last_practiced_at = "The user recently exercised the general skill domain."
```

A proxy may update `last_practiced_at` only when all four hold: the signal proves relevant
PvP activity occurred; the milestone declares that signal via `practiced_by`; the proxy does
**not** set `achieved = true`; the proxy does **not** claim competence from mere
participation.

Domains: `lms · nh_combat · wilderness_pvp · vengeance_pvp · anti_pking · general_pvp`.

**The schema enforces the collection boundary, not convention (§12.1).** Constrain
`practice_events` to the summarized shape with `additionalProperties: false`, so any attempt
to send opponent names, chat, prayer selections or tick-level location is rejected by the
contract itself (G8).

---

## Step 8a — Contract, auth, sync endpoint

**Depends on:** 3a · **Unblocks:** 8b

### Tasks

1. **`contracts/sync_payload.schema.json`** — JSON Schema, source of truth for both
   languages. Mark it **`"x-status": "provisional"`** until Step 8.5 (see M5 rationale).
   Covers `payload_version`, player identity, skills, quests, unlocks, **spellbook / diaries
   / combat achievements as `unlock` entries with `spellbook_*` / `diary_*` / `ca_*` key
   prefixes (A12 — do not invent a field with no sink)**, observed equipment, observed bank
   **plus container scan timestamps**, and `practice_events` in exactly the §7.6 shape:
   ```json
   { "domain": "lms", "started_at": "...", "ended_at": "...", "evidence_type": "lms_match_completed" }
   ```
   `additionalProperties: false` throughout.
2. `tracker/api/auth.py` — bearer dependency, constant-time comparison, 401 + a `SyncEvent`
   row with `player_id = NULL`, `remote_addr`, `reason` (A17).
3. `tracker/api/router.py` — the `/api` router with the auth dependency attached at router
   level.
4. `tracker/api/sync.py` — `POST /api/sync`: validate against the JSON Schema **file** via
   `jsonschema` (do not re-declare it in Pydantic — one owner, §12.1), record `SyncEvent`,
   409 on unsupported `payload_version`.
5. `tracker/api/health.py` — `GET /healthz`, unauthenticated, outside `/api` (A16).
6. Tests:
   - schema accepts the canonical payload, rejects extra fields
   - **a payload containing opponent names or per-tick location is rejected (G8)**
   - missing/invalid token → 401 **and** a `SyncEvent` with `player_id IS NULL`
   - unsupported `payload_version` → 409 **and** a `SyncEvent`
   - **a newly added dummy `/api/*` route inherits auth without being listed anywhere** —
     this is what makes §11.2 structural rather than per-endpoint discipline

### Exit criteria

- [ ] Schema is valid JSON Schema, marked provisional, and rejects unsummarized telemetry (G8)
- [ ] Auth is attached at router level; the inheritance test passes
- [ ] `GET /healthz` is unauthenticated and outside `/api` (A16)
- [ ] 401 and 409 paths each produce a `SyncEvent` row

---

## Step 8b — Merge and precedence

**Depends on:** 8a · **Unblocks:** 8c

### Tasks

1. `tracker/sync/merge.py` — the §7.4 rules; write a `ContainerScan` row per scanned
   container **even when the container holds nothing tracked** (this is what makes
   "unsatisfied" distinguishable from "unknown", §6.5); XP monotonicity guard.
2. Tests: stale WOM XP does not overwrite fresher RuneLite XP (**G4** — §16.4's
   "stale-source-must-not-regress"); tie on `observed_at` resolves by source precedence; an
   empty bank scan still records a `ContainerScan`.

### Exit criteria

- [ ] **G4** has a named test in this step and merge never regresses XP
- [ ] An empty container scan is recorded, not skipped

---

## Step 8c — Freshness service

**Depends on:** 8b · **Unblocks:** 8.5, 9

### Tasks

1. `tracker/freshness/service.py` — map `PracticeEvent` rows onto milestones via
   `practiced_by`; update `last_practiced_at` **only**; never touch `achieved`.
2. Tests:
   - a `PracticeEvent` refreshes `last_practiced_at` and leaves `achieved` unchanged (**G7**)
   - **G1:** advance the clock arbitrarily far and assert no milestone's `achieved`
     transitions true → false. This is §16.2's *"`achieved` never transitions true → false
     from the passage of time alone"* and **this step owns it** — the recommendation engine
     is pure and cannot.
   - an event whose domain is not in a milestone's `practiced_by` refreshes nothing
   - a `knowledge`-class milestone is never given a freshness effect (§6.6)

### Exit criteria

- [ ] The freshness service is the **only** writer of `last_practiced_at`
- [ ] **G1** and **G7** each have a named test in this step
- [ ] No code path in this module writes `achieved`

## Rollback (all of Step 8)

`git branch -D` the sub-step branches. Steps 8.5 and 12 have not started yet by construction.

---

# Step 8.5 — Plugin spike and contract reconciliation

**Tier:** default · **Depends on:** 8c · **Unblocks:** 12a · **Size:** small

> **Inserted after adversarial review.** Freezing `sync_payload.schema.json` before any
> RuneLite code exists contradicts the SDD's own rationale for side-loading: §13 chose it for
> *"freedom to evolve the payload contract aggressively … the plugin and app are tightly
> coupled through §12's schema and **early development will churn it**"*, and §12.2 assumes
> *"Plugin and app will drift"*. A Python agent with no RuneLite context must otherwise guess
> quest identity (`quest_id` string vs RuneLite's `Quest` enum), varbit→unlock key mapping,
> diary/CA shape, and whether the client can even signal a *complete* bank scan.

## Context brief

**Read before starting:** SDD §7.1, §12.1, §12.2, §13, and `contracts/sync_payload.schema.json`.

Build a throwaway RuneLite collector that dumps **one real snapshot** to disk. Compare it to
the provisional schema. Amend the schema, bump `payload_version` if the shape changed, then
freeze. Nothing from this spike ships.

## Tasks

1. Minimal RuneLite plugin that, on a hotkey, serializes everything §7.1 lists to
   `~/snapshot.json`. No auth, no HTTP, no practice detection.
2. Capture one snapshot from a real account.
3. Diff against `contracts/sync_payload.schema.json`; record every mismatch in
   `docs/CONTRACT_RECONCILIATION.md` — especially quest identity, varbit→unlock key mapping,
   diary/CA representation, and whether a *complete* bank scan is detectable.
4. Amend the schema; bump `payload_version` if the shape changed; remove `"x-status":
   "provisional"`.
5. Update `SUPPORTED_PAYLOAD_VERSIONS` in `tracker/api/sync.py` and the Step 8a tests.
6. Commit the captured snapshot (redacted of username) as
   `tests/contracts/fixtures/real_snapshot.json`; add a test validating it against the schema.
7. Delete the spike code.

## Verification

```bash
make test ARGS="tests/contracts -v"
python -c "import json,jsonschema; s=json.load(open('contracts/sync_payload.schema.json')); jsonschema.Draft202012Validator.check_schema(s); print('schema ok')"
```

## Exit criteria

- [ ] A real snapshot validates against the schema
- [ ] `docs/CONTRACT_RECONCILIATION.md` records every mismatch and its resolution
- [ ] `"x-status": "provisional"` removed — **the schema is now frozen**; later changes
      require a `payload_version` bump and a coordinated Step 12 update
- [ ] Spike code deleted; `plugin/` still empty

## User gate

This step needs a **local RuneLite install and a human to launch the game and press the
hotkey**. An agent can write the spike; it cannot capture the snapshot. See
[Open items](#open-items-for-the-user).

## Rollback

`git branch -D step-08.5-contract-spike`; the provisional schema stands.

---

# Step 9 — Orchestration pipeline and application entrypoint

**Tier:** default · **Depends on:** 3b, 6, 7, 8c · **Unblocks:** 10 · **Size:** medium

## Context brief

**Read before starting:** SDD §5, §11, §12, §16.1, plus amendments A16, A18, A19.

Wire the parts into the §12 pipeline. This step owns the **caller** side of the §16.1 purity
boundary: it reads the DB, builds `PlayerState`, calls `recommend()`, persists the result,
and persists the DTOs Step 7's clients returned. The engine stays untouched.

```
RuneLite launches
    ↓ Plugin POSTs snapshot + practice_events to /api/sync (token, payload_version)   [client]
    ↓ Server validates against JSON Schema; records SyncEvent                          [8a]
    ↓ Facts merged under precedence rules (§7.4)                                       [8b]
    ↓ Freshness service maps PracticeEvents onto milestones (§7.6)                     [8c]
    ↓ Prices refreshed for referenced items, if TTL expired (§8.3)                     [7 + 9]
    ↓ Progression engine recomputes CapabilityState                                    [4]
    ↓ Recommendation engine runs; snapshot persisted                                   [6 + 9]
    ↓ Dashboard refreshes over websocket                                               [10]
```

`run_pipeline` executes **stages 2–7** — stage 1 is the plugin's POST and stage 8 is the
browser's websocket refresh; neither is a server-side function call. Stage 8 is an event
emission.

NiceGUI runs on FastAPI/uvicorn, so **the UI and the sync API are one process on one port**
(default `8502`). There is no second service. Mount NiceGUI onto the existing FastAPI app;
do not create a second application object.

Hysteresis (§9.9) reads the incumbent from the most recent `RecommendationSnapshot` — this
step loads it and passes it into `recommend()`.

## Tasks

1. `tracker/sync/pipeline.py` — `run_pipeline(session, player_id, now)` executing stages 2–7;
   each stage independently loggable and testable.
2. `tracker/db/persist_prices.py` — write Step 7's `PriceDTO`s plus Step 5's
   `selected_price_gp` / `selection_policy` / `selection_reason` (A19).
3. `tracker/progression/persist.py` — materialize `CapabilityState` **and**
   `Milestone.freshness` (A18).
4. `tracker/recommendations/persist.py` — write `RecommendationSnapshot`
   (`roadmap_selection` read from `ActiveRoadmap`, `scoring_profile_version`) and
   `RecommendationEntry` rows (`rank`, `candidate_kind`, `score`, `factors`, `reason`,
   `estimated_hours`, `estimated_gp`, `estimate_confidence`, `blocked`).
5. `tracker/app.py` — build the FastAPI app, mount the `/api` router and `/healthz`, mount
   NiceGUI, read bind address/port from settings, refuse to start without `api_token`.
6. Background worker: periodic WOM poll + price TTL refresh; **single-flight** so a manual and
   a scheduled refresh cannot race.
7. Wire `make run`.
8. `docs/DEPLOYMENT.md` — bind-address choice, **Tailscale ACLs restricting which devices may
   reach the port as defense in depth** (§11.4), and **no inbound port forwarding, ever;
   there is no public deployment story** (§11.5). These two §11 rules have no other home.
9. Tests: end-to-end pipeline over a seeded DB and a fixture payload producing a
   `RecommendationSnapshot` with entries; a second identical run does not displace the
   incumbent (hysteresis); price fetch skipped when TTL is valid; `Milestone.freshness`
   materialized.

## Verification

```bash
make test && make typecheck
make run & sleep 3
BIND=$(python -c "from tracker.config.settings import Settings; s=Settings(); print(f'{s.bind_address}:{s.port}')")
curl -s -o /dev/null -w 'healthz=%{http_code}\n' "http://$BIND/healthz"                       # 200
curl -s -o /dev/null -w 'sync_noauth=%{http_code}\n' -X POST "http://$BIND/api/sync" -d '{}'  # 401
kill %1
```
> The URL is read from settings, not hardcoded to `localhost` — the app may be bound to a
> tailnet address (§11.1).

## Exit criteria

- [ ] One process, one port; both UI and API reachable at the configured bind address
- [ ] The pipeline is the only place DB reads meet engine calls — enforced by Step 4's AST
      import-boundary test, which must still pass
- [ ] `RecommendationSnapshot.scoring_profile_version` populated from `profile.yaml`
- [ ] `roadmap_selection` read from `ActiveRoadmap` (A13), not hardcoded
- [ ] Hysteresis demonstrably prevents churn across two near-identical runs
- [ ] App refuses to start with `bind_address: 0.0.0.0` or a missing token
- [ ] `docs/DEPLOYMENT.md` covers §11.4 and §11.5

## Rollback

`git branch -D step-09-orchestration`.

---

# Step 10 — UI part 1: shell, dashboard, capabilities, unlocks, skills

**Tier:** default · **Depends on:** 9 · **Unblocks:** 11 · **Size:** medium

## Context brief

**Read before starting:** SDD §4.4, §6.2, §6.5, §15.

These are the **status-honesty views** — where the three-layer separation becomes visible.
Getting the rendering wrong undoes the modelling work of Steps 2–6.

**Capabilities is the headline view** — *"what can I actually do today?"* Each capability
shows all three layers of §4.4 as **distinct** fields, never merged into one badge:

```
Budget Wilderness NH            High-risk Deep Wilderness NH
  Status:               unlocked  Status:               unlocked
  Readiness confidence: medium    Readiness confidence: low
  Recommended now:      yes       Recommended now:      no — complete a refresher first

Voidwaker NH
  Status:               unknown
  Readiness confidence: —
  Recommended now:      no — bank contents have never been observed
```

**Blockers ("do this") and unknowns ("sync this") are separate lists with separate calls to
action** (§15). They demand different user actions and must never be concatenated.

**Unlocks render four states, and `unknown` must never render as locked** (§15): unlocked =
green · available = yellow · locked = gray · **unknown = outlined/hatched**. The same rule
applies to capability `status: unknown`. Unknown means *"sync RuneLite"*, not *"go do this."*

**Skills:** unranked skills render as unranked, **not as level 1** (§6.2).

**Item staleness copy (§6.5):** say *"last saw your bank 3 weeks ago"*, never *"you don't
have a Voidwaker."*

**Mobile (§15):** reached over Tailscale; responsive, phone-first. Build mobile-first rather
than retrofitting.

> **Make every visual distinction machine-checkable.** Emit `data-state="unknown|locked|
> available|unlocked"` on every status-bearing element, and `data-testid` on each list
> container. "Visually distinct" is a human judgment; *"these two selectors are disjoint"*
> is a test.

## Tasks

1. `tracker/ui/shell.py` — nav, responsive layout, theme, websocket refresh.
2. `tracker/ui/dashboard.py` — character summary, overall readiness, roadmap progress, top
   recommendation with its generated reason, quick actions. **"Current goal" = the
   top-ranked entry of the latest snapshot** — §15 names it but §6 defines no model for it,
   so derive it rather than inventing storage.
3. `tracker/ui/capabilities.py` — three fields rendered distinctly; separate
   `data-testid="blockers"` and `data-testid="unknowns"` containers with distinct CTAs.
4. `tracker/ui/unlocks.py` — four-state cards, each carrying `data-state`.
5. `tracker/ui/skills.py` — progress bars; unranked rendered as unranked.
6. `tracker/ui/components/` — reusable `StatusBadge`, `ConfidenceChip`, `UnknownCard`,
   `StalenessNote` (the "last saw your bank …" phrasing lives here, once).
7. Tests with `nicegui.testing` + `pytest-playwright`:
   - the set of elements with `data-state="unknown"` and the set with `data-state="locked"`
     are **disjoint**, and each renders a different CSS class
   - `data-testid="blockers"` and `data-testid="unknowns"` are separate DOM nodes
   - an unranked skill's rendered text never contains the token `1` as a level
   - at a 390 px viewport, `document.documentElement.scrollWidth <= clientWidth`

## Verification

```bash
make test ARGS="tests/ui -v" && make lint
```

## Exit criteria

- [ ] `unknown` and `locked` produce disjoint selectors in **both** the unlocks and
      capabilities views — the SDD's hardest UI requirement, now mechanically checked
- [ ] Three status layers render as three fields, never collapsed into one badge
- [ ] Blockers and Unknowns are separate DOM containers with separate CTAs
- [ ] Unranked skills never display as level 1
- [ ] No horizontal scroll at 390 px, asserted by the Playwright test

## User gate

*"Visually distinct"* in the aesthetic sense stays a human judgment. The tests prove the
markup differs; a human confirms the hatched treatment actually reads as "unknown".

## Rollback

`git branch -D step-10-ui-status`.

---

# Step 11 — UI part 2: recommendations, practice freshness, settings, history

**Tier:** default · **Depends on:** 10 · **Unblocks:** — · **Size:** medium

## Context brief

**Read before starting:** SDD §4.3, §6.10, §8.4, §9.6, §9.8, §9.10, §15.

**Recommendations view (§15):** sortable ranked list with a per-item factor breakdown, the
estimate, and a confidence marker for anything below `high`. Blocked candidates in a separate
collapsed section. **At most one refresher appears here** (§9.8, G10).

Target output shape (§9.10):

```
Next Recommendation

  Train Magic  87 → 94
  Unlocks      Ice Barrage
  Advances     Ice Barrage NH, Deep Wilderness NH
  Estimate     ~4.5 hours  ·  ~1.8M gp    [medium — price from a 3-day-old trade]
  Priority     ★★★★★

  Why: high PvP value (+0.61) · unblocks 2 capabilities (+0.44) · close to target (+0.30)
```

The "Why" line renders `RecommendationEntry.reason`, which Step 6 generated from log
contributions. **Do not compose new prose here** — that is how displayed reasons drift from
actual rankings.

> **§8.4's warning:** *"The UI must visually distinguish anything below `high`. An unqualified
> '4.5 hours' that is actually a guess erodes trust in every other number on the page."*

**Practice freshness view (§15):** dedicated view for **all** stale practice groups — this is
where refreshers beyond the first live, so freshness never crowds out objective progression.
Two explicit completion actions (§9.8), *because a single tap must not silently attest to
five separate skills*:

| Action | Effect |
|---|---|
| **Mark session complete** | Refreshes every milestone listed in that session |
| **Review individual skills** | Lets the user refresh a subset |

A RuneLite-derived LMS session refreshes all milestones whose `practiced_by` includes `lms`
**without any prompt** — derived evidence needs no confirmation.

**Settings (§15, §9.6):** GP sensitivity asked as *"How strongly should expensive upgrades be
deprioritized?"* — **Strongly / Normally / Barely**. The UI never says "κ" or even "GP
sensitivity". Roadmap selection weights stay behind advanced settings; defaults `1.00`
primary / `0.25` secondary (§4.3), written to `ActiveRoadmap` (A13). Price attribution footer
from Step 7.

**History (§15):** XP charts (Plotly), roadmap progress over time, and recommendation history
including *why* the top recommendation changed and under which `scoring_profile_version`.

## Tasks

1. `tracker/ui/recommendations.py` — ranked list, factor-breakdown drawer, confidence
   markers, collapsed blocked section, and a render-time assertion of the one-refresher rule
   as belt-and-braces over Step 6's guarantee.
2. `tracker/ui/practice.py` — stale group cards; both completion actions; self-attestation
   prompts for the small self-attested set only.
3. `tracker/ui/roadmaps.py` — primary selector + optional secondaries writing to
   `ActiveRoadmap`; weights behind advanced settings.
4. `tracker/ui/settings.py` — the three-way sensitivity question in user language;
   attribution footer; bind address and token *presence* displayed, never the token value.
5. `tracker/ui/history.py` — Plotly XP charts, roadmap progress, and a snapshot **diff** view
   showing which factor moved between two runs (§6.10: *"two runs can be diffed to see which
   factor moved"*).
6. Tests: exactly one refresher renders when three groups are stale (G10); an estimate with
   `confidence: medium` renders a `data-confidence="medium"` marker; "Mark session complete"
   refreshes all listed milestones and **only** those; the settings page source contains
   neither `κ` nor `kappa` nor `GP sensitivity`.

## Verification

```bash
make test ARGS="tests/ui -v" && make lint && make test
```

## Exit criteria

- [ ] Every estimate below `high` carries a `data-confidence` marker (§8.4)
- [ ] At most one refresher in the primary list; the rest in Practice freshness (G10)
- [ ] Both completion actions present and behaviourally distinct
- [ ] Settings uses user language — no "κ", "kappa" or "GP sensitivity" in the rendered page
- [ ] History shows `scoring_profile_version` alongside each snapshot
- [ ] "Why" strings come from persisted `reason`, not new UI prose

## Rollback

`git branch -D step-11-ui-recommendations`.

---

# Step 12 — RuneLite companion plugin (Java)

**Tier:** default · **Depends on:** 8.5 · **Unblocks:** — · **Size:** large
— split 12a / 12b / 12c · **Parallel with:** 9, 10, 11, 13

## Context brief (shared by 12a, 12b, 12c)

**Read before starting:** SDD §7.1, §7.6, §12, §13, D6, and the **frozen**
`contracts/sync_payload.schema.json` plus `docs/CONTRACT_RECONCILIATION.md` from Step 8.5.

Java plugin, Gradle, **side-loaded from a local build**. §13/D5 is explicit: **side-loading is
the only supported distribution path for v1.** Plugin Hub submission is triggered by external
adoption, is not an architectural requirement, and **must not appear on the critical path.**

**Provides (§7.1):** quest completion and quest points, skills and XP, spellbook, diaries,
combat achievements, observed equipment, observed bank contents, unlock flags, and summarized
practice events. Most unlock and quest state comes from **varbits**, which is why the plugin
is authoritative and freshest. Spellbook, diaries and CAs are transmitted as `unlock` entries
with `spellbook_*` / `diary_*` / `ca_*` key prefixes (A12).

**Narrow seam (§13.2):**
```java
interface TrackerSyncClient { void submit(AccountSnapshot snapshot); }
```
How the plugin is *distributed* must not influence snapshot construction, serialization,
authentication, versioning, or app-side ingestion. If a future Plugin Hub submission would
require changing any of those, the boundary has eroded.

**Collection boundary — a hard limit (§7.6, §3, G8).** No opponent names, attack sequences,
chat, individual prayer selections, fight-time inventories, or tick-by-tick location history.

> Verify RuneLite API specifics (event classes, varbit ids, sideload directory) against the
> RuneLite version you build against. This brief specifies *what* to observe, not the current
> API surface.

---

## Step 12a — Gradle skeleton, config, sync client, contract test

### Tasks

1. `plugin/` Gradle project against the RuneLite plugin API; `build.gradle` + wrapper.
2. `TrackerConfig` — server URL, bearer token (masked), sync-on-login toggle, practice
   detection toggle.
3. `TrackerSyncClient` — POST with bearer token and `payload_version`; serialize to the
   frozen schema; retry with backoff; surface failures in the RuneLite sidebar, never
   silently.
4. **Cross-language contract test:** serialize a sample `AccountSnapshot` in a Java test and
   validate it against `contracts/sync_payload.schema.json`; POST the same fixture from
   `tests/contracts/test_plugin_fixture.py` on the Python side.
   > The fixture lives in `tests/contracts/`, **not** `tests/api/` — Steps 8 and 9 own
   > `tests/api/` and Step 12 runs in parallel with Step 9.

### Exit criteria (agent-verifiable)

- [ ] `cd plugin && ./gradlew build test` passes
- [ ] The cross-language contract test passes on both sides
- [ ] Field names are read from the schema, not hand-transcribed

---

## Step 12b — Collectors

### Tasks

1. Skills/XP, quests + quest points, varbit-derived unlocks, spellbook, diaries, combat
   achievements, equipment.
2. Bank collector: on bank-interface close, record a **container scan timestamp even when the
   bank holds nothing tracked** — this is what makes "unsatisfied" distinguishable from
   "unknown" (§6.5). Getting this wrong silently disables the entire unknown-state design.

### Exit criteria (agent-verifiable)

- [ ] Every §7.1 field maps to a schema field; none is collected without a sink
- [ ] An empty bank still emits a container scan

---

## Step 12c — Practice detector

### Tasks

1. `PracticeDetector` implementing **the table and its rejections**:

   | Signal | May refresh | Confidence |
   |---|---|---|
   | Entry into and exit from an LMS match | `lms`, `nh_combat`, `general_pvp` | high |
   | Sustained player combat in LMS | `lms`, `nh_combat` | high |
   | Sustained player combat inside the Wilderness | `wilderness_pvp`, `general_pvp` | high |
   | Attacked on a PvM setup in the Wilderness | `anti_pking` — **only if the player fights back** | medium |
   | Merely entering the Wilderness | nothing | — |
   | Equipping multiple combat styles | nothing | — |
   | Switching prayers rapidly | nothing on its own | — |
   | Logging in after a long break | nothing | — |

2. **Combat-occurred threshold for v1:** at least **two player-directed attacks**, or at least
   **ten seconds** in a player-combat state. *"This prevents a milestone refreshing because
   someone misclicked another player or took a single hit while escaping."*
3. Emit summarized events only — the §7.6 four-field shape, nothing more.
4. `docs/PLUGIN_SIDELOAD.md` — build and side-load instructions plus the **app/plugin version
   compatibility note** (§13.1 stage 1 is "manually matched app/plugin versions").
5. Java tests: one attack does **not** refresh; <10s does **not** refresh; Wilderness entry
   alone emits nothing; prayer switching alone emits nothing; anti-PK emits only when the
   player fights back.
6. **Payload-path collection audit:** a test that walks the serialized `AccountSnapshot` JSON
   and asserts its key set is a subset of the schema's declared properties.
   > This replaces grepping for `opponent|chatMessage|playerName`, which both false-positives
   > on legitimate RuneLite API use and fails to actually check the payload path.

### Exit criteria (agent-verifiable)

- [ ] A passing **negative** test for every rejected signal in §7.6
- [ ] Two-attack / ten-second threshold enforced and tested
- [ ] The payload-path key-set audit passes (**G8**)
- [ ] No Plugin Hub work was done (§13, D5)

## Exit criteria (human-verifiable — user gate)

- [ ] Plugin side-loads into a local RuneLite
- [ ] A real sync populates skills, quests, unlocks and a container scan in the app

## Verification

```bash
cd plugin && ./gradlew build test
make test ARGS="tests/contracts -v"
```

## Rollback

`rm -rf plugin/build`; `git branch -D` the sub-step branches. Note Step 12a **does** add one
Python file (`tests/contracts/test_plugin_fixture.py`) — remove it too.

---

# Step 13 — Golden corpus and weight tuning

**Tier:** ⚑ **strongest** · **Depends on:** 6 · **Unblocks:** — · **Size:** large
· **Parallel with:** 9, 10, 11, 12

## Context brief

**Read before starting:** SDD §9.4, §9.6, §9.7, §16 (all), D4.

Steps 4–6 shipped their own invariant tests. This step builds the **judgment corpus** and
runs the tuning procedure that turns provisional v1 weights into tuned ones.

**Judgments, not exact orderings (§16.1).** Asserting a full exact ordering is brittle: two
near-tied candidates flip on noise and the test fails for no meaningful reason.

```yaml
scenario:
  player_state: ...
  roadmap_selection: {main_nh: 1.0}
expectations:
  must_rank_above:
    - [complete_desert_treasure_i, train_woodcutting]
    - [train_magic_87_to_94, buy_voidwaker]
  top_3_contains: [train_magic_87_to_94, unlock_rigour]
  must_not_be_top: [buy_high_risk_gear]
```

**Pairwise judgments the SDD names (§16.2):** DT1 outranks buying a Voidwaker while Ancients
are still locked; 94 Magic outranks 99 Strength when the target capability requires Barrage;
Rigour does not outrank Protect Item for an account below 25 Prayer, when Protect Item gates
initial Wilderness practice.

**Stability tests (§16.2):** +10,000 Magic XP does not replace the top recommendation unless
a threshold is crossed; a 2% item price movement does not move a candidate from rank 8 to
rank 1; a milestone crossing 30 days does not reorder the primary progression list.

**Tuning procedure (§16.3, D4)** — weights are **not** optimized against exact expected ranks:

1. Build ~20 realistic scenarios.
2. Record pairwise expert preferences for each.
3. Grid or Bayesian search over weights, τ and κ, subject to §9.6's constraints
   (`kappa_gp ∈ [1M, 250M]`; ordering `high < normal < low`).
4. Maximize **pairwise-agreement rate**.
5. **Review every disagreement manually** — *"a disagreement is as likely to reveal a bad
   judgment as a bad weight."*
6. Round to humanly interpretable values.
7. Persist to `content/scoring/profile.yaml`, incrementing `version` and setting
   `tuned_against_corpus`.

> Step 5 is a human judgment call. Do not auto-accept a tuned profile that disagrees with
> recorded preferences — surface the disagreements and stop.

## Tasks

1. `tests/golden/scenarios/*.yaml` — ~20 scenarios spanning: fresh account; mid-game main;
   maxed pure; **unknown-bank account** (exercises the whole tri-state path); all-stale
   account; multi-roadmap account; blocked-fast-method account.
2. `tests/golden/loader.py` — scenario YAML → `PlayerState` + `RoadmapSelection`.
3. `tests/golden/test_judgments.py` — assert `must_rank_above`, `top_3_contains`,
   `must_not_be_top`.
4. `tests/golden/test_stability.py` — the three §16.2 stability tests.
5. `tools/tune_weights.py` — grid/Bayesian search maximizing pairwise agreement subject to
   §9.6's constraints; emits a disagreement report; **does not write the profile
   automatically**.
6. **Commit `tests/golden/` first**, then run the tuning and write
   `content/scoring/profile.yaml` in a **second** commit with `version: 2` and
   `tuned_against_corpus` = the hash of the corpus commit.
   > Two commits, because a single one is circular: the hash isn't known until the corpus is
   > committed, and writing the profile changes the tree.
7. `docs/TUNING.md` — the procedure, the corpus, and every recorded disagreement with its
   resolution.

## Verification

```bash
make test ARGS="tests/golden -v"
python tools/tune_weights.py --report
make validate-content          # κ constraints must still hold after the retune
make test                      # all Step 4–6 invariants must still pass
```

## Exit criteria

- [ ] ≥20 scenarios with recorded pairwise preferences
- [ ] Judgment tests assert relative order, never exact full rankings
- [ ] All three stability tests pass
- [ ] Tuned profile satisfies §9.6's κ min/max/ordering constraints
- [ ] `profile.yaml` has `version: 2` and a non-null `tuned_against_corpus` naming the
      corpus commit
- [ ] Every disagreement documented with a resolution in `docs/TUNING.md`
- [ ] **All Step 4–6 invariant tests still pass under the tuned weights — if tuning breaks an
      invariant, the invariant wins**

## User gate

§16.3 step 5 (disagreement review) is explicitly a human judgment. An agent runs the search
and produces the report; it must not accept the result unsupervised.

## Rollback

`git checkout content/scoring/profile.yaml` (reverts to the v1 provisional weights, a valid
shipping state per D4); `git branch -D step-13-tuning`.

---

## Plan mutation protocol

Plans decay on contact with implementation. When a step turns out wrong:

| Situation | Protocol |
|---|---|
| **Split** — a step is too large for one PR | Renumber as `NNa`, `NNb`; both inherit the parent's dependencies and context brief; log it below |
| **Insert** — missing prerequisite discovered | Number it `NN.5`; state which steps now depend on it; re-check the parallel-windows table |
| **Skip** — a step proves unnecessary | Record *why*, and confirm no exit criterion elsewhere depended on it |
| **Reorder** — a dependency was wrong | Update the graph **and** the parallel-windows table; never one without the other |
| **Abandon** — objective changed | Mark the plan superseded and link the successor; do not silently edit |

**Never** silently edit a completed step. Append to the audit log.

### Audit log

| Date | Mutation | Unit(s) | Reason |
|---|---|---|---|
| 2026-08-04 | Created | — | Initial blueprint from SDD v0.4 |
| 2026-08-04 | Insert | **2.5** | Adversarial review: `Candidate` is a core noun (§4) with a content directory (§10.1) but **no schema anywhere in the SDD**; Steps 6 and 13 were unexecutable without it |
| 2026-08-04 | Insert | **8.5** | Freezing the sync contract before any RuneLite code contradicts §13's stated rationale for side-loading; a real snapshot must reconcile it first |
| 2026-08-04 | Split | 2 → 2a/2b/2c · 3 → 3a/3b · 8 → 8a/8b/8c · 12 → 12a/12b/12c | Each bundled 3+ PRs |
| 2026-08-04 | Reorder | **7** now depends on 2c, not 3 | Clients return DTOs; Step 9 persists. Widens the post-2c parallel window to four units |
| 2026-08-04 | Correction | 6 → 7, 8c | G1 and G6 reassigned; `recommend()` is pure and structurally cannot test either |
| 2026-08-04 | Correction | all | `make test -- tests/x` replaced with `make test ARGS=tests/x`; the former exits 2 under GNU make |
| 2026-08-04 | Correction | 4 | `unlock_fraction` denominator corrected to *all* leaves per §6.9 (was: exclude unknowns from both sides) |
| 2026-08-04 | Ratified | all | All 21 amendments folded into `docs/SDD.md` **v0.5**; traced in SDD §20. `Candidate` landed at **§10.6** (not §10.8), validation renumbered to §10.7, `ActiveRoadmap` at §6.12, Migrations to §6.13. D11/D12 and §4.5 added. A21 settled as Python 3.12+. **The SDD is now authoritative over this plan.** |

---

## Anti-patterns to watch for during execution

From the SDD's own decision log — these are the mistakes the design was *specifically written
to prevent*, which makes them the ones most likely to creep back in:

1. **Collapsing `Tri` into `bool`.** Any `Optional[bool]`, `if not satisfied`, `if tri:`,
   or `bool(tri)` reintroduces D8's bug. (§9.1)
2. **Letting freshness touch `status`.** Staleness affects only `readiness_confidence`,
   `recommended_now`, and refresher generation. (D1, D8)
3. **Treating `unlock: available` as satisfied.** It means purchasable, not owned. (A5)
4. **Deriving price confidence from `fetched_at`.** A fresh fetch of a stale trade is stale.
   (D10)
5. **Treating "no `ObservedItem` row" as "doesn't own it."** Without a `ContainerScan` it
   means "never looked." (§6.5)
6. **Summing roadmap weights instead of blending them.** Convex combination — never max,
   never sum. (D3)
7. **Letting refresher group size drive rank.** Max member urgency + capped breadth bonus.
   (D9)
8. **Giving a refresher zero hours.** `effort_decay = 1.0` makes it maximally attractive and
   breaks G10. (A8)
9. **Hand-authoring reason prose.** Reasons are read off log-space contributions or they
   drift from the ranking. (§9.5)
10. **Putting game content in code.** New quests, items, capabilities, roadmaps, milestones
    and profiles must never require a code change. New requirement *types* and practice
    *domains* may. (§10.7)
11. **Building for Plugin Hub.** Explicitly out of scope; must not touch the critical path.
    (D5, §13)
12. **Ranking "further and slower" as better.** The v0.1 formula's defect; Step 6 carries a
    regression test. (§9.4)

---

## Open items for the user

1. ~~Ratify the SDD amendments.~~ **Done** — `docs/SDD.md` is v0.5; all 21 are closed and
   traced in its §20. One judgment call inside that worth knowing you can reverse: **A21 was
   settled as `Python 3.12+`** rather than installing 3.13, since nothing in the design needs
   3.13. Flip §14.1 and Step 1 if you'd rather pin 3.13.
2. **Step 8.5 needs you.** Capturing a real RuneLite snapshot requires a local RuneLite
   install and a human to launch the game. An agent writes the spike; it cannot run it.
3. **Step 12 needs Gradle and RuneLite.** Neither `gradle` nor a RuneLite install is present.
   Either install Gradle or commit a `gradle-wrapper.jar` + `gradle-wrapper.properties` by
   hand. Side-load verification is a human gate.
4. **Step 13 needs you.** The tuning disagreement review (§16.3 step 5) is explicitly a human
   judgment. An agent runs the search and produces the report; it should not accept the
   result unsupervised.
5. **No git remote.** This plan assumes local branches. If you want PRs and CI, install `gh`
   and create a remote — the per-unit workflow gains `gh pr create` and nothing else changes.
