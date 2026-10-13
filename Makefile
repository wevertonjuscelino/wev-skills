PYTHON ?= python3

# Prefer a tool on PATH; otherwise run it through uvx (cached, nothing is installed into the
# project or the system Python); otherwise lint skips with a clear message.
RUFF  = $(shell if command -v ruff >/dev/null 2>&1; then echo ruff; \
	elif command -v uvx >/dev/null 2>&1; then echo uvx ruff; fi)
MYPY  = $(shell if command -v mypy >/dev/null 2>&1; then echo mypy; \
	elif command -v uvx >/dev/null 2>&1; then echo uvx mypy; fi)

.PHONY: test lint format check hooks

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -t . -v

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
