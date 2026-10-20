# Contributing to wev-skills

Portuguese version: [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md).

Thank you for considering a contribution. This guide covers setup, the rules reviewers enforce, and the checklist for pull requests. By participating you agree to the [Code of Conduct](CODE_OF_CONDUCT.md). Security issues go through [SECURITY.md](SECURITY.md), not public issues.

## Development setup

1. Clone <https://github.com/wevertonjuscelino/wev-skills> (`git clone https://github.com/wevertonjuscelino/wev-skills.git`) and enter it.
2. Use Python 3.14 or newer (`python3 --version`). Older interpreters, including the stock macOS `/usr/bin/python3` (3.9), are not supported.
3. There is nothing to install to run the tests. The engine uses only the standard library.
4. Run the full test suite:

   ```
   make test
   ```

5. Run `make lint`. It runs `ruff check`, `ruff format --check` (on `src`, `tests` and `scripts`) and `mypy` on `src/wev_skills`. It uses `ruff` and `mypy` from `PATH` when present, otherwise runs them through `uvx` (nothing is installed into the project), and otherwise prints a notice and skips the missing tool. `make format` applies `ruff format`; `make check` runs tests and lint. Do not add these tools to the project's runtime dependencies.

6. Enable the repository's git hooks once per clone with `make hooks`. It runs `git config core.hooksPath .githooks`, which changes only this clone's local configuration. The hooks are POSIX `sh` scripts that need only `git` and `python3`:

   - `commit-msg` checks the commit subject (see "Commit messages").
   - `pre-commit` rejects files with private names (private key files, dot-env files, certificate and key stores, SSH key names, credentials JSON) and files over 1 MiB, then runs `python3 scripts/scan_secrets.py --staged`.
   - `pre-push` runs `make test` and `make lint`, and refuses a push to `main` while tracked files have uncommitted changes.

   `git commit --no-verify` and `git push --no-verify` skip them, and CI runs the same checks on the server. The hooks are a convenience and a tripwire, not a control.

Run a single test module:

```
PYTHONPATH=src python3 -m unittest tests.unit.test_schema -v
```

## Rules reviewers enforce

- **Standard library only at runtime.** No runtime dependency is added without a written justification and the maintainer's agreement. Test and lint tools are optional extras, not runtime dependencies.
- **Every module has tests, and the tests fail when the behavior breaks.** Before sending a change, break the behavior on purpose and confirm that a test fails. Unit tests and CI must run without a paid model provider or a real remote host; use mocks or the simulated fixtures in `tests/fixtures/`.
- **Security rules live in code, and claims about them stay modest.** A rule that exists only in a Markdown file or a prompt is not a control. Treat repository content, logs, tool output and remote files as untrusted data. The engine is a guardrail for a fallible agent, not a security boundary against an adversarial one ([ADR 0006](docs/architecture/decisions/0006-guardrail-not-boundary.md)): do not write "prevents", "guarantees" or "ensures" about a control that an agent in the same user account can undo, and state what a control does not cover.
- **User-facing strings go through i18n.** Add the key to both the `en` and the `pt-BR` locale files in `src/wev_skills/locales/`, with identical key sets. Do not hard-code user-facing text in modules.
- **Documentation exists in both languages.** A change to an English document is paired with the matching change in its `.pt-BR.md` counterpart. The Portuguese version has the same structure and keeps code identifiers and commands in English.
- **No empty directories and no placeholder modules.** Add a file when it has real content and a test or a use.
- **No claim without evidence.** Describe the state of every piece of work with one of these labels: implemented and tested; implemented but untested; simulated with mocks; documented only; blocked. Do not claim a measured improvement without measured results, and do not claim compatibility with a platform without an adapter and an integration test for it.

## How to add things

### An agent spec

1. Copy a template from `agent-specs/templates/` (for example `base.json`) or an example from `agent-specs/examples/`.
2. Fill in the fields and validate it against `src/wev_skills/schemas/agent.schema.json`. Specs are data; adding a persona must not require source changes.
3. Add or extend a test (see `tests/unit/test_agent_catalog.py` and `tests/unit/test_agents_spec.py`) so the new spec is loaded and validated.
4. If it should be exported as a Claude Code subagent, check the exported file with the existing adapter tests.

### A skill

