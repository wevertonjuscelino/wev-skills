# Creating agents

Portuguese version: [creating-agents.pt-BR.md](creating-agents.pt-BR.md).

An agent in wev-skills is data, not code. Each agent is a versioned JSON file, validated against a schema. A new persona needs a new file and never a source change. The engine validates specs, resolves inheritance, enforces some of the fields below (and only those; the next section says which), and exports specs as Claude Code subagent files. The skill `wev-agent-builder` walks Claude Code through the same steps.

Status: spec loading, validation, inheritance, the permission ceiling and export are implemented and tested. The exported subagent files have not been loaded by a live Claude Code session. An exported agent does not run by itself: the orchestrating session delegates to it (see the [orchestration guide](orchestration.md)). The engine never lets one agent start another.

In this guide `wev` stands for `"$WEV_HOME/bin/wev"` (see the [installation guide](installation.md)). Outputs are real, from a temporary directory, and shortened where marked.

## The spec

Source of truth: `src/wev_skills/schemas/agent.schema.json`. Unknown keys are rejected. Fields that hold text (marked "text") accept a plain string or an object `{"en": "...", "pt-BR": "..."}`; `en` is required in the object form and `pt-BR` is optional.

| Field | Required | Type and limits | Notes |
|---|---|---|---|
| `schema_version` | yes | the number `1` | |
| `id` | yes | lowercase letters, digits and single hyphens, at most 64 | Becomes the subagent name |
| `name` | yes | text, at most 120 | |
| `description` | yes | text, at most 1024 | Claude Code uses it to decide when to delegate, so say what the agent does and when |
| `specialties` | no | up to 32 unique strings of at most 64 | The routing rule matches task words against these first |
| `instructions` | no | text, at most 20000 | The subagent's system prompt body |
| `responsibilities` | no | up to 64 texts | |
| `extends` | no | an agent id | One parent |
| `model` | no | a tier (`economy`, `standard`, `premium`) or a model id, at most 128 | On export a tier becomes `haiku`, `sonnet` or `opus` |
| `model_policy` | no | `min_tier`, `max_tier`, `escalate_on_failure` | The tiers the router may use for this agent; `min_tier` must not exceed `max_tier` |
| `tools` | no | `allow`, `deny`: up to 64 unique tool names each | Names such as `Read`, `Edit`, `Bash`, `Bash(git status:*)` |
| `skills` | no | up to 32 unique skill names | Exported as `skills` |
| `permissions` | no | `modes` (`plan`, `execute`), `max_risk` (`low`, `medium`, `high`), `may_mutate`, `may_use_remote`, `ceiling` | See below |
| `budget` | no | `max_units` (at least 1) | Exported as `maxTurns` |
| `timeout_seconds` | no | at least 1 | |
| `max_attempts` | no | integer 1 to 100 | |
| `success_criteria`, `stop_conditions` | no | up to 64 texts each | |
| `escalation` | no | `on_failure` (`continue`, `change_strategy`, `reduce_scope`, `escalate`, `ask_human`, `stop`), `to` (an agent id) | |
| `required_checks` | no | up to 32 command strings of at most 512 | |
| `output_format` | no | text, at most 20000 | |

Delegation is not a spec field. The base instructions tell agents not to delegate, and the orchestrating session alone hands out contracts.

## What the engine enforces and what it only carries

A field in a spec is one of two kinds, and the difference matters when you decide what to rely on.

| Enforced by the engine | How |
|---|---|
| `required_checks` | They join the task's checks and must pass; they are listed in the contract |
| `budget.max_units` | Becomes the task's budget in the execution guard (without it, a task has none) |
| `max_attempts`, `timeout_seconds` | The lower of the agent's value and the run's wins, for that agent's tasks |
| `permissions.may_mutate` | An agent with `may_mutate: false` may run through `wev exec` read-only commands, the task's own declared checks and the check commands discovered in the repository at `run start` (for example `make test`, `make lint`), by exact argv match, because running the test suite is how a reviewer verifies. Everything else is refused with `agent_read_only`. Those commands still go through the policy, so one that needs approval still needs it. In an execute run the command acts for a running task (`--task` must name a running task, or the only running task is used and the output says so), so this does not depend on the caller naming the task; with two tasks running the caller still chooses which one, and the engine cannot tell which agent is typing |
| `permissions.modes`, `permissions.max_risk` | A task outside them cannot be assigned to or started by the agent |
| `permissions.may_use_remote` | `wev remote start` needs the task's agent to have it |
| `permissions.ceiling` | Descendants cannot widen an ancestor's permissions (checked when specs load) |

