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
