# wev-skills

Portuguese version: [README.pt-BR.md](README.pt-BR.md).

An open source, evidence-oriented orchestration harness for AI coding agents: a dependency-free Python engine with a JSON command-line interface (`wev`), plus Claude Code skills, subagents and hooks. It helps an agent carry out multi-step work with a recorded plan, task contracts, permission checks, loop detection, verification evidence and resumable state, and it reports every result with a label that says how much evidence stands behind it.

It is for a developer who wants larger tasks planned, delegated and verified with a record of what was actually checked, for a team that wants to define its own agents as versioned configuration instead of code, and for a maintainer who wants to compare harness settings on a fixed set of tasks. Nothing in it assumes a particular repository, language or company. Claude Code is the only environment with an adapter; the engine does not depend on it.

> [!IMPORTANT]
> Pre-release 0.1.0, published on 2026-10-13 at https://github.com/wevertonjuscelino/wev-skills. The CI workflows exist and have not completed a run. Nothing has been exercised in a live Claude Code session, and there has been no real tmux or SSH run. There is no package on PyPI and no listing in an official marketplace. Every claim below carries one of five evidence labels, and nothing is claimed without evidence.

Skill maintenance across repositories uses `wev-skill-maintenance` ([guide](skills/wev-skill-maintenance/SKILL.md)) and a [reviewed external source pin](skills/wev-skill-maintenance/references/upstream.json). The external Netresearch skill-repo guide is installed separately; updates and conflicts follow the [maintenance policy](skills/wev-skill-maintenance/references/policy.md), with no automatic synchronization.

## Status

The labels are: implemented and tested; implemented but untested; simulated with mocks; documented only; blocked. The [MVP status](docs/mvp-status.md) lists the evidence for each acceptance criterion.

| Capability | Status | Evidence and caveats |
|---|---|---|
| Engine: classification, strategy, plan, task contracts, state, resume, report | implemented and tested | Unit tests and a CLI flow integration test, all without a model |
| Verification gate: `verified` needs a passing check made after the task last started, on the tree as it is; a baseline of the checks is taken when a task starts | implemented and tested | Unit tests. The checks are written by the agent or the plan author; the engine verifies that they ran and passed, not that they are sufficient |
| Permissions, approvals, command classification, redaction, state-directory protection, configuration pinned per run | implemented and tested | Unit tests and a security suite. Classification is a heuristic; not independently reviewed |
| Human-operator commands (`approval grant`, `approval deny`, `guard acknowledge`, `task reopen`) | implemented and tested | They need a terminal and a typed word and accept no bypass flag. A determined process can fake a terminal; see the warning below |
| Execution guard: loops, repeated failures, no progress, hand-off cycles, time | implemented and tested | Deterministic unit tests. The budget rule has no input in a live run today |
| Tool selection (`wev select-tools`, `harness.tool_selection`, `wev task tools`) with the local policy | implemented and tested | Unit tests |
| Context manager (staged compaction) | implemented and tested | Used by `wev context compact` and the evaluation harness. It does not manage Claude Code's own context |
| Agent specs: registry, factory, inheritance, permission ceiling, export to subagents | implemented and tested | The exported subagent files have not been loaded by a live Claude Code session |
| Decision provider: local policy | implemented and tested | Deterministic rules, no network |
| Decision provider: JEV adapter (optional, off by default) | simulated with mocks | Tested against a fake `jev` serving one recorded real response (2026-10-13, synthetic input). Sends the task objective to a third party when enabled |
| Remote module (SSH and tmux, optional) | simulated with mocks | Tested against a simulated host only; never run against real tmux or a real server |
| Evaluation harness | simulated with mocks | Scripted agent, simulated units, no model |
| `wev claude-md` and `wev readme check` | implemented and tested | Unit tests. `claude-md` writes only a file named `CLAUDE.md` inside the repository; `readme check` only reads |
| Plugin hooks: brief re-injection, Bash pre-check | implemented and tested | Unit and subprocess tests. Once a run is known a problem becomes `ask`, not silence |
| Seven skills and the plugin manifests | implemented and tested | Unit tests for format and command references. `claude plugin validate .` passes with one warning (a `CLAUDE.md` at the plugin root is not loaded as plugin context), checked with Claude Code 2.1.296 on 2026-10-13 |
| Skills, subagents and hooks inside a live Claude Code session | implemented but untested | Never exercised in a live session |
| Mechanisms taken from the research paper (conditional planning, tool profiles, plan reminder, capability profiles) | implemented and tested | Mechanics tested; effect not measured with a real model |
| CI workflows | implemented but untested | The files parse as YAML and pin their actions to commit SHAs. No run has completed as of this commit |
| Installation by marketplace or `pip install` | documented only | Commands read from `--help` output; not run |
| Adapters for other environments; evaluation against real models | documented only | Future work |
| Windows | blocked | The state store uses POSIX file locks |