| Carried as instructions only | What happens |
|---|---|
| `stop_conditions`, `success_criteria`, `escalation`, `output_format` | They reach the agent in its task contract and its exported prompt. Nothing in the engine checks that they were followed. Escalation to a higher model tier is decided by the engine's own attempt rules, not by the spec's `escalation` |

`tools.allow` and `tools.deny` shape the exported subagent file and the tool list in the contract. They are enforced by Claude Code when the file is loaded there, not by the engine, and an agent's own file tools are outside the engine's view. Treat the table as the list of what the engine will refuse; for anything else, check the diff.

## Templates and shipped agents

Templates are in `agent-specs/templates/` and are meant to be extended. Real resolved values:

| Template | Tools allowed | Tools denied | Modes | Max risk | May change files |
|---|---|---|---|---|---|
| `base` | Read, Grep, Glob | none | plan | low | no |
| `base-engineer` | Read, Grep, Glob, Edit, Write, Bash | none | plan, execute | medium | yes |
| `base-reviewer` | Read, Grep, Glob, Bash | Edit, Write, NotebookEdit | plan, execute | high, with `ceiling: true` | no |

`agent-specs/examples/` holds ten agents: `architect`, `code-reviewer`, `context-manager`, `decision-judge`, `frontend-engineer`, `remote-ops`, `researcher`, `security-auditor`, `senior-engineer`, `test-engineer`. `agent list` shows ids, parents and models; `agent show <id> --resolved` shows a spec with inheritance applied. The files in the top-level `agents/` directory are generated from these specs by `wev agent export`; they are output, not source. Edit the spec and export again.

## Inheritance (`extends`)

`extends` names one parent. Cycles and unknown parents are errors. When the factory resolves a spec:

- Single values (`instructions`, `model`, `output_format`, `timeout_seconds`, `max_attempts`) take the child's value when it sets one.
- Lists (`specialties`, `responsibilities`, `skills`, `success_criteria`, `required_checks`, `stop_conditions`) are the parent's entries followed by the child's, without duplicates.
- Objects (`model_policy`, `budget`, `escalation`, `permissions`) merge field by field.
- `tools`: the `allow` lists are united, the `deny` lists are united, and then anything denied is removed from `allow`. Deny wins, and a child cannot remove a parent's deny entry. A denied `Bash` also removes `Bash(...)` variants.

Real example of deny inheritance: a child of `code-reviewer` that asks for `Edit` gets nothing for it.

```text
$ wev agent create --template code-reviewer --id r2 --set 'tools.allow=["Edit"]'
  tools: {"allow": ["Read", "Grep", "Glob", "Bash"], "deny": ["Edit", "Write", "NotebookEdit"]}
```

## Permissions and the ceiling

Without a ceiling, permissions are plain inheritance: the object merges field by field and the child's value wins, at any depth. A child of `base-engineer` may therefore raise `max_risk` or add a mode. Real example: `--set 'permissions.max_risk="high"'` on a child of `base-engineer` is accepted and resolves to `max_risk: high`, `may_mutate: true`.

`permissions.ceiling` is an optional boolean. When any ancestor sets `ceiling: true`, every descendant may narrow but never widen the ancestor's resolved `max_risk`, `may_mutate`, `may_use_remote` or `modes` (fewer or equal modes, lower or equal risk, and neither flag may become true when the ancestor's is false), and may not set `ceiling: false`. A descendant may set `ceiling: true` again at a narrower level, which then binds its own descendants. Real refusals:

