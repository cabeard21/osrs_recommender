# OSRS PvP Progression Tracker — developer targets.
#
# Argument passing uses ARGS=, not trailing bare words: GNU make treats trailing
# words as *goals*, so `make test -- tests/x` exits 2. Use:
#     make test ARGS="tests/test_config.py -v"
#
# Parallel steps append to this file; never reorder or reformat existing targets.

ARGS ?=
VENV ?= .venv
PY   := $(VENV)/bin/python
PIP  := $(VENV)/bin/pip

.PHONY: install venv browsers test test-ci test-cov lint format typecheck validate-content migrate run clean

venv: ; @test -d $(VENV) || python3 -m venv $(VENV)

install: venv ; $(PIP) install --upgrade pip -q && $(PIP) install -e ".[dev]"

# `pip install pytest-playwright` installs the *client*, not the browser it drives, so a
# fresh clone runs every UI test in tests/ui/test_pages_browser.py straight into a
# "browser executable doesn't exist" error. Separate from `install` because it downloads
# ~150 MB and only the browser-backed tests need it.
browsers: ; $(PY) -m playwright install chromium

test:              ; $(PY) -m pytest $(ARGS)
test-ci:           ; $(PY) -m pytest --ignore=tests/golden --ignore=tests/ui/test_pages_browser.py $(ARGS)
test-cov:          ; $(PY) -m pytest --cov=tracker --cov-report=term-missing --cov-fail-under=80 $(ARGS)
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

clean: ; rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
