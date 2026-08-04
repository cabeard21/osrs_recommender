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
