# Orchestration guide

Portuguese version: [orchestration.pt-BR.md](orchestration.pt-BR.md).

This guide describes how a multi-step task moves through the engine, command by command. The skill `wev-orchestrate` tells Claude Code to do the same thing when `wev jev status` reports `orchestration` `wev`, and to use the harness's own flow when it reports `harness`; you can also drive every step by hand. Every output below was produced on 2026-10-13 by running the real CLI in a temporary git repository (a `Makefile` with a `test` target). Outputs are shortened where marked; paths in logs are shortened to `.wev/...`.

In this guide `wev` stands for `"$WEV_HOME/bin/wev"` or a symlink to it (see the [installation guide](installation.md)).

## What the engine is, in one paragraph

The engine is a guardrail for a fallible agent and a recorder of decisions. It is not a security boundary against an adversarial agent in the same user account. The human gate is Claude Code's permission prompt, reached through the plugin's hook; without the plugin's hooks, approvals are records. Read the [security guide](security.md) before you rely on any control described below.

## The flow

`REQUEST → DISCOVER → CLASSIFY → PLAN → DECIDE → EXECUTE → VERIFY → REVIEW → DELIVER`

The engine records the phase and refuses steps that skip one. You move it forward with commands; the model does the reasoning and the editing. What each phase does is in the [architecture](../architecture/architecture.md), section 2.

The commands are covered by unit tests and by the CLI flow integration test. How well a model follows the `wev-orchestrate` skill in a live Claude Code session has not been observed.

## Runs, configuration and the active run

- A repository has **one active run** at a time. `wev run start` is refused (`run_active`, exit 5) until `wev run finish` ends the current one. A run's mode never changes.
- Commands without `--run` use the active run. Pass `--run ID` only to read an old run.
- The state directory (`.wev/` by default) is resolved at the repository root, whatever directory you run in. It carries its own `.gitignore` that ignores everything in it, so nothing needs to be added to the project's.
- **The configuration is pinned.** At `run start` the engine resolves it (`--config PATH`, else `<repository root>/wev.config.json`, else the defaults) and stores it in the run. Every later command of that run uses the stored one, and a different `--config` is refused (`config_pinned`). To change the configuration, finish the run and start another. See the [configuration guide](configuration-and-providers.md).
- Every answer has `next_step` (the first thing to do) and `next_steps` (a list of everything that can be done now). Where only a person can act, the step is an instruction to stop and ask, never a command an agent could run to approve itself.

## Modes

| Mode | Effect |
|---|---|
| `plan` | Investigate only. The engine refuses commands that are not read-only (`exec` exits 3 with `permission_denied`), refuses `task next` (`plan_mode`, exit 3) and starts nothing remotely. |
| `execute` | Act within the permissions granted. A permission to act is not blanket authorization: risky commands still need approval. Ordinary mutation (`mv`, `sed -i`, redirections, running a script) is how work gets done and is not gated. |
| `auto` (default) | The engine picks the flow from the classification, so a one-line change gets no ceremony. |
| resume | Not a mode you start a run in. `wev run resume` reloads an existing run and compares it with the real repository; the run keeps the mode it began with. |

## The commands, in order

### 1. Start: request, discover, classify

```text
$ wev run start --objective "Add a greeting file" --files 1 --run-id demo-1
```

The answer (shortened) holds the run id, the classification, the strategy, the pinned configuration and the checks the engine discovered by reading `Makefile`, `package.json`, `pyproject.toml`, `Cargo.toml` and `go.mod` as data (nothing is executed). The discovered text came from the repository, so it comes back sanitized and fenced as untrusted data:

```json
{
  "run_id": "demo-1",
  "mode": "auto",
  "classification": { "complexity": "trivial", "risk": "low", "uncertainty": 0.0, "parallelizable": false, "source": "local-policy" },
  "strategy": { "flow": "direct", "needs_plan": false, "needs_independent_review": false, "needs_approval": false, "max_parallel": 1, "max_attempts": 3 },
  "discovery": { "untrusted": true, "source": "repository discovery", "count": 1,
                 "text": "<<<WEV_UNTRUSTED_DATA id=... source=\"repository discovery\">>>\n...\nmake test  [Makefile, test]\n<<<END_WEV_UNTRUSTED_DATA id=...>>>" },
  "config": { "source": "defaults", "digest": "b382..." },
  "next_step": "wev task next --run demo-1",
  "next_steps": ["wev task next --run demo-1"]
}
```

