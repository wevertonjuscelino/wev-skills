---
name: wev-harness-evaluation
description: "Runs and extends the scripted evaluation harness (wev eval): list tasks and configurations, run them, read the metrics, validate or write a task fixture, and state what the results do and do not show. Use when a user wants to test harness settings such as context compaction, guards, routing, retries or scheduling, add an evaluation task, or interpret an evaluation report. Em português: avaliar o harness, rodar a avaliação scriptada, ler métricas e escrever tarefas de avaliação."
argument-hint: "[list|run|validate|new-task] <details>"
---

# wev-harness-evaluation

Request: $ARGUMENTS

The evaluation harness replays fixed, scripted trajectories against the real engine components (context manager, execution guard, model router, local decision policy). No model is called. It is a test bench for the harness mechanics (it does not drive the `run`/`task` orchestration flow, the hooks, approvals, the remote module or the real tool selection provider): it shows that thresholds, guards, routing, retries and scheduling behave as designed on trajectories built to exercise them.

Answer the user in the language they write; when they write Portuguese, pass `--lang pt-BR` before the command group. Commands use `"${CLAUDE_PLUGIN_ROOT}/bin/wev"`. Outside a plugin the same commands work as `wev` when it is on PATH, or as `python3 -m wev_skills` with the package importable.

**Non-negotiable rule: follow YAGNI and prefer the solution with less code.** It applies to everything you write or change through this skill.

## What the results mean, and what they do not

State this whenever you present numbers.

- Scripted results measure harness mechanics with simulated units. The script decides every outcome; a configuration "passes" because the task was written so that it would. A table shows that a mechanism fired, not that it is useful.
- They say nothing about the quality of any model, and they are not performance improvements. Never write "configuration X is faster, cheaper or better". Cost and duration are simulated units (not money, not time), and token counts are estimates.
- The shipped tasks are examples, not a benchmark. Do not quote their pass rates as one.
- Evaluation against real models is future work. No real-model results exist for this project. The context manager that the harness exercises serves `wev context compact` and this harness; the orchestration flow (`run`, `task`) does not use it.

Every report starts with a notice saying this; keep it when you relay a report.

## Commands

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" eval list
"${CLAUDE_PLUGIN_ROOT}/bin/wev" eval run --task simple-fix --config baseline --format md
"${CLAUDE_PLUGIN_ROOT}/bin/wev" eval run --out report.json
"${CLAUDE_PLUGIN_ROOT}/bin/wev" eval validate evals/tasks/simple-fix.json
```

- `eval list` prints the task ids and the configuration ids with the directories it read.
- `eval run` runs every selected task under every selected configuration. `--task` and `--config` are repeatable; without them everything runs. `--format json|md` (json is default), `--out FILE` writes the report instead of printing it, `--lang en|pt-BR` sets the report language. `--format md` without `--out` prints a JSON object whose `content` field holds the Markdown.
- `--tasks-dir` and `--configs` point at your own task directory and configurations file. The defaults are the `evals/` directory of the source repository; an installation without that directory fails with `evals_dir_not_found`, so pass both options.
- `eval validate` checks one task file against the schema and the consistency rules.

Runs are deterministic: two runs give identical reports.

## Reading a report

Per run and summed per configuration: success (all acceptance criteria met), criteria met, attempts, escalations, tier escalations, guard trips (total and by rule), context overflows, items elided or summarized, information-loss failures, unexecuted verifications, tool selection misses, estimated tool-definition tokens selected, simulated cost and simulated duration. The report gives raw counts and rates and does not compute differences between configurations. If the user wants a comparison, put two rows side by side and say what mechanism differs; do not call one better.

Configurations change one setting each from `baseline`: planning on, off or auto; context policy; routing policy or a fixed tier; parallelism; attempt limit; guard on or off; tool profile (`tools-lean`); per-task tool selection (`tools-selection-off`, `tools-selection-local`, read side by side). Tool token figures are estimates from rough per-tool constants, not measurements. Two capability profiles (`profile-economy`, `profile-premium`) set planning auto, the executor tier, a fixed tier and tool profile auto together. Each run lists its executor tier and the tools offered under its profile. The executor tier decides whether `planning: auto` makes a plan; a tool profile only changes the listed tools, because the scripted agent calls none. The summarizer in the summarizing configuration is a stub that truncates text; it is not a model.

## Writing a task fixture

A task is one JSON file. Start from a shipped one in `evals/tasks/` and run `eval validate` after every edit. Main fields: `id`, `title`, `category` (one of `simple-fix`, `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop`, `remote-diagnosis`, `tool-selection`), `signals`, `window_tokens`, `acceptance_criteria` (each `{id, text}`), `subtasks` (`{id, objective, depends_on, files, read_only}`) and `script` (ordered steps). Every acceptance criterion needs at least one `verify` step that lists it. Step kinds, conditions and the rules the harness applies are in [references/task-fixtures.md](references/task-fixtures.md).

Write fixtures that exercise one mechanism, say in `description` what it exercises, and keep step texts as filler. A fixture added to the shipped directory changes the committed baseline report; the repository's tests compare that report byte for byte, so tell the user the report files need regenerating.

## Verification

The work is done when `eval validate` accepts the new or changed task, `eval run` completes for it, and your summary to the user includes the notice that the results are simulated and mechanics-only. If you could not run something, say so rather than describing expected results.
