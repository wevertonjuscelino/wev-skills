# Roadmap

Portuguese version: [ROADMAP.pt-BR.md](ROADMAP.pt-BR.md).

This is the direction of wev-skills, not a promise. <!-- wev:release-status -->Latest release: [v7.0.0](https://github.com/wevertonjuscelino/wev-skills/releases/tag/v7.0.0), published on 2026-10-23. Open milestone for the next release: [v8.0.0](https://github.com/wevertonjuscelino/wev-skills/milestone/7).<!-- /wev:release-status --> The major number counts releases to `main` (each merged pull request from `dev` into `main` publishes the next major); it does not signal breaking changes as in Semantic Versioning, so read the [changelog](CHANGELOG.md) for what changed. The scheme is in the [maintaining guide](docs/guides/maintaining.md). It promises no dates and no order inside a section. Every item says what is true of it today, using the project's evidence labels: implemented and tested; implemented but untested; simulated with mocks; documented only; blocked. An item without an implementation is "documented only". The sources are the [specification](docs/spec.md), the [MVP status](docs/mvp-status.md), the known limits in [SECURITY.md](SECURITY.md) and the [hypotheses](docs/research/hypotheses.md).

## How to read this

- A section is a direction. Moving an item up or down needs no announcement, and an item can be dropped.
- "Evidence today" is the state of the work now. It is never evidence that the finished work will help: no measured improvement is claimed for any item.
- An item moves to the [changelog](CHANGELOG.md) when it ships, with its label.

## Now: hardening

Work that makes the existing behavior trustworthy and checked. No new capability.

- **Try the plugin in a live Claude Code session**: load it, run `wev-orchestrate` on a small task, see the hooks fire and the subagents load. Evidence today: documented only. `claude plugin validate .` passes with one expected warning; nothing has been seen loading in a live session.
- **Run the remote module against a real tmux and a real SSH host.** Evidence today: simulated with mocks for SSH; the local tmux integration tests run in the main CI workflow, so read the Actions history for their result.
- **Independent re-verification of the fixes made after the last review round.** Evidence today: not done; no record of a re-verification exists.
- **Second reader for the Portuguese documents and for the status and compatibility claims.** Evidence today: not done.
- **Apply the intended GitHub repository settings** (rulesets, private vulnerability reporting, secret scanning, labels) described in the [maintaining guide](docs/guides/maintaining.md). Evidence today: documented only; to apply.
- **Narrow the known limits that a rule can narrow**, for example more of the Git commands that run helpers, listed under "Known limits" in [SECURITY.md](SECURITY.md). Evidence today: implemented and tested for the explicit `--textconv` and `--ext-diff` options; implicit helpers enabled by repository configuration remain an open limit.
- **Decide the `CLAUDE.md` plugin-root warning** of `claude plugin validate` (move the file or accept it). Evidence today: the warning is known and accepted for now.

## Next: 0.3.0

Candidates for the next minor version. Each one needs its own design and tests before it is promised.

- **Hooks for tools other than Bash**, for example checking Edit and Write against a task's declared files. Evidence today: documented only (the specification lists it as out of scope for the MVP). Only Bash passes through the hook now.
- **Evaluation against real models** and a measured comparison between configurations, following [the experiment plan](docs/research/experiments.md). Evidence today: the scripted harness is implemented and tested and says nothing about any model. The mechanisms of hypotheses H1 to H10 are implemented; their effect on a real model is not measured.
- **A recall tool surfaced to the model during a session.** Evidence today: `wev context recall` is implemented and tested as a CLI command; nothing surfaces it to a model.
- **Live validation of objective intake and project specialists** with a real model. Evidence today: implemented and tested with focused unit tests; live interviews and exported specialists in a live session are unvalidated.

## Later

Directions without a plan. They may never ship.

- **Adapters for agent environments other than Claude Code.** Evidence today: documented only. The core does not import an adapter, but only the Claude Code adapter exists, so no other compatibility is claimed.
- **YAML input for agent specs.** Evidence today: documented only; specs are JSON ([ADR 0003](docs/architecture/decisions/0003-json-specs-and-schema-subset.md)).
- **Windows support for the state store.** Evidence today: documented only. The documented platforms are macOS and Linux.
- **Distribution beyond a clone or the Claude Code marketplace route**, such as a package on PyPI. Evidence today: documented only; there is no package and no decision to publish one.

## Not planned

Stated so that nobody waits for them.

- **A security boundary against an adversarial agent in the same user account.** The engine is a guardrail for a fallible agent ([ADR 0006](docs/architecture/decisions/0006-guardrail-not-boundary.md)). Operating-system isolation is the answer to that threat, and it is outside this project.
- **Runtime dependencies in the core.** The engine is standard library only ([ADR 0001](docs/architecture/decisions/0001-python-stdlib-engine.md)); ruff, mypy and uvx stay tooling.
- **Support for Python older than 3.14.**
- **Claims of token savings or quality gains without measurements**, and compatibility claims for a platform without an adapter and an integration test.
- **Granting approvals on behalf of the human operator.** The operator commands stay human-only.

## How the roadmap is tracked

Work is tracked on GitHub with milestones (one per planned version) and the labels in [.github/labels.json](.github/labels.json). An issue is linked to a milestone only when a maintainer accepts it (`status: accepted`). Milestones are named after the release they feed (`v3.0.0` is the next); the older milestones `0.2.x` and `0.3.0` will be renamed to match. This file is the summary; the milestones and issues are the detail, and where they differ, the issue and the changelog are the more current record. To propose a change, open a feature request or start a thread in Discussions (see [SUPPORT.md](SUPPORT.md)).
