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

.PHONY: install venv test test-cov lint format typecheck validate-content migrate run clean

venv: ; @test -d $(VENV) || python3 -m venv $(VENV)

install: venv ; $(PIP) install --upgrade pip -q && $(PIP) install -e ".[dev]"

test:              ; $(PY) -m pytest $(ARGS)
test-cov:          ; $(PY) -m pytest --cov=tracker --cov-report=term-missing $(ARGS)
lint:              ; $(PY) -m ruff check . && $(PY) -m ruff format --check .
format:            ; $(PY) -m ruff format .
typecheck:         ; $(PY) -m mypy tracker
validate-content:  ; $(PY) -m tracker.content.validate $(ARGS)
migrate:           ; $(PY) -m alembic $(if $(ARGS),$(ARGS),upgrade head)
run:               ; @echo "stub — implemented in step 9"

clean: ; rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage
