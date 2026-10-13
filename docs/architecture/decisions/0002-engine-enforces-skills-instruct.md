# ADR 0002: The engine enforces, the skills instruct

Portuguese version: [0002-engine-enforces-skills-instruct.pt-BR.md](0002-engine-enforces-skills-instruct.pt-BR.md).

Status: accepted (2026-10-13)

## Context

A Claude Code skill is Markdown that a model reads. Instructions in Markdown shape behavior but cannot guarantee it. The brief requires that security does not depend only on Markdown instructions, and that the core stays independent of any one agent environment.

## Decision

Split the system in two layers:

1. An engine with a JSON command-line interface that owns every rule that can be checked by code: plan validity, task state transitions, permission decisions, approval gates, loop detection, evidence records, remote session ownership.
2. Environment adapters. For Claude Code these are skills that tell the model when to call the engine, an exporter that renders agent specs as Claude Code subagent files, and plugin hooks that call the engine from inside the session (added 2026-10-13, see Consequences).

The model reasons and edits. The engine records, decides what is allowed, and refuses invalid transitions with a non-zero exit code.

## Consequences

- The engine can be tested without a model, and the same engine can back another agent environment later through a new adapter.
- Enforcement is limited to actions that pass through the engine. A model that edits a file directly with its own tools bypasses the engine's command gate, and can rewrite the run state, the approvals file, the audit log and the per-user run registry. ADR 0006 states what follows from this: the engine is a guardrail and a recorder, not a security boundary.
- Hooks narrow the gap for shell commands. A `PreToolUse` hook for the Bash tool judges the command under the active run's pinned configuration, mode and risk and answers `deny` or `ask`; it never answers `allow` and it never reads the approval store, so it can only tighten the user's existing permission settings. The person's answer in Claude Code's permission prompt is the human gate. `SessionStart` (after compaction or resume) and `UserPromptSubmit` hooks inject the fenced, sanitized brief of the active run.
- The hooks stay silent only while no run can be found for the directory, the enclosing directories or the paths the command names. Once a run is known, an unreadable state, an internal error, oversized or malformed input and a command too long to analyze all become `ask`. The earlier text of this record said the hooks fail open on any internal error; that was replaced on 2026-10-13. Under a Python older than 3.10 `bin/wev` exits quietly for hook subcommands and says so on stderr, so a hook checks nothing there. `wev exec` remains the gate that fails closed.
- Limits that remain: file edits made with Claude's own tools (Edit, Write) are not seen; in execute mode `python3 script.py`, `make`, `mv`, `sed -i`, redirections and unknown absolute-path programs are not gated; a script that drives a pseudo-terminal is not seen by the hook; the hooks have unit and subprocess tests but have not been exercised inside a real Claude Code session.
- Delegation is centralized. The orchestrating session requests one task contract at a time and records the result; the engine does not let an agent start other agents. Claude Code itself allows nested subagents, so the skills state the rule and the engine detects hand-off cycles.
- What an agent spec field means is stated in ADR 0003: some fields are enforced by the engine, others are carried as instructions in the task contract.

## Alternatives considered

- Skills only, no engine: simplest to ship, but every rule would be advisory.
- A standalone agent runtime that calls model APIs itself: duplicates what Claude Code already does and would need paid provider access to test.
