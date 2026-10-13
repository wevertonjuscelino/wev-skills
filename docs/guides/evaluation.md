# Evaluation guide

Portuguese version: [evaluation.pt-BR.md](evaluation.pt-BR.md).

The evaluation harness replays fixed, scripted trajectories against the real engine components (the context manager, the execution guard, the model router and the local decision policy). **No model is called.** It has its own attempt loop and scheduler and does not call the orchestration engine (`wev run`, `wev task`), so baselines, approvals, the permission policy and the verification engine are not exercised by its results. It is a test bench for harness mechanics: it shows that thresholds, guards, routing, retries and scheduling behave as designed on trajectories built to exercise them.

Status: the harness is implemented and tested; every result it produces is **simulated with mocks**. The script decides every outcome, a configuration "passes" a task because the task was written so that it would, and cost and duration are simulated units, not money and not time. The results say nothing about the quality of any model and are not evidence that any setting improves anything. **No real-model evaluation exists for this project.** The full reference is [evals/README.md](../../evals/README.md); this guide is the short path through it.

In this guide `wev` stands for `"$WEV_HOME/bin/wev"`. Everything runs with no network and no installation.

## Run it

```text
wev eval list
wev eval run
wev eval run --task context-overload --config baseline --config context-none
wev eval run --format md --lang pt-BR --out report.md
wev eval validate evals/tasks/simple-fix.json
```

`eval list` prints the tasks (id, title, category, window size, subtasks, steps) and the configuration ids, and the directories it read. `eval run` runs every selected task under every selected configuration. `--task` and `--config` are repeatable; without them everything runs. Options: `--tasks-dir`, `--configs`, `--out FILE`, `--format json|md` (JSON is the default), `--lang en|pt-BR`. With `--format md` and no `--out`, the CLI prints a JSON object whose `content` field holds the Markdown, because the CLI always prints JSON.

The defaults are the `evals/` directory of the source tree. An installation without it fails with `evals_dir_not_found`; pass `--tasks-dir` and `--configs`.

Runs are deterministic: no randomness and no wall-clock time, so two runs give identical reports. `evals/reports/scripted-baseline.json` and `.md` are the committed output of the shipped tasks and configurations, and a unit test fails if running the harness no longer reproduces them byte for byte. After changing a task, a configuration or a component, regenerate both:

```text
PYTHONPATH=src python3 -m wev_skills --lang en eval run --out evals/reports/scripted-baseline.json
PYTHONPATH=src python3 -m wev_skills --lang en eval run --format md --out evals/reports/scripted-baseline.md
```

## Shipped tasks and configurations

Eight tasks, each built to exercise one mechanism: `simple-fix` (a control where nothing depends on the configuration), `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop` (three loops with no exit; no configuration can succeed), `remote-diagnosis` (polling must not count as a loop), `two-file-change` (a control for capability profiles) and `tool-selection-miss` (a read-only subtask that gets a shorter tool list, and a subtask scripted to need a tool the local policy drops, which is recorded as a miss and restored).

Eighteen configurations, each changing one setting of `baseline` (planning on, elision at 0.6, 3 attempts, sequential, policy routing, guard on, executor tier auto, structured tools), except the two capability profiles which set a group of settings together: `baseline`, `planning-off`, `planning-auto`, `context-none`, `context-elide-aggressive`, `context-elide-summarize`, `routing-fixed-standard`, `routing-fixed-premium`, `parallel-3`, `attempts-1`, `attempts-2`, `attempts-4`, `guard-off`, `profile-economy`, `profile-premium`, `tools-lean`, `tools-selection-off`, `tools-selection-local`. The summarizer used by `context-elide-summarize` is a stub that keeps the first 60 characters of each text; it is not a model. A tool profile only changes the tools a fixed reference agent lists, and the scripted agent calls no tool, so `tools-lean` has the same counts as `baseline`. Tool selection (`tool_selection`: `off` or `local`) hands each subtask the tools the local policy selects for its `objective`; a step may name the tool it stands for with `needs_tool`, and with selection on a step whose tool was dropped records a miss and the tool is restored from the reference agent's own list (a tool outside that list fails the subtask as `tool_unavailable`). `tools-selection-off` has the same settings as `baseline` and is named to be read next to `tools-selection-local`.