```text
$ wev agent create --template code-reviewer --id fixer --set 'permissions.may_mutate=true'      # exit 2
{"error": {"code": "permission_widening",
  "message": "permissions.may_mutate: the ancestor 'code-reviewer' sets a permission ceiling; a descendant may narrow its permissions but not widen them",
  "details": {"field": "permissions.may_mutate", "ancestor": "code-reviewer"}}}

$ wev agent create --template code-reviewer --id fixer2 --set 'permissions.ceiling=false'       # exit 2
{"error": {"code": "ceiling_unset",
  "message": "permissions.ceiling: the ancestor 'code-reviewer' sets a permission ceiling and a descendant cannot unset it", ...}}
```

The ceiling is set by `base-reviewer`, `code-reviewer`, `decision-judge`, `security-auditor` and `researcher`. Nothing derived from them can gain write or remote access. `base` and `base-engineer` have no ceiling.

Defaults when nothing sets them: modes `plan` only, `max_risk` low, `may_mutate` false, `may_use_remote` false.

Other checks: an agent that allows `Edit`, `Write` or `NotebookEdit` must have `may_mutate` true, or it fails with `mutating_tool_without_permission`; `create` refuses to override `extends`, and every new agent needs an id.

What the ceiling does and does not do: it constrains what the spec may declare. It is checked when specs are loaded, in code. It does not sandbox the agent at run time; a task's tool list and permissions come from the spec, and the permission policy checks commands that pass through the engine. See the [security guide](security.md).

## Bilingual text fields

Write `name`, `description`, `instructions` and the other text fields as an object to serve both languages:

```json
"name": { "en": "Docs writer", "pt-BR": "Redator de documentação" }
```

Export renders the language chosen with `--lang` (default: the CLI language, from `--lang`, `WEV_LANG` or `LANG`). A plain string is used for every language. Identifiers and field names stay in English.

## Validate

```text
$ wev agent validate specs/docs-writer.json
{"valid": true, "path": "specs/docs-writer.json", "id": "docs-writer"}
```

`validate` checks the file against the schema and the factory's rules (the parent exists, tools and permissions are consistent). `--dir` adds a directory of specs (repeatable; later directories override earlier ones) and can be set once under `agents.directories` in the configuration. A directory must be inside the repository or the user's configuration directory, and a spec from such a directory cannot reuse the id of a built-in agent unless `agents.allow_override` is true (otherwise it is refused). A `.json` file in such a directory that has `schema_version` or `id` claims to be a spec and must be valid or the command fails; a JSON file with neither (a `package.json`, for example) is skipped and named in the `warnings` list.

## A worked example

Create a documentation writer that may edit files but only at low risk. This sequence was run as written.

```text
$ wev agent create --template base-engineer --id docs-writer \
    --set 'name={"en":"Docs writer","pt-BR":"Redator de documentação"}' \
    --set 'description={"en":"Writes and updates documentation files only.","pt-BR":"Escreve e atualiza apenas arquivos de documentação."}' \
    --set 'specialties=["documentation"]' \
    --set 'model="standard"' \
    --set 'permissions.max_risk="low"' \
    --out specs/docs-writer.json
```

`--set key=value` overrides a field; dots nest and values parse as JSON, falling back to plain text. The command prints the resolved agent and, with `--out`, writes only the child spec (`--force` overwrites):

```json
{
  "schema_version": 1,
  "name": { "en": "Docs writer", "pt-BR": "Redator de documentação" },
  "description": { "en": "Writes and updates documentation files only.", "pt-BR": "Escreve e atualiza apenas arquivos de documentação." },
  "specialties": ["documentation"],
  "model": "standard",
  "permissions": { "max_risk": "low" },
  "id": "docs-writer",
  "extends": "base-engineer"
}
```

Inheritance is resolved when the file is loaded. Check the result:

```text
$ wev agent validate specs/docs-writer.json
$ wev agent show docs-writer --dir specs --resolved
  tools.allow: Read, Grep, Glob, Edit, Write, Bash   permissions: modes plan+execute, max_risk low, may_mutate true
```

Export it for Claude Code. The engine writes only inside the repository root and never into `.git`, the state directory or `.claude`, with one exception made for this command: `<repository root>/.claude/agents`, where Claude Code reads a project's subagents. `agent export` creates that directory if it is missing and writes only `<id>.md` files in it:

```text
$ wev agent export --dir specs --id docs-writer --out .claude/agents
{"exported": [".../.claude/agents/docs-writer.md"], "lang": "en", "tool_profile": "structured", "warnings": []}

$ wev agent export --dir specs --id docs-writer --out .claude/hooks      # exit 3
{"error": {"code": "output_refused", "message": "Refusing to write .claude/hooks: nothing is written into .git or .claude under ...", ...}}
```

Every other path under `.claude` stays refused: `settings.json`, `settings.local.json`, `hooks/`, `commands/`, `skills/`, a subdirectory of `agents/`, and a spelling that differs by case. A symlinked `.claude` or `.claude/agents` is refused as well, so the export cannot be pointed out of the repository. A file already in `.claude/agents` is replaced only if it carries the generated-file marker; a hand-written agent file is never overwritten. `wev agent create --out` still refuses everything under `.claude`.

`wev agent create --out` and `wev agent export` do not overwrite a file that is not already an agent spec or a generated subagent file (`--force` applies only to a file that already is a spec). `wev agent create --out` also refuses the reserved name `wev.config.json` (in any directory, in any letter case) and any existing file that is not an agent spec. With the plugin installed and a wev run active, the PreToolUse hook answers `ask` for both commands when it can read the command line, so you confirm an export into `.claude/agents` inside Claude Code.

The file starts with:

```markdown
---
name: "docs-writer"
description: "Writes and updates documentation files only."
tools: "Read, Grep, Glob, Edit, Write, Bash"
model: "sonnet"
maxTurns: 40
---
<!-- Generated from specs/docs-writer.json. Do not edit by hand. -->

# Docs writer
```

## Export to Claude Code subagents

`wev agent export --out DIR` writes `<id>.md` files. Without `--id` it exports every non-template agent; `--id` is repeatable; `--lang en|pt-BR` picks the language of the text.

- Frontmatter carries only fields the Claude Code documentation lists: `name`, `description`, `tools`, `disallowedTools`, `model`, `skills`, `maxTurns`, each when the spec sets it. A tier becomes `haiku`, `sonnet` or `opus`; a concrete model id is passed through; with no `model`, the field is left out. `budget.max_units` becomes `maxTurns`.
- Everything else (instructions, responsibilities, success criteria, limits, escalation, required checks, stop conditions) goes into the Markdown body, which is the subagent's system prompt. The engine enforces `required_checks` and the attempt, time and budget limits when it hands out and records tasks; `escalation`, `stop_conditions`, `success_criteria` and `output_format` are instructions only.
- `--tool-profile structured|lean|auto` overrides `harness.tool_profile` for the export. `structured` (the default) keeps the full allow list. `lean` reduces an agent that may change files and has `Bash` allowed to `Bash`, `Read` and `Edit` (as far as it had them). `auto` uses `lean` only for agents on the premium tier. A profile never adds a tool, never changes the deny list and never changes permissions. The effect of a profile on any model has not been measured.
- Place the files where Claude Code reads agents. For a project, `.claude/agents/` in the repository, so the agents belong to that project and its team; `wev agent export --out .claude/agents` writes there directly (see above), and no other path under `.claude` is writable. The agents this plugin ships are named `wev-skills:<id>` when delegating; a file you export is named by its plain id.

The comment line in the generated file names the spec it came from. Do not edit the exported file by hand.

## How the engine picks an agent for a task

`plan set` assigns an agent to each task: the plan's `agent_hint` if it names a known agent, otherwise the best score from a whole-word match between the task's title and objective and each agent (a specialty word weighs 3, a specialty matched in full adds 2, a description word weighs 1; ties break by id). With no match the task goes to `agents.default_agent` (default `senior-engineer`) when that agent may change files. Outside plan mode a task goes to an agent that may change files, unless the task is marked `read_only`. A task about remote systems keeps the agents with `may_use_remote`. This is a heuristic: it assigned `test-engineer` to a documentation task in the [orchestration guide](orchestration.md). Read the `agent_id` in the contract and override it with `agent_hint` when it does not fit.