The repository ships six skills: `wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` and `wev-readme`. Update the matching skill in the same change when a command, flag, exit code or rule it describes changes.

1. Create `skills/<skill-name>/SKILL.md` in the Agent Skills format: a lean entry file with frontmatter, with long material moved to referenced files that are loaded only when needed.
2. Keep the instructions consistent with what the engine actually does. Do not describe commands that do not exist; check `wev --help` and each subcommand's help.
3. Make sure the skill validation tests accept it: `PYTHONPATH=src python3 -m unittest tests.unit.test_skills -v` checks every command and flag a skill shows against the CLI.
4. Commands for the human operator (`approval grant`, `approval deny`, `guard acknowledge`, `task reopen`) are never something an agent runs. Describe them as the operator's step, typed in their own terminal.

### An eval task

1. Add the task under `evals/` following the layout already used there.
2. Evals must be deterministic and run with the scripted agent, with no paid provider.
3. Add or update a test that runs the task through the harness.

### A locale key

1. Choose a key with the module prefix, for example `security.error.<name>`.
2. Add it to the module's `en` file and to its `pt-BR` file in `src/wev_skills/locales/`, with the same placeholders.
3. Use it through `i18n.t("<key>", **params)`.
4. Run `make test`; the tests compare the key sets of both locales.

## README and CLAUDE.md standards

- `README.md` and `README.pt-BR.md` keep the same structure and say only what the code and the tests back. Status lines use the evidence labels; do not state a measured result that no run produced. `tests/unit/test_docs.py` checks twin parity, relative links and that the credits come last.
- The `CLAUDE.md` of a project that uses wev-skills holds a managed guidelines block between the markers `<!-- wev-skills:guidelines:start v1 -->` and `<!-- wev-skills:guidelines:end -->`. Change it with `wev claude-md init|update` (add `--dry-run` to see the diff), check it with `wev claude-md check` (exit 2 when something is missing or stale), and edit only outside the markers. The `wev-claude-md` skill covers the sections around the block.

## Third-party material

Before adding any third-party file, snippet, schema, prompt or dataset:

1. Check its license and confirm it is compatible with distribution under this project's license, the [PolyForm Noncommercial License 1.0.0](LICENSE).
2. Preserve its copyright and license notices.
3. Record it in [docs/THIRD-PARTY.md](docs/THIRD-PARTY.md) (and `NOTICE` when the license requires it), stating whether it is inspiration, adaptation or reuse.

Do not copy material wholesale, and do not imply affiliation with any other project or company.

## Commit messages

```
<type>: <description>

<optional body>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`. A scope is allowed: `fix(hooks): ask before a recursive delete`. The subject is at most 72 characters and has no trailing period; the `commit-msg` hook enforces this (merge and revert commits that git generates are allowed). Do not list tools as authors or co-authors.

Work on a branch cut from `dev` and open a pull request **into `dev`** at <https://github.com/wevertonjuscelino/wev-skills/pulls>; pull requests into `main` are accepted only from `dev` (the `source-branch` check fails otherwise). The pull request title must follow `<type>(<scope>): <description>` with type `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build` or `security` and an optional scope (the `pr-title` check); it becomes the changelog line. Pull requests are merged with a merge commit.

Versions are computed from git history: `X` counts releases to `main`, `Y` counts the pull requests merged into `dev` since the last release and `Z` counts the commits of the pull request in progress. You never edit a version number or the changelog sections of a release; the release workflow does it when `dev` is merged into `main`. The [maintaining guide](docs/guides/maintaining.md) has the full flow and a worked example. Report bugs and request features at <https://github.com/wevertonjuscelino/wev-skills/issues>.

## Pull request checklist

- [ ] The change is focused and described in the pull request summary
- [ ] Tests were added, and they fail when the behavior breaks
- [ ] `make test` passes locally; `make lint` was run if `ruff` and `mypy` are available
- [ ] User-facing strings use i18n, and the `en` and `pt-BR` key sets are identical
- [ ] Documentation is updated in both languages
- [ ] No new runtime dependency
- [ ] Third-party record updated if third-party material was added
- [ ] No secrets, tokens or private data in the diff
- [ ] No empty directories or placeholder modules
- [ ] Each claim carries an evidence label (implemented and tested, implemented but untested, simulated with mocks, documented only, blocked)