## Read a report

A report starts with a notice that it comes from a scripted agent, and gives, per run and summed per configuration, raw counts and rates. It does not compute differences between configurations. Real output, two shipped tasks (`context-overload`, `agent-loop`) under three configurations, aggregated:

| Config | Runs | Successes | Success rate | Criteria met | Attempts | Escalations | Guard trips | Context overflows | Items elided | Unexecuted verifications | Cost (simulated units) | Duration (simulated units) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | 2 | 1 | 0.5000 | 2/5 | 8 | 2 | 10 | 0 | 3 | 3 | 138549 | 33 |
| `context-none` | 2 | 0 | 0.0000 | 0/5 | 7 | 2 | 10 | 1 | 0 | 5 | 64095 | 23 |
| `guard-off` | 2 | 1 | 0.5000 | 2/5 | 11 | 3 | 0 | 0 | 3 | 0 | 497319 | 98 |

(Columns for the criteria rate, tier escalations, items summarized, information-loss failures, tool-selection misses and the tool-definition token estimates are omitted here; for `baseline` the first four were 0.4000, 1, 0, 0.) What this table can be read to say: with the guard off, the same two scripted tasks ran for more attempts (11 against 8) and more simulated cost before the scripts ended them; with no context management, the window overflowed once. That is a statement about what the components did on these trajectories. It is not a statement that the guard or the elision "helps a model".

| Metric | Meaning |
|---|---|
| Success | Every acceptance criterion is met. Success rate is successes divided by runs |
| Criteria met | Criteria whose `verify` steps all ran and passed in the final attempt of their subtask |
| Attempts | Attempts started, over all subtasks |
| Escalations | Times the local policy answered "escalate" after a failed attempt |
| Tier escalations | Attempts that ran at a higher tier than the first attempt of their subtask |
| Guard trips | Guard verdicts other than "continue", in total and by rule |
| Context overflows | Steps after which the context exceeded the window |
| Items elided, items summarized | Items the context manager replaced by a stub or folded into a summary |
| Information-loss failures | Attempts ended because a required item had been elided or summarized |
| Unexecuted verifications | `verify` steps that did not run in the final attempt of their subtask |
| Tool-selection misses | Steps whose tool had been dropped by selection and was restored |
| Est. tool-definition tokens offered, selected (approximate) | Sums of rough, hand-set constants per tool (`approx_definition_tokens` in the tool registry), for the agent's whole list and for the selected list. Estimates for comparison, not measurements for any model or client |
| Cost (simulated units) | Sum over steps of tokens in context times a constant per tier (economy 1, standard 3, premium 15) |
| Duration (simulated units) | One unit per step, one for the plan; concurrent subtasks overlap |

If you want to compare two configurations, put two rows side by side and say which mechanism differs. Do not write that one is faster, cheaper or better.

## Write a task

A task is one JSON file, validated against `src/wev_skills/schemas/eval-task.schema.json` and then checked for consistency. Start from a shipped one in `evals/tasks/` and run `eval validate` after every edit. This task was written and run for this guide:

```json
{
  "id": "retry-once",
  "title": "A verification that passes only on the second attempt",
  "description": "Exercises the attempt limit: with one attempt the task fails, with two or more it passes.",
  "category": "failing-test",
  "signals": { "objective": "Make one scripted check pass", "files_touched_estimate": 2, "unknowns": 1, "independent_subtasks": 1 },
  "window_tokens": 8000,
  "acceptance_criteria": [ { "id": "check-passes", "text": "The scripted check passes." } ],
  "subtasks": [ { "id": "work", "files": ["a.py"] } ],
  "script": [
    { "id": "edit-a", "subtask": "work", "kind": "edit", "tokens": 60 },
    { "id": "check", "subtask": "work", "kind": "verify", "signature": "make test", "tokens": 40,
      "criteria": ["check-passes"], "conditions": { "pass_from_attempt": 2 } }
  ]
}
```

