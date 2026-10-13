# ADR 0006: The engine is a guardrail, not a security boundary

Portuguese version: [0006-guardrail-not-boundary.pt-BR.md](0006-guardrail-not-boundary.pt-BR.md).

Status: accepted (2026-10-13)

## Context

ADR 0002 splits the system into an engine that enforces and skills that instruct. The first approval and hook controls were written as if the engine could stop the agent it constrains. Three rounds of independent review on 2026-10-13, before publication, tested that and found the approval and hook controls bypassable by the constrained agent. The structural reason is the same in every finding: the engine runs in the same user account as the agent. Inside one account the CLI cannot tell who is typing, and every file the engine keeps can be rewritten with the agent's own file tools.

## Decision

State the security position in one way everywhere, using the wording of [SECURITY.md](../../../SECURITY.md):

- The engine is a guardrail for a fallible agent and a recorder of decisions. It is not a security boundary against an adversarial agent in the same user account.
- The human gate is Claude Code's permission prompt, reached through the plugin's `PreToolUse` hook, which answers `deny` or `ask` and never `allow`. The person's answer in that prompt is the approval for that call.
- Without the plugin's hooks, approvals are records, not gates.
- Isolation against an agent that sets out to defeat the engine has to come from outside: a container, a separate user, operating-system permissions, the permission settings of the agent platform.

Documents and skills must not say that a control "prevents", "guarantees" or "ensures" something that an agent in the same account can undo.

## What changed after the reviews

All of these are implemented and covered by unit or subprocess tests; the fixes made after the last review round have not been independently re-verified (see [mvp-status.md](../../mvp-status.md)).

- Approvals are single-use, expire (`permissions.approval_ttl_seconds`, default 900), and are bound to the exact argv, the working directory, the run and, for a remote action, the host. Reusable grants were removed. A denial is final for the same words in the same order within the run (the working directory, risk, reason and quoting do not make a fresh request) unless the operator reopens it. A command whose text redaction would alter is refused instead of being sent for approval. `wev approval verify` cross-checks grants against the audit log.
- The human-operator commands (`approval grant`, `approval deny`, `approval request --reopen-denied`, `guard acknowledge`, `task reopen`) need a terminal on stdin and stdout and a typed confirmation word. They have no bypass flag.
- The Bash hook never answers `allow` and never reads the approval store. It routes the engine's own sensitive commands to the human when the command line is one it can read, directly, behind a known wrapper or in an inline `sh -c` (operator commands, `approval request`, `run start`, `run finish`, `agent create`, `agent export`, `remote start`, `remote stop`, anything with `--config`), answers `ask` (or `deny` in plan mode) for environment-assignment prefixes, unresolved shell expansions and wrappers it cannot analyze, finds the run from the working directory, enclosing directories or a per-user registry matched against paths in the command, and once a run is known fails to `ask` instead of staying silent.
- The configuration is pinned in the run state at `run start`; a differing `--config` on a later command is refused.
- The executor resolves programs on a fixed safe path (`permissions.exec_path`), records the resolved path and redacts argv as a whole in logs.
- Captured output (exec tails, remote capture, and run discovery output) is stripped of control characters and fenced as data before the CLI returns it.
- The JEV program is resolved on the same safe path or must be an absolute path outside the run root.

## What remains open

These are the known limits listed in SECURITY.md. The engine does not defend against them:

- The agent's own file tools (Edit, Write) can rewrite the run state, the approvals file, the audit log, the configuration and the per-user run registry.
- A pseudo-terminal can type the confirmation word, and a script that drives one (for example `python3 pty_type.py`) names nothing on the command line the hook reads, so it is not asked about.
- In execute mode `python3 script.py`, `make`, `mv`, `sed -i`, redirections and unknown absolute-path programs are not gated.
- Child processes inherit the caller's environment.
- Classification is a heuristic; paths are checked when a command is judged, not when it runs; redaction and instruction-pattern scanning miss shapes and paraphrases.
- The hooks act only when the plugin is installed and enabled, and under a Python older than 3.14 (the stock macOS `/usr/bin/python3` is 3.9) they check nothing.
- Plan amendments are recorded, not prevented: `wev plan set --amend --reason` changes the criteria, checks, files, risk or `read_only` flag of a started task, and the engine does not judge whether the new criteria are weaker.
- The tree fingerprint leaves out files git ignores, so a change to them is not seen as work.
- A run is not found for a path built from a variable; a `$` expansion is asked about when any run is registered, and command substitution, here-documents and globs where no run is found are not covered.
- The report is recomputed at report time, not continuously; a change made and reverted between two reports is not seen.

## Consequences

- Claims about security are limited to what the code does against a mistake. The user guide and the skills tell the operator what to read before answering a permission prompt.
- Documents that describe a control must say what it does not cover. The wording is checked by reading, not by a test.
- A future change that moves a limit from "open" to "closed" needs a test that fails when the control breaks, and a new record.

## Alternatives considered

- Keep describing the controls as preventive: rejected, because the reviews showed it to be false for an adversarial agent.
- Store a signing key to authenticate operator commands: rejected, because a key readable by the user account is readable by the agent.

## Evidence label

Documented only for the position itself. The changes under "What changed after the reviews" are implemented and tested in the unit and security suites; the effect of the hooks inside a live Claude Code session has not been observed.
