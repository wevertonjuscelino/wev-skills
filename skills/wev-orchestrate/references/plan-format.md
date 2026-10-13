# Plan file format

`plan set --file plan.json` validates the file, stores it, and assigns an agent and a model to each task. Only these keys are allowed (extra keys are rejected):

- Top level: `objective` (string, required), `tasks` (array, required).
- Each task: `id` (required; letters, digits, dot, underscore, hyphen; at most 64 characters), `title` (required), `objective` (required), `depends_on` (list of task ids), `files` (list of paths the task edits), `risk` (`low`, `medium` or `high`), `acceptance_criteria` (list of statements), `checks` (list of checks run by `task check`: a command string, or an object `{"command": ..., "criteria": [...]}` that ties the command to specific acceptance criteria by zero-based index or by exact text; at least one criterion per object), `agent_hint` (string), `read_only` (boolean; true for a task that changes no files, such as a review, an audit or research), `status` (set by the engine; leave it out).

Guidance:

- Write acceptance criteria as statements that a check can prove. `task check` marks a criterion `met` only with evidence from a passing check; a criterion without evidence stays `unverified`.
- Put the real commands that prove the work in `checks`, for example the test command the engine discovered in `run start`. Prefer check objects that tie each command to the criteria it proves. A plain string supports every criterion and the report labels it untied (with a warning when the task has several criteria). The stored plan keeps the ties as `check_links`; do not write that key yourself.
- A check must be able to fail before the work is done. The engine runs each task's checks once when the task starts (the baseline); a check that already passed then, with no file changed since, does not verify the task. No-op checks (`true`, `echo`, `test` on constants, `exit 0`) carry no evidence. The agent's own `required_checks` are added to the task's checks.
- Mark a task `read_only` when it changes no files (review, audit, research). A task with no changed files is otherwise not accepted as verified, and baseline detection does not apply to a `read_only` task.
- List every file a task edits in `files`. The engine does not offer two tasks together when their files overlap, and it uses `depends_on` to order the rest.
- Agents are routed by whole-word match between the task's title and objective and each agent's specialties (weighted most) and description. A task that matches nobody goes to the default agent (`agents.default_agent` in the config, `senior-engineer` unless changed). Outside plan mode a task goes to an agent that may change files, unless it is marked `read_only` or names a read-only agent in `agent_hint`: mark reviews and audits `read_only` so they reach `code-reviewer` or `security-auditor`.
- `plan set` prints `warnings`: a check that will need approval at execution time (for example inline interpreter code such as `python3 -c ...`; use a script file or a named test instead), a check that will be refused, and a path in `files` or in a check's arguments that git ignores (the tree fingerprint does not cover ignored files). Once a task has ever been started, `plan set` refuses to change its criteria, checks, files, risk or `read_only` flag unless given `--amend --reason <text>`; the amendment is recorded, resets that task's verification and is listed in the report under "Plan amendments". The engine does not judge whether the new criteria are weaker.
- `agent_hint` is a hint, not a command. The assigned agent is printed by `plan set` and `task next`; check it fits the task and ask the user if it clearly does not.
- In `plan` mode, `plan set` stores the plan for review and `task next` is refused with the code `plan_mode` (exit 3).

A complete valid sample is `${CLAUDE_PLUGIN_ROOT}/examples/plan.example.json`.
