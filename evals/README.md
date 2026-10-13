# Scripted evaluation

Versão em português: [README.pt-BR.md](README.pt-BR.md).

> Results in this directory come from a scripted agent that replays fixed trajectories. No model is called. They measure harness mechanics only, use simulated cost and duration units, and are not evidence about the performance of any model.

## What this is

`wev eval` runs every task in `tasks/` under every configuration in `baselines/configs.json`. A scripted agent replays each task's fixed list of steps against the real engine components:

- the context manager (`wev_skills.context`), which receives every item and applies the configured compaction policy;
- the execution guard (`wev_skills.guards`), which receives real guard events and returns real verdicts;
- the model router (`wev_skills.models`) and the local decision policy (`wev_skills.decisions`), which classify the task, pick the tier of each attempt and decide on escalation.

What is not exercised: the harness has its own attempt loop and its own scheduler (`wev_skills.evaluation.agent` and `wev_skills.evaluation.harness`). It does not call the orchestration engine, so the engine's run and task flow (`wev run`, `wev task`), its retry and attempt accounting, baselines, approvals, permission policy and verification engine are not covered by these results. No command is executed. Retries, scheduling and parallelism in a report are the harness's own reimplementation, kept deliberately simple; they say how the components answer on a scripted trajectory, not how the engine orchestrates.

The agent does not reason. Whether a step passes is written in the task file, sometimes as a condition on the configuration. The harness is therefore a test bench for the components: it shows that thresholds, guards, routing and escalation decisions behave as designed on trajectories built to exercise them. Everything is deterministic: there is no randomness and no wall-clock time, so two runs produce byte-identical reports. Evidence label for every result here: **simulated with mocks**.

## How to run

From the repository root, with no installation and no network:

```sh
PYTHONPATH=src python3 -m wev_skills eval list
PYTHONPATH=src python3 -m wev_skills eval run
PYTHONPATH=src python3 -m wev_skills eval run --task context-overload --config baseline --config context-none
PYTHONPATH=src python3 -m wev_skills eval run --format md --lang pt-BR --out /tmp/report.md
PYTHONPATH=src python3 -m wev_skills eval validate evals/tasks/simple-fix.json
```

`eval run` options: `--tasks-dir DIR`, `--configs FILE`, `--task ID` and `--config ID` (both repeatable), `--out FILE`, `--format json|md`, `--lang en|pt-BR`. Without `--out` the JSON report is printed; with `--format md` and no `--out` the Markdown text is printed inside a JSON object, in its `content` field, because the CLI always prints JSON. The defaults point at this directory, found relative to the source tree. When the package is installed without the repository the directory does not exist and the command fails with `evals_dir_not_found`; pass `--tasks-dir` and `--configs`.

`reports/scripted-baseline.json` and `reports/scripted-baseline.md` are the committed output of the shipped tasks and configurations. A unit test fails if running the harness no longer reproduces them byte for byte. After changing a task, a configuration or a component, regenerate both:

```sh
PYTHONPATH=src python3 -m wev_skills --lang en eval run --out evals/reports/scripted-baseline.json
PYTHONPATH=src python3 -m wev_skills --lang en eval run --format md --out evals/reports/scripted-baseline.md
```

## Shipped tasks

| Task | What the script exercises |
| --- | --- |
| `simple-fix` | Control: nothing depends on the configuration. Only simulated cost and duration differ. |
| `multi-file-feature` | Subtasks declared out of dependency order, two subtasks sharing a file, one verification that passes only at the premium tier. |
| `failing-test` | A verification that passes only from the second attempt. |
| `context-overload` | Six large tool outputs in a small window, a trace needed later, and a note that summarization replaces. |
| `agent-loop` | Three loops with no exit: a failing command retried unchanged, a passing command repeated, two agents handing work back and forth. No configuration can succeed. |
| `remote-diagnosis` | Polling a remote command (must not count as a loop) and long notes that elision cannot remove. |
| `two-file-change` | Control for capability profiles: classified simple (two files, low risk), so automatic planning plans it for an economy executor and not for a standard or premium one. |
| `tool-selection-miss` | Per-task tool selection: a read-only subtask that gets a shorter tool list, and a subtask scripted to need a tool the local policy drops, which is recorded as a miss and restored. |

