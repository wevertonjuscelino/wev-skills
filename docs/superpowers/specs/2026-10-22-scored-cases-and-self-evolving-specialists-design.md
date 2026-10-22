# Design: scored cases and self-evolving specialists

Portuguese version: [2026-10-22-scored-cases-and-self-evolving-specialists-design.pt-BR.md](2026-10-22-scored-cases-and-self-evolving-specialists-design.pt-BR.md).

Status: draft for the owner's approval (2026-10-22). Nothing here is implemented.

## Intent

The owner wants continuous end-to-end development in which every change raises the quality of the system and none lowers it. The model is the review flow the Claude Code team described in "How the Claude Code team does code review" (claude.dev, 2026-10-15). Its core loop is that every incident or revert becomes an eval case, every change to the reviewer is scored against all cases, and the change is kept only when the score goes up.

wev-skills already has the pieces that sit before that loop: `task record --status verified` is refused without engine-run evidence, risk tiers exist, loops are detected and project specialists learn lessons from checks and guard trips. What it lacks is the loop itself. A real failure teaches nothing today. On 2026-10-22 the end-to-end run found that the third-party health check read at most 1 MiB, while `rea` 6.7.0 answers `tools/list` with 3.1 MB. Every unit test passed because the fakes answered with small payloads. No case was kept, no specialist learned from it, and nothing would tell a future change that it had brought the bug back.

This design closes that loop for project specialists. Real failures become stored **cases**. A proposed lesson is **scored** by running the specialist with and without it against every case, and it enters or leaves on its own according to the score. The owner's words: "quero que ele atualize mediante nota sozinho para não ter tanta interação" (update by score on its own, so there is less interaction).

## Owner decisions

Decided in this conversation, not up to the builder:

- The work is three projects in this order: (1) the case and score ratchet, (2) specialists that evolve from the score, (3) the review layers of the article (`REVIEW.md`, parallel reviewers with voting, approvals tied to a commit, a PR template with risk and revert sections). This document covers 1 and 2. Project 3 gets its own design afterwards.
- Lessons enter and leave by score, without a person approving each one.
- The end-to-end bugs of 2026-10-22 are the first cases.
- The engine writes lesson text on its own from a failure, by calling the model, without a PR. The score, not a person, decides whether that text enters.
- The unattended `claude -p` runs with the wev plugin loaded and a limited tool set.

## Goals, non-goals and anti-goals

Goals:

- A committed, validated case format, with the three end-to-end bugs of 2026-10-22 as the first cases.
- A command that scores a specialist against all cases, with and without each proposed lesson, using a real harness run.
- Lessons written by the model from the cases the specialist fails, so a failure like the 1 MiB probe can teach "handle `tools/list` answers of several MB", which check-derived lessons never say.
- Automatic acceptance and retirement of lessons from the score, under the ratchet rule below.
- A record of every score run, so the owner can see the trend over time.

Non-goals:

- Scoring a reviewer or `REVIEW.md` (project 3).
- Feature flags, staged releases or reverting applied changes.
- Generating cases automatically from failures. In this version a case is written (by a person or an agent) and committed; turning an end-to-end report or a review finding into a case automatically is a later step.
- Lessons that change an agent's tools, permissions or model. Lessons stay advisory text.

Anti-goals (a failure even if it technically works):

- The score can be raised by editing the cases in the same work that is being scored.
- `make test` calls a model or the network.
- Tokens are spent without the owner having asked for a score run, or beyond a configured cap.
- A lesson the owner retired comes back on its own.
- A lesson enters while making any case that passed without it fail.
- Model-written text reaches an agent without having been scored, or carries an operator command, a tool grant or a permission change.

## Parts and order

### A. Cases

This is a product feature: any project that uses wev has its own cases at `evals/cases/` under the project root, next to its specialists in `agents.project_dir`. wev-skills is the first project to use it on itself, so implementing it includes creating wev-skills' own specialist and its first cases.

A case is one JSON file under `evals/cases/<id>.json`, validated by a schema in `src/wev_skills/schemas/`. It holds:

- `id`, `title`, `source` (`e2e`, `review`, `revert` or `incident`) and `ref` (the commit, PR or report where the failure was found).
- `agents`: optional list of specialist ids the case applies to; empty means all of the project's specialists.
- `base_commit`: a commit of the project from before the code that failed was written, so the specialist builds that code and either repeats the failure or does not.
- `objective`: the task given to the specialist, written as a person would ask for it, without naming the bug.
- `check`: the argv the engine runs after the specialist finishes, in the case's workspace. Passing means the specialist did not reproduce the failure. For the 1 MiB case, the check is a test that feeds a recorded 3.1 MB `tools/list` answer to the health probe.
- `files`: the paths the check needs that did not exist at `base_commit` (the reproducing test and its fixture), copied into the workspace before the check runs and never shown to the specialist.

The first cases in wev-skills are the Python bugs found on 2026-10-22: the health probe that read at most 1 MiB (`06fc92c`), the tarball check that rejected a confined `..` symlink (`06fc92c`) and the exec path that trusted directories the user does not own (`e3d7b2b`). The uninstall bug lives in `install.sh` and waits for a later case.

`wev cases list` and `wev cases validate` read and check the set; `wev cases validate --at-base` also confirms, locally, that each `check` fails at its `base_commit`. Adding a case is writing the file and committing it; the owner sees it in the PR like any other change.

### B. The case-set pin

A score run uses only case files that are committed and unchanged in the working tree; a modified or untracked file under `evals/cases/` refuses the run. The run records a sha256 over the sorted list of (path, bytes) of the case files, using the same canonical recipe as `config_digest`. If the set changes before the run ends, the run is refused and nothing is decided.

### C. The agent runner

`core/ports.py` gains an agent-runner port: given a workspace, a prompt, a tool set, a timeout and a token or turn limit, it returns whether the run ended normally plus its output. The core never imports the adapter. The first adapter lives in `adapters/claude_code/` and runs `claude -p` through the existing `SubprocessRunner`, with the specialist's exported prompt and the lesson set under test. Each case runs in a temporary `git worktree` at `base_commit`, removed afterwards. Unit tests use the existing `fake_bin/claude`.

Every unattended run loads the wev plugin, so its hooks and Bash guard apply, and allows only Read, Edit, Write, Glob, Grep and Bash. It never passes `--dangerously-skip-permissions` or a mode that bypasses permissions. A run that cannot load the plugin is refused rather than run without it.

### C2. Lessons written by the model

After the baseline of a score run, for each case the specialist failed, the engine asks the model for one candidate lesson. The request goes through the same port with no tools at all, and carries the case objective, the `check` output and the diff the specialist produced, each fenced and redacted as untrusted data with the existing `security/untrusted.py` and redactor. The answer must be a short JSON object with the lesson text; anything else is dropped.

The engine then filters the text before it becomes a lesson: a length cap, the same untrusted-text scan used elsewhere (which already flags operator commands such as `specialists accept`), and a refusal of text that names tools, permissions or models. A surviving text becomes a `proposed` lesson with a new kind (`model`) and its case as evidence, and is scored in the same run like any other proposal. Nothing the model writes reaches an agent unless the score lets it in.

At most `score_max_new_lessons` candidates are written per score run (default 3), and every generation call counts toward `score_max_runs`.

### D. Scoring and the ratchet rule

`wev specialists score <agent>` runs the specialist on every case with the active lessons (the baseline) and, for each proposed lesson, with the active lessons plus that one. Each configuration runs each case `score_samples` times; a case's score is its pass count.

A proposed lesson **enters** when, against the baseline, no case loses a pass and the total passes go up. A tie leaves it proposed, because a lesson that changes nothing only costs context.

An active lesson **leaves** when the run without it, against the baseline, loses no pass on any case and the total goes up. Ablating active lessons is part of the same run, within the cap below.

Before running, the command prints how many harness runs it will make (configurations × cases × samples) and refuses when that exceeds `specialists.score_max_runs`. Running the command is the consent to spend; there is no extra prompt.

### E. Decisions and audit

An automatic decision sets `accepted_by` to the reserved name `score`, like `engine` today, and writes an audit event (`specialists.auto_accept` or `specialists.auto_retire`) before the specialist file, with the lesson, the case-set hash and the pass counts before and after. Learning carries `score` decisions across relearning the same way it carries human ones.

