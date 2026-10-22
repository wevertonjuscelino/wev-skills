# MVP status

Portuguese version: [mvp-status.pt-BR.md](mvp-status.pt-BR.md).

Date of every check below: 2026-10-13. Machine: macOS (Darwin), Python 3.14.7 (see "Verification results"); Claude Code for `claude plugin validate`. Nothing was run on Linux or on Windows.

Repository state: <!-- wev:release-status -->Latest release: [v5.0.0](https://github.com/wevertonjuscelino/wev-skills/releases/tag/v5.0.0), published on 2026-10-20.<!-- /wev:release-status --> Public repository: <https://github.com/wevertonjuscelino/wev-skills>. The first publication (2026-10-13) is v1.0.0, first published as 0.1.0 and renumbered on 2026-10-15. As of this commit: the CI workflows exist; consult the Actions history for results by commit; nothing has been exercised in a live Claude Code session; there has been no real tmux or SSH run; three rounds of independent review were followed by fixes, and the fixes made after the last round have not been independently re-verified; the security position is the one in [SECURITY.md](../SECURITY.md). Tags and GitHub releases are created outside the working tree: the owner retags `v1.0.0` and `v2.0.0`, and later releases come from the release workflow (see "After publishing").

This document is strict. A criterion that depends on something that was not run is marked partial or blocked, with the reason. "Met" means the evidence named in [the specification](spec.md) exists and its recorded command passes; it does not mean the thing has been used in the field. Labels: implemented and tested; implemented but untested; simulated with mocks; documented only; blocked (see the [glossary](glossary.md)).

## Verification results

This section is the only place in this document that holds the result lines of the whole test suite and of the linters.

On 2026-10-13, at the end of the work that prepared the 0.1.0 publication, `make test` and `make lint` were run on Python 3.14.7 (macOS). The blocks below hold, in this order, the result lines of `make test` and of `make lint` (ruff and mypy through `uvx`). They come from the owner's machine, not from CI. An earlier run of the suite on Python 3.10 passed before the minimum Python was raised to 3.14; Python 3.10 is no longer tested.

```text
Ran 2076 tests in 167.282s
OK (skipped=8)
```

```text
All checks passed!
280 files already formatted
Success: no issues found in 146 source files
```

## Follow-up capabilities

The objective interview and project specialists were added after the original MVP verification above. [Objective intake](guides/intake.md) caps each round at three questions and attaches a finished brief to the run. [Project specialists](guides/specialists.md) retain permission ceilings, rebuild up to 30 lessons from engine records for the same repository and warn at 80% of whole-run limits. Command units and task-start attempts are separate budgets; these are not model tokens or currency.

Focused CLI, persistence, learning, routing and budget regression tests cover these additions. Their full-suite result belongs to the later commit and must be read from its CI/check output rather than inferred from the historical counts above. Live model interviews and exported specialists in a live session remain unvalidated. The [local security review](security-review-2026-10-13.md) records the append-permission and explicit Git-helper fixes and their remaining limits.

Harness adapters for Codex, Gemini CLI and OpenCode (`wev harness export|install|uninstall`, `wev hook ... --harness`) were added later. Status: implemented and tested with fake harness CLIs; not run against the real harnesses yet (e2e part). The OpenCode plugin was tested under node with a fake `wev` and never run inside OpenCode. They add no row to the 16 criteria; the limits are in [SECURITY.md](../SECURITY.md#other-harnesses).

## Summary

| # | Criterion | Status |
|---|---|---|
| 1 | The entry skill exists with valid frontmatter | Met |
| 2 | Local installation is documented and tested | Partial |
| 3 | The basic orchestration flow runs end to end | Met |
| 4 | At least two agents are customizable by configuration | Met |
| 5 | Routing has a documented interface and a working implementation | Met |
| 6 | Agent creation and validation have tests | Met |
| 7 | Plan and state persist and can be resumed | Met |
| 8 | Loop protection has deterministic tests | Met |
| 9 | Managed context has a testable compaction strategy | Met |
| 10 | Permission controls are verified by tests | Partial |
| 11 | SSH and tmux integration is isolated and tested with mocks | Met (simulated with mocks; real tmux not run) |
| 12 | Documentation exists in Portuguese and English | Met |
| 13 | CI workflows are configured | Partial |
| 14 | Test commands that were run have recorded results | Met |
| 15 | No secrets, no known broken references, no unsupported compatibility claims | Partial |
| 16 | The project is published as a pre-release and its status is recorded | Partial |

Criterion 10 is Partial because the project's security position (see [ADR 0006](architecture/decisions/0006-guardrail-not-boundary.md) and [SECURITY.md](../SECURITY.md)) is that the engine is a guardrail and a recorder, not a boundary, and because the fixes made after the last of three independent review rounds have not been independently re-verified.

## The 16 criteria

In the commands below, `PYTHONPATH=src` is set and the working directory is the repository root. "Result" is the last summary line printed.

### 1. The entry skill exists with valid frontmatter: Met

- Command: `python3 -m unittest tests.unit.test_skills`. Result: `OK`. It checks frontmatter, body length, Portuguese handling, relative links, that every command and flag shown in a skill exists in the CLI, manifests and example files.
- Command: `claude plugin validate .`. Result: `Validation passed with warnings`; one warning, "CLAUDE.md at the plugin root is not loaded as project context".
- Remains: no skill has been loaded by a live Claude Code session. The warning is about the project file at the repository root, not about a skill.

### 2. Local installation is documented and tested: Partial

- Evidence: [installation guide](guides/installation.md). Run: `bin/wev version` printed `{"version": "0.1.0"}`; `claude plugin validate .` (criterion 1).
- Not run: `git clone` of the published repository, `claude --plugin-dir` (it starts a session), `claude plugin marketplace add` (with the local path and with `wevertonjuscelino/wev-skills`), `claude plugin install`, `update`, `uninstall` (they change the machine's Claude Code configuration), and `pip install`. Those steps are documented only.
- Remains: load the plugin in a live session; run the marketplace install on a scratch profile; decide whether to test `pip install`.

### 3. The basic orchestration flow runs end to end: Met

- Command: `python3 -m unittest tests.integration.test_cli_flow`. Result: `OK`. It drives the real CLI from request to report, including operator steps typed on a pseudo-terminal, strict verification, baseline detection, config pinning and gated runs.
- Remains: no model took part. How well a model follows the `wev-orchestrate` skill is unobserved.

### 4. At least two agents are customizable by configuration: Met

- Command: `python3 -m unittest tests.unit.test_agent_catalog tests.unit.test_agents_spec tests.unit.test_adapter_claude_subagent`. Result: `OK`. The ten example specs load, validate and export.
- Check: `bin/wev agent export` into a temporary directory produced files identical to `agents/` in the repository.
- Remains: the exported subagent files were not loaded by a live Claude Code session.

### 5. Routing has a documented interface and a working implementation: Met

- Command: `python3 -m unittest tests.unit.test_models_router tests.unit.test_decisions_local tests.unit.test_decisions_jev tests.unit.test_decisions_factory tests.unit.test_routing_catalog`. Result: `OK`. Interface: architecture 4.2 and 4.4.
- The built-in JEV HTTP client (default, `decision.jev.command` is `builtin`) and `wev jev status|ask|batch`: implemented and tested against a local fake server. The live TypeSafe service was not run in this change.
- Remains: the JEV adapter is tested with a fake client and with the recorded answer format; JEV was called three times for real with synthetic inputs (one classification, two tool selections, 2026-10-13) and the tool-selection answers were not saved as fixtures. Routing and tool selection are heuristics whose usefulness is unmeasured.

### 6. Agent creation and validation have tests: Met

- Command: `python3 -m unittest tests.unit.test_agents_factory tests.unit.test_agents_registry tests.unit.test_commands_agent`. Result: `OK`.
- Remains: nothing for this criterion.

### 7. Plan and state persist and can be resumed: Met

- Command: `python3 -m unittest tests.unit.test_state_store tests.unit.test_state_resume tests.unit.test_state_model`. Result: `OK`. Covers conditional commits on the loaded revision, the lock timeout, the optional `remote_runs` field and the refusal of older state files.
- Remains: resuming with a different version of the engine than the one that wrote the state has not been tested.

### 8. Loop protection has deterministic tests: Met

- Command: `python3 -m unittest tests.unit.test_guard_execution tests.unit.test_guard_reset`. Result: `OK`.
- Remains: the effect of the guard on a real agent is unobserved.

### 9. Managed context has a testable compaction strategy: Met

- Command: `python3 -m unittest tests.unit.test_context_manager`. Result: `OK`.
- Remains: the context manager serves `wev context compact` and the evaluation harness; the orchestration flow does not use it, and it cannot control Claude Code's own context window. Its effect on a model is unmeasured.

### 10. Permission controls are verified by tests: Partial

- Command: `python3 -m unittest discover -s tests/security -t .`. Result: `OK`. `python3 -m unittest tests.unit.test_hooks`: `OK`.
- Remains: three rounds of independent review on 2026-10-13, before publication, found the approval and hook controls bypassable by the constrained agent; each round was followed by fixes, which are implemented and tested, but the fixes made after the last round have not been independently re-verified (no record of a re-review exists). The engine is a guardrail for a fallible agent, not a security boundary against an adversarial agent in the same user account. Known open limits: the agent's own file tools can rewrite state, approvals, the audit log and the registry; a pseudo-terminal can type the confirmation word, and a script that drives one is not seen by the hook; `python3 script.py`, `make`, `mv`, `sed -i`, redirections and unknown absolute-path programs are not gated in execute mode; child processes inherit the caller's environment. See [ADR 0006](architecture/decisions/0006-guardrail-not-boundary.md).

### 11. SSH and tmux integration is isolated and tested with mocks: Met, simulated with mocks

- Command: `python3 -m unittest tests.unit.test_remote_inventory tests.unit.test_remote_transport tests.unit.test_remote_tmux tests.unit.test_remote_tmux_status tests.unit.test_commands_remote tests.security.test_remote_safety tests.unit.test_remote_run_state tests.unit.test_remote_cli_run`. Result: `OK`.
- Command: `python3 -m unittest tests.integration.test_tmux_local`. Result: `OK`, with every test skipped: tmux is not installed on this machine, so every real-tmux test was skipped.
- Remains: the module has never run against a real tmux or a real server.

### 12. Documentation exists in Portuguese and English: Met

- Command: `python3 -m unittest tests.unit.test_docs`. Result: `OK`. It checks that documents have twins with the same structure, that relative links resolve and related structure rules.
- Remains: the test checks structure, not translation quality. The Portuguese has not been reviewed by a second person.

### 13. CI workflows are configured: Partial

- Evidence: `.github/workflows/ci.yml` and `.github/workflows/remote-integration.yml` (manual, local tmux) exist.
- Remains: verify the Actions results for the commit being released. Actions are pinned to commit SHAs (`actions/checkout` v7.0.1 and `actions/setup-python` v7.0.0, looked up on 2026-10-13). The matrix is Ubuntu and macOS on Python 3.14 only.

### 14. Test commands that were run have recorded results: Met

- This document. See [Commands executed](#commands-executed).

### 15. No secrets, no known broken references, no unsupported compatibility claims: Partial

- Secrets: `python3 scripts/scan_secrets.py`. Result: `scan_secrets: no credential patterns found.` `tests/unit/test_repo_hygiene.py` also fails on home-directory paths, personal strings and non-placeholder email addresses in any file git would track. The script is a narrow tripwire, skips `tests/`, and would not detect a credential without a recognizable shape. Its own unit test prints a line about `b.txt` from a fabricated fixture; that is not a finding.
- Broken references: the `tests.unit.test_docs` link check passes. It checks files, not heading anchors, and not external URLs.
- Compatibility claims: the documents claim compatibility with Claude Code only as far as `claude plugin validate` accepts the manifests, and claim nothing for other environments. No independent review of the claims exists.
- Remains: independent review of the claims; a scan of the tracked files after the first commit (`python3 scripts/scan_secrets.py` reads the file system until then).

### 16. The project is published as a pre-release and its status is recorded: Partial

- Published: the owner authorized publication on 2026-10-13 as 0.1.0 (renumbered v1.0.0 on 2026-10-15) at <https://github.com/wevertonjuscelino/wev-skills> (public). The working tree was prepared for it: repository URL in the manifests and documents, git hooks, CODEOWNERS, Dependabot, pinned actions, a hygiene test, a maintaining guide.
- Not established: nothing was exercised in a live Claude Code session; no real tmux or SSH run; the fixes after the last review round have not been independently re-verified. See [After publishing](#after-publishing).
- Versioning and release automation, checked on 2026-10-15 (macOS, Python 3.14): `scripts/versioning.py`, `scripts/release_prep.py` and `scripts/collect_release_prs.py` are implemented and tested (`tests.unit.test_versioning` and `tests.unit.test_release_prep`, against temporary git repositories and copies of the real target files); `make test` (2187 tests, OK), `make lint`, `bin/wev readme check`, `bin/wev claude-md check` and `python3 scripts/scan_secrets.py` passed with these changes; a dry run in a temporary copy printed `2.2.2` for a dev with two merged pull requests of two commits each, `3.0.0` as the next release, and `release_prep.py --version 3.0.0` rewrote 13 files. The workflows `release.yml` (push to `main`) and `pr-policy.yml` are implemented but untested: they can only run on GitHub, and no run exists yet. Network calls (`gh`) and the pushes with the job token were not exercised.
- Not done in the working tree: the commit, the push, the tag `v1.0.0`, the GitHub release and every repository setting. The owner does those.

## Commands executed

All on 2026-10-13, after the last code change.

| Command | Result |
|---|---|
| `make test` | see "Verification results" |
| `make lint` (ruff and mypy through `uvx`) | see "Verification results" |
| `python3 scripts/scan_secrets.py` | `scan_secrets: no credential patterns found.` |
| `bin/wev readme check` | `"ok": true`, no findings, no warnings |
| `bin/wev claude-md check` | `"ok": true`, exit 0 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_docs tests.unit.test_skills tests.unit.test_repo_hygiene` | `Ran 42 tests`, `OK` |
| `claude plugin validate .` | `Validation passed with warnings` (1 warning, see criterion 1) |
| the per-criterion unittest commands above | all `OK` |
| `bin/wev --help` and `--help` of every group and subcommand | printed; used to write the guides and skills |
| Hand-run command sequences in a temporary git repository outside this one (run, plan, task, exec, report, agent, config, claude-md, hooks) | outputs are quoted in the guides and skills; none contacted a network, a model, SSH or the real `jev` |

The skipped tests are those of `tests/integration/test_tmux_local.py`.

Not run on purpose: `wev approval grant`, `wev approval deny`, `wev guard acknowledge` and `wev task reopen` (they are the human operator's steps), the real `jev`, any SSH (with one unintended exception: while documenting, one `wev remote start` against the example alias `staging-1` started the system `ssh` client, which failed to resolve the alias with `remote_connection_failed`; no connection was made), `claude -p`, `claude --plugin-dir`, and the marketplace and install commands.

## Not verified

- Nothing was run in a live Claude Code session: skills, exported subagents and hooks have not been seen loading, triggering or being followed.
- GitHub Actions results must be checked for the commit being released.
- No real tmux and no real SSH host: the remote module is simulated with mocks only.
- Nothing was run on Linux, and only Python 3.14.7 was used. Python 3.10 to 3.13 are not supported and not tested; the one earlier run on 3.10 predates the change of minimum.
- JEV is verified by three real calls with synthetic inputs only: one classification response (recorded as a fixture) and two tool-selection responses (not saved). This establishes the answer format for this use and nothing about token savings or task success.
- Three rounds of independent review were followed by fixes. The fixes made after the last round have not been independently re-verified; no record of a re-verification exists.
- `pip install` of the package and the `wev` console script, `git clone` of the published repository, and `claude --plugin-dir`, marketplace add (local path and GitHub), install, update and uninstall.
- The git hooks in `.githooks/` were run by their tests in temporary repositories (with `make` replaced by a fake program for `pre-push`); `make hooks` was not run in this repository.
- The effect of any research-derived mechanism (conditional planning, tool profiles, tool selection, plan reminder, staged compaction, guards) on a real model, and any measured improvement. The evaluation harness uses a scripted agent and simulated units and says nothing about any model.
- Review of the Portuguese text by a second reader.
- Resuming a run with a different engine version.

## After publishing

The repository is published; none of these is done. The repository settings cannot be set from the working tree, so the items about settings are documented intent for the owner, not things already enabled.

- [ ] Check the CI run for the release commit on GitHub (`ci.yml`: test on Ubuntu and macOS with Python 3.14, lint, skills, git hooks and documents, secrets scan) and fix what it reports.
- [x] Applied on 2026-10-15 through the GitHub API (`gh repo edit`, `gh api`), as listed in the "Repository settings" section of the [maintaining guide](guides/maintaining.md): description and topics, features (Issues and Discussions on, Wiki and Projects off), merge settings, private vulnerability reporting, secret scanning and push protection, Dependabot alerts and security updates, the branch ruleset `main protection` and the tag ruleset `release tags`, the labels of `.github/labels.json` and the milestones `0.2.x` and `0.3.0` (to be renamed to `v3.0.0` and later). Evidence: the API answers at the time; check the repository settings page for the current state.
- [ ] To do (owner's account settings, not the repository): "keep my email address private" and "block command line pushes that expose my email".
- [ ] Try the plugin in a live Claude Code session: load it with `--plugin-dir`, run `wev-orchestrate` on a small task, check that the hooks fire and that the subagents load. Then try the published route (`claude plugin marketplace add wevertonjuscelino/wev-skills`). Record the result.
- [ ] Run the manual `remote-integration.yml` workflow (real tmux, locally on the runner) and `tests/integration/test_tmux_local.py` on a machine with tmux.
- [ ] Run `make hooks` in the clone, and confirm that commits carry the author name Weverton Juscelino, a GitHub no-reply email address, and no co-author trailers.
- [ ] To do (owner): retag the two published releases under the release-counting scheme (`v1.0.0` on `4ab225b`, `v2.0.0` on `e6035b7`) and recreate their GitHub releases as final releases; apply the `main` and `dev` rulesets and the merge settings of the maintaining guide; create `dev` from `main`; rename the old milestones. The new release workflow (`.github/workflows/release.yml`) and the PR policy workflow are implemented but untested: they can only run on GitHub. The first dev-to-main merge after that is the first real run.
- [ ] Have the fixes made after the last review round independently re-verified.
- [ ] Decide on the `CLAUDE.md` plugin-root warning (move the file or accept it).
- [ ] Have a second person read the Portuguese documents and the claims about compatibility and status.