```text
$ wev eval validate mytasks/retry-once.json
{"valid": true, "path": "mytasks/retry-once.json", "id": "retry-once", "subtasks": 1, "steps": 2}

$ wev eval run --tasks-dir mytasks --config attempts-1 --config baseline --format md
  baseline    1 run  1 success  attempts 2  guard trips 0
  attempts-1  1 run  0 successes attempts 1  guard trips 1
```

A task whose acceptance criterion has no `verify` step fails validation (exit 2):

```text
{"error": {"code": "invalid_eval_task", "message": "Invalid eval task mytasks/bad.json: Criterion check-passes is not supported by any verify step.", ...}}
```

Fields:

| Field | Meaning |
|---|---|
| `id`, `title`, `description` | Identification; `description` is optional |
| `category` | `simple-fix`, `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop`, `remote-diagnosis` or `tool-selection` |
| `signals` | Task signals; the local policy classifies them, and the classification sets the starting tier, whether `planning: auto` plans, and whether subtasks may run in parallel |
| `window_tokens` | Context window of each subtask |
| `acceptance_criteria` | `{id, text}`; each needs at least one `verify` step |
| `subtasks` | `{id, depends_on, files, objective, read_only}`; each runs as one delegated agent with its own context. `objective` and `read_only` are optional and are read by tool selection |
| `script` | Ordered steps with `id`, `subtask`, `kind` and the fields the kind needs |

Step kinds: `tool_output`, `note`, `requirement`, `decision` (add an item of `tokens` tokens to the context; requirements and decisions are pinned), `command` (a guard event with a `signature`; `outcome: fail` makes it fail; `repeat`, `polling`, `flaky`), `edit` (a progress event), `verify` (decides the listed `criteria`; a failing verification ends the attempt), `handoff` (a hand-off event). Any step may set `tokens`; `needed_later: true` marks an item a later step requires; `needs_tool` names the tool the step stands for. Conditions make the outcome depend on the configuration: `requires_verbatim: [ids]` (fails if a listed item was elided or summarized), `pass_from_attempt: N`, `min_tier: T`. The full rules are in [evals/README.md](../../evals/README.md) and the skill reference `skills/wev-harness-evaluation/references/task-fixtures.md`.

Write fixtures that exercise one mechanism, say in `description` what it exercises, and keep step texts as filler. A task added to `evals/tasks/` changes the committed baseline report, so regenerate it as shown above or the test that compares it will fail.

## The limits of scripted evaluation

- The script decides every outcome. The tables show that a mechanism fired, not that it is useful.
- Token counts are estimates (characters divided by 4) and item texts are filler.
- Costs and durations are constants chosen for this harness. They match no provider's prices or latencies.
- Recall of archived originals is not modelled: an elided item counts as lost to a step that requires it.
- A scripted agent cannot change strategy. A guard verdict that asks for a new strategy only ends the attempt.
- The shipped tasks are examples, not a benchmark. Their pass rates must not be quoted as one.
- The mechanisms that the research paper motivates (staged compaction, conditional planning, tool profiles, plan reminders and others) are implemented as configurable defaults whose effect on a real model has not been measured. See `docs/research/hypotheses.md` and `docs/research/experiments.md`.

## Evaluating with a real model

Future work; not implemented. It needs a model provider, which this repository does not call (unit tests and CI run without a paid provider), an agent that implements the harness agent interface by calling a model, tasks backed by real repositories and real checks, repeated runs per task and configuration, and a record of model identifiers, dates and raw outputs. Until such a run is made and recorded, the hypotheses stay untested.