## Shipped configurations

Each configuration changes one setting of `baseline` (planning on, elision at 0.6, 3 attempts, sequential, policy routing, guard on, executor tier auto, structured tools), except the two capability profiles, which set a group of settings together.

| Comparison | Configurations |
| --- | --- |
| Planning | `baseline` (on), `planning-off`, `planning-auto` (plan when the local policy asks for one) |
| Context | `context-none` (unmanaged), `baseline` (elision), `context-elide-aggressive`, `context-elide-summarize` |
| Routing | `baseline` (policy), `routing-fixed-standard`, `routing-fixed-premium` |
| Scheduling | `baseline` (sequential), `parallel-3` |
| Attempt limit | `attempts-1`, `attempts-2`, `baseline` (3), `attempts-4` |
| Guard | `baseline` (on), `guard-off` |
| Capability profile | `profile-economy` (planning auto, economy executor, every attempt at the economy tier, tool profile auto), `profile-premium` (the same at the premium tier) |
| Tool profile | `baseline` (structured), `tools-lean` |
| Tool selection | `tools-selection-off` (the same settings as `baseline`), `tools-selection-local` |

The executor tier decides whether `planning: auto` makes a plan. A tool profile only changes which tools of a fixed reference agent (`Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash`) a run lists: the scripted agent calls no tool, so `tools-lean` has the same counts as `baseline`, apart from the estimated tool-definition tokens of the shorter list. Neither row says anything about whether a profile helps a model.

Tool selection (`tool_selection`: `off` or `local`) hands each subtask the tools the local policy selects for its `objective`. A step may name the tool it stands for with `needs_tool`. With selection on, a step whose tool was dropped records a miss and the tool is restored from the reference agent's own list; a tool outside that list fails the subtask as `tool_unavailable`. With selection off no step checks its tool. The report's tool-definition token columns are sums of rough, hand-set constants per tool (`approx_definition_tokens` in the tool registry): estimates for comparison, not measurements for any model or client.

The summarizer used by `context-elide-summarize` is a stub that keeps the first 60 characters of each text. It is not a model and does not understand what it shortens.

## How to write a task

A task is one JSON file validated against `src/wev_skills/schemas/eval-task.schema.json` and then checked for consistency. Run `wev eval validate <file>` while writing it.

| Field | Meaning |
| --- | --- |
| `id`, `title`, `description` | Identification. `description` is optional. |
| `category` | One of `simple-fix`, `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop`, `remote-diagnosis`, `tool-selection`. |
| `signals` | A `TaskSignals` object. The local policy classifies it; the classification sets the starting tier, whether `planning: auto` plans, and whether subtasks may run in parallel (`independent_subtasks` of 2 or more). |
| `window_tokens` | Size of the context window of each subtask. |
| `acceptance_criteria` | List of `{id, text}`. Each must be supported by at least one `verify` step. |
| `subtasks` | List of `{id, depends_on, files, objective, read_only}`. Each subtask runs as one delegated agent with its own context. `objective` and `read_only` are optional and are read by tool selection. |
| `script` | Ordered steps. Each has `id`, `subtask`, `kind`, and the fields its kind needs. |

Step kinds:

| Kind | Effect |
| --- | --- |
| `tool_output`, `note`, `requirement`, `decision` | Adds an item of `tokens` tokens to the context. Requirements and decisions are pinned by the context manager. |
| `command` | Emits a command guard event with `signature`; `outcome: fail` makes it a failing command, which does not end the attempt. `repeat` emits it several times. `polling` and `flaky` are passed to the guard. |
| `edit` | Emits a progress guard event with a new fingerprint. |
| `verify` | Emits a verification guard event and decides the listed `criteria`. A failing verification ends the attempt. |
| `handoff` | Emits a hand-off guard event from `from_agent` to `to_agent`. |

