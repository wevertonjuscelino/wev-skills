# Agent spec fields

Source of truth: the engine's agent schema. Unknown keys are rejected. Text fields marked "text" accept either a plain string or an object `{"en": "...", "pt-BR": "..."}`; `en` is required in the object form and `pt-BR` is optional. Text length limits are in characters.

| Field | Required | Type and limits | Notes |
|---|---|---|---|
| `schema_version` | yes | the number `1` | |
| `id` | yes | lowercase letters, digits and single hyphens, at most 64 | Used as the subagent name |
| `name` | yes | text, at most 120 | |
| `description` | yes | text, at most 1024 | Claude Code uses it to decide when to delegate, so say what the agent does and when |
| `specialties` | no | up to 32 unique strings of at most 64 | |
| `instructions` | no | text, at most 20000 | The system prompt body |
| `responsibilities` | no | up to 64 texts | |
| `extends` | no | an agent id | One parent |
| `model` | no | a tier (`economy`, `standard`, `premium`) or a model id, at most 128 | Tier maps to haiku, sonnet, opus on export |
| `model_policy` | no | object: `min_tier`, `max_tier` (tiers), `escalate_on_failure` (boolean) | The tiers the agent allows for model routing; `min_tier` must not exceed `max_tier` |
| `tools` | no | object: `allow`, `deny`, each up to 64 unique tool names | Names like `Read`, `Edit`, `Bash`, `Bash(git status:*)` |
| `skills` | no | up to 32 unique skill names | Exported as `skills` |
| `permissions` | no | object: `modes` (`plan`, `execute`; one or two), `max_risk` (`low`, `medium`, `high`), `may_mutate`, `may_use_remote`, `ceiling` (booleans) | Enforced by the engine (modes, max_risk, may_mutate, may_use_remote); with `may_mutate: false` an agent may run through `wev exec` only read-only commands, the task's declared checks and the checks discovered at `run start`, by exact argv (the rest is refused with `agent_read_only`); `ceiling` limits descendants.  `ceiling: true` stops every descendant from widening `modes`, `max_risk`, `may_mutate` or `may_use_remote` beyond this agent, and from unsetting the ceiling |
| `budget` | no | object: `max_units` (number, at least 1) | Enforced as the task's guard budget; exported as `maxTurns` |
| `timeout_seconds` | no | number, at least 1 | Enforced: the lower of this and the run's task timeout (`limits.task_timeout_seconds`, default 3600) |
| `max_attempts` | no | integer 1 to 100 | Enforced: the lower of this and the run's limit |
| `success_criteria` | no | up to 64 texts | Instruction only |
| `escalation` | no | object: `on_failure` (`continue`, `change_strategy`, `reduce_scope`, `escalate`, `ask_human`, `stop`), `to` (an agent id) | Instruction only; the engine's escalation rules do not read it |
| `required_checks` | no | up to 32 command strings of at most 512 | Enforced: added to the task's checks |
| `output_format` | no | text, at most 20000 | Instruction only |
| `stop_conditions` | no | up to 64 texts | Instruction only |

Conflict rules in short: when parent and child disagree on a single value the child wins; lists accumulate; `deny` beats `allow` and a parent's deny entry cannot be dropped; permissions follow the child unless an ancestor sets `permissions.ceiling: true`, after which descendants may only narrow them.

Shipped specs to copy from: `agent-specs/templates/` (`base`, `base-engineer`, `base-reviewer`) and `agent-specs/examples/` (ten agents: architect, code-reviewer, context-manager, decision-judge, frontend-engineer, remote-ops, researcher, security-auditor, senior-engineer, test-engineer).
