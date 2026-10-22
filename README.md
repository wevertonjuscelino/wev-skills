# wev-skills

A source-available orchestration engine for developers who want AI coding agents to plan, execute and report work with recorded verification evidence.

[Português brasileiro](README.pt-BR.md) · [Installation](docs/guides/installation.md) · [Architecture](docs/architecture/architecture.md) · [Examples](examples/README.md)

[![CI](https://github.com/wevertonjuscelino/wev-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/wevertonjuscelino/wev-skills/actions/workflows/ci.yml)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue)](pyproject.toml)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-green)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](CHANGELOG.md)

The standard-library-only Python engine provides the `wev` JSON CLI. A Claude Code plugin connects it to skills, subagents and hooks. Task contracts, resumable state and evidence labels make the work inspectable; the engine enforces the rules that code can check.

## Status

> [!IMPORTANT]
> Version <!-- wev:version -->5.0.0<!-- /wev:version --> is an alpha release. The CLI and plugin format have automated tests; a live Claude Code session, real remote execution and model-quality evaluation remain unvalidated. There is no PyPI package or official marketplace listing. The CI badge links to current workflow results.

| Capability | Evidence | Practical limit |
|---|---|---|
| Plans, task contracts, state, resume and delivery reports | Implemented and tested | Local tests use no model |
| Permissions, single-use approvals and verification gates | Implemented and tested | Heuristics and audit records; no sandbox |
| Agent registry, inheritance and subagent export | Implemented and tested | Exported agents have not been loaded in a live session |
| Objective interview: at most three questions per round | Implemented and tested | Local CLI and stored briefs; model-led interview unvalidated |
| Project specialists, bounded experience and run budgets | Implemented and tested | Engine records only; advisory lessons; command units, not tokens or money |
| Skills, hooks and plugin manifests | Implemented and tested | Format and subprocess tests; live integration untested |
| Optional JEV, SSH/tmux and evaluation adapters | Simulated with mocks | A recorded JEV response and simulated remote hosts |
| Codex, Gemini CLI and OpenCode: package export, install, uninstall, hook codecs | Implemented and tested with fake harness CLIs; not run against the real harnesses yet (e2e part) | A policy ask becomes allow plus a warning there; see [SECURITY.md](SECURITY.md) |
| Other agent environments and Windows support | Documented only / blocked | Future adapters; POSIX file locks today |

Detailed acceptance evidence is in [MVP status](docs/mvp-status.md). The [local security review of 2026-10-13](docs/security-review-2026-10-13.md) records findings and scope; it is an internal review, not a certification.

## Requirements

- **Python 3.14+** on macOS or Linux, and **Git**. The engine has no runtime dependencies.
- **Claude Code** for plugin use. The CLI works independently.
- Optional: `ssh` and `tmux` for remote operations; `ruff` and `mypy`, or `uvx`, for linting.

Check `python3 --version` before using the plugin. Older interpreters are unsupported, and plugin hooks can exit without checking commands when Python is too old. Windows is unsupported.

## Quick start

Clone the public repository and locate its CLI. These clone commands are the reader's installation step and were not executed during this documentation review:

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
cd wev-skills
export WEV_HOME="$PWD"
"$WEV_HOME/bin/wev" --help
```

The following read-only example was executed locally on 2026-10-13. It uses the default local policy, makes no model call and changes no project files:

```text
$ bin/wev classify --objective 'Add a greeting file' --files 1
{
  "complexity": "trivial",
  "risk": "low",
  "uncertainty": 0.0,
  "parallelizable": false,
  "reasons": [
    "Low risk: no risk rule fired.",
    "Trivial: at most one file, no unknowns, a single piece of work."
  ],
  "source": "local-policy"
}
```

For a plugin session, run the following reader's step (live session not validated):

```sh
claude --plugin-dir "$WEV_HOME"
```

The [installation guide](docs/guides/installation.md) covers persistent plugin installation, updates and removal. The [orchestration guide](docs/guides/orchestration.md) walks through starting a run, executing tasks, recording checks and generating a report.

Objective intake is documented in [the interview guide](docs/guides/intake.md). Project roles, evidence-based experience and the 80%/100% command-budget limits are documented in [the specialists guide](docs/guides/specialists.md).

## Features and documentation

| Area | Guide | Skill |
|---|---|---|
| Plan → task → execute → verify → report; resume and execution guards | [Orchestration](docs/guides/orchestration.md) | `wev-orchestrate` |
| JSON agent specs, templates, inheritance and permission ceilings | [Creating agents](docs/guides/creating-agents.md) | `wev-agent-builder` |
| Deterministic evaluation of harness mechanics | [Evaluation](docs/guides/evaluation.md) | `wev-harness-evaluation` |
| Inventory-based SSH and task-owned tmux sessions | [Remote operations](docs/guides/remote-ops.md) | `wev-remote-ops` |
| Managed project guidelines in `CLAUDE.md` | [Guidelines skill](skills/wev-claude-md/SKILL.md) | `wev-claude-md` |
| Bilingual README checks | [README standard](skills/wev-readme/SKILL.md) | `wev-readme` |
| Skills, guard hooks and agents for Codex, Gemini CLI and OpenCode | [Installation: Codex, Gemini CLI and OpenCode](docs/guides/installation.md#codex-gemini-cli-and-opencode) | CLI `wev harness` |
| Reviewed upstream updates and conflict reconciliation | [Maintenance policy](skills/wev-skill-maintenance/references/policy.md) | `wev-skill-maintenance` |
| Install, check daily, update, roll back and freeze third-party skills | [Installation: third-party skills](docs/guides/installation.md#third-party-skills-install-daily-check-update-rollback-freeze) | CLI `wev skills` |

Harnesses: Claude Code uses the plugin; Codex, Gemini CLI and OpenCode get the skills and the guard through `wev harness install --target <name>`.

Configuration, local decisions and the optional third-party JEV provider are documented in [configuration and providers](docs/guides/configuration-and-providers.md). Skills instruct the agent; engine code enforces task transitions and verification rules ([ADR 0002](docs/architecture/decisions/0002-engine-enforces-skills-instruct.md)).

```text
src/wev_skills/   Python engine, CLI and adapters
skills/          Agent instructions
agent-specs/     Source JSON specifications for agents
agents/          Generated Claude Code subagents
hooks/           Plugin integration
tests/          Unit, integration and security tests
docs/           Guides, architecture, evidence and provenance
examples/       Sample configuration and task contracts
```

Project files: [contributing](CONTRIBUTING.md), [security policy](SECURITY.md), [changelog](CHANGELOG.md), [code of conduct](CODE_OF_CONDUCT.md), [license](LICENSE) and [NOTICE](NOTICE). External material and separate license terms are recorded in [third-party provenance](docs/THIRD-PARTY.md).

wev-skills is source-available, not open source in the sense of the Open Source Initiative. Starting with the next release (3.0.0), it is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE): anyone may use, change and redistribute it for any noncommercial purpose, and commercial use is prohibited. Everything published before the change remains under the MIT License: releases 1.0.0 to 2.0.0 and the commits up to `577a6f6`. Third-party material keeps its own license.

## Verification

```sh
make test
make lint
bin/wev readme check
```

Tests use standard-library `unittest`, fixture fakes and no paid model or real remote host. Lint checks Ruff formatting and rules plus strict mypy. Missing tools can be skipped: inspect the output before claiming a passing lint run. tmux integration tests skip when tmux is unavailable.

The prior recorded local baseline (2026-10-13, Python 3.14.7) was **2076 tests, 8 skipped**, with strict mypy reporting **146 source files without issues**. This is historical evidence, not a claim that the current checkout has passed; see [MVP status](docs/mvp-status.md) and [CI runs](https://github.com/wevertonjuscelino/wev-skills/actions/workflows/ci.yml) for validation records.

## Limitations

> [!WARNING]
> This engine is not a security boundary against an adversarial agent running as the same user. Allowed commands inherit that user's permissions, and state can be rewritten. Use operating-system isolation when a real trust boundary is needed.

- Command classification and secret redaction are heuristics. Scripts and interpreters can do more than their command line reveals.
- Repository configuration can enable Git helpers even in read-only commands; see the [security review](docs/security-review-2026-10-13.md) before working with unfamiliar repositories.
- Approvals provide friction and an audit trail, not human authentication; a process can emulate a terminal.
- Plugin enforcement sees Bash calls that pass through its hooks. Native file-tool edits are outside those checks.
- Passing checks prove that the recorded checks ran successfully, not that the acceptance criteria or tests are sufficient.
- JEV is optional and off by default. When enabled it sends task data to a third party; review the provider policy before enabling it.
- Evaluation uses a scripted agent, so it does not measure model quality. Remote operations have only simulated-host evidence.
- `limits.budget_units` has no live-run input. Context settings apply to the CLI context manager and evaluation harness, not Claude Code's own context.

## Roadmap

Future work, not implemented or validated:

- Exercise skills, exported agents and hooks in a live Claude Code session.
- Validate local tmux and a staging SSH host; evaluate with real models.
- Add adapters for other agent environments and support Windows state locking.
- Extend hook coverage beyond Bash and expose recall during an agent session.

## Credits

wev-skills was written by Weverton Juscelino. It is based on the following work. No third-party file has been copied into this repository; the provenance record is [docs/THIRD-PARTY.md](docs/THIRD-PARTY.md) and the research notes are in [docs/research/](docs/research/sources.md).

- **addyosmani/agent-skills**, by Addy Osmani, https://github.com/addyosmani/agent-skills. License: MIT, "Copyright (c) 2025 Addy Osmani". Studied at commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe` (2026-10-10). Architectural inspiration and compatible conventions (`SKILL.md`, persona-style agents, plugin manifests, evaluation tiers). No files copied.
- **"An Empirical Study of Harness Design for Coding Agents"**, arXiv:2609.20804 (v1, 17 Sep 2026), by Run-Ze Fan, Zihao Zhang, Simin Ma, Yebowen Hu, Shouju Wang, Kaiqiang Song, Fei Liu, Hamed Zamani and Xiaoyang Wang, https://arxiv.org/abs/2609.20804. Source of the testable hypotheses behind the harness defaults, treated as hypotheses and not as guarantees. Its reuse license was not checked, and no text or figure is reproduced.
- **andrej-karpathy-skills**, by forrestchang, https://github.com/forrestchang/andrej-karpathy-skills (the reference copy was https://github.com/multica-ai/andrej-karpathy-skills at commit `2c606141936f1eeef17fa3043a72095b4765b9c2`, checked 2026-10-13). License: MIT as stated in its README; the repository has no LICENSE file. The project describes its guidelines as derived from Andrej Karpathy's public observations on pitfalls of coding with LLMs. Source of the guidelines block that `wev claude-md` writes, adapted in this project's own wording.
- **`create-readme` skill of github/awesome-copilot**, by GitHub, Inc., https://github.com/github/awesome-copilot, path `skills/create-readme/SKILL.md`, commit `156736fb63e965b2f547a1460f3b5972c46e6b24` (consulted 2026-10-13). License: MIT, "Copyright GitHub, Inc.". Source of the ideas behind the README standard in the skill `wev-readme`, rewritten in this project's own wording and extended with this project's own rules.
- **Agent Skills specification**, https://agentskills.io/specification. The skill file format the skills follow. Its license was not checked, and no text is reproduced.
- **Claude Code documentation**, published by Anthropic, https://code.claude.com/docs (skills, plugins and marketplaces, subagents, hooks, headless mode). Consulted to learn the interfaces the plugin, the exporter and the hooks use. Its license was not checked, and no text is reproduced.
- **tmux**, https://github.com/tmux/tmux, by the tmux contributors. Referenced for the optional remote module; no tmux code is used, and its license is not recorded in this repository.

wev-skills is an independent project and is not affiliated with or endorsed by any of the projects, papers, authors or organizations listed above.
