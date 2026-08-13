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
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin
PYTHONPATH := src

export PYTHONPATH

.DEFAULT_GOAL := help

# ---------------------------------------------------------------- the seven

.PHONY: compliance
compliance: ## BAR-007: PRD ID audit + invariant lints; nonzero on any finding
	@$(PY) scripts/compliance.py

.PHONY: demo
demo: ## Offline end-to-end: ingest -> agenda -> replay interview -> successor query
	@$(PY) -m baraza.cli demo --offline

.PHONY: demo-agenda
demo-agenda: ## Cold ingest -> disputed ledger + interview agenda, unattended
	@$(PY) -m baraza.cli demo-agenda --offline

.PHONY: demo-interview
demo-interview: ## Interview loop. Add REPLAY=1 to feed canned answers on a timer
	@$(PY) -m baraza.cli demo-interview $(if $(REPLAY),--replay,) $(if $(PERSONA),--persona $(PERSONA),)

.PHONY: verify-manifest
verify-manifest: ## Prints "found N of N planted problems" AND the misses
	@$(PY) scripts/verify_manifest.py

.PHONY: verify-anchors
verify-anchors: ## Resolves every citation anchor against its registered source
	@$(PY) scripts/verify_anchors.py

.PHONY: adaptation-metric
adaptation-metric: ## BAR-330: standalone scorer over fixtures/transcripts/
	@$(PY) scripts/adaptation_metric.py fixtures/transcripts

# ------------------------------------------------------- supporting targets
# Not part of the seven. Listed separately so the contract stays legible.

.PHONY: install
install: ## Create the venv and install the package with dev extras
	@$(PY) -m venv $(VENV)
	@$(BIN)/pip install --quiet --upgrade pip
	@$(BIN)/pip install --quiet -e '.[dev]'
	@echo "installed. activate with: source $(VENV)/bin/activate"

.PHONY: test
test: ## Unit + property tests (no cloud, no emulator)
	@$(BIN)/pytest tests/unit tests/property -q

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
teardown: ## Remove everything bootstrap created. Safe to run repeatedly
	@scripts/teardown.sh

.PHONY: gate
gate: ## The mechanical phase gate: compliance + tests + named ACs
	@$(MAKE) --no-print-directory compliance
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
	@grep -E '^(install|test|test-emulator|test-all|verify-models|corpus|bootstrap|teardown|gate|help):.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
