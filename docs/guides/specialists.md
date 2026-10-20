# Project specialists and engine budgets

[Português brasileiro](specialists.pt-BR.md).

Create a project specialist from a resolved catalog role:

```sh
bin/wev specialists create project-engineer --template senior-engineer --specialty implementation
bin/wev specialists list
bin/wev specialists export --lang en
```

Specs live in `wev-specialists/` by default (`agents.project_dir`). They are discovered by
routing and by `wev agent` commands automatically. Exports live in `.claude/agents/`.
Creation preserves the role's tools, permission limits, model policy and checks. A project
can hold at most `specialists.max_per_project` specialists (default five). Existing ids
are never overwritten by creation. Specialist directories and files cannot be symlinks.

After running and verifying work assigned to a specialist, rebuild its observations:

```sh
bin/wev specialists learn project-engineer
bin/wev specialists export --lang en
```

Learning only proposes. A new lesson has status `proposed` and is not shown anywhere until
the person at a terminal accepts it; a lesson the engine accepted before this step existed
(`accepted_by` is `engine`) is proposed again, and is not shown even before learning runs
again. The operator reviews the lessons in
`wev specialists list` and decides each one:

```sh
bin/wev specialists accept project-engineer lesson-0123456789abcdef01234567
bin/wev specialists retire project-engineer lesson-0123456789abcdef01234567
```

Both are human-operator commands, like `approval grant`: they need a terminal on stdin and
stdout, show the lesson, its full text, its authored excerpts and note, and its evidence, ask
for a word printed on screen, and record the operating-system user in `accepted_by` and the
user and terminal in the audit log. The audit event is written before the specialist file,
so a failed audit leaves no decision. If the lesson changed after it was shown, nothing is
decided (exit 5) and the command must be run again. The user name `engine` is reserved and
refused. An agent never runs them; the plugin's Bash hook answers `ask` for them. Acceptance
and retirement survive relearning, and when more lessons are found than the cap allows,
proposals are dropped before decided lessons; counters keep being recalculated.

Learning recalculates counters from stored engine runs, so running it again does not add
confirmations. A successful check contributes only for a verified task with an `all_met`
verification. Failed checks count as contradictions; guard trips become pitfalls. Trivial
checks, baseline runs, review prose and model notes do not become lessons. Check signatures
identify the recorded commands without turning command text into agent instructions.
The lesson points to the latest supporting run, task and record timestamp.

At most 30 lessons are stored, even when calling the learning function directly. Active
lessons rank ahead of stale ones, then by confirmations and contradictions. Lessons unseen
for `specialists.stale_after_runs` runs (default 20) become stale. At most
`specialists.max_lessons_rendered` active lessons appear in exports and task contracts
(default 12), with a separate character cap. Experience is advisory and cannot widen tools
or permissions. Rebuilding uses the local retained history; deleting history also removes
its contribution to counters. Files remain subject to the engine's local state trust
boundary: learning does not authenticate externally supplied or manually modified states.

`task start` records the ids of the lessons its contract shows as a `lessons.shown` event
in the run's `events.jsonl` (they also appear as `lessons_shown` in the `task.started` audit
event). They are kept out of `state.json`, so a run stays resumable by release 2.0.0, which
refuses fields it does not know there; runs written by 3.0.0 keep the ids in a
`lessons_shown` field of the task, which is still read and counted. Before it commits, the start reads the specialist's
file again under the lock that `specialists accept` and `specialists retire` take; if the
file is gone or its lessons changed since the command loaded them, the start is refused
(`lessons_changed`, exit 5) and must be run again. The event is written only after the state, so
every record is a start that happened; a process that dies between the two leaves that
start uncounted rather than crediting a lesson that was never shown. Each record names the
agent, and learning counts only records for the agent that ended the task; ids a 3.0.0 run
kept on the task count only while no record shows another agent. Learning reads the events
only of runs of this repository. A decision made after the start applies from the next start.
Learning then counts, per lesson, the
agent's tasks that were shown it and ended verified (`shown_verified`) or failed, blocked or
partial (`shown_unverified`); tasks that have not ended count in neither.

Ranking uses these counters conservatively, against the agent's own average: the verified
share over every ending of its active lessons, recomputed at each learning, so the bar moves
as the agent improves or gets worse. Each lesson's share is pulled toward that average by
three virtual tasks, so a lesson with few endings stays near it. A lesson with at least three
endings whose adjusted share is more than 0.1 below the average goes after the others. Its
rate never promotes a lesson, and never hides or retires one: a demoted lesson still counts
toward the rendered cap, keeps its counters and moves back once its share recovers. A
correlation between a lesson and an outcome is not evidence that the lesson caused it.

In a task contract, a lesson learned from a check the task will run (same argv) goes
before the other lessons, after the demotion above; relevance never hides a lesson and does
not lift a demoted one. Exported subagents have no task, so they keep the plain order.

The whole-run budget uses engine command units, **not currency or model tokens**:
`limits.run_budget_units` defaults to 400, and `limits.run_max_attempts_total` defaults to
12 task starts. Local execution, verification checks, baseline checks and recorded remote
starts each consume one unit. Commands outside an active run are outside this accounting.
State payloads warn at 80% of either limit; at 100% of command units the engine refuses new
work. The task-start cap refuses additional starts while allowing the last admitted task
to finish. Task guard resets and human reopening do not erase whole-run spending.

Execution operations share a run lock. Batches are checked against their maximum command
count before running, so a batch that might exceed the remaining budget is refused in
advance. A started remote process may continue after the run reaches its limit; this
budget does not terminate processes. Task budgets and their existing guards still apply.

Learning uses only runs whose recorded repository matches the current project; records
without a repository identity and runs belonging to another project are ignored.