## How it works

The engine (`src/wev_skills/`, Python 3.14+, standard library only) owns every rule that code can check: whether a plan is valid, which task transitions are legal, whether a command is allowed, whether an approval covers it, whether the agent is stuck in a loop, and whether a task can be recorded as verified. The six skills in `skills/` (`wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` and `wev-readme`) are Markdown instructions that tell Claude Code when to call the engine and how to act on its answers. The model reasons and edits; the engine records, decides and refuses invalid steps with a non-zero exit code. The reasoning is in [ADR 0002](docs/architecture/decisions/0002-engine-enforces-skills-instruct.md) and the [architecture](docs/architecture/architecture.md).

The flow is `REQUEST → DISCOVER → CLASSIFY → PLAN → DECIDE → EXECUTE → VERIFY → REVIEW → DELIVER`, with the modes `plan` (look, change nothing), `execute`, `auto` and a resume operation that compares the recorded run with the real repository first.

> [!WARNING]
> The engine is a guardrail for a fallible agent and a recorder of decisions. It is not a security boundary against an adversarial agent in the same account: it runs as the same user as the agent it constrains, and every file it keeps can be rewritten by that agent. Isolation has to come from outside (a container, a separate user, operating-system permissions). Enforcement also covers only what passes through the engine or the Bash hook; edits made with Claude Code's own file tools are not seen. See [SECURITY.md](SECURITY.md).

## Requirements

- Python 3.14 or newer on macOS or Linux. Nothing to install: the engine uses only the standard library. Older interpreters are not supported, including the stock macOS `/usr/bin/python3` (3.9). With an older `python3` first on `PATH` the plugin's hooks exit quietly and check nothing (check with `python3 --version`). The suite last ran on Python 3.14.7, as recorded in the [MVP status](docs/mvp-status.md).
- `git`, for run snapshots and drift detection.
- Claude Code, only for the plugin (skills, subagents, hooks). The CLI works without it.
- Optional: `tmux` and `ssh` (remote module), `ruff`, `mypy` or `uvx` (`make lint`).

## Quick start

Clone the repository (documented only; the clone was not run for this README) and call the clone `$WEV_HOME`. Update, uninstall, verification and rollback are in the [installation guide](docs/guides/installation.md).

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
export WEV_HOME="$PWD/wev-skills"
"$WEV_HOME/bin/wev" --help
```

Below, `wev` stands for `"$WEV_HOME/bin/wev"`. This is a real run, made today in a temporary git repository with a `Makefile` that has a `test` target and `.wev/` in `.gitignore`. Outputs are shortened to the fields that matter; the engine prints more. State is written to `.wev/` in the current directory.

```text
$ wev run start --objective "Add a greeting file" --files 1 --run-id demo-1
  classification: complexity trivial, risk low        (source: local-policy)
  strategy:       flow direct, no plan, no independent review
  discovery:      make test (from Makefile)
  config:         source defaults, digest pinned for the run
  next_step:      wev task next --run demo-1

$ wev task next
  offered: task-1  agent senior-engineer  model claude-sonnet-5-5  checks ["make test", "git diff --stat"]

$ wev task start task-1
  status running, attempt 1, contract handed out
  baseline: taken, passed ["make test", "git diff --stat"]

