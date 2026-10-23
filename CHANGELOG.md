# Changelog

All notable changes to this project are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow the release-counting scheme of the [maintaining guide](docs/guides/maintaining.md): the major counts releases to `main`, so it does not signal breaking changes as in [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Layered review upgrade note: task reviews (`task review`) recorded before this change carry no tree fingerprint and no longer count as accepted, so a run in flight that needs an independent review must have its tasks reviewed again. `review_stale` and the `--compare` record are judged on the content tree (a commit alone changes nothing); a reviewer change passes the finish gate when no case loses a pass (a tie counts, a rule the owner has yet to confirm); a review prompt over 100,000 characters is refused (`review_diff_too_large`); with `review.depth` off nothing about review is computed or read. Implemented and tested with fake agents.

### Added

- `wev specialists score` keeps each agent run's event stream, redacted and cut at 2,000,000 characters, in `.wev/score-logs/<score id>/<case>-<n>.jsonl`; the unattended run now uses `--output-format stream-json --verbose`. Implemented and tested with a fake CLI. The docs record that the wev hooks fire inside the unattended run, checked by hand on 2026-10-23.
- `wev specialists score` prints one progress line per agent run to stderr (case, pass or fail, seconds), and Ctrl-C in any `wev` command prints a short message and exits 130 instead of a traceback. Implemented and tested.

## [7.0.0] - 2026-10-23

### Added

- Scored cases: `evals/cases/<id>.json` with three first cases, `wev cases list|validate [--at-base]`, `wev specialists score <id>` and `wev specialists scores [<id>]`, and `specialists.score_samples|score_max_runs|score_max_new_lessons|score_timeout_seconds|score_on_finish` (the last scores the specialists that ended a task at `run finish`). A lesson enters as accepted by `score` when no case loses a pass and the total rises; ablation retires one the same way; a person's decision stays final. Model-written lessons come only from failed cases, pass a text filter and are shown inside the untrusted-data fence. Implemented and tested with fake runners and agents; the real `claude -p` path is implemented but untested until the owner runs it, and the owner must confirm on the first real run that the wev hooks fire under `--restricted`. `specialists score` is person-only (asked on Claude Code, denied on the other harnesses). Residual risks are listed in `SECURITY.md` under "Unattended scoring" and "Known limits".
- scored cases and specialists that evolve by score ([#18](https://github.com/wevertonjuscelino/wev-skills/pull/18))

### Fixed

- judge the linux-core dependency check by the installer summary line ([#17](https://github.com/wevertonjuscelino/wev-skills/pull/17))

### Documentation

- add the installation process to the README ([#16](https://github.com/wevertonjuscelino/wev-skills/pull/16))

## [6.0.0] - 2026-10-22

### Added

- Harness adapters for Codex, Gemini CLI and OpenCode: `wev hook pre-tool-use|session-context --harness codex|gemini|opencode`, `wev harness export|install|uninstall --target ...` with a manifest under `$XDG_DATA_HOME/wev-skills/harness/<target>/`. Implemented and tested with fake harness CLIs; not run against the real harnesses yet (e2e part). A policy ask becomes allow plus a warning on these harnesses and a fail-safe ask becomes deny; Codex commands are judged under the session cwd; the OpenCode plugin was tested under node with a fake `wev` and never run inside OpenCode. See SECURITY.md, "Other harnesses".
- Optional intake field `outcome` (`wev intake set ID --field outcome`): what should happen after the goal is reached. It is kept in the brief, in the `run.intake_attached` event and in the plan reminder, where it has the lowest priority so it never pushes out the task lines. A record without an outcome is unchanged; a record that has one cannot be read by earlier versions. Implemented and tested.
- `wev-orchestrate` skill: a deeper-plan step before `plan set`, an optional wider review with at most two agents in `planned` and `gated` flows, primary sources named in the plan task's `objective` so they reach the contract, and asking the user for verification access before falling back to manual evidence. Instructions to the model only (documented only); their effect has not been measured, and the evaluation guide describes how to compare real runs.
- Built-in JEV client (`decision.jev.command` `builtin`): an HTTP client that looks the key up in `TYPESAFE_API_KEY`, the user's wev-skills env file (mode 600) and the macOS keychain, retries only 429 and 529 inside `decision.jev.timeout_seconds`, reads at most 1 MiB of a response, and falls back to the local policy on any failure. Setting `command` keeps the external-program path. Implemented and tested against a local fake server; the live TypeSafe service was not run in this change.
- `wev jev status|ask|batch`; `status` reports `orchestration` (`wev` or `harness`), which the `wev-orchestrate` skill reads first. The Bash hook answers `ask` for `jev ask` and `jev batch`, which send data to the JEV service; `jev status` is not asked. Implemented and tested.
- `wev skills list|check [--daily]|decline|install [--version]|update [SOURCE] [--yes]|rollback|freeze [--off]|activate|deactivate|show` for third-party skills: `rea` (npm `rea-agents`), `agent-skills` and `wev-skills`, with versions kept under `$XDG_DATA_HOME/wev-skills/third-party/`, a health check before the active version switches, a previous version kept for `rollback`, and activation links in `~/.claude/skills` and `~/.agents/skills`. A Claude Code `SessionStart` `startup` hook runs `wev skills check --daily` (10 second budget, silent on failure) and the model asks once before `update`. Downloads are treated as untrusted data (https allow-list, 50 MiB cap, validated tar extraction); the GitHub tarball has no checksum, and the health check catches a broken update, not a malicious one. Status: implemented and tested with a local fake registry, a fake npx and local tarballs; the real registries, downloads and the real rea server are not run in this change (e2e part). The daily check is wired only for Claude Code so far. See SECURITY.md, "Third-party skill updates".
- rea integration: `wev rea serve|status|mode|build-image` starts the rea MCP server for the harness in an isolated mode (a `wev-rea:<version>` Docker image built from `docker/rea/Dockerfile`; working directory read-only, network on, runtime tools unavailable) or a direct mode (`npx` on the host). Registered by the plugin `.mcp.json` (Claude Code), `gemini-extension.json` (Gemini CLI) and `opencode.json` `mcp.rea` (OpenCode; a foreign entry or a symlinked file is refused); Codex is left to `codex mcp add`. `rea mode|build-image` is asked on Claude Code and denied elsewhere, and `~/.config/wev-skills` is a protected path in the Bash guard. Implemented and tested with fake `npx` and `docker` executables (unit tests); the real rea server, the real container build and the real harness loaders are not run in this change (e2e part). The `wev-reverse` skill is documented only. See SECURITY.md, "rea: reverse-engineering server".

- `install.sh`: an interactive installer (`bash install.sh`; flags `--yes`, `--lang`, `--harness`, `--jev`/`--no-jev`, `--rea-mode`, `--source`, `--uninstall`, `--purge`, `--help`). It reads its questions from the terminal, bootstraps the latest release through `wev skills update wev-skills`, stores the JEV key, installs rea and agent-skills, registers the chosen harnesses through the CLI, prints a summary and next steps, can run again to reconfigure and can uninstall. Implemented and tested with fake harness CLIs and a local source (unit tests, offline); the download route, a real `claude plugin install`, the real harnesses, a real JEV probe and the interactive dependency-install path are not run in this change (e2e part); the `curl | bash` line is documented only until the owner publishes it. See the installation guide and SECURITY.md, "Installer".
- User-level configuration tier: `$XDG_CONFIG_HOME/wev-skills/wev.config.json` (else `~/.config/wev-skills/wev.config.json`; a regular file only) is read below the repository's `wev.config.json`, which is deep-merged over it (arrays replace); `--config` still stands alone. The merged object is validated once and the trust rules apply to it; `wev config show` adds `config_sources` and `config_source` can be `<user> + <repo>`; a `language` in the user file counts outside a run. A repository without its own file inherits the user file. Implemented and tested.
- `wev jev key set`: reads the key from stdin and writes `TYPESAFE_API_KEY` into the env file atomically (0600 in a 0700 directory, other lines kept, symlinks refused); prints the path, `key_source`, `usable` and `shadowed_by_env`, never the key. Person-only: asked on Claude Code, denied on the other harnesses. Implemented and tested.

- End-to-end runner (`make e2e`, `scripts/e2e.py`) and scenarios under `tests/e2e/`: it lists each scenario with what it spends, asks for `yes` (or `WEV_E2E_CONFIRM=yes`), installs into an isolated temporary `HOME`, and writes `evals/reports/e2e-<date>.md`. `macos-core` is implemented and tested: it passed 13 of 13 checks on macOS with an isolated HOME (not a clean machine) on 2026-10-22, against the real npm registry and GitHub releases. `linux-core` (blank container from `docker/e2e/Dockerfile`) and `macos-isolated` (rea in its container) are implemented but were skipped because the Docker daemon was not running. The `claude`, `codex`, `gemini`, `opencode`, `jev` and `update-daily` scenarios are implemented but untested: never run against a real harness or a real key, and they spend your account, tokens or a key you type. The first run found three product problems; their fixes are recorded on their own branches. See the installation guide, "End-to-end tests".
- built-in JEV client, no-run Bash guard and YAGNI rule ([#6](https://github.com/wevertonjuscelino/wev-skills/pull/6))
- add ambition practices to intake and wev-orchestrate ([#7](https://github.com/wevertonjuscelino/wev-skills/pull/7))
- deliver the wev guard and skills to codex, gemini cli and opencode ([#9](https://github.com/wevertonjuscelino/wev-skills/pull/9))
- install, check daily, update and roll back third-party skills ([#10](https://github.com/wevertonjuscelino/wev-skills/pull/10))
- integrate the rea reverse-engineering server (Part 5) ([#11](https://github.com/wevertonjuscelino/wev-skills/pull/11))
- interactive installer, user config tier and jev key set (Part 1) ([#12](https://github.com/wevertonjuscelino/wev-skills/pull/12))
- end-to-end tests for the installer, third parties and rea ([#13](https://github.com/wevertonjuscelino/wev-skills/pull/13))

### Changed

- `decision.jev.command` default changed from `jev` to `builtin`; set `"command": "jev"` to keep the external program.
- The built-in JEV client sends a key stored in the env file or the macOS keychain only to the default endpoint (same scheme, host and port as `https://api.typesafe.ai/v1/systemone`). For another non-loopback `JEV_API_URL` only `TYPESAFE_API_KEY` is used; with only a stored key the call fails with `key_not_for_endpoint` before any request, `wev jev status` reports `harness` and `wev config show` warns. Previously any key went to whatever https host `JEV_API_URL` named. Implemented and tested.
- Behavior change (spec decision 14): a default install (provider `local`) now reports orchestration `harness`, so the `wev-orchestrate` skill uses the harness's own flow unless JEV is configured (`decision.provider` set to `jev` and a key available). The Bash guard stays active: without a run, the PreToolUse hook now judges each command under the built-in default policy (execute mode, medium risk) instead of staying silent, and it does not read the repository's configuration. Approvals and loop detection need a run, so they are not in use in harness mode. Implemented and tested.
- The Claude Code hooks trust only a run the per-user registry lists by root, state directory and run id. An open run in the tree that the registry does not list (a `.wev/` shipped inside a repository, a lost entry), or a registry file that cannot be read, makes every Bash command `ask`, except what the built-in default policy denies, which stays `deny`; the plan-brief hooks print nothing for it. Implemented and tested.
- The per-user run registry's directory is a protected path in the Bash hook, with or without a run, matched by path even when it is missing; a leading `~/` in a word is expanded before protected paths are matched. Moving or removing a directory that holds any protected path (`mv` sources, `rm`, `rmdir`, `unlink`, `find -delete`, `rsync --remove-source-files`) now needs approval: `ask` in the hook (`deny` in plan mode), and approval in `wev exec`. The agent's own file tools can still edit the registry. Implemented and tested.
- Behavior change: `mv`, `rm` and `rmdir` of a folder that holds a protected path (for example a folder holding `.git`, or a dotenv file), or of a tree over 20,000 entries that cannot be cleared (for example `mv node_modules x`), now needs approval, in the Bash hook and in `wev exec`. Implemented and tested.
- The protected-path checks also cover a symlinked ancestor (`mv`, `rm` or `unlink` of a symlinked `~/.local` asks), any unambiguous prefix of `mv --target-directory` (`--t`, `--targ`), the `~+` and `~-` tilde forms, and, on macOS and Windows, a protected location spelled in another case (`~/.LOCAL/state/wev-skills`); Linux keeps exact comparison for locations. Extracting an archive or copying into a directory above the registry, or onto a missing one, without naming the registry is not caught; SECURITY.md lists these limits. Implemented and tested.
- `run start` writes the registry entry before it creates the run and fails with `registry_unwritable` (exit 5) when it cannot, instead of starting a run with a warning. Implemented and tested.
- The hooks compare a command's paths and working directory with the registry's roots without case on macOS and Windows when the file system confirms the same place (`os.path.samefile`; a case-sensitive volume keeps `Repo` and `repo` apart), so `rm -rf /USERS/me/repo/src` from another directory is judged by the run of `/Users/me/repo`; Linux keeps exact comparison. The recursive-reader check expands `~+` and `~-` operands, and `grep -r` and `rg` given only their pattern are treated as walking the working directory even when the pattern names an existing file. Implemented and tested.
- Behavior change: engine commands that apply policy (`exec`, `task`, `plan set`, `run resume|report|finish`, `check-command`, `approval request|grant|deny`, `remote`, `specialists`, `agent create|export`, `jev ask|batch`) refuse an open run the per-user registry does not list, or one whose run id differs from its entry, with `unregistered_run` (exit 5), even with `--run`. `run status`, `run brief`, `plan show` and `state show|list` still work and report `registered`. A finished run is refused (`run_finished`) before anything else by every command that changes it or runs something, except `run report`, `run finish`, `guard check` and `task next`. New human-operator command `wev run adopt` shows the run's pinned configuration on single lines without terminal control characters, asks for a typed word at a terminal and registers the run; the Bash hook answers `ask` for it. Implemented and tested.
- An unexpected error anywhere in the PreToolUse hook now answers `ask` instead of printing nothing (the stderr note stays); the plan-brief hooks still fail silent. Implemented and tested.
- add a Claude Code end-to-end suite and per-feature report ([#14](https://github.com/wevertonjuscelino/wev-skills/pull/14))

### Fixed

- The health check of the real rea server could never pass: its `tools/list` answer (207 tools) is one line of about 3.2 MB and the 1 MiB line cap refused it as `bad_jsonrpc`. The cap is now 32 MiB, still bounded, and a longer line fails as `reply_too_large`, naming the limit and the size read. Found by a real end-to-end run against the latest `rea-agents`. Implemented and tested with a fake server.
- The agent-skills tarball was refused (`unsafe_member`) because of its symlink `.opencode/skills -> ../skills/`, which stays inside the archive. A symbolic link is now refused only when its target, read from the link's own directory, is absolute or leaves the single top-level directory; hard links keep the old rule, and the post-extraction check still confines every link to the promoted directory. Found by the same real run. Implemented and tested with local tarballs.

## [5.0.0] - 2026-10-20

### Fixed

- Lesson usage counts only what was shown: every committed start writes one `lessons.shown` record after the commit, naming the agent and the attempt, even when it showed no lesson; a failed write leaves the start standing and is audited (`lessons.shown_failed`). Learning counts only records for the agent that ended the task and, after a reopen, only the last cycle of starts; ids a 3.0.0 run kept on the task count only while no record shows another agent or a new cycle; records 4.0.0 wrote before the commit and without an agent are not counted; a line cut short is skipped; and only runs of this repository are read. Implemented and tested.
- count only committed starts of the ending agent ([#4](https://github.com/wevertonjuscelino/wev-skills/pull/4))

## [4.0.0] - 2026-10-20

### Fixed

- Run state is readable by release 2.0.0 again: `task start` records the lessons a contract shows as a `lessons.shown` event in the run's `events.jsonl` instead of a `lessons_shown` field in `state.json`, and learning counts usage from those events. Runs written by 3.0.0 keep their `lessons_shown` field, which is still read and counted. Implemented and tested.
- A task start reads the specialist's file again under the lock that `specialists accept` and `specialists retire` take, and is refused (`lessons_changed`, exit 5) when the file is gone or its lessons were accepted or retired after the command loaded them (lessons added by `extends` do not count as a change), so a start never records or shows a lesson an operator had already retired. Implemented and tested.
- keep shown lessons out of run state and refuse stale starts ([#2](https://github.com/wevertonjuscelino/wev-skills/pull/2))

## [3.0.0] - 2026-10-20

### Added

- Automatic versioning from git history: `scripts/versioning.py` prints `X.Y.Z` for a ref (`X` counts releases to `main`, `Y` the pull requests merged into `dev` since the last release, `Z` the commits of the pull request in progress), and `--next-release` prints the next release. Implemented and tested against temporary repositories. CI prints the computed version in the job summary of `lint`.
- Release automation: `.github/workflows/release.yml` now runs on every push to `main` and releases only when the pushed commit is the merge of a pull request from `dev`. It computes the version, collects the merged pull requests (`scripts/collect_release_prs.py`), rewrites the version files, the changelog and the generated release-status blocks (`scripts/release_prep.py`), commits as `github-actions[bot]`, tags, publishes a final release, rotates the milestones and fast-forwards `dev`. The scripts are implemented and tested; the workflow is implemented but untested, because it can only run on GitHub.
- `.github/workflows/pr-policy.yml` with the checks `pr-title` (conventional title for the changelog) and `source-branch` (only `dev` may target `main`).
- Specialist lessons are measured and ranked: `task start` records the lessons a contract shows (`lessons_shown`), learning counts the tasks shown each lesson that ended verified or not, a lesson clearly below the agent's own average (shrunk toward it, at least three endings) goes after the others, and in a task contract lessons about a check the task will run come first. Implemented and tested with fake runs; the thresholds are untuned and no effect on task outcomes has been measured.
- `wev specialists accept` and `wev specialists retire`: human-operator commands (terminal and typed word, `ask` in the Bash hook) that decide a proposed lesson. The prompt shows the full lesson, the audit event (with the terminal) is written before the decision, a lesson changed after it was shown is not decided, the user name `engine` is refused, a lesson only the engine accepted or retired before this release is not shown and is proposed again, and the lesson cap drops proposals before decisions. Implemented and tested.
- Run state written by this release carries `lessons_shown` on each task; release 2.0.0 rejects that field, so a run started or resumed here cannot be resumed after going back to 2.0.0. Documented only.

### Changed

- License: wev-skills is relicensed from the MIT License to the PolyForm Noncommercial License 1.0.0, starting with the next release. Use, changes and redistribution for any noncommercial purpose are allowed; commercial use is prohibited. The project is now source-available, not open source in the sense of the Open Source Initiative. Everything published before the change, releases 1.0.0 to 2.0.0 and the commits up to `577a6f6`, remains under the MIT License, and third-party material keeps its own license. `LICENSE`, `NOTICE`, the plugin manifest, `pyproject.toml`, the READMEs, the contributing guides, the third-party record and the `wev-skill-maintenance` skill are updated.
- Releases are numbered by counting: the two published releases are now `v1.0.0` (first published as 0.1.0) and `v2.0.0` (first published as 0.2.0), and all releases are final releases, never pre-releases. The next release is `v3.0.0`. The major number does not signal breaking changes.
- Contributions target `dev`; `dev` is merged into `main` with a merge commit to release. The maintaining and contributing guides, the roadmap and the MVP status describe the new flow; the version sentence of the READMEs, `CLAUDE.md` and the installation guides are marker-driven so the release job can rewrite them.
- `SECURITY.md` no longer lists versions: the latest release receives security fixes.
- `wev specialists learn` only proposes lessons: a new lesson is `proposed` and shown nowhere until an operator accepts it. Lessons stored before this change with `accepted_by: engine` become proposed again and disappear from contracts and exports until accepted.

## [2.0.0] - 2026-10-15

First published as 0.2.0 and renumbered on 2026-10-15 under the release-counting scheme (see [docs/guides/maintaining.md](docs/guides/maintaining.md)). Adds objective intake, project specialists, run-level budgets and coordinated skill maintenance, and hardens private log files and Git command classification. Evidence labels follow the project convention; see [CONTRIBUTING.md](CONTRIBUTING.md). The workflows run on GitHub Actions; read their results for the commit you care about. The verification record is in [docs/mvp-status.md](docs/mvp-status.md). Live Claude Code sessions, real tmux or SSH hosts and model-quality effects of the new features remain unvalidated.

### Added

- Objective intake: `wev intake start|set|next|show|finish` records an interview before a run. Each round asks at most three questions; the engine requires an objective, completion evidence, scope and work kind. `intake.max_rounds` (default 3, 1 to 10) bounds the rounds, after which `next` lists the fields that must be assumed instead of inventing answers. Records are private to the user, written atomically and redacted for known secret patterns. `wev run start --from-intake ID` requires a finished interview, uses its goal as the objective, refuses a different `--objective`, stores the brief in the run state and records a `run.intake_attached` audit event. See [docs/guides/intake.md](docs/guides/intake.md).
- Project specialists: `wev specialists create|list|export|learn` creates specialists from a catalog role in `wev-specialists/` (`agents.project_dir`), discovered by routing and by `wev agent` commands, with at most `specialists.max_per_project` (default 5). Creation preserves the role's tools, permission limits, model policy and checks. `learn` rebuilds up to `specialists.max_lessons` (default 30) lessons from stored engine records, so running it again adds no confirmations. See [docs/guides/specialists.md](docs/guides/specialists.md).
- Run-level budgets: `limits.run_budget_units` (default 400) and `limits.run_max_attempts_total` (default 12) cap the engine units and task starts of a whole run; they are separate from the per-task limits and are not model tokens or currency.
- Skill `wev-skill-maintenance` and its policy and pinned-upstream references (English and Portuguese) for coordinated skill maintenance across repositories, with the third-party record updated.
- GitHub Actions: `tmux` integration tests now run in the main `ci.yml` workflow.

### Changed

- The `agent` spec schema and the Claude Code subagent export carry the project-specialist fields; the `config` schema gains the `intake` and `specialists` sections and `agents.project_dir`, which must be a directory below the repository root and outside `.git`, `.claude` and the state directory.
- Appended log and lock files are created privately and an existing file of ours that is too open is tightened before any content is written, instead of after (`core/fsutil.py`).
- The Git command classifier requires approval for the explicit `--textconv` and `--ext-diff` options on `diff`, `show`, `log`, `blame`, `grep` and `cat-file`. Repository configuration and attributes can still enable helpers for an ordinary `git diff`; this is recorded as a known limit in [SECURITY.md](SECURITY.md) and in the [local security review](docs/security-review-2026-10-13.md).
- The `pre-push` hook unsets Git's repository-local environment variables before it runs `make test`, so the tests' temporary repositories are not redirected into the repository being pushed.
- The README files were rewritten for the public repository, and the statements in `ci.yml` and `SECURITY.md` that no workflow had completed a run were removed in favour of the Actions history.
- The pattern label `openai-style-key` in `scripts/scan_secrets.py` is now `model-api-key`, and provider names were removed from the related code comments; the patterns are unchanged.
- The version is 2.0.0 in `pyproject.toml`, `.claude-plugin/plugin.json` and `src/wev_skills/__init__.py`.

### Fixed

- A hook test measured the worst-case long command line against a 2.0 s wall-clock bound that failed on a shared macOS runner (2.1 s); the bound is now half of the `PreToolUse` hook timeout (10 s).
- Concurrent appends and lock-file creation share one private-open helper, so the permission tightening no longer happens after the write.

## [1.0.0] - 2026-10-13

First published as 0.1.0 and renumbered on 2026-10-15 under the release-counting scheme (see [docs/guides/maintaining.md](docs/guides/maintaining.md)). Initial engine, published on 2026-10-13. Evidence labels follow the project convention; see [CONTRIBUTING.md](CONTRIBUTING.md). Test status is whatever `make test` reports on your machine; the CI workflows exist; their results are in the repository's Actions history, not in this entry. The verification record is in [docs/mvp-status.md](docs/mvp-status.md).

### Added

- Orchestration: `wev run start|status|resume|brief|finish|report`, `wev plan set|show`, `wev task next|start|check|record|review|reopen|tools` and `wev exec`. One active run per repository; commands without `--run` use it, and a run's mode never changes. Answers carry `next_step` and a `next_steps` list.
- Strict `verified`: the working-tree fingerprint is recomputed at `task record`; checks run once as a baseline at `task start` (`harness.baseline_checks`, default on) and a check that already passed with no change does not verify; no-op checks carry no evidence; plan checks may be objects that tie a command to specific criteria; manual evidence must reference an existing file inside the repository or the run's logs; a verified task with no changed files needs `read_only`.
- State: commits conditional on the loaded revision with bounded retry and a lock timeout (`limits.lock_timeout_seconds`); the state directory resolves at the repository root and has its own `.gitignore`.
- Attempts and escalation: every start counts as an attempt; escalation to a higher model tier fires at half the attempts or on a repeated error signature; exhausted tasks become BLOCKED; `wev task reopen` is an operator step.
- Execution guard fed with real progress and budget events, alternating command cycle detection and a polling cap; `wev exec` and `wev task check` refuse while a STOP or ASK_HUMAN verdict stands, and trips stay in the report.
- Agent specs: versioned, schema-validated JSON specs with a registry, a factory with templates and inheritance, ten example agents, and an exporter to Claude Code subagent files. The engine enforces `required_checks`, `budget.max_units`, `max_attempts`, `timeout_seconds`, `permissions.may_mutate`, `modes`, `max_risk`, `may_use_remote` and `permissions.ceiling`; `stop_conditions`, `success_criteria`, `escalation` and `output_format` are carried as instructions only.
- Decisions and model routing: a vendor-neutral decision interface, a local deterministic provider, an optional JEV adapter, and a model router. Classification applies a lexical floor from the objective text in English and Portuguese; an external provider can only raise risk and complexity.
- Tool selection per task (`harness.tool_selection`: `off`, `local`, `provider`), `wev select-tools`, `wev task tools --add`, and a report section with approximate definition-token estimates. The JEV answer format was checked against two real responses on 2026-10-13 with synthetic tasks; the responses are not part of the test suite and nothing is claimed about token savings.
- Configuration: `wev.config.json` at the repository root, pinned in the run state at `run start`. New keys include `harness.planning`, `executor_tier`, `plan_reminder`, `plan_reminder_max_chars`, `tool_profile`, `tool_selection`, `baseline_checks`, `permissions.approval_ttl_seconds`, `permissions.exec_path`, `limits.lock_timeout_seconds`, `agents.default_agent` and `agents.allow_override`.
- Security and governance: refusal of shell syntax, command risk classification, path confinement, plan-mode denial, single-use expiring approvals bound to the exact argv, working directory, run and (for remote) host, `wev approval verify`, untrusted-content fencing, secret redaction of argv as a whole, and an audit log. Operator commands (`approval grant`, `approval deny`, `guard acknowledge`, `task reopen`) need a terminal and a typed confirmation and have no bypass flag.
- Claude Code plugin hooks (`hooks/hooks.json`, `wev hook ...`): `PreToolUse` on Bash answers `deny` or `ask`, never `allow`, and does not consult the approval store; it routes the engine's own sensitive commands to the human and finds the run from the working directory, enclosing directories or a per-user registry. `SessionStart` and `UserPromptSubmit` inject the fenced, sanitized brief. Once a run is known a problem becomes `ask`, not silence. Not exercised in a real Claude Code session.
- `wev claude-md init|update|check|show` with the skill `wev-claude-md`.
- Remote module: an SSH transport and tmux controller restricted to an inventory of aliases with strict host-key checking, tested against a simulated host. Mode and risk come from the active run; status needs matching ownership before trusting an exit file. Not verified against a real host.
- Context manager (`wev context compact|recall`), used by the evaluation harness, and a scripted evaluation harness (`wev eval list|run|validate`) that runs without a model provider.
- A JSON command-line interface, `wev`, and bilingual messages (`en` and `pt-BR`) through an i18n layer.
- Skills: `wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` and `wev-readme`.
- ADR 0006 (guardrail, not boundary) and a rewritten security policy that states what the engine does not defend against.
- Public-repository conventions: git hooks in `.githooks/` enabled with `make hooks` (`commit-msg`, `pre-commit`, `pre-push`), `scripts/scan_secrets.py --staged`, `CODEOWNERS`, Dependabot for GitHub Actions, `.gitattributes`, `.editorconfig`, the maintaining guide, and a repository-hygiene test that fails on home-directory paths, personal strings and non-placeholder email addresses.
- Project files: MIT license, NOTICE, contribution guide, security policy, code of conduct, issue and pull request templates, third-party record, and GitHub Actions workflows (test matrix, lint, skills validation, credential-pattern scan, and a manual local tmux check).

### Changed

- The minimum Python is 3.14 (`requires-python = ">=3.14"`). `bin/wev` refuses older interpreters: hook subcommands exit 0 with one line on stderr saying nothing was checked, other commands print a message and exit 1. The engine uses `StrEnum`, `type` aliases and generic function syntax. Python 3.10 to 3.13 are no longer supported or tested. See the addendum to [ADR 0001](docs/architecture/decisions/0001-python-stdlib-engine.md).
- The CI workflows pin their actions to full commit SHAs, set `persist-credentials: false` on checkout and a timeout on every job, and run on Python 3.14 only (Ubuntu and macOS).
- Denial is final for the same words in the same order within a run: the working directory, stated risk, reason, quoting, whitespace and token grouping no longer produce a fresh request, and a remote denial is per host. The comparison is on words and does not resolve paths. Only `wev approval request --reopen-denied` replaces a denial; the grant is unchanged.
- The Bash hook also asks for `approval request` (with or without `--reopen-denied`) while a run is active, and recognizes the engine's sensitive commands by words directly, behind a known wrapper, in an inline `sh -c`, `bash -c` or `zsh -c`, or as arguments handed to another program. It cannot see inside a script file or a program (for example a script that types into a pseudo-terminal).
- The hook also asks for `rm` with abbreviated long options, `git rm -r`/`-f`, `git clean` that is not a dry run, `rsync --delete*` and `--remove-source-files`, and for a recursive reader given a directory that contains a protected path (a heuristic, at most 20,000 entries). It matches a path that is a parent of a registered run root and asks for a `$` expansion when no run is found but one is registered.
- Redaction (best effort) of the whole argv now also applies on refused paths, and any audit event that stores a list under `argv` is masked as one command line; `tests/integration/test_refused_redaction.py` checks seven event types for a canary.
- Documents no longer say that the requester cannot grant its own request; a request records a self-declared `requested_by`, a decision records the operating-system user, terminal and time, and nothing compares them.
- `wev exec` in an execute run acts for a running task: `--task` must name a running task, without it the only running task is used (`task_implied`, `task_note`), and with none or several running only read-only commands are accepted.
- An agent with `may_mutate: false` may run read-only commands, the task's declared checks and the checks discovered at `run start` through `wev exec`, by exact argv; everything else is refused with `agent_read_only`.
- `wev plan set` refuses to change the criteria, checks, files, risk or `read_only` flag of a started task without `--amend --reason`; amendments are recorded (`plan.amended`), reset that task's verification and are listed in the report under "Plan amendments". It also prints `warnings` for a check that will need approval or be refused, and for ignored paths.
- The tree fingerprint covers the commit, status, staged and unstaged diffs and untracked files git does not ignore; ignored files are outside it by design.
- `wev run report` and `wev run finish` compare the tree with the one at the latest `verified` record and report "verified, then changed" and status `incomplete` until `wev task check` passes again.
- An exhausted task cannot be recorded `not_executed` and its `next_step` asks for `wev task reopen`; read-only `wev exec` commands do not count toward the no-progress window; `next_step` can be an instruction (pending approval, denied gate, plan ready for human review, a check on an unchanged tree); a stale approval no longer blocks `next_step` and is listed under `stale_approvals`.
- Manual evidence must reference an existing file under the run's log directory, its evidence directory or a file the task lists in the plan; `wev agent create --out` refuses `wev.config.json` and any existing file that is not an agent spec.
- Documentation: the Python requirement states that the stock macOS `/usr/bin/python3` is 3.9, unsupported, and that the hooks exit quietly under it; test and file counts were removed from the status documents and verification results live in one section of `docs/mvp-status.md`.
- With the plugin, Claude Code's permission prompt is reached for command lines the hook can read; a script the hook cannot see into, or a pseudo-terminal driven by one, is not stopped.
- Agent permission inheritance: a child overrides permissions freely unless an ancestor sets `permissions.ceiling: true`.
- `limits.task_timeout_seconds` defaults to 3600.
- A pending approval's `next_step`, and the refusals of the operator commands, tell the caller to stop and ask the human operator; they no longer print a command line an agent could run to approve itself.
- A remote start that needs approval files the request and returns its id.
- The read-only command list covers common diagnostics (`uptime`, `df`, `ps`, `journalctl`, `kubectl get` and others) and refuses their writing or executing options.
- The hooks no longer fail open once a run is known (see ADR 0002).

### Removed

- Reusable approvals (`--reusable`) and the operator bypass flag; older state files do not load.

### Fixed

- Agent routing sent every task without a matching word to `frontend-engineer`.
- The guard's own `task_timeout_seconds` default was 600 while the configuration default is 3600; both now use `config.DEFAULT_TASK_TIMEOUT_SECONDS`. The committed scripted evaluation baseline was regenerated for it.
- `wev config show` and `wev config validate` now resolve configuration like every other command (`--config`, else `<repository root>/wev.config.json`, else defaults), print the source, show a run's pinned configuration while one is active, and warn when `decision.provider` is `jev` and the program does not resolve.
- The `language` configuration key is now read: `--lang`, `WEV_LANG`, a `language` set in a config file (pinned by the run), `LANG`, then English.
- `wev agent export --out .claude/agents` is allowed, and only that path under `.claude`: `<id>.md` files, no symlinks, overwriting only generated files.
- When the JEV program is not found, the recorded fallback reason says it was not found on the allowed path and names the two fixes (`decision.jev.command` as an absolute path, or `permissions.exec_path`); an absolute path must be a regular executable file.
- `wev agent export` named `agent-specs/examples/<id>.json` as the source of every agent; `wev agent list --dir` failed on a JSON file that is not a spec; remote alias errors showed the alias inside literal quotes.

[Unreleased]: https://github.com/wevertonjuscelino/wev-skills/compare/v7.0.0...HEAD
[7.0.0]: https://github.com/wevertonjuscelino/wev-skills/compare/v6.0.0...v7.0.0
[6.0.0]: https://github.com/wevertonjuscelino/wev-skills/compare/v5.0.0...v6.0.0
[5.0.0]: https://github.com/wevertonjuscelino/wev-skills/compare/v4.0.0...v5.0.0
[4.0.0]: https://github.com/wevertonjuscelino/wev-skills/compare/v3.0.0...v4.0.0
[3.0.0]: https://github.com/wevertonjuscelino/wev-skills/compare/v2.0.0...v3.0.0
[2.0.0]: https://github.com/wevertonjuscelino/wev-skills/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/wevertonjuscelino/wev-skills/releases/tag/v1.0.0
