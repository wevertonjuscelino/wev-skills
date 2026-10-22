PYTHON ?= python3

# Prefer a tool on PATH; otherwise run it through uvx (cached, nothing is installed into the
# project or the system Python); otherwise lint skips with a clear message.
RUFF  = $(shell if command -v ruff >/dev/null 2>&1; then echo ruff; \
	elif command -v uvx >/dev/null 2>&1; then echo uvx ruff; fi)
MYPY  = $(shell if command -v mypy >/dev/null 2>&1; then echo mypy; \
	elif command -v uvx >/dev/null 2>&1; then echo uvx mypy; fi)

.PHONY: test e2e lint format check hooks

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -t . -v

# End-to-end scenarios for real (network, installer, rea); asks for `yes` first.
# Usage: make e2e E2E=macos-core   (WEV_E2E_CONFIRM=yes answers without a terminal)
e2e:
	PYTHONPATH=src $(PYTHON) scripts/e2e.py $(E2E)

lint:
	@if [ -n "$(RUFF)" ]; then \
		$(RUFF) check src tests scripts && $(RUFF) format --check src tests scripts; \
	else echo "lint: ruff not installed (and uvx not found), skipping ruff check"; fi
	@if [ -n "$(MYPY)" ]; then $(MYPY) src/wev_skills; \
	else echo "lint: mypy not installed (and uvx not found), skipping mypy"; fi

format:
	@if [ -n "$(RUFF)" ]; then $(RUFF) format src tests scripts; \
	else echo "format: ruff not installed (and uvx not found), nothing done"; fi

check: test lint

# Enable the repository's git hooks (.githooks/) for this clone. It changes only this
# repository's local git configuration.
hooks:
	git config core.hooksPath .githooks
	@echo "git hooks enabled: commit-msg, pre-commit, pre-push (see CONTRIBUTING.md)"
