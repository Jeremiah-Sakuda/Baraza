# Baraza — make targets.
#
# The seven targets named in AGENTS.md are the contract; a judge should be able
# to clone this repository and run any of them. They are grouped first below.
# Everything after them is supporting scaffolding (install, test, lint, deploy)
# and is not part of that seven.
#
# Targets that are not yet implemented exit 1 with "not implemented" rather than
# exiting 0 with nothing. A green target that did nothing is worse than a red
# one, because only one of those gets noticed.

SHELL := /bin/bash
VENV ?= .venv
BIN := $(VENV)/bin

# Prefer the interpreter `make install` created. Without this, the documented
# `make install && make demo` sequence installs the corpus readers into .venv
# and then runs the demo under the *system* interpreter, which does not have
# them. Observed: `make corpus` printed six SKIPPED round-trip lines and, before
# the accompanying fix, still exited 0. Overridable — `make PY=python3.11 demo`.
PY ?= $(shell [ -x $(BIN)/python ] && echo $(BIN)/python || echo python3)

PYTHONPATH := src

export PYTHONPATH

.DEFAULT_GOAL := help

# ---------------------------------------------------------------- the seven

.PHONY: compliance
compliance: ## BAR-007: PRD ID audit + invariant lints; nonzero on any finding
	@$(PY) scripts/compliance.py

.PHONY: demo
demo: ## Offline end-to-end: ingest -> agenda -> replay session -> dossier query
	@$(PY) -m baraza.cli demo --offline

.PHONY: demo-agenda
demo-agenda: ## Cold ingest -> disputed ledger + interview agenda, unattended
	@$(PY) -m baraza.cli demo-agenda --offline

.PHONY: demo-interview
demo-interview: ## Partner session loop. Add REPLAY=1 to feed canned turns on a timer
	@$(PY) -m baraza.cli demo-interview --offline $(if $(REPLAY),--replay,) $(if $(SCRIPT),--script $(SCRIPT),)

.PHONY: verify-manifest
verify-manifest: ## Prints "found N of N planted problems" AND the misses
	@$(PY) scripts/verify_manifest.py

.PHONY: verify-anchors
verify-anchors: ## Resolves every citation anchor against its registered source
	@$(PY) scripts/verify_anchors.py

.PHONY: adaptation-metric
adaptation-metric: ## The two honest numbers: determinism replay + compliance battery; no application imports
	@$(PY) scripts/adaptation_metric.py

# ------------------------------------------------------- supporting targets
# Not part of the seven. Listed separately so the contract stays legible.

.PHONY: battery-run
battery-run: ## Record raw battery outputs to out/battery_outputs.json for the scorer
	@echo "battery-run: not implemented — owed by the demo-staging workstream." >&2
	@echo "It must run each fixtures/battery/ task per phase and record raw" >&2
	@echo "outputs (schema baraza.battery.outputs.v1) to out/battery_outputs.json." >&2
	@exit 1

.PHONY: install
install: ## Create the venv and install from requirements.lock (ranges if absent)
	@$(PY) -m venv $(VENV)
	@$(BIN)/pip install --quiet --upgrade pip
    # The lock first, then the package itself without its dependency resolution,
    # so a clone in October gets the versions this tree was tested against
    # rather than whatever PyPI has that morning. `make install-latest`
    # deliberately takes the other path.
	@if [ -f requirements.lock ]; then \
		$(BIN)/pip install --quiet -r requirements.lock && \
		$(BIN)/pip install --quiet --no-deps -e . ; \
	else \
		echo "no requirements.lock; resolving from pyproject ranges" && \
		$(BIN)/pip install --quiet -e '.[dev]' ; \
	fi
	@echo "installed. activate with: source $(VENV)/bin/activate"

.PHONY: install-latest
install-latest: ## Resolve from pyproject ranges, ignoring the lock. For refreshing it.
	@$(PY) -m venv $(VENV)
	@$(BIN)/pip install --quiet --upgrade pip
	@$(BIN)/pip install --quiet -e '.[dev]'
	@echo "resolved from ranges. Run 'make gate', then regenerate the lock:"
	@echo "    $(BIN)/pip freeze --exclude-editable"

.PHONY: test
test: ## Unit + property + integration tests (no cloud, no emulator, no credentials)
	@$(BIN)/pytest tests/unit tests/property tests/integration -q

.PHONY: lint
lint: ## ruff, with the rules this project selected for itself
	@$(BIN)/ruff check .

.PHONY: test-emulator
test-emulator: ## Tests requiring the Firestore emulator, incl. the kill-survival rig
	@scripts/with_emulator.sh $(BIN)/pytest tests/emulator -q

.PHONY: test-all
test-all: test test-emulator ## Everything

.PHONY: verify-models
verify-models: ## Resolve every pinned model ID against live Vertex; nonzero if any fails
	@$(PY) scripts/verify_models.py

.PHONY: corpus
corpus: ## Regenerate the synthetic corpus from fixtures/corpus/BIBLE.md
	@$(PY) scripts/generate_corpus.py

.PHONY: bootstrap
bootstrap: ## Provision GCP: APIs, Firestore, service accounts, Jobs, Scheduler
	@scripts/bootstrap_gcp.sh

.PHONY: teardown
teardown: ## Remove everything bootstrap created. Safe to run repeatedly. Needs CONFIRM=--yes-destroy
	@scripts/teardown.sh $(CONFIRM)

.PHONY: gate
gate: ## The mechanical phase gate: compliance + lint + tests + named ACs
	@$(MAKE) --no-print-directory compliance
	@$(MAKE) --no-print-directory lint
	@$(MAKE) --no-print-directory test
	@$(MAKE) --no-print-directory verify-anchors
	@$(MAKE) --no-print-directory verify-manifest
	@echo "gate: green"

.PHONY: help
help: ## Show this help
	@echo "Baraza — the seven contract targets:"
	@grep -E '^(compliance|demo|demo-agenda|demo-interview|verify-manifest|verify-anchors|adaptation-metric):.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "supporting:"
	@grep -E '^(install|install-latest|test|lint|test-emulator|test-all|verify-models|corpus|battery-run|bootstrap|teardown|gate|help):.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