A lesson the score retired goes back to `proposed` at the next learning and can be scored again, because one run may lose to sampling noise. The human commands stay as overrides: `specialists retire` always works, and a lesson retired by a person is never accepted again by score; `accepted_by` tells the two apart. `specialists accept` remains for a lesson the owner wants without scoring it.

### F. Configuration

New keys in the `specialists` section, with schema validation, tests and docs in both languages: `score_samples` (default 3), `score_max_runs` (default 60), `score_max_new_lessons` (default 3), `score_timeout_seconds` (per harness run) and `score_on_finish` (default `false`; when `true`, `run finish` starts a score run for the specialists the run used). `docs/guides/configuration-and-providers.md` gets a `specialists` section in both languages, since it has none today.

### G. Score history

Each score run appends one line to `.wev/scores.jsonl` (agent, case-set hash, configuration, pass counts, decisions, harness runs used) and `wev specialists scores` prints the trend. The file is local, like the rest of `.wev/`.

### H. Text that must change

Auto-accept contradicts statements that lessons need a person. Each must be updated in both languages in the same change: `SECURITY.md` (lines 57, 78 and 115), `CLAUDE.md` (the human-operator list stays, with a note that score decisions do not need it), `docs/guides/specialists.md`, `docs/guides/installation.md`, `docs/glossary.md`, the docstrings of `commands/specialists.py`, `agents/experience.py` and `agents/learning.py`, and the locale keys under `agents.specialists`. The security text must say that the pin, the cap, the text filter and the score guard against a fallible agent, not an adversarial agent in the same account, and must describe what the unattended `claude -p` run may do and that model-written lessons are untrusted text until scored.

## Tests

- Unit, no network and no model: lesson generation with a fake model answer (valid JSON, malformed answer, an operator command, a tool grant, an over-long text, each dropped or kept as designed); the plugin-load refusal; the case schema; the pin (a modified, untracked or changed-during-run case refuses the run); the ratchet rule (enter, tie, regression, ablation, human-retired never returns); the run cap; audit before write; the fake `claude` adapter, including timeout and abnormal exit. Each is broken on purpose once to see it fail.
- The three cases of 2026-10-22: a unit test runs each `check` against the current tree and expects a pass, without a model and without history, so a shallow CI clone works. That each `check` fails at its `base_commit` is confirmed locally with `wev cases validate --at-base`.
- A real score run with `claude -p` is run by the owner, spends tokens and is reported as untested until it has run.

## Constraints

- Standard library only, Python 3.14 or newer, mypy strict, frozen dataclasses, functions under 50 lines, files under 400.
- Every user-facing string in i18n with the same keys in `en` and `pt-BR`; docs in both languages in the same commit.
- `make test` never calls a model, the network or a real harness.
- Never push, publish or release without the owner's explicit authorization.

## What is left to the builder

- Module names and layout, within the package responsibilities in `CLAUDE.md`.
- Exact JSON field names beyond those above, and the prompt template given to `claude -p`.
- How the runner limits a harness run (turns, tokens or time), as long as `score_timeout_seconds` bounds it.
- The output shape of `wev cases` and `wev specialists scores`.

## Calls I made without the owner

- Scoring runs on demand by default; `score_on_finish` is off by default.
- The ratchet rule: no case may lose a pass, and the total must strictly go up; a tie keeps the lesson proposed.
- Pass counts over three samples per case, to absorb the model's variation.
- Case files must be committed and clean to be scored.
- Lessons a person retired never come back by score; `specialists accept` stays as a manual path.
- The cap of 60 harness runs per score command.
- Score history stays local in `.wev/`.
- A product feature for every project, with wev-skills as the first user; cases at the project root, optionally tagged by specialist.
- In a case the specialist builds the code from before it existed, so it can repeat the failure or avoid it.
- The first cases are the three Python bugs of 2026-10-22; the `install.sh` uninstall bug waits.
- A lesson the score retired can be scored again; only a person's retirement is final.
- The unit test checks only that each case passes on the current tree; failing at the base is a local check.
- Lessons are generated only from failed cases during a score run, not from every failed check of ordinary runs, because a case has a known passing state to score against.
- At most three new lessons per score run, and the generation call has no tools.
- Cases themselves are still written and committed; only lessons are generated without a PR.
