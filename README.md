# OSRS PvP Progression Tracker

A locally hosted, single-user web app that answers *"what should I work on next to become a
better Wilderness PKer?"* It ingests facts about a character (from a companion RuneLite
plugin, Wise Old Man, and the OSRS Wiki price API), evaluates which PvP **capabilities** those
facts unlock, and ranks **candidate** actions against a weighted **roadmap**.

The design is specified in [`docs/SDD.md`](docs/SDD.md) — that document is authoritative for
every behavioural question. The construction order is
[`plans/osrs-tracker-sdd-implementation.md`](plans/osrs-tracker-sdd-implementation.md); where
the plan and the SDD disagree, the SDD wins.

## Getting started

```bash
make install                 # create .venv and install the package with dev extras
cp config.example.yaml config.yaml
# edit config.yaml: set bind_address and api_token
make lint typecheck test
```

`config.yaml` is gitignored — it holds the bearer token shared with the RuneLite plugin.
`bind_address` has no default and `0.0.0.0` is rejected outright (§11.1).

## Gear progression

`/gear` answers *what should I be wearing, and what do I buy next* (§23). It places the account on
the OSRS Wiki's own progression ladders and, for each slot, names the best rung whose **requirements
it actually meets** — not merely the next rung up, which for a fresh account is often forty levels
and two quests away.

It computes; it does not rank. No candidate, no score and no estimate changes because of it, and the
advisor is handed the same computed setup rather than left to invent one. Three states everywhere:
*held*, *not held*, and *unknown* — and until every container has been scanned, *unknown* is the
honest answer rather than *no*.

## Optional: the two AI features

Both are **off by default**, both need an Anthropic API key, and both are *terminal outputs* —
no ranking, estimate or capability state depends on either, so an install without a key ranks,
syncs and renders identically to one with it (D14). Turning them off again is likewise a no-op.

| Feature | What it answers | Switch |
|---|---|---|
| **Task guidance** (§21) | *"How do I actually do this one task?"* — a button on the Next up page (`/recommendations`) | `integrations.llm.enabled` |
| **The advisor** (§22) | Anything else, at `/advisor`, with your whole account as context — including general OSRS questions | `integrations.llm.enabled` **and** `integrations.llm.advisor.enabled` |

The advisor needs its own switch rather than following the first: a guidance note costs one
model call, while an advisor turn costs one per lookup plus the answer, so enabling *"how do I
do this?"* is not consent to a chat surface. Each has its own daily ceiling for the same reason
(§22.7) — a shared budget would let one conversation silently starve the button.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or set integrations.llm.api_key in config.yaml
```

The advisor reads already-computed state and can look things up — the candidate corpus, a
capability's requirement tree, training methods, quest status, cached item prices, the gear setup
above — but it cannot rank, estimate, write, or fetch anything from the network (D15). Its conversations live
in their own two tables and nothing else reads them.

Both features are honest about what they do not know: an unobserved account type is *unknown*
and never *main*, unobserved coins are *unknown* and never zero, and anything drawn from the
model's own knowledge of the game rather than from your account is flagged as such.
