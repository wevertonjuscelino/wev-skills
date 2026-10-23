# Review layers Implementation Plan

Portuguese version: [2026-10-22-review-layers.pt-BR.md](2026-10-22-review-layers.pt-BR.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind reviews and publishing grants to the code they saw, run engine-owned review rounds (parallel finders, verifier voting, tags) under a `REVIEW.md`, cap rounds with diff-only re-review, gate `run finish` on open Important findings, add Risk and How-to-revert to the PR, and score the reviewer on review cases with the existing ratchet.

**Architecture:** A new `review/` package holds `REVIEW.md` parsing, git tree snapshots and diffs, finding and vote parsing, prompts, the round and the finish gate. It depends only on `core/ports.py` (`Runner`, `AgentRunner`) and on records in a new `state/review_records.py`, so the state never imports `review/`. Commands wire the Claude Code adapter in, as `CLAUDE.md` requires. Scoring reuses `evaluation/` and calls the same finder-and-vote function the round uses.

**Tech Stack:** Python 3.14 standard library (`concurrent.futures`, `fnmatch`, `json`), `unittest`, the repository's schema validator, `git write-tree` with a temporary `GIT_INDEX_FILE`, `git diff`, Claude Code CLI through the existing `ClaudeAgentRunner`.

**Spec:** [docs/superpowers/specs/2026-10-22-review-layers-design.md](../specs/2026-10-22-review-layers-design.md)

## Global Constraints

- Standard library only, Python 3.14 or newer, mypy strict, frozen dataclasses, functions under 50 lines, files under 400 (`governance/approvals.py` is at 392, `config.py` at 384, `state/model.py` at 408: new code goes into new modules).
- Every user-facing string through `i18n.t` with identical keys in `en` and `pt-BR`; new messages go in a new `review` locale domain (`locales/review.en.json`, `locales/review.pt-BR.json`) unless they extend an existing domain's messages.
- Docs in English and Brazilian Portuguese in the same commit; `PYTHONPATH=src python3 -m unittest tests.unit.test_docs` passes; `bin/wev claude-md check` and `bin/wev readme check` pass.
- `make test` never calls a model, the network or a real harness. Use `FakeAgent` from `tests/unit/test_scoring.py` (move it to `tests/fixtures/fake_agent.py` in Task 8 so other tests import it) and `tests/fixtures/fake_claude_agent.py`.
- Each new test is broken on purpose once (revert the line it guards, see it fail, restore).
- Old run state files keep loading: every new state field has a default.
- Never push, publish or release without the owner's explicit authorization. Commit subjects follow `<type>: <description>`. No AI assistant named as author anywhere. Never run `make test` concurrently with another `make test`.
- Values pinned by the spec: `review.depth` default `off`; presets `quick` 1/1/quorum 1, `standard` 3/3/2, `deep` 5/5/3; `max_rounds` 3; `full_rounds` 2; `max_runs_per_round` 12; nit cap default 3; a high-risk run uses at least `standard` when review is on; finders and verifiers get exactly `Read`, `Glob`, `Grep`.
- Outcome labels exactly `wrong`, `intentional`, `does-not-matter` (plus `fixed`, set by the engine).

## Review Focus

- A `REVIEW.md` whose `Skip` list matches every changed file: the round still runs, and the summary says how many findings `REVIEW.md` skipped (test in Task 9).
- A finder answer naming line 0, a negative line, a line past the end, a binary file or a path outside the repository: dropped as unproven, never crashes the round (test in Task 7).
- Two `wev review run` started at once (the agent backgrounds it twice): the second commit is refused with a state conflict and records nothing (test in Task 9).
- One finder times out while others answer: the round continues with what came back; every finder failing without a timeout raises `ProviderError("review_agent_failed")` and records no round (test in Task 9).
- A run started before this change (no `base`) and old state files: state loads, `review run` refuses with `review_no_base`, nothing else breaks (test in Task 3).

---

### Task 1: Task review bound to the task's own verified tree

**Files:**
- Modify: `src/wev_skills/state/records.py` (`ReviewRecord`), `src/wev_skills/schemas/state.schema.json` (`$defs.review`), `src/wev_skills/core/task_outcomes.py` (`review_task`), `src/wev_skills/core/progress.py` (`review_accepted`)
- Test: `tests/unit/test_review_binding.py`

**Interfaces:**
- Produces: `ReviewRecord(task_id, at, reviewer, accepted, summary, fingerprint: str = "")`; `progress.recorded_tree(state: RunState, task_id: str) -> str` (the fingerprint of the task's last `verified` task-attempt event from `verified_trees`, `""` if none).

- [ ] **Step 1: Write the failing tests:**
  - `test_review_stores_the_task_recorded_tree`: after `task record --status verified` and `task review --accept`, the stored review's `fingerprint == recorded_tree(state, id)` and is non-empty.
  - `test_review_survives_another_task_editing_other_files`: task A reviewed, task B edits another file and is recorded; `review_accepted(state, "A")` is `True`.
  - `test_review_voids_when_the_task_is_redone`: task A reviewed, reopened, edited and recorded again; `review_accepted(state, "A")` is `False` and `task next` names A for review.
  - `test_review_survives_a_recheck_before_finish`: a re-check (`task check`) on a changed tree does not change `review_accepted`.
  - `test_old_review_without_fingerprint_does_not_count`: a state file whose review lacks `fingerprint` loads, and `review_accepted` is `False`.
- [ ] **Step 2: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_review_binding -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Add the field with default `""` and to `$defs.review` (not required). `review_task` sets it from `recorded_tree`. `review_accepted` requires `review.accepted`, a non-empty fingerprint, and `review.fingerprint == recorded_tree(state, task_id)`. Drop the `at >= finished_at` comparison; the fingerprint replaces it.
- [ ] **Step 4: Run** the module and `PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*review*"`. Expected: PASS.
- [ ] **Step 5: Commit** `fix: bind a task review to the tree its task recorded`.

### Task 2: Grants for external-effect commands bound to `HEAD` and the tree

**Files:**
- Create: `src/wev_skills/governance/approval_anchor.py`
- Modify: `src/wev_skills/governance/approvals.py` (`ApprovalRequest`, `ApprovalStore.__init__`, `grant`, `_usable`), `src/wev_skills/core/wiring.py` (pass the anchor), locales
- Test: `tests/unit/test_approval_anchor.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Anchor: head: str; tree: str`
  - `needs_anchor(argv: Sequence[str]) -> bool`: true when the command classifier that builds `CommandRisk` for an argv (the one `security/permissions.py` uses) sets `external_effect`.
  - `ApprovalRequest` gains `head: str = ""`, `tree: str = ""`.
  - `ApprovalStore(..., anchor: Callable[[], Anchor] | None = None)`; `ApprovalStore.is_stale(action: Action, cwd: str = "") -> bool`.
  - `wiring` passes `lambda: Anchor(head=<git rev-parse HEAD or "">, tree=engine fingerprint of root)`.
- [ ] **Step 1: Write the failing tests** with a fake anchor whose values the test changes:
  - `test_push_grant_records_head_and_tree`: grant for `("git", "push", "origin", "dev")` stores the anchor values.
  - `test_push_grant_goes_stale_on_new_commit`: change `head` after grant; `is_granted` is `False`, `is_stale` is `True`.
  - `test_push_grant_goes_stale_on_tree_change`: same with `tree`.
  - `test_ordinary_grant_ignores_the_tree`: grant for `("rm", "-r", "build")` stays usable after both change.
  - `test_publish_entries_are_anchored`: `needs_anchor` true for `("gh", "pr", "merge", "1")`, `("npm", "publish")`; false for `("make", "test")`.
- [ ] **Step 2: Run** the module. Expected: FAIL.
- [ ] **Step 3: Implement.** `grant` sets `head` and `tree` from `anchor()` when `needs_anchor(record.argv)`; `_usable` adds: a record with `head` or `tree` set is usable only while `anchor()` equals them. The exec path that reports "approval needed" adds the reason `stale_grant` when `is_stale` (one new locale key per language). Keep `approvals.py` under 400 lines by putting the comparison in `approval_anchor.py`.
- [ ] **Step 4: Run** the module and `tests.unit.test_approvals*`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: tie grants for publishing commands to HEAD and the tree`.

### Task 3: Run base, tree snapshots and touched lines

**Files:**
- Create: `src/wev_skills/review/__init__.py`, `src/wev_skills/review/trees.py`
- Modify: `src/wev_skills/state/model.py` (`RunState.base`), `src/wev_skills/schemas/state.schema.json`, `src/wev_skills/core/run_start.py` (`_open`)
- Test: `tests/unit/test_review_trees.py`

**Interfaces:**
- Produces:
  - `write_tree(runner: Runner, root: Path) -> str`: a git tree id of the working tree including untracked, non-ignored files, written with a temporary `GIT_INDEX_FILE` (seeded by `git read-tree HEAD`, then `git add -A`, then `git write-tree`), using `evaluation/workspace.GIT_HARDENING` and `GIT_ENV`. It touches no ref and not the real index. Raises `StateConflict("review_tree_failed")` on git failure.
  - `diff_trees(runner: Runner, root: Path, old: str, new: str, context: int = 3) -> str`.
  - `touched_lines(diff: str) -> dict[str, frozenset[int]]`: new-side line numbers added or changed per path, parsed from `@@ -a,b +c,d @@` hunks of a `--unified=0` diff.
  - `RunState.base: str = ""`, set once by `run start` to `write_tree(...)`, never written by `run resume`.
- [ ] **Step 1: Write the failing tests** in a temp git repository:
  - `test_write_tree_includes_untracked_and_leaves_index_alone`: an untracked file appears in `git ls-tree`; `git status --porcelain` is unchanged afterwards.
  - `test_write_tree_skips_ignored_files`.
  - `test_touched_lines_reads_hunks`: a fixed diff text gives `{"a.py": frozenset({3, 4}), "b.py": frozenset({10})}`; a pure deletion gives no lines for its file.
  - `test_run_start_records_base_and_resume_keeps_it`: `base` non-empty after start; unchanged after edits plus `run resume`.
  - `test_uncommitted_change_at_start_is_in_base`: a file dirty at `run start` does not show in `diff_trees(base, write_tree(now))`.
  - `test_state_without_base_loads`.
- [ ] **Step 2: Run** the module. Expected: FAIL.
- [ ] **Step 3: Implement** as above. `run_git` sets its own environment; add an `env` keyword to `run_git` (default none, merged over its environment) rather than duplicating it.
- [ ] **Step 4: Run** the module plus `tests.unit.test_run_start*` and `tests.unit.test_case_workspace`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: record a fixed run base as a git tree`.

### Task 4: Quorum in `resolve_conflict`

**Files:**
- Modify: `src/wev_skills/decisions/local.py`, `src/wev_skills/decisions/__init__.py` (protocol), `src/wev_skills/decisions/jev.py` (delegate)
- Test: `tests/unit/test_resolve_quorum.py`

**Interfaces:**
- Produces: `resolve_conflict(self, verdicts: Sequence[Verdict], quorum: int | None = None) -> Verdict`. `None` keeps unanimity; otherwise `accepted = sum(v.accepted) >= quorum`. Score stays `min`, reasons merged as today. `quorum < 1` or `> len(verdicts)` raises `ValidationError("bad_quorum")`.
- [ ] **Step 1: Tests:** `test_default_stays_unanimous`, `test_two_of_three_accepts`, `test_one_of_three_rejects_at_quorum_two`, `test_bad_quorum_refused`, `test_jev_delegates_quorum`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** in all three places.
- [ ] **Step 4: Run** the module and `tests.unit.test_decisions*`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: let resolve_conflict accept by quorum`.

### Task 5: The `review` configuration section

**Files:**
- Create: `src/wev_skills/config_review.py`
- Modify: `src/wev_skills/config.py` (`Config.review`, `trust_errors`), `src/wev_skills/schemas/config.schema.json`, `docs/guides/configuration-and-providers.md` and its `.pt-BR.md` twin
- Test: `tests/unit/test_config_review.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ReviewConfig(Serializable)`: `agent: str = ""`, `depth: str = "off"`, `finders: int = 0`, `verifiers: int = 0`, `quorum: int = 0` (0 = from the preset), `max_rounds: int = 3`, `full_rounds: int = 2`, `max_runs_per_round: int = 12`, `timeout_seconds: float = 600.0`.
  - `@dataclass(frozen=True) class ReviewShape: finders: int; verifiers: int; quorum: int`
  - `review_shape(config: ReviewConfig, risk: RiskLevel) -> ReviewShape`: preset from `depth`, raised to `standard` when `risk` is HIGH, then explicit non-zero keys override.
- Schema bounds: `depth` enum `off|quick|standard|deep`; `finders`, `verifiers`, `quorum` 0–10; `max_rounds` 1–10; `full_rounds` 0–10; `max_runs_per_round` 1–50; `timeout_seconds` 0.1–3600.
- [ ] **Step 1: Tests:** `test_defaults_are_off`, `test_presets` (the three exact tuples), `test_high_risk_raises_quick_to_standard`, `test_explicit_keys_override`, `test_depth_on_needs_agent` (`trust_errors` reports it), `test_quorum_above_verifiers_refused`, `test_unknown_key_refused`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**, and document every key in both language versions of the configuration guide.
- [ ] **Step 4: Run** the module, `tests.unit.test_config*` and `tests.unit.test_docs`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add the review configuration section`.

### Task 6: `REVIEW.md` parsing and `wev review md check`

**Files:**
- Create: `src/wev_skills/review/guide.py`, `src/wev_skills/commands/review.py` (group `review`, action `md check` only here), `src/wev_skills/locales/review.en.json`, `src/wev_skills/locales/review.pt-BR.json`
- Test: `tests/unit/test_review_guide.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ReviewGuide: failure: str = ""; skip: tuple[str, ...] = (); nit_cap: int = 3; nits: str = ""; important: str = ""`
  - `HEADINGS: Mapping[str, str]` mapping each English and Portuguese heading (`What failure looks like` / `Como é uma falha`, `Skip` / `Ignorar`, `Nits`, `Important` / `Importante`, case-insensitive) to a field.
  - `parse_guide(text: str) -> ReviewGuide`; an unknown second-level heading, a `max:` that is not an integer from 0 to 50, or a file over 20,000 characters raises `ValidationError("invalid_review_md")` naming the line.
  - `load_guide(root: Path) -> ReviewGuide`: defaults when `REVIEW.md` is absent.
  - `skipped(path: str, guide: ReviewGuide) -> bool` (`fnmatch` on the POSIX path).
- [ ] **Step 1: Tests:** `test_parses_english_headings`, `test_parses_portuguese_headings`, `test_missing_file_gives_defaults`, `test_bad_max_refused`, `test_unknown_heading_refused`, `test_skip_glob_matches`, `test_md_check_command_reports_ok_and_error` (exit 2 on error).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** The command group follows `commands/cases.py` (`resolve_scope`, an `actions` subparser, payload dict).
- [ ] **Step 4: Run** the module and `tests.unit.test_skills` (it checks commands named in skills against `--help`). Expected: PASS.
- [ ] **Step 5: Commit** `feat: read REVIEW.md for reviewers`.

### Task 7: Findings, votes and prompts

**Files:**
- Create: `src/wev_skills/state/review_records.py`, `src/wev_skills/review/findings.py`, `src/wev_skills/review/prompts.py`
- Modify: `src/wev_skills/adapters/claude_code/agent_runner.py`, `src/wev_skills/core/ports.py` (tool set argument), locales
- Test: `tests/unit/test_review_findings.py`, `tests/unit/test_agent_runner.py` (extend)

**Interfaces:**
- Produces:
  - In `state/review_records.py`: `FindingRecord(Serializable)`: `id: str`, `round: int`, `file: str`, `line: int`, `title: str`, `body: str`, `tag: str` (`important|nit|pre_existing`), `class_wide: bool`, `votes_real: int`, `votes_total: int`, `status: str = "open"` (`open|fixed|dismissed`), `outcome: str = ""`, `reason: str = ""`, `resolved_by: str = ""`. `ReviewRoundRecord(Serializable)`: `number: int`, `at: str`, `scope: str` (`full|diff`), `tree: str`, `fingerprint: str`, `depth: str`, `findings: tuple[FindingRecord, ...]`, `skipped: int`, `runs_used: int`, `summary: str`.
  - In `review/findings.py`: `RawFinding(file, line, title, body, tag, class_wide)`; `Vote(index: int, real: bool, tag: str, kind: str)`; `finding_id(file: str, line: int, title: str) -> str` (first 12 hex of sha256 over `file\0line\0lowercased, whitespace-collapsed title`); `parse_findings(answer: str) -> tuple[RawFinding, ...]` (JSON `{"findings": [...]}`, at most `MAX_FINDINGS = 20`, `TITLE_MAX = 120`, `BODY_MAX = 1200`, an item whose text `untrusted.scan` flags is dropped, any malformed answer gives `()`); `parse_votes(answer: str, count: int) -> tuple[Vote, ...]` (JSON `{"votes": [{"index", "real", "tag", "kind"}]}`, `kind` in `bug|security|style|diagnostic|cleanup`; an out-of-range index or bad kind drops that vote); `proven(raw: RawFinding, root: Path) -> bool` (a regular, non-binary file under `root`, `1 <= line <=` its line count).
  - In `review/prompts.py`: `finder_prompt(diff: str, intent: str, guide: ReviewGuide, claude_md: str, posted: Sequence[FindingRecord], lang: str) -> str`; `verifier_prompt(diff: str, candidates: Sequence[RawFinding], rechecks: Sequence[FindingRecord], guide: ReviewGuide, lang: str) -> str`. Every repository-derived part goes through `wrap(redact(text), source=...)`; the instructions come from locale keys `review.prompt.finder` and `review.prompt.verifier` and ask for the exact JSON above.
  - `AgentRunner.run_agent(workspace, spec, objective, timeout, tools: Sequence[str] = UNATTENDED_TOOLS)`; `READ_ONLY_TOOLS = ("Read", "Glob", "Grep")` in `agent_runner.py`.
- [ ] **Step 1: Tests:** `test_parses_valid_findings`; `test_malformed_answer_gives_nothing`; `test_operator_command_in_body_dropped` (`wev approval grant` in `body`); `test_over_long_title_dropped`; `test_more_than_twenty_capped`; `test_unproven_lines_dropped` (line 0, −1, past end, binary file, `../x`); `test_finding_id_stable_across_whitespace`; `test_votes_parse_and_drop_bad_index`; `test_prompt_fences_repository_text` (a planted `</untrusted>` cannot close the fence); `test_runner_passes_read_only_tools` (`--tools Read,Glob,Grep` and the same `--allowedTools` in the fake's logged argv); `test_runner_default_tools_unchanged`.
- [ ] **Step 2: Run** both modules. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both modules plus `tests.unit.test_scoring`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: parse review findings and votes; let the runner take a tool set`.

### Task 8: Find and vote

**Files:**
- Create: `src/wev_skills/review/vote.py`, `tests/fixtures/fake_agent.py` (moved from `tests/unit/test_scoring.py`, extended with scripted answers per prompt kind)
- Test: `tests/unit/test_review_vote.py`

**Interfaces:**
- Consumes: Tasks 3, 4, 6 and 7.
- Produces:
  - `@dataclass(frozen=True) class VoteInputs: root: Path; agent: AgentRunner; spec: AgentSpec; diff: str; run_touched: Mapping[str, frozenset[int]]; intent: str; guide: ReviewGuide; claude_md: str; posted: tuple[FindingRecord, ...]; rechecks: tuple[FindingRecord, ...]; shape: ReviewShape; timeout: float; round: int; decide: Callable[[Sequence[Verdict], int], Verdict]; lang: str`
  - `@dataclass(frozen=True) class VoteResult: kept: tuple[FindingRecord, ...]; fixed: tuple[str, ...]; skipped: int; runs_used: int`
  - `find_and_vote(inputs: VoteInputs) -> VoteResult`.
- Algorithm: run `shape.finders` finders in a `ThreadPoolExecutor` with `READ_ONLY_TOOLS`. A timed-out finder contributes nothing; if every finder fails without a timeout, raise `ProviderError("review_agent_failed")`. Drop unproven, skipped (counted in `skipped`) and already-posted ids. Merge candidates in the same file within `DUPLICATE_LINE_WINDOW = 3` lines, keeping the first. Run `shape.verifiers` verifiers in parallel on candidates plus rechecks. For each candidate, turn each vote into `Verdict(accepted=real and kind in {"bug", "security"}, score=1.0)`; keep it when `decide(verdicts, shape.quorum).accepted`. Tag `important` when most accepting votes say so, else `nit`. Tag `pre_existing` when `line` is not in `run_touched[file]`. Apply the nit cap, keeping the most-voted. A recheck is `fixed` when the quorum votes it no longer real. `runs_used` counts every started harness run.
- [ ] **Step 1: Tests**, with the fake agent: `test_quorum_keeps_and_drops`; `test_style_votes_drop_a_finding`; `test_pre_existing_from_run_diff_not_round_diff`; `test_nit_cap_keeps_most_voted`; `test_duplicates_merged`; `test_posted_ids_not_repeated`; `test_skipped_counted`; `test_recheck_marks_fixed`; `test_one_finder_timeout_continues`; `test_all_finders_fail_raises`; `test_runs_used_counts_every_run`.
- [ ] **Step 2: Run** the module. Expected: FAIL.
- [ ] **Step 3: Implement**, and update `tests/unit/test_scoring.py` to import the moved fake.
- [ ] **Step 4: Run** the module and `tests.unit.test_scoring`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: find and vote on review findings`.

### Task 9: The review round, `review run|show|resolve|dismiss` and the round cap

**Files:**
- Create: `src/wev_skills/review/round.py`, `src/wev_skills/review/summary.py`, `src/wev_skills/commands/_agent_runner.py` (the `ClaudeAgentRunner` construction now in `commands/_scoring.py`, shared by both)
- Modify: `src/wev_skills/state/model.py` (`review_rounds`, `review_allowance`), `src/wev_skills/schemas/state.schema.json`, `src/wev_skills/commands/review.py`, `src/wev_skills/core/guard_ack.py`, `src/wev_skills/adapters/claude_code/engine_cli.py` (`OPERATOR_COMMANDS`), `src/wev_skills/security/untrusted.py` (operator-command rule), `src/wev_skills/adapters/harness_hooks.py` (person-only deny on other harnesses, if it keeps its own list)
- Test: `tests/unit/test_review_round.py`, `tests/unit/test_review_commands.py`

**Interfaces:**
- Consumes: Tasks 3, 5, 7 and 8.
- Produces:
  - `RunState.review_rounds: tuple[ReviewRoundRecord, ...] = ()`, `RunState.review_allowance: int = 0`.
  - `run_round(engine: Engine, agent: AgentRunner, lang: str) -> ReviewRoundRecord`: refuses `review_off` (exit 2) when depth is `off`, `task_running` (exit 5), `review_no_base` (exit 5); when `len(review_rounds) >= max_rounds + review_allowance`, records a `GuardTrip` with rule `review_rounds` and raises `GuardTripped` (exit 6). It refuses `review_over_cap` (exit 6) before any run when `finders + verifiers > max_runs_per_round`, and prints the planned count to stderr like `evaluation.scoring.plan`. Scope is `full` while `number <= full_rounds`, else `diff` (previous round tree to now). `run_touched` always comes from `diff_trees(base, now, context=0)`. Rechecks are open findings whose file and ±3 lines intersect the lines touched since their round. It commits with `base=state`, so a concurrent round conflicts (exit 5).
  - `summarize(findings: Sequence[FindingRecord], skipped: int, lang: str) -> str`: first line counts open Important, Nit and Pre-existing, or the locale's "Nothing to fix"; then findings by severity with `file:line`; then "N skipped by REVIEW.md" when `skipped > 0`.
  - `review show` prints the last round. `review resolve <id> --as wrong|intentional|does-not-matter --reason <text>` resolves a Nit or Pre-existing finding and refuses an Important one with `PermissionDenied("review_dismiss_person_only")`. `review dismiss <id> --as ... --reason ...` is person-only through `commands/_human.OperatorPrompt` and works on any tag.
  - `guard acknowledge` on a run-level `review_rounds` trip adds 1 to `review_allowance`.
- [ ] **Step 1: Tests:** `test_round_records_findings_and_summary`; `test_summary_nothing_to_fix`; `test_summary_counts_skips_when_skip_matches_everything`; `test_off_refused`; `test_no_base_refused`; `test_running_task_refused`; `test_over_cap_refused_before_any_run`; `test_third_round_is_diff_only`; `test_fourth_round_trips_guard`; `test_acknowledge_allows_exactly_one_more`; `test_concurrent_round_conflicts`; `test_resolve_refuses_important`; `test_dismiss_needs_a_terminal`; `test_dismiss_is_an_operator_command` (`engine_cli` asks; `untrusted.scan` flags `wev review dismiss`; other harnesses deny).
- [ ] **Step 2: Run** both modules. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both modules, `tests.unit.test_guard*`, `tests.unit.test_bash_guard*`, `tests.security`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: run review rounds with a round cap`.

### Task 10: The finish gate

**Files:**
- Create: `src/wev_skills/review/gate.py`
- Modify: `src/wev_skills/core/orchestrator.py` (`finish`)
- Test: `tests/unit/test_review_gate.py`

**Interfaces:**
- Consumes: Tasks 3, 5 and 9; `.wev/scores.jsonl` comparison records from Task 13.
- Produces: `finish_refusal(state: RunState, config: Config, fingerprint: str, touched: Mapping[str, frozenset[int]], comparisons: Sequence[Mapping[str, object]]) -> WevError | None`, in this order:
  1. an open Important finding: `StateConflict("review_open_important")`, listing ids;
  2. depth not `off` and (no round, or the last round's `fingerprint != fingerprint`): `StateConflict("review_stale")`;
  3. `touched` includes `REVIEW.md` or `<agents.project_dir>/<review.agent>.json`, and no comparison has `fingerprint` equal to the current one with `improves` true: `StateConflict("reviewer_unscored")`.
  `Orchestrator.finish()` raises the refusal before recording anything; with depth `off` and nothing open it behaves as today.
- [ ] **Step 1: Tests:** one per refusal, `test_off_finishes_as_before`, `test_dismissed_important_does_not_block`, `test_pre_existing_never_blocks`, `test_improving_comparison_lets_reviewer_change_finish`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the module and `tests.unit.test_run*`, `tests.unit.test_score_on_finish`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: refuse run finish on open Important findings or a stale review`.

### Task 11: Plan risk and revert, PR template and `run report --format pr`

**Files:**
- Create: `src/wev_skills/core/report_pr.py`
- Modify: `src/wev_skills/schemas/plan.schema.json`, `src/wev_skills/core/contracts.py` (`Plan`), `src/wev_skills/core/plan_flow.py` (`adopt_plan`), `src/wev_skills/core/report.py` (`build_report` keys), `src/wev_skills/commands/run.py` (`FORMATS`), `.github/PULL_REQUEST_TEMPLATE.md`
- Test: `tests/unit/test_plan_revert.py`, `tests/unit/test_report_pr.py`

**Interfaces:**
- Produces: `Plan.risk_notes: str = ""`, `Plan.revert: str = ""`; `adopt_plan` raises `ValidationError("plan_needs_revert")` when either is blank and `higher_risk` of `state.classification.risk` and every task's `risk` is MEDIUM or HIGH. The report dict gains `risk_notes`, `revert` and `review` (`{"summary": str, "dismissed": [{"id", "tag", "outcome", "reason"}]}`). `render_pr(report: Mapping[str, Any], lang: str) -> str` prints `## Summary`, `## What was tested`, `## Risk`, `## How to revert`, `## Review` in that order. The template gains the same three new headings.
- [ ] **Step 1: Tests:** `test_low_risk_plan_without_revert_ok`; `test_medium_task_risk_needs_revert`; `test_high_run_risk_needs_revert`; `test_pr_body_sections_in_order`; `test_pr_body_lists_dismissed_findings`; `test_template_has_risk_revert_review` (reads `.github/PULL_REQUEST_TEMPLATE.md`).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both modules and `tests.unit.test_plan*`, `tests.unit.test_report*`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: require risk and revert notes and print a PR body`.

### Task 12: Review cases

**Files:**
- Modify: `src/wev_skills/schemas/case.schema.json`, `src/wev_skills/evaluation/cases.py`, `src/wev_skills/commands/cases.py` (`--at-base`), `src/wev_skills/evaluation/workspace.py` (`case_workspace` commit argument)
- Test: `tests/unit/test_review_cases.py`

**Interfaces:**
- Produces: `Case` gains `kind: str = "build"`, `head_commit: str = ""`, `expect: tuple[Expect, ...] = ()` with `Expect(file: str, first: int, last: int)`. The schema adds `kind` (`build|review`), `head_commit`, `expect`; `check` and `files` become optional in the schema, and `load_cases` enforces per kind: `build` needs `check`; `review` needs `head_commit` and a stored `evals/cases/<id>/change.diff`, and forbids `check` and `files`. `case_workspace(runner, root, case, scratch, commit: str | None = None)`. `review_case_passed(case: Case, kept: Sequence[FindingRecord]) -> bool`: a bug case passes when an `important` finding has `file == e.file` and `e.first <= line <= e.last` for some `e`; a clean case (`expect` empty) passes when none is `important`. `--at-base` for a review case checks that `git diff base_commit head_commit` equals the stored `change.diff` byte for byte.
- [ ] **Step 1: Tests:** `test_review_case_loads`; `test_review_case_with_check_refused`; `test_build_case_without_check_refused`; `test_expect_must_lie_in_stored_diff` (`touched_lines` of `change.diff`, offline); `test_pass_rule_bug_case`; `test_pass_rule_clean_case`; `test_nit_does_not_pass_a_bug_case`; `test_old_cases_still_load`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the module, `tests.unit.test_cases`, `tests.unit.test_first_cases`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add review cases`.

### Task 13: Scoring the reviewer and `--compare`

**Files:**
- Modify: `src/wev_skills/evaluation/score_runs.py` (`_attempt` by kind), `src/wev_skills/evaluation/scoring.py` (`planned_runs`, cap check, `ScoreReport.depth`), `src/wev_skills/commands/specialists.py` (`--compare`)
- Create: `src/wev_skills/evaluation/compare.py`
- Test: `tests/unit/test_score_review_cases.py`

**Interfaces:**
- Consumes: Tasks 8 and 12.
- Produces: a review case sample runs `find_and_vote` in a workspace at `head_commit`, with `diff` and `run_touched` from the stored `change.diff`, `intent = case.objective`, the guide and spec as configured, and the shape `review_shape(config.review, LOW)`. It passes by `review_case_passed`. On a fail, `Failure.output` is the summary and `Failure.diff` is the case diff, so project 2's lesson writer works unchanged. `planned_runs` takes `runs_per_sample` (1 for build, `finders + verifiers` for review) and the baseline cap check uses it. `ScoreReport.depth: str = ""`. `compare_reviewer(root, config, runner, agent, agent_id, rev: str, audit) -> CompareReport` scores the spec and `REVIEW.md` read with `git show <rev>:<path>` against the working tree on the same pinned cases, with no lesson decisions. It appends `{"compare": rev, "fingerprint", "depth", "baseline", "current", "improves"}` to `scores.jsonl`. `--compare` is part of `specialists score`, so it stays person-only.
- [ ] **Step 1: Tests:** `test_review_case_scored_with_fake_votes`; `test_runs_per_sample_in_plan_and_cap`; `test_depth_recorded`; `test_compare_records_improves_true_and_false`; `test_compare_refuses_dirty_cases` (the pin); `test_build_cases_unchanged`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the module and `tests.unit.test_scoring`, `tests.unit.test_score_decisions`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: score the reviewer on review cases`.

### Task 14: Noise records and `wev review stats`

**Files:**
- Create: `src/wev_skills/review/stats.py`
- Modify: `src/wev_skills/review/round.py`, `src/wev_skills/commands/review.py`
- Test: `tests/unit/test_review_stats.py`

**Interfaces:**
- Produces: appends to `<state_dir>/reviews.jsonl` one `{"kind": "round", "at", "run_id", "round", "depth", "important", "nit", "pre_existing", "skipped", "runs_used"}` per round and one `{"kind": "outcome", "at", "run_id", "finding", "tag", "outcome", "depth", "round"}` per resolution, dismissal or engine `fixed`. `review_stats(path: Path) -> dict[str, object]`, per depth: findings per round, share by outcome, rounds per run, runs passing after one round, plus `clean_case_candidates` (person-dismissed `wrong` findings).
- [ ] **Step 1: Tests:** `test_round_and_outcome_lines_written`; `test_stats_aggregate_by_depth`; `test_wrong_dismissal_listed_as_candidate`; `test_missing_file_gives_empty_stats`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the module. Expected: PASS.
- [ ] **Step 5: Commit** `feat: record review outcomes and print review stats`.

### Task 15: wev-skills' own reviewer, `REVIEW.md` and first review cases

**Files:**
- Create: `REVIEW.md`, `wev-specialists/wev-reviewer.json` (same shape as `wev-specialists/wev-engineer.json`), `wev.config.json` (`{"review": {"agent": "wev-reviewer", "depth": "standard"}}`), three bug review cases and two clean review cases under `evals/cases/`, each with its `change.diff`
- Test: `tests/unit/test_first_review_cases.py`

- [ ] **Step 1:** Find the commits that introduced the three bugs fixed by `06fc92c` (health probe 1 MiB, tarball `..` symlink) and `e3d7b2b` (`install.sh` exec path) with `git log -L` on the lines the fixes changed. Write each as a bug case whose `expect` covers those lines on the `head_commit` side.
- [ ] **Step 2:** Pick two merged commits that no later fix touched (confirm with `git log --follow` on their changed lines) and write them as clean cases. Each case's `title` says why it is clean.
- [ ] **Step 3: Test** `test_first_review_cases_are_consistent`: they load, every `expect` intersects `touched_lines(change.diff)`, and there are 3 bug and 2 clean cases. Run `bin/wev cases validate --at-base` locally and paste the output in the commit body.
- [ ] **Step 4:** `REVIEW.md` "What failure looks like" lists the five failures named in the spec (part B). `bin/wev review md check` passes.
- [ ] **Step 5: Commit** `chore: add wev-skills' reviewer, REVIEW.md and first review cases`.

### Task 16: Documentation and security text

**Files:**
- Modify, each with its `.pt-BR.md` twin: `SECURITY.md`, `CLAUDE.md` (human-operator list gains `review dismiss`; package list gains `review/`), `docs/guides/orchestration.md`, `docs/guides/evaluation.md`, `docs/guides/specialists.md`, `docs/glossary.md`, `skills/wev-orchestrate/SKILL.md`
- Create: `docs/guides/review.md` and `docs/guides/review.pt-BR.md` (with a `REVIEW.md` template)

- [ ] **Step 1:** Write the text the spec lists in part I, labelling each capability (`implemented and tested` for what the unit tests cover; `implemented but untested` for a real `claude -p` round and a real reviewer score). Security wording: a guardrail for a fallible agent; the agent's file tools can still edit run state and findings.
- [ ] **Step 2:** The skill says to start `wev review run` in the background before `run finish`, read `review show`, fix or `review resolve` Nits and Pre-existing findings, and stop and ask a person for an Important finding it believes is wrong or for a `review_rounds` trip.
- [ ] **Step 3: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_docs tests.unit.test_skills`, `bin/wev claude-md check`, `bin/wev readme check`. Expected: PASS.
- [ ] **Step 4: Commit** `docs: document review layers in both languages`.

### Task 17: Whole-branch check

- [ ] **Step 1: Run** `make check` (alone on the machine). Expected: every test passes; ruff and mypy clean.
- [ ] **Step 2: Run** `claude plugin validate .`. Expected: only the known `CLAUDE.md` warning.
- [ ] **Step 3:** Ask the owner to run, from a terminal, one real `wev review run` on a small run and one `wev specialists score wev-reviewer`. Until then, report both as implemented but untested.