$ wev exec --task task-1 -- touch greeting.txt
  record: status passed, exit_code 0, changed_files ["greeting.txt"]    guard: continue

$ wev task check task-1
  all_met true: "1 of 1 acceptance criteria met, 0 unmet, 0 unverified; 0 checks not run."

$ wev task record task-1 --status verified --summary "greeting file added" --changed-file greeting.txt
  status verified   next_step: wev run finish --run demo-1

$ wev run report --format md
  # Delivery report: run demo-1
  - Overall status: complete
  ### task-1: Add a greeting file     Status: verified   Evidence: tested
  | Check that ran | Exit code | Log | Evidence |    make test | 0 | ... | tested |

$ wev run finish
  {"run_id": "demo-1", "phase": "done", "complete": true, ...}
```

Trying to skip the evidence is refused, and a destructive command asks for a person:

```text
$ wev task record task-1 --status verified --summary "too early"
  exit 2  verification_required: Task task-1 cannot be recorded as verified: 1 acceptance criterion(s) have no passing check made after the task last started and no tested evidence.

$ wev exec --task task-1 -- rm -rf build
  exit 4  approval_required: Command needs approval: Approval needed: the command removes files recursively or without confirmation.
```

The agent must stop there and ask the human operator, who reviews the approval and grants it in their own terminal. That step needs a terminal and a typed word, so it was not run for this README; it is shown as the operator's step:

```sh
wev approval grant <approval-id>
```

The [orchestration guide](docs/guides/orchestration.md) shows the full flow with plans, independent review and resume.

To load the plugin (six skills, ten subagents and three hooks) for one session only:

```sh
claude --plugin-dir "$WEV_HOME"
```

To install it in every session, add the repository as a marketplace and install the plugin (documented only; these commands change the Claude Code configuration of the machine and were not run):

```sh
claude plugin marketplace add wevertonjuscelino/wev-skills
claude plugin install wev-skills@wev-skills-marketplace
```

Inside a Claude Code session the equivalents are `/plugin marketplace add wevertonjuscelino/wev-skills` and `/plugin install wev-skills@wev-skills-marketplace` (documented only). From a clone, `claude plugin marketplace add "$WEV_HOME"` adds the local marketplace instead.

## Features

- **Orchestration** with task contracts: objective, context, scope, exclusions, constraints, acceptance criteria, checks, response format, permissions, agent and model, handed to exactly one agent. Parallel tasks only when independent, never two on the same files. [Orchestration guide](docs/guides/orchestration.md).
- **Evidence labels**: the report labels every claim `tested`, `untested`, `mocked`, `documented_only` or `blocked`.
- **Agents as data**: schema-validated JSON specs, templates, inheritance, a permission ceiling, bilingual text and export to Claude Code subagents. [Creating agents](docs/guides/creating-agents.md).
- **Permissions and approvals**: no shell, command classification, plan-mode denial, protected paths, approvals bound to the exact command, single use and expiring, redaction. [Security guide](docs/guides/security.md).
- **Execution guard**: identical repeated commands, consecutive failures, no progress, hand-off cycles and time.
- **Decision providers and model routing**: a local deterministic policy and an optional JEV adapter; tiers `economy`, `standard`, `premium`; optional per-task tool selection. A run pins its configuration (`wev.config.json` at the repository root, or `--config` at start). [Configuration and providers](docs/guides/configuration-and-providers.md).
- **Claude Code plugin hooks**: re-inject the run brief after compaction and with each prompt, and check Bash commands against the run's pinned policy by answering `ask` or `deny`, never `allow`. Plain hooks were chosen over Claude Code mods: [ADR 0005](docs/architecture/decisions/0005-hooks-not-mods.md).
- **Remote module** (optional): inventory-only SSH aliases, strict host-key checking, tmux sessions owned by the task, production gated by approval. [Remote operations guide](docs/guides/remote-ops.md).
- **Scripted evaluation harness**: deterministic, no model. [Evaluation guide](docs/guides/evaluation.md).
- **Documentation helpers**: `wev claude-md init|update|check|show` keeps a managed guidelines block in a project's `CLAUDE.md` ([skill `wev-claude-md`](skills/wev-claude-md/SKILL.md)), and `wev readme check` verifies README files against this project's README standard ([skill `wev-readme`](skills/wev-readme/SKILL.md)).
- Reference: [architecture](docs/architecture/architecture.md), [specification](docs/spec.md), [decision records](docs/architecture/decisions/), [glossary](docs/glossary.md), [research notes](docs/research/hypotheses.md), [third-party record](docs/THIRD-PARTY.md).

> [!NOTE]
> Evaluation results come from a scripted agent that replays fixed trajectories against the engine's components. No model is called, so they say nothing about the quality of any model.

> [!NOTE]
> The remote module has only been tested against a simulated host. It has never run against real tmux or a real server.

## Testing and linting

```sh
make test
make lint
```

`make test` runs `unittest discover` with no network, no model and nothing to install. `make lint` runs `ruff check`, `ruff format --check` and `mypy` in strict mode on the package, using the tools on `PATH`, then `uvx`, and otherwise reports that it skipped. Unit tests and CI run without a paid model provider and without a real remote host.

Last recorded run (2026-10-13, Python 3.14.7, on the owner's machine, not in CI): `make test` ended with `Ran 2076 tests in 167.282s` and `OK (skipped=8)`; `make lint` ended with `Success: no issues found in 146 source files`. The full record is in the [MVP status](docs/mvp-status.md). The tmux integration tests are skipped where tmux is not installed.

Project files: [LICENSE](LICENSE) (MIT; see also [NOTICE](NOTICE)), [CONTRIBUTING.md](CONTRIBUTING.md), the [maintaining guide](docs/guides/maintaining.md), [SECURITY.md](SECURITY.md), [CHANGELOG.md](CHANGELOG.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Limitations

- It is not a sandbox. An allowed command runs with the full permissions of your user, and the engine does not read what a script does.
- Command classification is a heuristic; a command it does not recognize may be treated as lower risk than it is. Interpreters and scripts (`python3 script.py`, `make`, `npm test`) run whatever their files say.
- Approvals are friction plus an audit record, not authentication. Without the plugin's hooks nothing stands between a process and a pseudo-terminal that types the confirmation word, and even with them a script that drives a pseudo-terminal names nothing on the command line the hook reads, so it is not asked about.
- Redaction is best effort and catches recognizable secrets only.
- The hooks see the Bash tool only, and only act when the plugin is installed and enabled. The engine does not check edits made with Claude Code's own file tools.
- The skills, subagents and hooks have not been exercised in a live Claude Code session. Compatibility with Claude Code is claimed only as far as its own validator accepts the manifests.
- The JEV adapter was verified against one recorded response; live calls are untested. A JEV installed outside the system directories is not found by name: set `decision.jev.command` to its absolute path (see the configuration guide).
- The mechanisms taken from the research paper are configurable defaults whose effect has not been measured with a real model.
- Agent routing is a word-matching heuristic and can pick an unsuitable agent; read the `agent_id` in each contract. Classification depends on signals the caller estimates.
- Some configuration keys do not do what their names suggest: `limits.budget_units` has no input in a live run, and `context.*` applies to `wev context compact` and the evaluation harness only.
- Windows is not supported (POSIX file locks).
- The CI workflows exist and have not completed a run. Only Python 3.14 is supported and tested; older interpreters are refused by `bin/wev`. Nothing was run on Linux.

## Roadmap

Future work, none of it implemented:

- Hooks for tools other than Bash, and a run of the existing hooks inside a real Claude Code session.
- Adapters for agent environments other than Claude Code.
- YAML input for agent specs.
- Evaluation against real models, and any measured comparison between configurations.
- Windows support for the state store.
- A recall tool surfaced to the model during a session.
- First real runs of the remote module, starting with the local tmux test and a staging host.

What remains to do after publishing is listed under "After publishing" in [docs/mvp-status.md](docs/mvp-status.md).

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
