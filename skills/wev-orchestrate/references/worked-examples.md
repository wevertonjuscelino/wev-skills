# Worked examples

Both sequences were run with the real CLI on 2026-10-13 in a temporary git repository that held one commit with a `Makefile` whose `test` target prints a line and exits 0. State went to `.wev/` at the repository root. Outputs are summarized; the engine prints full JSON. Every answer carries `next_step` (one command) and `next_steps` (all the commands that may follow); they end with `--run <id>`, which may be left out because commands act on the active run. Run them with the plugin path as shown here.

## DIRECT run: one small change

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" run start --objective "Add a greeting file" --files 1
```
Answer: complexity `trivial`, risk `low`, flow `direct`, the discovery text listed one check, `make test  [Makefile, test]`, fenced as untrusted data.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task next
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task start task-1
```
The engine synthesized `task-1` with `make test` and the agent's required check `git diff --stat` as its checks, and one criterion taken from the objective. Starting it ran those checks once as the baseline: both passed, which shows only that the repository was healthy before the work.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" exec -- touch greeting.txt
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task check task-1
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task record task-1 --status verified --summary "greeting added" --changed-file greeting.txt
"${CLAUDE_PLUGIN_ROOT}/bin/wev" run report
"${CLAUDE_PLUGIN_ROOT}/bin/wev" run finish
```
`exec` answered with guard action `continue`. `task check` answered `all_met: true`; the criterion was `met` by an untied check, which the report labels as weaker evidence. It counted because the tree had changed since the baseline. Had `task check` run with no file change, the baseline checks would not have verified the task. The report status was `complete`. After `run finish`, a further `task record` fails with `no_active_run`.

## PLANNED run: tied checks and a read-only task

Config file `wev.config.json` at the repository root (it is pinned when the run starts):

```json
{ "harness": { "tool_selection": "local" } }
```

`plan.json` has two tasks. `parser` edits `parser.py` and has two criteria, `parser.py exists` and `make test passes`, with the checks `{"command": "test -f parser.py", "criteria": [0]}` and `{"command": "make test", "criteria": ["make test passes"]}`. `audit` depends on `parser`, is `read_only`, has the criterion `parser reviewed` and the plain check `make test`.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" run start --objective "Add parser" --files 8 --unknowns 1
"${CLAUDE_PLUGIN_ROOT}/bin/wev" plan set --file plan.json
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task next
```
Flow `planned`, independent review required, `config.source` pointing at `wev.config.json`. The plan was stored with the ties as `check_links`. `task next` offered `parser` to `senior-engineer`; its contract listed `Tools for this task` in `context`, and `audit` was deferred.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task start parser
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task check parser
```
The baseline of `parser` showed `test -f parser.py` failed and `make test` passed. The first `task check` failed the same check, so `all_met` was false and the criterion `parser.py exists` was `unmet`.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" exec -- touch parser.py
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task check parser
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task record parser --status verified --summary "parser added" --changed-file parser.py
```
Now both criteria were `met` by checks tied to them. After `record`, `next_step` was a `task review parser --reviewer code-reviewer ...` command. In a real session the review is done by a different agent than the one that did the work, and the summary states what was read.

```
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task review parser --reviewer code-reviewer --verdict accept --summary "read the diff and the check output"
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task start audit
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task check audit
"${CLAUDE_PLUGIN_ROOT}/bin/wev" task record audit --status verified --summary "reviewed"
```
`audit` is `read_only`, so it was verified with no file change; its plain check was reported as untied.

A second `run start` at this point fails with `run_active` and names `run finish --run <id>`.

## What a refusal looks like

- `verified` before a passing check: exit 2, `verification_required`, with the open criteria in `missing`.
- `verified` after a file changed since the passing check: exit 2, `tree_changed`, with the `task check` command to run again.
- A destructive command through `exec` (for example `rm -rf`): exit 4, `approval_required`, an approval id and a reason. Stop and ask the human; the human grants it in their own terminal and you retry the same command once.
- Plan-mode refusals exit 3. A different `--config` after `run start` exits 2 (`config_pinned`).
