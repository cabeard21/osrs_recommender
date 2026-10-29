# OSRS Account Companion — developer targets.
#
# Argument passing uses ARGS=, not trailing bare words: GNU make treats trailing
# words as *goals*, so `make test -- tests/x` exits 2. Use:
#     make test ARGS="tests/test_config.py -v"
#
# Parallel steps append to this file; never reorder or reformat existing targets.

ARGS ?=
# Routine CI checks deployment boundaries and a small optimizer regression set.
# Keep this list explicit so new expensive suites do not silently enter this lane.
SMOKE_TESTS := tests/test_ci_workflow.py tests/test_config.py tests/test_app.py \
    tests/test_container_entrypoint.py tests/test_container_smoke.py \
    tests/api/test_auth.py tests/api/test_contract.py tests/api/test_sync.py \
    tests/api/test_gear_optimizations.py::test_real_delegation_numeric_parity_baseline_and_determinism \
    tests/api/test_gear_optimizations.py::test_hypothetical_does_not_mutate_account_and_budget_enforced \
    tests/db/test_migrations.py \
    tests/db/test_m3_migration.py tests/gear/test_optimizer.py \
    tests/gear/test_transitions.py tests/gear/test_transition_cache.py
VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: install venv browsers test test-full test-ci test-smoke test-cov lint format typecheck validate-content migrate run clean

venv: ; @test -d $(VENV) || python3 -m venv $(VENV)

install: venv ; $(PIP) install --upgrade pip -q && $(PIP) install -e ".[dev]"

# `pip install pytest-playwright` installs the *client*, not the browser it drives, so a
# fresh clone runs every UI test in tests/ui/test_pages_browser.py straight into a
# "browser executable doesn't exist" error. Separate from `install` because it downloads
# ~150 MB and only the browser-backed tests need it.
browsers: ; $(PY) -m playwright install chromium

test:              ; $(PY) -m pytest -m "not browser and not llm_live" $(ARGS)
test-full:         ; $(PY) -m pytest -m "not llm_live" $(ARGS)
test-ci: test-smoke
test-smoke:        ; $(PY) -m pytest -m "not browser and not llm_live" $(SMOKE_TESTS) $(ARGS)
# Measure the established supported account, goal, sync, API, persistence and gear boundary.
test-cov:          ; $(PY) -m pytest -m "not llm_live" --cov=tracker.accounts --cov=tracker.quest_cape --cov=tracker.sync --cov=tracker.api --cov=tracker.mcp --cov=tracker.db --cov=tracker.config --cov=tracker.content.requirements --cov=tracker.domain.tri --cov=tracker.gear --cov-report=term-missing --cov-fail-under=80 $(ARGS)
lint:              ; $(PY) -m ruff check . && $(PY) -m ruff format --check .
format:            ; $(PY) -m ruff format .
# `tests` is checked too, deliberately. A Protocol is only verified where an
# implementation is assigned to it, so a cross-unit seam that lives in no production
# module is invisible to `mypy tracker` — see tests/integration/test_evaluator_seam.py.
typecheck:         ; $(PY) -m mypy tracker tests
validate-content:  ; $(PY) -m tracker.content.validate $(ARGS)
migrate:           ; $(PY) -m alembic $(if $(ARGS),$(ARGS),upgrade head)
# One process, one port (§5): UI at /, sync API at /api/sync, health at /healthz.
# The bind address comes from config.yaml and has no default (§11.1) — see docs/DEPLOYMENT.md.
run:               ; $(PY) -m tracker.app

.PHONY: run-mcp validate-quest-cape
run-mcp:           ; $(PY) -m tracker.mcp
validate-quest-cape: ; $(PY) tools/generate_quest_cape.py --check

clean: ; rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