Any step may set `tokens` to also add an item to the context. `needed_later: true` marks an item that a later step of the same subtask requires. `needs_tool` names the tool the step stands for (see tool selection above).

Conditions (`conditions` on any step) make the outcome depend on the configuration. An unmet condition ends the attempt as failed.

| Condition | The step fails when | Models |
| --- | --- | --- |
| `requires_verbatim: [ids]` | a listed item was elided or replaced by a summary | information lost by compaction |
| `pass_from_attempt: N` | the attempt number is lower than N | work that succeeds only on a retry |
| `min_tier: T` | the attempt runs at a tier below T | work that succeeds only at a given model tier |

Rules the harness applies, all mechanical:

- The context overflows when its estimated tokens exceed `window_tokens` after a step. Overflow and information loss end the subtask without a retry, because a retry replays the same trajectory under the same policy.
- A new attempt starts with a fresh context. The router is given the number of failed attempts, so the tier rises from the third attempt under policy routing.
- The guard is asked after every step and after every failed attempt. `change_strategy` and `reduce_scope` end the attempt; any other verdict ends the subtask. A verdict already acted on is not counted twice.
- With a plan, subtasks start in declaration order as soon as their dependencies succeeded, a slot is free and no running subtask shares a file. Without a plan, they run one at a time in declaration order and a subtask reached before its dependencies is blocked.
- A subtask whose dependency failed is not executed.

## What each metric means

Reports give these per run and summed per configuration. They are raw counts and rates. The reports do not compute differences between configurations.

| Metric | Meaning |
| --- | --- |
| Success | Every acceptance criterion is met. Success rate is successes divided by runs. |
| Criteria met | Criteria whose `verify` steps all ran and passed in the final attempt of their subtask. A criterion is unmet when one failed, unverified when one did not run. |
| Attempts | Attempts started, over all subtasks. |
| Escalations | Times the local policy answered "escalate" after a failed attempt. |
| Tier escalations | Attempts that ran at a higher tier than the first attempt of their subtask. |
| Guard trips | Guard verdicts other than "continue", in total and by rule. |
| Context overflows | Steps after which the context exceeded the window. |
| Items elided, items summarized | Items the context manager replaced by a stub or folded into a summary. |
| Information-loss failures | Attempts ended by `requires_verbatim`. |
| Unexecuted verifications | `verify` steps that did not run in the final attempt of their subtask. |
| Cost (simulated units) | Sum over steps of tokens in context multiplied by a per-tier constant (economy 1, standard 3, premium 15). Not money. |
| Duration (simulated units) | One unit per step, one for the plan; concurrent subtasks overlap. Not time. |

## Limits of scripted evaluation

- The script decides every outcome. A configuration "passes" a task because the task was written so that it would. The tables show that the mechanism fired, not that it is useful.
- Token counts are estimates (characters divided by 4), and the item texts are filler.
- Costs and durations are constants chosen for this harness. They do not correspond to any provider's prices or latencies.
- Recall of archived originals is not modelled: an elided item counts as lost to a step that requires it.
- A scripted agent cannot change strategy. A guard verdict that asks for a new strategy only ends the attempt.
- The shipped tasks are examples that exercise mechanisms. They are not a benchmark and their pass rates must not be quoted as one.

No report from this harness may be used to claim that a configuration improves success, cost or speed for a model. See [`docs/research/experiments.md`](../docs/research/experiments.md) for which questions the scripted agent can answer and which need a model.

## Evaluating with a real model

This is future work. It is not implemented, and **no real-model results exist** for this project.

It needs a model provider, which this repository does not call: unit tests and CI run without a paid provider. A real-model run would need an agent that implements the harness agent interface by calling a model, tasks backed by real repositories and real checks instead of scripts, repeated runs per task and configuration, and a record of model identifiers, dates and raw outputs. Until such a run is made and recorded, the hypotheses in [`docs/research/hypotheses.md`](../docs/research/hypotheses.md) remain untested.