The signals are your estimate, not a measurement; wrong signals produce a wrong strategy. The flags are `--files`, `--unknowns`, `--subtasks`, `--remote`, `--production`, `--destructive`, `--external`, `--no-tests` and `--irreversible`, or `--signals-file`. When unsure, overestimate. The engine also reads the objective text: words in English and Portuguese that name production, destructive operations, deploys, remote systems, credentials or schema changes raise the matching signal (a floor under your flags, with false positives and misses; it never lowers anything). To preview a decision without starting a run, use `wev classify`, `wev strategy` or `wev route-model` with the same flags. `--run-id` is optional; without it the engine generates one such as `20261013T144156Z-6db122`.

The flow decides the path:

| Flow | Meaning |
|---|---|
| `direct` | Low risk and small. The engine synthesizes one task, `task-1`, with the discovered check as its check. When no check was discovered, a plan must supply the checks (the answer says so). |
| `planned` | Write a plan first. Independent review is usually required. |
| `gated` | High risk. A human approves before work starts. |

With 8 files and 1 unknown the same repository gives risk `medium` ("about 8 files are touched (more than 5)"), flow `planned`, `needs_plan` true, `needs_independent_review` true and `next_step: wev plan set --file plan.json --run demo-2`.

### 2. Plan (planned and gated flows)

