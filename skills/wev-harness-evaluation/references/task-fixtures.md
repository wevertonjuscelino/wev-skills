# Task fixtures

A fixture is validated against the engine's eval-task schema and then checked for consistency (`eval validate` reports both kinds of problems). The shipped examples are in `evals/tasks/`; `evals/baselines/configs.json` holds the configurations (`defaults` plus a `configs` list where each entry changes settings from the defaults).

## Fields

| Field | Meaning |
|---|---|
| `id`, `title`, `description` | Identification; `description` is optional |
| `category` | `simple-fix`, `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop`, `remote-diagnosis` or `tool-selection` or `tool-selection` |
| `signals` | Task signals (objective, files_touched_estimate, unknowns, independent_subtasks and the other signal keys); the local policy classifies them |
| `window_tokens` | Context window size of each subtask |
| `acceptance_criteria` | List of `{id, text}`; each must be supported by at least one `verify` step |
| `subtasks` | List of `{id, objective, depends_on, files, read_only}` (only `id` is required; the objective and `read_only` feed tool selection); each runs as one delegated agent with its own context |
| `script` | Ordered steps, each with `id`, `subtask`, `kind` and the fields its kind needs |

## Step kinds

- `tool_output`, `note`, `requirement`, `decision`: add an item of `tokens` tokens to the context. Requirements and decisions are pinned and never elided.
- `command`: a command event with a `signature`; `outcome: fail` makes it a failing command; `repeat` emits it several times; `polling` and `flaky` are passed to the guard.
- `edit`: a progress event.
- `verify`: a verification event that decides the listed `criteria`; a failing verification ends the attempt.
- `handoff`: a hand-off event from `from_agent` to `to_agent`.

Any step may set `tokens` to add a context item; `needed_later: true` marks an item that a later step needs. `needs_tool` names a tool the step needs; with tool selection on, a step whose tool was dropped records a selection miss and the tool is restored. Nothing calls a tool.

## Conditions

`conditions` on a step make the outcome depend on the configuration; an unmet condition ends the attempt as failed.

- `requires_verbatim: [ids]`: fails when a listed item was elided or summarized (models information lost by compaction).
- `pass_from_attempt: N`: fails when the attempt number is below N (work that succeeds only on a retry).
- `min_tier: T`: fails when the attempt runs below tier T (work that succeeds only at a given tier).

## Rules the harness applies

- The context overflows when its estimated tokens exceed `window_tokens` after a step; overflow and information loss end the subtask without a retry.
- A new attempt starts with a fresh context, and the router sees the number of failed attempts.
- The guard is asked after every step and after every failed attempt.
- With a plan, subtasks start in declaration order once dependencies succeeded, a slot is free and no running subtask shares a file; without a plan they run one at a time in declaration order.
- A subtask whose dependency failed is not executed.

## Limits

The script decides every outcome. Token counts, costs and durations are estimates and constants of the harness. Recall of archived originals is not modelled. A scripted agent cannot change strategy. Eight shipped tasks do not make a benchmark.
