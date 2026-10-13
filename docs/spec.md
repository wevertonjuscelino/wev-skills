# wev-skills product specification (MVP)

Portuguese version: [spec.pt-BR.md](spec.pt-BR.md).

## Purpose

wev-skills helps a coding agent carry out multi-step work with a recorded plan, explicit task contracts, permission checks, loop detection, verification evidence and resumable state. It is generic: nothing in it assumes a particular repository, language or domain.

## Users

- A developer using Claude Code who wants larger tasks to be planned, delegated and verified with a record of what was actually checked.
- A team that wants to define its own agents (reviewer, security auditor, remote operator) as versioned configuration files.
- A maintainer who wants to compare harness settings on a fixed task set.

## MVP scope

1. A Python engine with a JSON CLI covering classification (with a lexical risk floor read from the objective in English and Portuguese), strategy, planning, task contracts, state with conditional commits, permissions, approvals, loop detection, command execution, verification with strict evidence rules, model routing and reporting. Context budgeting is available as `wev context compact` and in the evaluation harness; the orchestration flow does not use it.
2. Agent specs as schema-validated JSON, with a registry, a factory with templates and inheritance, ten example agents, and an exporter to Claude Code subagent files.
3. A decision interface with a local deterministic provider and an optional JEV adapter. External providers can only raise risk and complexity; they can never remove a review or an approval.
4. An optional remote module for SSH plus tmux, tested with a simulated transport.
5. A deterministic evaluation harness with a scripted agent.
6. Claude Code skills that drive the engine, packaged as a Claude Code plugin with a marketplace manifest.
7. Plugin hooks for Claude Code: the sanitized, fenced brief of the active run is re-injected after context compaction and with each prompt, and Bash commands are checked against the run's pinned permission policy (deny, or ask the human; never allow). The hooks also route the engine's own sensitive commands (approval and acknowledgement commands, `run start`, `run finish`, anything with `--config`, and a few others) to the human's permission prompt when the command line is one the hook can read. They are silent only while no run is known; once one is known, a problem becomes an `ask`. They do not see file edits made with Claude's own tools.
8. Per-task tool selection (`harness.tool_selection`, `wev select-tools`, `wev task tools --add`) with a local policy and an optional JEV provider, and a report section with approximate tool-definition token estimates.
9. The CLAUDE.md feature (`wev claude-md init|update|check|show`, skill `wev-claude-md`) and the README feature (`wev readme check`, skill `wev-readme`), both producing and checking guideline text for a project.
10. Six Claude Code skills in total: `wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` and `wev-readme`.
11. Documentation in English and Brazilian Portuguese, CI workflows, license and third-party record.

## Security position

The engine is a guardrail for a fallible agent and a recorder of decisions. It is not a security boundary against an adversarial agent in the same user account. The human gate is Claude Code's permission prompt, reached through the hook; without the plugin's hooks, approvals are records. Known open limits include: the agent's own file tools can rewrite state, approvals, the audit log and the run registry; a pseudo-terminal can type the confirmation word of the human-operator commands, and a script that drives one is not seen by the hook; `python3 script.py`, `make`, `mv`, `sed -i`, redirections and unknown absolute-path programs are not gated in execute mode; child processes inherit the caller's environment. See [SECURITY.md](../SECURITY.md) and [ADR 0006](architecture/decisions/0006-guardrail-not-boundary.md).

## Out of scope for the MVP (future work)

- Hooks for tools other than Bash (for example checking Edit and Write against a task's scope), and a run of the existing hooks inside a real Claude Code session.
- Adapters for agent environments other than Claude Code.
- YAML input for specs.
- Evaluation runs against real models, and any measured comparison between configurations.
- Windows support for the state store.
- A recall tool surfaced to the model during a session.

## Acceptance criteria

Each criterion is checked by the named evidence. Status is tracked in [docs/mvp-status.md](mvp-status.md).

| # | Criterion | Evidence |
|---|---|---|
| 1 | The entry skill exists with valid frontmatter | Skill validation test; `claude plugin validate` if available |
| 2 | Local installation is documented and tested | Install guide; plugin load check |
| 3 | The basic orchestration flow runs end to end | Integration test driving the CLI from request to report |
| 4 | At least two agents are customizable by configuration | Example specs load, validate and export |
| 5 | Routing has a documented interface and a working implementation | Router and provider unit tests |
| 6 | Agent creation and validation have tests | Factory and registry unit tests |
| 7 | Plan and state persist and can be resumed | State store and resume tests |
| 8 | Loop protection has deterministic tests | Execution guard unit tests |
| 9 | Managed context has a testable compaction strategy | Context manager unit tests |
| 10 | Permission controls are verified by tests | Security test suite |
| 11 | SSH and tmux integration is isolated and tested with mocks | Remote module tests with a simulated transport |
| 12 | Documentation exists in Portuguese and English | Docs parity test |
| 13 | CI workflows are configured | Workflow files |
| 14 | Test commands that were run have recorded results | `docs/mvp-status.md` |
| 15 | No secrets, no known broken references, no unsupported compatibility claims | Secret scan, link check, review |
| 16 | The project is published as a pre-release and its status is recorded | "After publishing" list in `docs/mvp-status.md` |

## Non-goals

wev-skills does not replace the agent runtime, does not call model APIs itself in the MVP, and does not control Claude Code's own context window.