Write a plan file (format in the skill's `references/plan-format.md`; a complete sample is `examples/plan.example.json`) and store it:

```text
$ wev plan set --file plan.json
```

A plan's `checks` are command strings or objects that tie a command to the criteria it proves, by zero-based index or exact text:

```json
{ "id": "greet", "title": "Add greeting", "objective": "Create greeting.txt containing hello",
  "files": ["greeting.txt"],
  "acceptance_criteria": ["greeting.txt exists", "greeting.txt contains hello"],
  "checks": [ { "command": "test -f greeting.txt", "criteria": [0] },
              { "command": "grep -q hello greeting.txt", "criteria": ["greeting.txt contains hello"] } ] }
```

A plain command string supports every criterion and is labeled untied: it counts, but as weaker evidence, and the report and warnings say so. Tie checks to criteria whenever you can. The engine validates the plan, assigns an agent and a model to each task, and records both. A task's own `risk` can only raise the run's risk, never lower it, and the routing of agents is a heuristic: read the `agent_id` in each contract and decide whether it fits (the plan field `agent_hint` names one). Mark a task `read_only: true` when it should change nothing. `wev plan set` prints `warnings`: a check that will need approval at execution time (for example inline interpreter code such as `python3 -c ...`; use a script file or a named test instead), a check that will be refused, and a path in a task's `files` or a check's arguments that git ignores (the tree fingerprint does not cover ignored files, so a change there is not seen as work). Once a task has ever been started, `plan set` refuses to change its acceptance criteria, checks, files, risk or `read_only` flag unless given `--amend --reason <text>`. An amendment is recorded as a decision and a `plan.amended` audit event, resets that task's verification and is listed in the report under "Plan amendments" with before and after. The engine does not judge whether the new criteria are weaker, and whoever can run `plan set` can amend. Adding tasks and changing tasks never started stays free. `wev plan show` prints the stored plan. In `plan` mode this is where you stop and show the plan to the person.

Before storing a plan, the `wev-orchestrate` skill asks for a deeper plan, not a bigger one: for each task, what a leading practitioner would add, which primary material (logs, raw data, source) they would start from, which methods and tools they would use, and which command would show the result is right. Each answer becomes a criterion or a check, or is dropped; a demanding target belongs in the criteria only when a check measures it. In `planned` and `gated` flows the skill may add up to two reviewing agents from `wev agent list` whose work brings another field (for example `security-auditor`), each producing something checkable: they run before `task review`, a check they propose joins the task with `wev plan set --amend --reason <text>`, and their findings go into the review summary. Primary sources reach a subagent only when the plan task's `objective` names them; the engine does not add them. These are instructions to the model, not engine rules (documented only); what the engine enforces is the rest of this section.

### 3. Decide and execute: one contract, one agent

```text
$ wev task next
```

`task next` returns the contracts of the tasks that may start now: objective, context, scope, exclusions, constraints, acceptance criteria, checks (with `check_links` and `required_checks`), response format, permissions, `agent_id`, `model`, `risk`, and from the agent spec `max_attempts`, `timeout_seconds`, `budget_units`, `may_mutate`, `may_use_remote`, `success_criteria`, `stop_conditions` and `escalation`. The engine enforces `required_checks`, the budget, the attempts, the timeout, `may_mutate` and the agent's modes and maximum risk; `success_criteria`, `stop_conditions`, `escalation` and `output_format` are instructions the agent receives and nothing checks them. It offers at most `max_parallel` tasks, none with unverified dependencies, and never two whose `files` overlap (a task without `files` runs alone). `deferred` lists the rest with the reason. Starting a task that is not offered is refused (`task_not_startable`, exit 2).

One of the constraints, and a line of the run brief that the hooks show, is the owner's non-negotiable rule: follow YAGNI and prefer the solution with less code. The base agent template carries it as a responsibility, so every agent that extends it receives it too. It is an instruction to the model; nothing in the engine checks it. The brief drops that line before the next step when its character limit is tight.

Start the task, hand its contract to exactly one agent, and have commands run through the engine so they are permission-checked, logged and loop-guarded:

```text
$ wev task start task-1
$ wev exec -- touch greeting.txt
```

`task start` counts as an **attempt** (every start counts), and it **runs the task's checks once as a baseline** (`harness.baseline_checks`, default on). The answer shows which checks already passed before any work:

```json
"baseline": { "taken": true, "passed": ["git diff --stat"], "failed": ["make test"], "skipped": [] }
```

In an execute run a command acts for a task that is `RUNNING`. `--task` must name a running task (a pending, finished or unknown id is refused and the error names the running tasks); without `--task` the only running task is used and the output says so (`task_implied: true` and a `task_note`); with no task running, or with several running and no `--task`, only read-only commands are accepted. So `may_mutate: false` and the task's risk do not depend on the caller naming the task. With two tasks running the caller still chooses which running task a command is for; the engine cannot tell which agent is typing. Plan mode is unchanged (read-only commands only). An agent with `may_mutate: false` may run through `wev exec` read-only commands, the task's own declared checks and the check commands discovered in the repository at `run start` (for example `make test`, `make lint`), by exact argv match; everything else is refused with `agent_read_only`. Those commands still go through the policy, so one that needs approval still needs it. Read-only `wev exec` commands do not count toward the no-progress window (a repeated identical command is still a loop), and reading in plan mode does not trip `no_progress`.

`wev exec` options: `--task`, `--timeout SECONDS`, `--polling` (the command only polls a long process; counts only for a running task that already ran a command, and a cap of `limits.max_polling_commands` consecutive polls applies) and `--flaky` (a known flaky test). The engine runs the argument vector directly, never through a shell, looks the program up only in `permissions.exec_path` (never in `$PATH`), records the resolved path, and returns the output tail redacted and fenced as untrusted data (`"untrusted_output": true`). The child process inherits your environment.

The engine fully governs only what passes through `exec`. With the plugin installed, a hook also checks plain Bash commands and sends the sensitive ones it can read to your permission prompt (see the [security guide](security.md)); it cannot see inside a script file or a program. Edits made with Claude Code's own file tools are not checked by the engine; the contract's `scope` and `exclusions` and the verification step are what catch them.

To see whether a command would be allowed without running it:

```text
$ wev check-command -- git push origin main     # exit 4
  "decision": {"outcome": "needs_approval", "reason": "Approval needed: the command pushes to a remote repository."}
```

`check-command` exits 0 (allow), 3 (deny) or 4 (needs approval). It does not file a request.

### 4. Verify

```text
$ wev task check task-1
```

This runs the task's checks and stores the evidence. If you ran it right after `task start`, with the repository as it was, the Makefile check fails (as it should: the file does not exist yet) and the criterion is `unmet`. After the work:

```json
{ "task_id": "task-1", "all_met": true,
  "report": { "criteria": [ { "criterion": "The objective is achieved and checked: Add a greeting file", "status": "met", "support": "untied" } ],
              "summary": "1 of 1 acceptance criteria met, 0 unmet, 0 unverified; 0 checks not run." },
  "baseline": "taken", "tree_changed": true, "warnings": [],
  "next_step": "wev task record task-1 --status verified --summary <text> --run demo-1" }
```

**What counts as evidence.** `verified` is strict, and the strictness is the point:

- A check that **already passed at the baseline, on a tree that has not changed since the task started**, shows nothing about the work. The real answer when a task is started on a repository where `make test` already passes and nothing is changed:

  ```text
  all_met: false
  warnings: ["Every passing check had already passed before any work and no file changed since the task started."]
  criterion reason: "The checks already passed before any work on this task and no file changed since it started, so they do not show the work was done."
  ```

  Recording `verified` then fails with `verification_required` (exit 2). Do the work, or write a check that fails until the work exists. A `read_only` task is exempt from this rule.
- A **no-op check** (`true`, `echo`, `printf`, `test` on constants, `sh -c 'exit 0'` and similar) carries no evidence. The list is a floor: a cleverer vacuous check is not caught, and the engine does not judge whether checks are sufficient. That is the plan author's job.
- An **untied** check (a plain string in a plan, or the discovered default check) supports every criterion but is labeled as weaker evidence in the report. A **tied** check supports only its criteria.
- **Manual evidence** (`wev task record ... --evidence-file F`, a JSON file with an `evidence` list where each item names its criterion in `kind` and its `ref`) counts only when the `ref` is an existing file under the run's log directory, under the run's evidence directory (`<state dir>/runs/<id>/evidence/`) or one of the files the task lists in the plan; any other existing file is refused and the error says so. To show a file or an output, run it through `wev exec` and reference the log. It is the agent's claim and the report labels it so.
- The working-tree fingerprint is **recomputed at `task record`**. If files changed after the passing `task check`, `verified` is refused (`tree_changed`); check again.
- A verified task that is not `read_only` and changed no file since it started does not make the run `complete`.

Then record the outcome the agent reported:

```text
$ wev task record task-1 --status verified --summary "greeting file added" --changed-file greeting.txt
```

Other statuses are `partial`, `blocked`, `failed` and `not_executed`; use them when they are the truth, and add `--blocker` for blocked work. `failed` needs a running task. `verified` without evidence is refused:

```text
$ wev task record parser --status verified --summary "too early"          # exit 2
{"error": {"code": "verification_required", "message": "Task parser cannot be recorded as verified: 1 acceptance criterion(s) have no passing check made after the task last started and no tested evidence.", "details": {"next_step": "wev task check parser --run demo-2"}}}
```

**Attempts and escalation.** Every `task start` counts. A failure records an attempt with an error signature. Escalation to a higher model tier fires at half of the attempts (rounded up) or when the same error signature repeats, whichever comes first; `next_model` in the answer names the model for the next attempt. When the attempts are used up, the task becomes `BLOCKED` and the next step tells you to ask a person. **Only a person reopens it**, in their own terminal (see "Steps only a person takes").

### 5. Review

When the strategy sets `needs_independent_review`, `task record` answers with a `task review` command as `next_step`. The reviewer must be a known agent other than the one that ran the task:

```text
$ wev task review parser --reviewer senior-engineer --verdict accept --summary "self review"      # exit 3
{"error": {"code": "self_review", "message": "Agent senior-engineer executed task parser and cannot review it."}}

$ wev task review parser --reviewer code-reviewer --verdict accept --summary "read the diff and the check output"
{"task_id": "parser", "reviewer": "code-reviewer", "reviewer_identity": "self-declared", "verdict": "accept", "task_status": "verified"}
```

A `reject` reopens the task with your summary as context. The engine records the reviewer name the caller gave (`self-declared`); it cannot tell whether that agent really read the diff, and several agents running on the same model are not statistically independent.

**Layered review (optional).** When `review.depth` is not `off`, run `wev review run` before `run finish`: it starts finders and verifiers (unattended `claude -p`, read-only tools), so start it from a terminal or in the background. Read the outcome with `wev review show`. Fix the code, or close a Nit or Pre-existing finding with `wev review resolve <finding> --as wrong|intentional|does-not-matter --reason "<words>"`. An Important finding is closed only by a person with `wev review dismiss`; an agent that thinks one is wrong stops and asks. Reaching `review.max_rounds` (default 3) trips the `review_rounds` guard (exit 6), which a person clears with `guard acknowledge`. With review on, `run finish` refuses an open Important finding (`review_open_important`), a stale or missing round (`review_stale`), a changed `REVIEW.md` or reviewer spec without an improving `specialists score --compare` record (`reviewer_unscored`) and a lowered review configuration (`review_config_weakened`). A plan for a medium or high-risk run needs `risk_notes` and `revert` (`plan_needs_revert`). Status: implemented and tested with fake agents; a real round is implemented but untested. See the [review guide](review.md).

### 6. Deliver and finish

```text
$ wev run report --format md
```

`wev run report --format pr` prints a pull request body instead (Summary, What was tested, Risk with tier, reasons and notes, How to revert, Review). A plan the engine synthesizes for a one-task run is exempt from the revert text, and the body says "Not given.".

Real report for the first run (shortened). The body is fenced as data, because it repeats text an agent wrote:

```markdown
# Delivery report: run demo-1

<<<WEV_UNTRUSTED_DATA id=... source="wev run record">>>
- **Objective:** Add a greeting file
- **Overall status:** complete
- **Classification:** risk low, complexity trivial
- **Strategy:** direct flow, up to 1 in parallel, up to 3 attempts

### task-1: Add a greeting file

- **Status:** verified
- **Evidence:** tested
- **Attempts:** 1

| Acceptance criterion | Result | Evidence | What stands behind it |
|---|---|---|---|
| The objective is achieved and checked: Add a greeting file | met | tested | Met by a check not tied to this criterion: a generic check passed, which is weaker evidence. |
...
## Guard trips
None.
<<<END_WEV_UNTRUSTED_DATA id=...>>>
```

The overall status is `complete` only when every task is verified (and, unless `read_only`, changed something) and every required review is accepted; otherwise `incomplete` or `blocked`, with a section "Why the run is not complete". Guard trips and their acknowledgements stay in the report. The report is recomputed when you ask for it (and at `run finish`), not continuously: the tree is compared with the one seen at the latest `verified` record, and if it differs and no task is running, every verified task whose checks have not passed on the current tree is reported as "verified, then changed" and the status is `incomplete` until `wev task check <id>` passes again (the `next_step` says so). A change made and reverted between two reports is not seen; while a task is running, changes count as that task's work. Present a report as it is: do not upgrade a label. When tool selection is on, the report has a section with the tools offered and selected and approximate definition-token estimates.

| Label in the report | Meaning |
|---|---|
| `tested` | A command ran, recorded an exit code and a log, and the check passed |
| `untested` | No evidence of a passing check |
| `mocked` | Evidence from a fake or simulated stand-in |
| `documented_only` | Described, not run |
| `blocked` | Could not be run or verified |

These map to the project's five labels (implemented and tested, implemented but untested, simulated with mocks, documented only, blocked). `--lang pt-BR` renders the Markdown report in Portuguese.

Finally close the run, whatever its outcome, so it stops being the active run and the hooks go quiet:

```text
$ wev run finish
{"run_id": "demo-1", "phase": "done", "complete": true, "next_step": "wev run report --run demo-1"}
```

A finished run keeps its record (`run status`, `run report` still work) and accepts no further changes (`run_finished`). `wev run finish` is one of the commands the hook sends to your permission prompt. Do not finish a run you still want to continue.

`wev run brief` prints the short plain-text summary of the active run that the hooks inject, fenced as data.

## Tool selection

`harness.tool_selection` (default `off`) can narrow the tools a task's agent is handed: `local` uses an offline policy, `provider` asks the decision provider. Selection is computed once per task, always keeps a floor (the read tools, the edit tool when the task changes files, the shell when the task has checks), and can only choose among the tools the agent already has. `wev select-tools --task-file task.json --agent senior-engineer` shows a selection without storing it. If a dropped tool turns out to be needed, restore it while the task runs:

```text
$ wev task tools task-1 --add Write --reason "the task needs a new file"
```

Only a tool the agent is allowed can be restored, and each restore is counted as a selection miss. See the [configuration guide](configuration-and-providers.md) for what is sent when the provider is JEV. No saving of tokens or improvement in task success has been measured.

## Exit codes

| Code | Meaning | What to do |
|---|---|---|
| 0 | Success | Follow `next_step` |
| 1 | Unexpected error, or an `exec` command that failed | Read the output; fix the cause |
| 2 | Usage or validation error (for example `verified` without evidence, a pinned configuration, a bad plan) | Fix the input or run the missing step |
| 3 | Permission denied (plan mode, protected path, self-review, host not in the inventory, an agent that may not do this) | Do not work around it; change the plan |
| 4 | Approval required | Stop and ask the human operator |
| 5 | State conflict (the run changed under you, or another run is active) | `wev run status`, then continue from the real state |
| 6 | Guard tripped | Change approach, or stop |
| 7 | Not found (run, task, agent, approval) | Check the id with `wev state list` or `wev plan show` |
| 8 | Remote or provider failure | Report it as it is |

Errors are JSON on stderr: `{"error": {"code", "message", "details"}}`.

## Steps only a person takes

Six commands are for the human operator: `wev approval grant`, `wev approval deny`, `wev approval request --reopen-denied`, `wev guard acknowledge`, `wev task reopen` and `wev review dismiss`. Each needs an interactive terminal on standard input and output, shows the full action and asks the person to type a word printed on the screen. There is no flag that skips this. An agent cannot run them and must not try to; it stops, shows the person what is needed and waits. A determined process can fake a terminal. With the plugin installed, Claude Code's permission prompt is reached for command lines the hook can read (the grant command typed directly, behind a known wrapper, or in an inline `sh -c`); a script the hook cannot see into, or a pseudo-terminal driven by one, is not stopped (see the [security guide](security.md)).

### Approvals

When a command needs approval (a recursive delete, a push, a production host), the engine files a request and exits 4. Real example:

```text
$ wev exec -- rm -rf build        # exit 4
{"error": {"code": "approval_required",
  "message": "Command needs approval: Approval needed: the command removes files recursively or without confirmation.",
  "details": {"approval_id": "apr-fbe3eac8c14c6768",
              "next_step": "Stop and ask the human operator: they review approval apr-fbe3eac8c14c6768 (wev approval show apr-fbe3eac8c14c6768) and, if they agree, run 'wev approval grant apr-fbe3eac8c14c6768' themselves in their own terminal. Do not grant it yourself; afterwards, retry the command that was refused."}}}
```

What a person does, in their own terminal:

```text
wev approval list --status pending
wev approval show apr-fbe3eac8c14c6768
wev approval grant apr-fbe3eac8c14c6768      # only after reading the exact command
```

and `wev approval deny <id>` to refuse or revoke. This guide does not run `grant` for the examples. The rules of a grant:

- It is bound to the **exact argv**, the **resolved working directory** and the **run** (for a remote action, the host alias too). A grant for a command with an external effect (`git push`, `gh pr merge`, `gh release create`, the `publish` entries) also records HEAD and the working-tree fingerprint and is usable only while both still match; one without that anchor fails closed, and `wev approval verify` reports a blanked anchor. The anchor does not cover other refs named in a push refspec, ignored files a publish command packs, or remote actions (see [SECURITY.md](../../SECURITY.md), "Known limits").
- It is **single use** and **expires** after `permissions.approval_ttl_seconds` (default 900). The execution that uses it consumes it. There are no reusable grants.
- A **denial is final** for that action in that run. "The same action" means the same words in the same order within the run: the working directory (`--cwd`), the stated risk, the reason, quoting, whitespace and how words are grouped into tokens do not produce a fresh request, and for a remote action the host alias is the first word, so a denial is per host. `wev approval request` returns the denied record and `wev exec` answers denied. The comparison is on words and does not resolve paths (`build` and `./build` differ), and the record is a file in the agent's account. A new run starts clean. Only the person can replace it with a fresh pending request, with `wev approval request --reopen-denied`; the grant itself is unchanged (exact argv, resolved directory, run, single use, expiring). When the gate is denied, `next_step` says so ("denied by the operator") and how the operator reopens it, never a grant command.
- A command whose text redaction would alter (it holds something that looks like a secret) is **refused**, not sent for approval, so the person never approves a masked version of what would run. Pass the secret through a file or an environment variable.
- A request records `requested_by`, a name the caller supplies (self-declared); a decision records the operating-system user, the terminal device and the time. Nothing compares the two, because inside one account the engine cannot tell requester from operator.
- Every decision is also in the audit log, and `wev approval verify` compares the approvals file with the log and lists mismatches (exit 1). This is tamper evidence for accidents; an agent that can write both files can forge both.

An agent may file a request ahead of time with `wev approval request --risk high --reason "..." --requested-by <agent> -- <command and arguments>`.

### Guard trips and acknowledgement

The execution guard watches the events the engine records (commands, hand-offs, attempts, verifications, progress, budget) and returns a verdict: `continue`, `change_strategy`, `reduce_scope`, `escalate`, `ask_human` or `stop`. It detects identical repeated commands, alternating command cycles, consecutive failures, exhausted attempts, hand-off cycles, no observable progress, budget and timeout overruns, repeated verification with no change in between, and polling beyond a cap. Real example, `limits.max_identical_commands` being 3: running `wev exec -- false` four times gave exit 1, 1, 6, 6 and then:

```text
$ wev guard check        # exit 6
{"action": "change_strategy", "rule": "identical_commands",
 "reasons": ["Command 972a67578a6d7c28 ran 4 times without progress (allowed 3).",
             "4 consecutive failures (limit 3); change strategy."], "run_id": "demo-4"}
```

Exit 6 means: change approach or stop and tell the person. When the same command keeps running after that advice, the verdict becomes `ask_human` (`ignored_loop`). While a `stop` or `ask_human` verdict stands for the run or the task, **`wev exec` and `wev task check` are refused** (`guard_tripped`, exit 6) and `task next` hands out no more work. Every trip is kept in the run and in the report even after it is cleared. Only a person clears it, in their own terminal:

```text
wev guard acknowledge --run <run id> [--task <task id>] --reason "why it is safe to continue"
```

The guard then counts again from that moment. A command that only polls a long process should be run with `--polling`.

### Reopening a blocked task

When a task has used its attempts it is `BLOCKED` and only a person can give it more:

```text
wev task reopen <task id> --reason "why it gets more attempts"
```

The attempt count restarts from zero; the history stays in the record. The agent reports the blocked task, shows the reason, and waits. An exhausted task cannot be recorded `not_executed`; its primary `next_step` is the instruction to ask the human to run `wev task reopen`, not `wev task next`.

`next_step` can be an instruction instead of a command: a pending approval; a denied gate; in plan mode once the plan is set ("ready for human review"; execution needs a new run in execute mode after `wev run finish`); a check on a tree nothing changed in (do the work, or mark the task `read_only` in the plan with `--amend --reason`). A stale approval (the check that needed it was replaced and `task check` now reports `all_met`) no longer blocks `next_step`; it is listed under `stale_approvals`.

## Resume

```text
wev state list
wev run resume --run <run id>
```

`run resume` compares the recorded run with the real repository. Real answer after a stray file appeared and a task was left running:

```json
{ "run_id": "demo-2",
  "drift": { "drifted": true, "head_changed": false, "branch_changed": false,
             "new_dirty_files": ["parser.py", "stray.txt"], "missing_files": [],
             "stale_running_tasks": ["notes"],
             "notes": ["Tasks recorded as running must be verified again, not assumed finished: notes.",
                       "2 file(s) are modified now that were clean when the run was recorded."] },
  "needs_reverification": ["notes"],
  "next_step": "..." }
```

Old records are claims, not facts. Run `wev task check` again for every task in `needs_reverification` before recording anything. State is written with revision checks and a lock (`limits.lock_timeout_seconds`), and a state file from an older layout does not load. `wev state drift` shows the same comparison without recording a decision, and `wev state show` prints the whole stored state.

## Hooks, in short

With the plugin installed, three hooks run while a run is known for the current directory, a parent up to the git root, or a path a command names. They re-inject the brief after compaction and with each prompt, and check Bash commands against the run's pinned policy. They answer `deny` or `ask`, never `allow`, and never read the approval store; the engine's own sensitive commands (the operator commands, `approval request`, `run start`, `run finish`, anything with `--config`, `agent create`, `agent export`, `remote start`, `remote stop`, `jev ask`, `jev batch`) go to the person's prompt when the hook can read the command line, directly, behind a known wrapper or in an inline `sh -c`; a script file or a program is opaque to it. Without a run the brief hooks stay silent and the Bash check judges commands under the built-in default policy (execute mode, medium risk; a repository configuration is not read); a problem in the Bash check becomes an `ask`. They have not been exercised in a live Claude Code session. Details and limits are in the [security guide](security.md); after `wev run finish` the brief hooks are quiet again and the Bash check falls back to the default policy.
