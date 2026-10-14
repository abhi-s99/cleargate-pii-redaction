# ClearGate developer targets. Works with GNU make on Linux/macOS and on Windows
# (Git Bash sh). Local secrets in .env are exported to every recipe.
-include .env
export

ifeq ($(OS),Windows_NT)
  VENV_BIN := .venv/Scripts
  BOOTSTRAP_PY ?= py -3.13
else
  VENV_BIN := .venv/bin
  BOOTSTRAP_PY ?= python3
endif
PY := $(VENV_BIN)/python

.PHONY: setup keys doctor lint format test test-all smoke eval run ui e2e check clean gate-demo

setup:
	test -x $(PY) || $(BOOTSTRAP_PY) -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"
	$(PY) -m spacy download en_core_web_lg
	$(PY) scripts/genkeys.py .env
	$(PY) -m pre_commit install

keys:
	$(PY) scripts/genkeys.py .env

doctor:
	$(PY) scripts/doctor.py

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy

format:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

test:
	$(PY) -m pytest -m "not samples and not slow"

test-all:
	$(PY) -m pytest

smoke:
	$(PY) scripts/smoke.py

eval:
	$(PY) -m eval.run_eval

ui:
	cd cleargate-ui && npm ci && npm run build

run:
	test -f cleargate-ui/dist/index.html || $(MAKE) ui
	$(PY) -m cleargate.cli serve

e2e:
	$(PY) -m pytest -m e2e tests/e2e -q

check: lint test
	$(PY) scripts/check_matrix.py
	$(PY) scripts/check_style.py

gate-demo:
	$(PY) scripts/gate_demo.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis htmlcov .coverage
