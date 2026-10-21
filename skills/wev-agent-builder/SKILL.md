---
name: wev-agent-builder
description: "Creates, validates, composes and exports custom agents defined as JSON specs, using the wev agent commands, and turns them into Claude Code subagent files. Use when a user wants a new agent persona (reviewer, auditor, engineer, researcher), wants to adjust or inherit from an existing agent, check an agent spec, or install agents into a project's .claude/agents directory. Em português: criar, validar, combinar e exportar agentes personalizados."
argument-hint: "<what the agent should do>"
---

# wev-agent-builder

Request: $ARGUMENTS

Agents in wev-skills are data, not code. Each agent is a versioned, schema-validated JSON spec. A new persona needs a new file, never a source change. The engine validates specs, resolves inheritance, enforces the permission rules below, and exports specs as Claude Code subagent Markdown files.

Answer the user in the language they write; when they write Portuguese, pass `--lang pt-BR` before the command group. Commands use `"${CLAUDE_PLUGIN_ROOT}/bin/wev"`. Outside a plugin the same commands work as `wev` when it is on PATH, or as `python3 -m wev_skills` with the package importable.

**Non-negotiable rule: follow YAGNI and prefer the solution with less code.** It applies to everything you write or change through this skill.

## Workflow

1. Look at what exists: `agent list` shows ids, `extends` and model; `agent show <id> --resolved` shows a spec with its inheritance applied.
2. Pick the closest template or agent to extend. Templates: `base` (read-only investigator), `base-engineer` (edits files, runs commands, max risk medium), `base-reviewer` (read-only, reports findings with file and line). Examples such as `code-reviewer` or `security-auditor` can be extended too.
3. Create the child spec with `agent create`, overriding only what differs.
4. Validate with `agent validate`.
5. Export with `agent export --out .claude/agents` (the one place under `.claude` it may write), or to another directory in the repository, and read the exported file.
6. Tell the user what was created, which permissions the agent has, and that exporting does not itself make the agent run: it must be delegated to by the orchestrating session.

## Create from a template

`--set key=value` overrides a field; dots nest (`permissions.max_risk`), and values parse as JSON, falling back to plain text. Quote JSON values for the shell. `--out` writes the spec file, which must be a `.json` path inside the repository root (the command prints the resolved agent either way; without `--out` nothing is written). `--force` overwrites the file only if it exists and already is an agent spec. `--out` also refuses the reserved name `wev.config.json` (any directory, any letter case) and any existing file that is not an agent spec. `agent create` is a sensitive command: with the plugin installed, the hook sends it to the human's permission prompt when it can read the command line.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" agent create --template base-engineer --id docs-writer --set 'name={"en":"Docs writer","pt-BR":"Redator de documentação"}' --set 'description={"en":"Writes and updates documentation files only.","pt-BR":"Escreve e atualiza apenas arquivos de documentação."}' --set 'specialties=["documentation"]' --set 'model="standard"' --set 'permissions.max_risk="low"' --out specs/docs-writer.json
```

The file written contains only the child spec (`extends: base-engineer` plus your overrides); inheritance is resolved when it is loaded. Check it, then export it:

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" agent validate specs/docs-writer.json
"${CLAUDE_PLUGIN_ROOT}/bin/wev" agent export --dir specs --id docs-writer --out exported-agents
```

`--dir` adds a directory of specs (repeatable; later directories override earlier ones, but none may reuse the id of a built-in agent unless `agents.allow_override` is true in the config). Directories named in `agents.directories` must be inside the repository root or the user's wev-skills configuration directory. A `.json` file directly inside that has `schema_version` or `id` claims to be a spec and must be a valid one, or the command fails. A JSON file with neither field (a `package.json`, for example) is skipped and named in the `warnings` list of `agent list` and `agent export`. Directories can also be set once in a config file under `agents.directories`.

`--out` for `agent export` is a directory inside the repository root. It refuses `.git`, the state directory and everything under `.claude` (`output_refused`) except exactly `<repository root>/.claude/agents`, which it creates if missing: only `<id>.md` files go there, a symlinked `.claude` or `agents` is refused, a file in it is replaced only if it carries the generated-file marker, and `.claude/settings.json`, `.claude/settings.local.json`, hooks, commands and skills stay refused. `agent create --out` still refuses all of `.claude`. Exporting is also a sensitive command: while a wev run is active, the PreToolUse hook answers `ask`, so the person confirms it inside Claude Code. Without `--id`, export writes every non-template agent. `--lang pt-BR` renders the exported text in Portuguese; the default is the CLI language. `--tool-profile structured|lean|auto` overrides `harness.tool_profile` from the config for this export: `structured` (the default) keeps the agent's full allow list; `lean` reduces an agent that may change files and has `Bash` allowed to `Bash`, `Read` and `Edit` as far as it already had them; `auto` uses `lean` only for agents whose model is the premium tier. A profile never adds a tool, never changes the deny list and never changes permissions.

## Where exported agents go

