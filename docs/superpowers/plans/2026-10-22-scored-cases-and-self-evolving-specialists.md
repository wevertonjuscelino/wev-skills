# Scored cases and self-evolving specialists Implementation Plan

Portuguese version: [2026-10-22-scored-cases-and-self-evolving-specialists.pt-BR.md](2026-10-22-scored-cases-and-self-evolving-specialists.pt-BR.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store real failures as cases, score a specialist against them with and without each lesson through an unattended `claude -p`, let the model write lessons from failed cases, and accept or retire lessons by score alone.

**Architecture:** Cases, the pin, the ratchet rule, the lesson filter and the scoring loop live in `evaluation/` and depend only on two ports in `core/ports.py` (the existing `Runner` and a new `AgentRunner`). The Claude Code adapter implements `AgentRunner` with `claude -p`. Lesson storage changes stay in `agents/`. Commands wire the adapter in, as `CLAUDE.md` requires.

**Tech Stack:** Python 3.14 standard library, `unittest`, the repository's JSON schema validator (`wev_skills.schema.validate`), `git worktree`, Claude Code CLI 2.1.302 flags confirmed with `claude --help`.

**Spec:** [docs/superpowers/specs/2026-10-22-scored-cases-and-self-evolving-specialists-design.md](../specs/2026-10-22-scored-cases-and-self-evolving-specialists-design.md)

## Global Constraints

- Standard library only, Python 3.14 or newer, mypy strict, frozen dataclasses, functions under 50 lines, files under 400.
- Every user-facing string through `i18n.t` with identical keys in `en` and `pt-BR` locale files.
- Docs in English and Brazilian Portuguese in the same commit; `PYTHONPATH=src python3 -m unittest tests.unit.test_docs` passes.
- `make test` never calls a model, the network or a real harness; use fakes under `tests/fixtures/`.
- Each new test is broken on purpose once (revert the line it guards, see it fail, restore).
- Never push, publish or release without the owner's explicit authorization. Commit subjects follow `<type>: <description>`. No AI assistant named as author anywhere.
- Never run `make test` concurrently with another `make test` on this machine.
- Defaults pinned by the spec: `score_samples` 3, `score_max_runs` 60, `score_max_new_lessons` 3, `score_on_finish` false.
- Unattended tools: exactly `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`; never `--dangerously-skip-permissions`, `--bare` or `--permission-mode bypassPermissions`.

## Review Focus

- A case `check` that hangs: it is killed at `score_timeout_seconds` and counts as a fail, and the score run continues (test in Task 2).
- A score run interrupted by an exception or Ctrl-C: no worktree is left under `.wev/scoring/` (test in Task 2).
- A `base_commit` that is absent (shallow clone, mistyped sha): a clear `case_base_missing` error before any model run, not a git traceback (test in Task 2).
- Two score runs on the same specialist at once: the second write sees changed lessons and is refused with `lessons_changed` (exit 5), deciding nothing (test in Task 6).
- A model answer that tries to close the untrusted fence, carries `specialists accept`, or is several MB: dropped, nothing written (test in Task 5).

---

### Task 1: Case format, pin and `wev cases list|validate`

**Files:**
- Create: `src/wev_skills/schemas/case.schema.json`, `src/wev_skills/evaluation/cases.py`, `src/wev_skills/commands/cases.py`
- Modify: `src/wev_skills/locales/evaluation.en.json`, `src/wev_skills/locales/evaluation.pt-BR.json`
- Test: `tests/unit/test_cases.py`

**Interfaces:**
- Produces:
  - `CASES_DIR = Path("evals") / "cases"`
  - `@dataclass(frozen=True) class Case(Serializable)`: `id: str`, `title: str`, `source: str`, `ref: str`, `agents: tuple[str, ...]`, `base_commit: str`, `objective: str`, `check: tuple[str, ...]`, `files: tuple[str, ...]`
  - `load_cases(root: Path) -> tuple[Case, ...]`, sorted by id; raises `ValidationError("invalid_case", ...)` naming the file.
  - `cases_for(cases: Sequence[Case], agent_id: str) -> tuple[Case, ...]`: empty `agents` means every specialist.
  - `case_set_digest(root: Path) -> str`: sha256 hex over every regular file under `CASES_DIR`, sorted by POSIX relative path, hashing `path + "\0" + bytes + "\0"` for each.
  - `ensure_committed(runner: Runner, root: Path) -> None`: runs `git status --porcelain --untracked-files=all -- evals/cases`; any output raises `StateConflict("cases_uncommitted", ...)`.
  - A case's stored files live at `evals/cases/<id>/<repo-relative path>` for each path in `files`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_cases.py`, each in a temp directory:
  - `test_loads_a_valid_case`: one JSON with every field; `load_cases(root)[0].check == ("python3", "-m", "unittest", "tests.unit.test_x")`.
  - `test_rejects_unknown_source`: `source: "rumor"` raises `ValidationError` with code `invalid_case`.
  - `test_rejects_file_listed_but_missing`: `files: ["tests/unit/test_x.py"]` without `evals/cases/<id>/tests/unit/test_x.py` raises `invalid_case`.
  - `test_rejects_path_escape`: `files: ["../x"]` raises `invalid_case`.
  - `test_cases_for_empty_agents_means_all` and `test_cases_for_filters_by_agent`.
  - `test_digest_changes_with_any_byte` and `test_digest_ignores_order_of_creation`.
  - `test_uncommitted_case_is_refused`: a fake `Runner` returning `?? evals/cases/a.json` raises `StateConflict` code `cases_uncommitted`; empty stdout passes.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_cases -v`. Expected: FAIL, `ModuleNotFoundError: wev_skills.evaluation.cases`.
- [ ] **Step 3: Implement** the schema (`source` enum `e2e`, `review`, `revert`, `incident`; `check` a non-empty array of strings; `additionalProperties: false`) and `evaluation/cases.py`. Paths in `files` go through the existing confinement in `security/paths.py`.
- [ ] **Step 4: Implement** `commands/cases.py` with `register(subparsers)`: `wev cases list` returns `{"cases": [case.to_dict() ...], "digest": ...}`; `wev cases validate` returns `{"valid": true, "count": n}`. `--at-base` is added in Task 2.
- [ ] **Step 5: Run** the module tests, then `bin/wev cases list` in a temp repo with one case. Expected: PASS, and JSON with `"digest"`.
- [ ] **Step 6: Commit** `feat: add the case format and wev cases list|validate`.

### Task 2: Case workspace, check runner and `validate --at-base`

**Files:**
- Create: `src/wev_skills/evaluation/workspace.py`
- Modify: `src/wev_skills/commands/cases.py`, both `evaluation.*.json` locales
- Test: `tests/unit/test_case_workspace.py`

**Interfaces:**
- Consumes: `Case`, `CASES_DIR` (Task 1); `Runner`, `RawCommandResult` (existing).
- Produces:
  - `@contextmanager case_workspace(runner: Runner, root: Path, case: Case, scratch: Path) -> Iterator[Path]`: `git cat-file -e <base_commit>^{commit}` first (failure raises `NotFound("case_base_missing", ...)`), then `git worktree add --detach <scratch>/<case.id>-<n> <base_commit>`; on exit, always `git worktree remove --force <path>`.
  - `run_check(runner: Runner, case: Case, root: Path, workspace: Path, timeout: float) -> RawCommandResult`: copies each file in `case.files` from `root / CASES_DIR / case.id` into `workspace`, then runs `case.check` with `cwd=workspace`.
  - `passed(result: RawCommandResult) -> bool`: `exit_code == 0 and not timed_out`.
  - The scratch directory is `state_dir(config, root) / "scoring"`.

- [ ] **Step 1: Write the failing tests** with a real temporary git repository (two commits, `git` from the system, as other unit tests in `tests/unit/` already do):
  - `test_workspace_is_at_base_and_removed`: inside the context `HEAD` equals `base_commit`; after it, the path is gone and `git worktree list` has one entry.
  - `test_workspace_removed_on_exception`: raise inside the `with`; the path is gone.
  - `test_missing_base_is_clear`: a sha that does not exist raises `NotFound` with code `case_base_missing`, and no worktree is created.
  - `test_check_sees_case_files`: the check `python3 -c "import pathlib,sys; sys.exit(0 if pathlib.Path('t.txt').exists() else 1)"` passes only because `files: ["t.txt"]` was copied.
  - `test_hanging_check_is_a_fail`: `check` is `python3 -c "import time; time.sleep(5)"` with timeout 0.5; `passed(...)` is false and the call returns.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_case_workspace -v`. Expected: FAIL on import.
- [ ] **Step 3: Implement** `evaluation/workspace.py`.
- [ ] **Step 4: Add** `--at-base` to `wev cases validate`: for each case, open a workspace and run its check; the result lists `{"id", "fails_at_base": bool}`, and the command fails (exit 2, `case_passes_at_base`) when any check passes at its base.
- [ ] **Step 5: Run** the tests. Expected: PASS.
- [ ] **Step 6: Commit** `feat: run case checks in a worktree at the base commit`.

### Task 3: The first three cases and wev-skills' own specialist

**Files:**
- Create: `evals/cases/health-large-tools-list.json`, `evals/cases/tarball-confined-dotdot-link.json`, `evals/cases/exec-path-owned-dirs.json`, each with its `evals/cases/<id>/` files; the specialist spec created with `bin/wev specialists create wev-engineer --template senior-engineer --specialty implementation`
- Test: `tests/unit/test_first_cases.py`

**Interfaces:**
- Consumes: `load_cases`, `run_check`, `passed` (Tasks 1 and 2).

- [ ] **Step 1: Find each `base_commit`.** For each fix (`06fc92c` for the 1 MiB probe and for the `..` link, `e3d7b2b` for the exec path), find the commit that introduced the code the fix changed (`git log --format=%H --diff-filter=A -- <file>` for a new file, `git log -L` for a function) and take its parent. Record it as `base_commit` and the fix as `ref`.
- [ ] **Step 2: Write each case.** `objective` asks for the feature as a person would, naming the function and signature the reproducing test calls, never the bug. `check` runs only the reproducing test, as `["env", "PYTHONPATH=src", "python3", "-m", "unittest", "<module>.<Class>.<test>"]`. `files` holds the reproducing test and fixture copied from the fix commit (`tests/fixtures/fake_npx_mcp.py` for the probe).
- [ ] **Step 3: Write the failing test** `tests/unit/test_first_cases.py::test_each_case_passes_on_current_tree`: for every case, run `case.check` with `cwd` at the repository root and assert `passed(...)` (the reproducing tests already exist in the current tree). It needs no git history, so a shallow CI clone works.
- [ ] **Step 4: Run** it, then break a fix on purpose (restore the 1 MiB cap in `third_party/health.py`), see the test fail, restore. Expected: PASS after restore.
- [ ] **Step 5: Run** `bin/wev cases validate --at-base` locally. Expected: every case `"fails_at_base": true`. If one passes at its base, its `base_commit` or `files` is wrong; fix it, not the check.
- [ ] **Step 6: Commit** `feat: add the first three cases and the wev-engineer specialist`.

### Task 4: The agent-runner port and the `claude -p` adapter

**Files:**
- Modify: `src/wev_skills/core/contracts.py`, `src/wev_skills/core/ports.py`
- Create: `src/wev_skills/adapters/claude_code/agent_runner.py`, `tests/fixtures/fake_claude_agent.py`
- Modify: `src/wev_skills/locales/harness.en.json`, `harness.pt-BR.json`
- Test: `tests/unit/test_agent_runner.py`

**Interfaces:**
- Produces:
  - In `core/contracts.py`: `@dataclass(frozen=True) class AgentRunResult(Serializable)`: `ok: bool`, `output: str`, `timed_out: bool = False`.
  - In `core/ports.py`: `class AgentRunner(Protocol)` with `run_agent(self, workspace: Path, spec: AgentSpec, objective: str, timeout: float) -> AgentRunResult` and `ask(self, prompt: str, timeout: float) -> AgentRunResult`.
  - `ClaudeAgentRunner(runner: Runner, plugin_root: Path, program: str = "claude")` in `adapters/claude_code/agent_runner.py`. `UNATTENDED_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")`.
  - `run_agent` argv, exactly: `[program, "-p", objective, "--output-format", "json", "--plugin-dir", str(plugin_root), "--tools", ",".join(UNATTENDED_TOOLS), "--allowedTools", ",".join(UNATTENDED_TOOLS), "--permission-mode", "dontAsk", "--no-session-persistence", "--append-system-prompt", <render_subagent(spec) body without frontmatter>]`, `cwd=workspace`.
  - `ask` argv, exactly: `[program, "-p", prompt, "--output-format", "json", "--plugin-dir", str(plugin_root), "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence"]`, `cwd` a fresh empty temporary directory.
  - Output: parse stdout as JSON and take the string field `result`; non-JSON or missing `result` gives `ok=False`.
  - Before any run, `plugin_root / ".claude-plugin" / "plugin.json"` and `plugin_root / "hooks" / "hooks.json"` must exist, else `ValidationError("plugin_missing", ...)`.

- [ ] **Step 1: Write `tests/fixtures/fake_claude_agent.py`**, a Python stand-in for `claude` that appends its argv as one JSON line to `$FAKE_LOG` and prints `$FAKE_CLAUDE_STDOUT` (default `{"result": "done"}`), exits with `$FAKE_CLAUDE_EXIT` (default 0) and sleeps `$FAKE_CLAUDE_SLEEP` seconds.
- [ ] **Step 2: Write the failing tests:** `test_argv_is_pinned` (the logged argv equals the list above, and contains none of `--dangerously-skip-permissions`, `--bare`, `bypassPermissions`); `test_ask_has_no_tools`; `test_result_field_is_output`; `test_non_json_is_not_ok`; `test_timeout_is_not_ok`; `test_missing_plugin_is_refused` (no fake is run).
- [ ] **Step 3: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_runner -v`. Expected: FAIL on import.
- [ ] **Step 4: Implement** the dataclass, the protocol and the adapter. Use the existing `SubprocessRunner`; reuse `render_subagent` and strip the frontmatter with the fence it already writes.
- [ ] **Step 5: Run** the tests. Expected: PASS.
- [ ] **Step 6: Commit** `feat: add the agent-runner port and the claude -p adapter`.

### Task 5: The ratchet rule and the model-lesson filter

**Files:**
- Create: `src/wev_skills/evaluation/ratchet.py`, `src/wev_skills/evaluation/lesson_writer.py`
- Modify: both `evaluation.*.json` locales
- Test: `tests/unit/test_ratchet.py`, `tests/unit/test_lesson_writer.py`

**Interfaces:**
- Consumes: `Case` (Task 1); `wrap`, `scan` from `security/untrusted.py`; `redact` from `security/redact.py`; `LESSON_TEXT_MAX` from `agents/experience.py`.
- Produces:
  - `improves(baseline: Mapping[str, int], other: Mapping[str, int]) -> bool`: true when the keys are equal, no case in `other` has fewer passes than in `baseline`, and `sum(other) > sum(baseline)`.
  - `lesson_request(case: Case, check_output: str, diff: str, lang: str) -> str`: the prompt, with the three inputs each fenced by `wrap(..., source="case objective" | "check output" | "agent diff")` after `redact`, asking for exactly `{"lesson": "<one practice, at most 600 characters>"}`.
  - `parse_lesson(answer: str) -> str | None`: `None` unless the answer is a JSON object with one key `lesson` holding a string of 1 to `LESSON_TEXT_MAX` characters, `scan(text)` is empty, and `FORBIDDEN` does not match.
  - `FORBIDDEN = re.compile(r"(?i)(allowed[-_ ]?tools|permission|bypass|dangerously|--tools|tools\s*:|model\s*:|\bsudo\b|\bchmod\b|specialists\s+(accept|retire))")`.

- [ ] **Step 1: Write the failing tests.** `test_ratchet.py`: enter (`{a:1,b:0}` → `{a:1,b:1}` true), tie (equal → false), regression (`{a:2,b:0}` → `{a:1,b:3}` false), different keys → false. `test_lesson_writer.py`: valid answer kept; extra key dropped; non-JSON dropped; empty and 601-character texts dropped; `"run specialists accept now"` dropped; `"use --allowedTools Bash"` dropped; an answer with a forged `<<<END_` marker dropped; a 5 MB answer dropped without slowing the suite (bound the parse by length first); `lesson_request` output contains each input inside a fence and never raw.
- [ ] **Step 2: Run** both modules. Expected: FAIL on import.
- [ ] **Step 3: Implement** both modules.
- [ ] **Step 4: Run** both modules. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add the ratchet rule and the model-lesson filter`.

### Task 6: Lesson storage for score decisions and model lessons

**Files:**
- Modify: `src/wev_skills/agents/experience.py`, `src/wev_skills/agents/learning.py`, `src/wev_skills/agents/project.py`, `src/wev_skills/schemas/agent.schema.json`, both `agents.*.json` locales
- Test: `tests/unit/test_score_decisions.py`; check `tests/unit/test_specialists_learning.py`, `test_agents_experience.py`, `test_lesson_acceptance.py` still pass unchanged

**Interfaces:**
- Produces:
  - In `experience.py`: `KIND_MODEL = "model"` added to `LESSON_KINDS`; `SCORER = "score"`, reserved like `PROPOSER`.
  - In `learning.py`: `model_lesson(case_id: str, text: str, score_id: str, now: str) -> Lesson` with `id=_id(("model", case_id, text))`, `kind=KIND_MODEL`, `status=PROPOSED`, `accepted_by=PROPOSER`, `evidence=LessonEvidence(score_id, case_id, ())`, `derivation="model"`.
  - `_carry` gains: a lesson with `status == RETIRED and accepted_by == SCORER` comes back `PROPOSED` with `accepted_by=PROPOSER`; `accepted_by == SCORER` and active is kept.
  - `reconcile` keeps every `KIND_MODEL` lesson of `old` that `derived` does not contain, passed through `_carry` with itself as `before`.
  - In `project.py`: `record_scores(root: Path, config: Config, agent_id: str, seen: tuple[Lesson, ...], decisions: ScoreDecisions, record: Record) -> AgentSpec`, where `@dataclass(frozen=True) class ScoreDecisions`: `new: tuple[Lesson, ...]`, `accepted: tuple[str, ...]`, `retired: tuple[str, ...]`. Under the specialists lock: if `spec.experience != seen` raise `StateConflict("lessons_changed", ...)`; add `new`; set `accepted` to `ACTIVE`/`SCORER` and `retired` to `RETIRED`/`SCORER`; never touch a lesson whose `status == RETIRED` and `accepted_by` is a person (anything but `PROPOSER` and `SCORER`); call `record()` before `_write`.
  - `_decide` keeps refusing `PROPOSER` and now also refuses `SCORER` as an operator name.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_score_decisions.py`: `test_score_accepts_proposed`; `test_score_retired_returns_proposed_after_learn`; `test_person_retired_never_changes` (a lesson retired by `"alice"` stays retired after `record_scores(accepted=(its id,))`); `test_model_lesson_survives_relearning`; `test_changed_lessons_refuse` (pass a stale `seen`, expect `StateConflict` code `lessons_changed` and an unchanged file); `test_audit_runs_before_write` (a `record` that raises leaves the file unchanged); `test_operator_name_score_is_reserved`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_score_decisions -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the changes and the schema enum for `kind`.
- [ ] **Step 4: Run** the new module and `tests.unit.test_specialists_learning tests.unit.test_agents_experience tests.unit.test_lesson_acceptance tests.unit.test_lesson_balance tests.unit.test_lesson_usage`. Expected: PASS, the old ones unchanged.
- [ ] **Step 5: Commit** `feat: store score decisions and model-written lessons`.

### Task 7: Configuration keys

**Files:**
- Modify: `src/wev_skills/config.py` (`SpecialistsConfig`), `src/wev_skills/schemas/config.schema.json`, `docs/guides/configuration-and-providers.md` and `.pt-BR.md` (a new `specialists` section listing all eight keys)
- Test: `tests/unit/test_config_specialists.py`

**Interfaces:**
- Produces: `SpecialistsConfig.score_samples: int = 3` (1..10), `score_max_runs: int = 60` (1..1000), `score_max_new_lessons: int = 3` (0..10), `score_timeout_seconds: float = 900.0` (> 0, at most 3600), `score_on_finish: bool = False`.

- [ ] **Step 1: Write the failing tests:** defaults; each bound refused with `invalid_config`; a state pinned with the old config (no score keys) still loads.
- [ ] **Step 2: Run** the module. Expected: FAIL.
- [ ] **Step 3: Implement** the fields and schema properties; write the docs section in both languages.
- [ ] **Step 4: Run** the module and `tests.unit.test_docs`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add the specialist scoring configuration`.

### Task 8: Scoring, history and `wev specialists score|scores`

**Files:**
- Create: `src/wev_skills/evaluation/scoring.py`
- Modify: `src/wev_skills/commands/specialists.py`, `src/wev_skills/adapters/claude_code/engine_cli.py`, `src/wev_skills/locales/core.en.json`, `core.pt-BR.json`, both `agents.*.json`
- Test: `tests/unit/test_scoring.py`, `tests/unit/test_hook_bypasses.py` (one new case)

**Interfaces:**
- Consumes: everything from Tasks 1, 2, 4, 5, 6 and 7.
- Produces:
  - `planned_runs(cases: int, proposals: int, active: int, samples: int, new_lessons: int) -> int`, exactly `(1 + proposals + new_lessons + active) * cases * samples + new_lessons`.
  - `@dataclass(frozen=True) class ScoreReport(Serializable)`: `score_id: str`, `agent: str`, `digest: str`, `baseline: dict[str, int]`, `accepted: tuple[str, ...]`, `retired: tuple[str, ...]`, `new: tuple[str, ...]`, `runs_used: int`.
  - `score_specialist(root: Path, config: Config, runner: Runner, agent: AgentRunner, agent_id: str, audit: AuditLog) -> ScoreReport`. Order: `ensure_committed`, digest, load spec and `cases_for`; refuse with `BudgetExhausted("score_over_cap", ...)` when `planned_runs(...)` with `new_lessons=score_max_new_lessons` exceeds `score_max_runs`; baseline over active lessons; for up to `score_max_new_lessons` failed cases, `agent.ask(lesson_request(...))` then `parse_lesson`; score each proposal and each model lesson as baseline plus it, and each active lesson as baseline minus it; decide with `improves`; recompute the digest and refuse with `StateConflict("cases_changed", ...)` if it moved; `record_scores` with audit events `specialists.auto_accept` / `specialists.auto_retire` (payload: specialist, lesson, digest, before, after) written in `record`; append the report as one JSON line to `state_dir(config, root) / "scores.jsonl"` with `append_line`.
  - The diff given to `lesson_request` is `git diff` in the workspace after the agent ran, through `Runner`.
  - CLI: `wev specialists score <id>` returns the report; `wev specialists scores [<id>]` returns the lines of `scores.jsonl`, newest last. The command wires `ClaudeAgentRunner(SubprocessRunner(), plugin_root)` with `plugin_root` = the repository root above `src/` (`ENGINE_LAUNCHER.parent.parent` in `engine_cli.py`).
  - Hook: `SCORE_COMMANDS = frozenset({("specialists", "score")})` with `REASON_SCORE = "engine_score"`, answered `ask` (it spends tokens) and not in `PERSON_ONLY_REASONS`; locale key `hooks.reason.engine_score`.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_scoring.py` with a fake `AgentRunner` whose `run_agent` writes or omits a fix in the workspace according to whether a given lesson text appears in `spec.experience`, and whose `ask` returns a scripted lesson: `test_planned_runs_formula`; `test_over_cap_refuses_before_any_run` (fake records zero calls); `test_lesson_that_fixes_a_case_enters`; `test_tie_stays_proposed`; `test_regression_never_enters`; `test_active_lesson_that_hurts_is_retired`; `test_model_lesson_written_and_scored`; `test_cases_changed_during_run_decides_nothing`; `test_history_line_written`; `test_audit_events_carry_digest_and_counts`.
- [ ] **Step 2: Add** to `test_hook_bypasses.py`: `wev specialists score x` gives `ask` with reason `engine_score`.
- [ ] **Step 3: Run** both. Expected: FAIL.
- [ ] **Step 4: Implement** `evaluation/scoring.py` (split helpers to keep each function under 50 lines and the file under 400), the two subcommands and the hook entry.
- [ ] **Step 5: Run** both modules. Expected: PASS.
- [ ] **Step 6: Commit** `feat: score specialists against cases and decide lessons by score`.

### Task 9: `score_on_finish`

**Files:**
- Modify: `src/wev_skills/commands/run.py` (`_finish`)
- Test: `tests/unit/test_score_on_finish.py`

**Interfaces:**
- Consumes: `score_specialist` (Task 8).
- Produces: when `config.specialists.score_on_finish` is true, after a successful finish, `score_specialist` runs once for each project specialist that ended a task in the run; its reports go into the finish payload under `"scores"`; a score failure is reported under `"score_errors"` and never undoes the finish.

- [ ] **Step 1: Write the failing tests:** off by default (no score call); on with two specialists used (two calls); a failing score leaves the run `done` and lists the error.
- [ ] **Step 2: Run, implement, run.** Expected: FAIL, then PASS.
- [ ] **Step 3: Commit** `feat: score the run's specialists at finish when configured`.

### Task 10: Documentation and security text

**Files:**
- Modify, each with its `.pt-BR.md` twin: `SECURITY.md` (lines 57, 78, 115 and a new paragraph on unattended scoring), `CLAUDE.md` (human-operator list kept, plus one line that score decisions do not need it, and `evaluation/` scoring in Architecture), `docs/guides/specialists.md`, `docs/guides/evaluation.md` (a cases section), `docs/guides/installation.md`, `docs/glossary.md`, `CHANGELOG.md`; docstrings of `commands/specialists.py`, `agents/experience.py`, `agents/learning.py`, `commands/_human.py`
- Test: `tests/unit/test_docs.py`, `tests/unit/test_skills.py`, `bin/wev claude-md check`, `bin/wev readme check`

- [ ] **Step 1: Write** the text. The security paragraph says what the unattended run may do (the six tools, `dontAsk`, the plugin loaded, no bypass), that model-written lessons are untrusted text until scored, and that the pin, the run cap, the text filter and the score guard against a fallible agent, not an adversarial agent in the same account. Label each capability: unit-tested with fakes; the real `claude -p` path untested until the owner runs it.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_docs tests.unit.test_skills -v`, `bin/wev claude-md check` and `bin/wev readme check`. Expected: PASS and no findings.
- [ ] **Step 3: Commit** `docs: describe scored cases and lessons decided by score`.

### Task 11: Whole-branch check

- [ ] **Step 1: Run** `make check` (alone on the machine). Expected: exit 0.
- [ ] **Step 2: Run** `claude plugin validate .`. Expected: pass with only the known `CLAUDE.md` warning.
- [ ] **Step 3: Report** what ran and what did not: the real `bin/wev specialists score wev-engineer` spends tokens and waits for the owner.
