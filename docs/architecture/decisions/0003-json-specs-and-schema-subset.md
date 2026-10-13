# ADR 0003: JSON agent specs validated by a JSON Schema subset

Portuguese version: [0003-json-specs-and-schema-subset.pt-BR.md](0003-json-specs-and-schema-subset.pt-BR.md).

Status: accepted (2026-10-13)

## Context

Agents must be defined by configuration, versioned, and validated before use. The engine has no third-party dependencies (ADR 0001), so neither a YAML parser nor a JSON Schema library is available.

## Decision

- Agent specs, configuration, plans, run state and eval tasks are JSON documents with a `schema_version` field.
- Their schemas live in `src/wev_skills/schemas/` and are valid JSON Schema (draft 2020-12) restricted to a documented subset of keywords.
- `wev_skills.schema` implements that subset and rejects a schema that uses a keyword it does not support, so a schema can never be "validated" by silently skipping part of it.

## Consequences

- Users can point any editor or external validator at the same schema files.
- JSON has no comments, so agent specs carry a `description` field and the guides explain each field.
- YAML input is future work. It would be an input format converted to the same JSON structure, behind an optional dependency.

## Agent spec to Claude Code subagent

The agent spec is the source of truth. The Claude Code adapter renders it to a subagent Markdown file using only frontmatter fields that the official documentation lists (`name`, `description`, `tools`, `disallowedTools`, `model`, `skills`, `maxTurns`). Fields that Claude Code has no equivalent for are written into the system prompt body of the subagent file, and the same values travel in the task contract. Which of them the engine checks is decided per field (verified in `src/wev_skills/core/agent_rules.py` and its callers on 2026-10-13):

- **Enforced by the engine:** `required_checks` (added to the task's checks), `budget.max_units` (per-task budget in the execution guard), `max_attempts`, `timeout_seconds`, `permissions.may_mutate` (a task for such an agent runs read-only commands only), `permissions.modes`, `permissions.max_risk`, `permissions.may_use_remote` (the remote commands refuse an agent without it), and `permissions.ceiling` (descendants may narrow permissions, never widen them).
- **Carried as instructions only:** `stop_conditions`, `success_criteria`, `escalation` and `output_format`. The agent receives them in its contract and nothing in the engine checks them. The agent's `escalation` field is therefore text; the engine's own escalation to a higher model tier is a separate mechanism that fires at half the attempts (rounded up) or on a repeated error signature, and does not read that field.