- For a project: `.claude/agents/` in the repository, so the agents belong to that project and its team. `agent export --out .claude/agents` writes there directly; read the files afterwards.
- Agents this plugin already ships are in its `agents/` directory and are named `wev-skills:<id>` when delegating. A file you export into `.claude/agents/` is named by its plain id.

Exported frontmatter carries `name`, `description`, `tools`, `disallowedTools`, `model`, `skills` and `maxTurns` when the spec sets them. A tier (`economy`, `standard`, `premium`) becomes `haiku`, `sonnet` or `opus`; a concrete model id is passed through; with no `model`, the field is left out. `budget.max_units` becomes `maxTurns`. Everything else (instructions, responsibilities, limits, escalation) goes into the Markdown body, which is the subagent's system prompt. The generated comment line names the spec file the agent came from, relative to the wev-skills repository for shipped agents and to the working directory for yours. Do not edit the exported file by hand; edit the spec and export again.

## What the engine enforces, and what it only passes on

Be exact when you describe an agent to the user.

Enforced by the engine:

- `permissions.modes`: a plan-mode run needs `plan`; any other mode needs `execute`.
- `permissions.max_risk`: a task above it is not given to the agent.
- `permissions.may_mutate`: with false, the agent may run through `wev exec` read-only commands, the task's own declared checks and the check commands discovered in the repository at `run start` (for example `make test`, `make lint`), by exact argv match, because running the test suite is how a reviewer verifies. Everything else is refused with `agent_read_only`. Those commands still go through the policy, so one that needs approval still needs it. In an execute run `wev exec` acts for a running task (`--task` must name one, or the only running task is used), so this does not depend on the caller naming the task; with two tasks running the caller still chooses which, and the engine cannot tell which agent is typing.
- `permissions.may_use_remote`: the remote commands refuse an agent without it.
- `permissions.ceiling`: stops descendants from widening permissions (below).
- `max_attempts` and `timeout_seconds`: the lower of the agent's value and the run's wins.
- `budget.max_units`: the task's budget for the execution guard.
- `required_checks`: run with the task's checks, and their results count.
- `tools.allow` and `tools.deny`: the contract and the exported file carry them. The engine does not stop Claude Code's own file tools.

Carried as instructions only (the agent receives them in its contract; nothing checks them): `stop_conditions`, `success_criteria`, `escalation` and `output_format`. Do not tell the user these are enforced. Escalation to a higher model tier is decided by the engine from the run's own rules (half the attempts, or a repeated error signature), not from the spec's `escalation` field.

## Rules the factory enforces

State these to the user when they matter; the engine refuses violations with exit 2.

- Inheritance: `extends` names one parent. Cycles and unknown parents are errors. A child overrides its parent: single values (`instructions`, `model`, `output_format`, `timeout_seconds`, `max_attempts`) take the child's value when set; lists (`specialties`, `responsibilities`, `skills`, `success_criteria`, `required_checks`, `stop_conditions`) are the parent's entries followed by the child's, without duplicates; objects (`model_policy`, `budget`, `escalation`, `permissions`) merge field by field.
- Tools: `deny` lists are united, `allow` lists are united, and then anything denied is removed from `allow`. Deny wins. A denied entry such as `Bash` also removes `Bash(...)` variants.
- Permissions without a ceiling are plain inheritance: the `permissions` object merges field by field and the child's value wins, at any depth. A child of `base-engineer` may therefore raise `max_risk` or add a mode.
- Permission ceiling: `permissions.ceiling` is an optional boolean. When any ancestor sets `ceiling: true`, every descendant may narrow but never widen `max_risk`, `may_mutate`, `may_use_remote` or `modes` beyond that ancestor's resolved permissions (fewer or equal modes, lower or equal risk, and neither flag may become true when the ancestor's is false), and may not set `ceiling: false`. Violations fail with `permission_widening` or `ceiling_unset`, naming the ancestor. A descendant may set `ceiling: true` again at a narrower level, which then binds its own descendants. `base-reviewer`, `code-reviewer`, `security-auditor`, `decision-judge` and `researcher` set a ceiling, so nothing derived from them can gain write or remote access; `base` and `base-engineer` do not.
- Defaults when nothing sets them: modes `plan` only, `max_risk` low, `may_mutate` false, `may_use_remote` false.
- An agent that allows `Edit`, `Write` or `NotebookEdit` must have `may_mutate` true (`mutating_tool_without_permission`).
- `model_policy.min_tier` may not be above `max_tier`.
- `create` refuses overriding `extends`, and every new agent needs an id.
- Delegation is not a spec field. The orchestrating session alone delegates; the base instructions tell agents not to delegate.

The full field list, with limits and allowed values, is in [references/spec-fields.md](references/spec-fields.md).

## Verification

The work is done when `agent validate` printed `"valid": true`, `agent show <id> --resolved` shows the permissions and tools the user intended, and the exported file exists at the target path. Report any tool or permission you narrowed on the user's behalf.
