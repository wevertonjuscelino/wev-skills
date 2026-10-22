# Design: review layers

Portuguese version: [2026-10-22-review-layers-design.pt-BR.md](2026-10-22-review-layers-design.pt-BR.md).

Status: draft for the owner's approval (2026-10-22). Nothing here is implemented.

## Intent

This is project 3 of the continuous-improvement plan. Project 1 (stored cases and a score ratchet) and project 2 (specialists whose lessons enter and leave by score) shipped in PR #18; their design is [2026-10-22-scored-cases-and-self-evolving-specialists-design.md](2026-10-22-scored-cases-and-self-evolving-specialists-design.md). This project adds the review layers from "How the Claude Code team does code review" (claude.dev, 2026-10-15) to a wev run.

The owner wants less interaction and continuous improvement that never regresses. Applied to review, that means three things. A review is run and checked by the engine, not described in a skill. A review can never stay valid for code it did not see. And the reviewer itself changes only when its score on stored cases goes up.

Today a review in wev is one record: `task review <id> --reviewer <agent> --accept|--reject --summary <text>`. The engine refuses self-review and refuses to review an unverified task, but it does not record which code the review covered. `review_accepted` compares times, not trees. If another task edits the same files after the review, the review still counts. No finding is structured, nothing is voted on, rounds are not counted, and approvals for a push are bound to the argv and run but not to the commit being pushed.

## Owner decisions

On 2026-10-22 the owner asked for the work to go ahead without more questions ("pode dar andamento e austar como achar melhor de forma a não travar e atingirmos nosso objetivo"). The scope below came from the session that started this design. Every other choice is listed under "Calls I made without the owner" and is open to the owner's change.

- Scope: a `REVIEW.md` per repository that the engine reads for reviewers; parallel bug-finding reviewers with verifier voting and Important, Nit and Pre-existing tags; review acceptance and approvals bound to the commit or tree; a cap on review rounds with diff-only re-review; a PR template with Risk and How-to-revert sections; and scoring a reviewer against the cases in `evals/cases/` with the ratchet from PR #18.

## Goals, non-goals and anti-goals

Goals:

- A review round run by the engine: several finders in parallel, then verifiers who vote on each finding, with only voted-in findings kept.
- Rules from `REVIEW.md` that code can check (skip paths, the nit cap, file and line evidence, a summary that starts with a count) are enforced by the engine, not left to the model.
- A review, a verification and a grant for a publishing command count only for the tree or commit they saw.
- At most `review.max_rounds` rounds per run. Rounds after the first `review.full_rounds` review only what changed since the previous round. Findings already posted are not repeated.
- `run finish` refuses while an Important finding is open.
- Review cases (a diff with a known bug, or a known-clean diff) in `evals/cases/`. The reviewer is scored on them with the same ratchet, so its lessons enter and leave by score, and a change to `REVIEW.md` or to the reviewer's spec is kept only when the score goes up.
- A PR template, and a PR body from `run report`, with Testing, Risk, How to revert and a review summary.

Non-goals:

- Posting comments on GitHub, reading PR threads, or any network call besides the harness run. The engine reviews the run's diff locally. Publishing the PR body stays with the agent, under the existing push and publish approvals.
- Branch protection, CODEOWNERS rules, merge queues, feature flags or release channels. These are repository settings, and only the owner may change them (see `CLAUDE.md`).
- A separate security-review pass. Security findings are Important findings of the same round. A separate pass can come later as a review-case source.
- Building review cases from dismissed findings automatically. Cases are still written and committed, as in project 1.
- A per-directory `REVIEW.md`. One file at the project root covers wev's projects today.

Anti-goals (a failure even if it technically works):

- A review, a verification or a publishing grant still counts after the tree it saw has changed.
- The agent whose work is under review dismisses an Important finding on its own.
- Tokens are spent on reviews that the configuration does not allow, or beyond the configured cap.
- `make test` calls a model or the network.
- The reviewer's score can be raised by editing review cases in the same work that is scored (the case-set pin of project 1 applies).
- Model output (a finding or a vote) gives an instruction to an agent, or carries an operator command, a tool grant or a permission change.
- Review rounds go on without end. The article reports a PR that ran more than fifty rounds overnight.

## Parts and order

The parts are listed in build order. A, B and C can ship without any model call. D through G need the agent runner from PR #18.

### A. Bind reviews and grants to what they saw

- Task review (`task review`) stays per task and keeps its role: when the strategy sets `needs_independent_review`, a task is complete only with an accepted review. It runs beside the run-level rounds of D, which do not replace or satisfy it. A task review covers the task's own result, and a round covers the run's final tree.
- `ReviewRecord` gains `fingerprint`, the tree fingerprint of the task's latest verification when the review is recorded. `review_accepted` requires that fingerprint to equal the fingerprint of the task's latest verification that the task itself recorded (`task record`), not a later re-check. A task that is reopened and redone needs a new review. A later task that edits other files, or the re-checks before `run finish`, does not invalidate it, because the whole-tree fingerprint would make every later task void every earlier review. Drift across tasks is what the run-level round, bound to the final tree, catches.
- A grant for an action that the classifier marks as having an external effect (`git push`, the `publish` entries in `command_tables.py`, `gh pr merge`, `gh release create` and the like) also records `HEAD` and the tree fingerprint at grant time. It is usable only while both still match. A mismatch reports `stale_grant` and needs a fresh grant. Other grants keep their current binding (argv, working directory, run, single use, TTL). Binding every grant to the tree would add prompts without stopping a regression.
- Status: these are code changes to `state/records.py`, `core/progress.py` and `governance/approvals.py`, with unit tests. Nothing in this part calls a model.

### B. `REVIEW.md`

A project may keep `REVIEW.md` at its root. The engine reads it for every review round and passes it to finders and verifiers as fenced project guidance. The rest of the repository is treated as untrusted text in the same way. The file has fixed second-level headings, recognized in English and Portuguese:

- `## What failure looks like` (`## Como é uma falha`): free text, given to reviewers.
- `## Skip` (`## Ignorar`): one glob per list item. Findings on matching paths are dropped by the engine.
- `## Nits` (`## Nits`): a line `max: <n>` caps the Nit findings kept per round (default 3), plus optional free text.
- `## Important` (`## Importante`): free text on what deserves the Important tag here.

The engine enforces these rules in code. A finding must name a file and a line that exist in the reviewed tree, or it is dropped as unproven. Nits beyond the cap are dropped, lowest vote count first. Skip globs drop findings. The round summary is written by the engine, not by the model. It starts with the counts ("2 Important, 1 Nit, 3 Pre-existing" or "Nothing to fix") and then lists the findings by severity.

`wev review md check` validates the headings and the `max:` line. `docs/guides/review.md` (in both languages) gives a template. wev-skills writes its own `REVIEW.md` as the first user. Its "what failure looks like" lines come from `CLAUDE.md`: a capability claimed without evidence, a user string outside i18n, a doc missing its twin, a rule that exists only in Markdown, and a security statement stronger than `SECURITY.md`. If there is no `REVIEW.md`, rounds still run with the built-in defaults (nit cap 3, no skip paths).

### C. The PR template and the PR body

- `.github/PULL_REQUEST_TEMPLATE.md` gains `## Risk` (the risk tier and what could break), `## How to revert` (the exact steps, including data or configuration that a `git revert` does not undo) and `## Review` (the count-first summary, plus the dismissed findings and their reasons). The existing "What was tested" section stays as the Testing section.
- `wev run report --format pr` prints a PR body with those sections filled in from the run: the risk tier and its reasons from the classification, the checks that ran from the evidence, and the review summary from the last round. The Risk and How-to-revert text comes from the plan.
- The plan schema gains optional top-level `risk_notes` and `revert` texts (not `risk`, which is already the per-task risk enum in `schemas/plan.schema.json`). `plan set` refuses the plan when either text is missing and the higher of the run's classification at `run start` and any task's `risk` is medium or high. This rule lives in code, so a high-risk run cannot reach `run finish` without a revert path. Per the article, the agent writes the text and the person who asked signs off on the PR.

### D. A review round

`wev review run` starts a round for the active run. It reviews the **run diff**: from the run's base to the current working tree. The run state has no stable base today. `RepoSnapshot.head` is set at `run start` (`core/run_start.py`) and overwritten by `run resume` (`core/orchestrator.py`). So `run start` gains a `base` field, written once and never overwritten. It holds the tree as it was at run start (`HEAD` plus uncommitted and untracked changes), stored in a form a later diff can use (the same choice as the round trees in "What is left to the builder"). Changes that were already uncommitted at run start are therefore part of the base and are not the author's lines. A run started before this change has no `base`, and `review run` refuses it with a clear message.

The round:

1. Refuses when `review.depth` is `off`, when a task is running, or when `review.max_rounds` rounds have already run (see E).
2. Runs `review.finders` finders in parallel through the agent-runner port, using the reviewer specialist named by `review.agent` (see G) with its active lessons. The port today always grants `UNATTENDED_TOOLS` (Read, Edit, Write, Glob, Grep, Bash) in `run_agent` and no tools in `ask` (`adapters/claude_code/agent_runner.py`). `run_agent` therefore gains a tool-set argument whose default is today's set, and rounds pass the read-only set. Each finder gets the diff, the run objective and plan as the stated intent, `REVIEW.md`, `CLAUDE.md`, and the read-only tools Read, Glob and Grep, with no Bash. It must answer with JSON findings: file, line, title, explanation, proposed tag (`important` or `nit`) and whether the bug is a class to fix everywhere. Anything else is dropped.
3. Merges duplicates (same file and nearby lines with the same claim). It drops findings that are unproven, on skip paths, or already posted in an earlier round of this run.
4. Runs `review.verifiers` verifiers in parallel. Each sees all the surviving findings at once, fenced as untrusted data, and votes on each one: real or not, Important or Nit, and whether it is style, diagnostic or cleanup only. A finding is kept when at least `review.quorum` verifiers call it real. Findings voted style, diagnostic or cleanup only are dropped, as in the article. The tag is the majority vote.
5. Tags a kept finding Pre-existing, in code, when its line is not among the lines that the run diff (base to current tree) added or changed. This is always the run diff, even in a diff-only round. Otherwise the author's own code from round 1 would read as Pre-existing in round 3 and could never block. This keeps old bugs from reading as the author's fault, and Pre-existing findings never block.
6. Records the round in the run state: number, base, the reviewed tree (fingerprint plus what E needs to diff against later), findings with their votes, harness runs used, and an audit event.

The votes are `Verdict` values. `LocalPolicyProvider.resolve_conflict` now accepts only unanimously. It gains a quorum argument, and the default stays unanimous so that the behaviour of existing callers does not change. That includes the `DecisionProvider` protocol (`decisions/__init__.py`) and the JEV adapter that delegates to it (`decisions/jev.py`). The round's tally calls it with `review.quorum`. `evaluate_result` stays as it is. It is not a reviewer.

Depth presets, following the article's Quick, Standard and Deep: `quick` uses 1 finder and 1 verifier (quorum 1), `standard` 3 and 3 (quorum 2), `deep` 5 and 5 (quorum 3). The explicit keys override a preset. A run classified high risk uses at least `standard` whenever review is on.

A round can take longer than an agent's Bash call is allowed to run (Claude Code stops one after 2 minutes by default). So the skill tells the agent to start `wev review run` in the background, and `wev review show` prints the last round. Each run starts at most `review.max_runs_per_round` harness runs; the command refuses beforehand when the depth needs more, and prints the planned count to stderr like `specialists score` does.

Who may start a round: the agent may, without a person. The configuration is the consent. `review.depth` defaults to `off` in the product, the run pins its configuration, and `--config` is already an ask. This differs from `specialists score`, which stays person-only. A score run changes what every later run sees, while a review round only reports on this run. wev-skills sets `review.depth: standard` in its own `wev.config.json`.

### E. Resolution, the round cap and diff-only re-review

- Each finding is `open`, `fixed` or `dismissed`. "Not found again" proves nothing, because finders are told not to repeat findings. So each round after the first also re-checks the open findings whose file and lines changed since the round that posted them. Its verifiers see each such finding next to the current code and vote whether it still holds. A finding becomes `fixed` when the quorum votes that it no longer holds. An open finding whose lines did not change stays open. The agent marks Nit and Pre-existing findings with `wev review resolve <finding> --as wrong|intentional|does-not-matter --reason <text>`. Dismissing an Important finding is a human-operator command, `wev review dismiss <finding> --as ... --reason ...`, with the same terminal and typed-word friction as `approval grant`. It goes on the list in `CLAUDE.md`, in the hook's ask list and in the deny list of the other harnesses.
- `run finish` refuses while an Important finding is open, or while the last round's tree is not the current tree and `review.depth` is not `off`. In that case the agent runs another round.
- Rounds after the first `review.full_rounds` (default 2) review only the diff between the previous round's tree and the current one. The findings already posted go to finders as "do not repeat", and the engine drops exact repeats anyway.
- After `review.max_rounds` (default 3, as in the article) the engine refuses another round. It records a guard trip of a new kind, `review_rounds`, with the message that the approach should be reconsidered. As with every guard trip, it is cleared by `guard acknowledge` from a person. Each acknowledgment allows exactly one more round, so a fix made after the cap needs one acknowledgment to be reviewed. This is the one place where the owner is asked by design, and the article's numbers say it should be rare (mean reviews to pass 1.32, five or more rounds 1.5%).

### F. Review cases

The case schema gains `kind`: `build` (the default, today's cases) or `review`. A review case has:

- `base_commit` and `head_commit`: the diff under review, for example the commit that introduced a bug that was later reverted or fixed.
- `objective`: the stated intent of that change, as the PR described it.
- `expect`: a list of `{file, lines: [first, last]}` where a real bug is. An empty list marks a known-clean change.
- `id`, `title`, `source`, `ref` and `agents`, as in build cases. `check` and `files` do not apply.

A sample passes when, for a bug case, at least one kept Important finding falls on an expected file and line range, and for a clean case, no Important finding is kept. Precision (false alarms) is measured by the clean cases, as the article measures noise on known-clean PRs. The case-set pin, sampling and pass counts are those of project 1.

The first review cases: the commits that introduced the three bugs of the 2026-10-22 end-to-end run (the 1 MiB health probe, the confined `..` symlink in the tarball check, the exec path in `install.sh`), as bug cases whose `expect` points at the lines the fix commits `06fc92c` and `e3d7b2b` changed. Two or three merged wev-skills commits that no later fix touched serve as clean cases. The builder picks them and records why each one is clean. `wev cases validate --at-base` gains the review check: the diff `base_commit..head_commit` must apply, and every `expect` range must lie in lines that the diff touches.

### G. Scoring the reviewer

The reviewer is an ordinary project specialist, `wev-reviewer` in wev-skills, named by the configuration key `review.agent`. The agent schema has no role field, and none is added. `wev specialists score <agent>` runs the cases that apply to that agent (through each case's `agents` list), and each case is scored by its `kind`. A build case runs the agent and its `check`. A review case runs one review round at the pinned configuration's `review.depth`, with the agent as the reviewer. The score record stores that depth, and runs at different depths are never compared. Each harness run of a round (every finder and every verifier) counts toward `specialists.score_max_runs`. The planned count printed before the run includes them, and the owner raises the cap when a deep setting needs it. Everything else is the machinery of project 2: baseline, with and without each proposed lesson, model-written lessons from failed cases, the `improves()` ratchet, `.wev/scores.jsonl`, and audit before the write. The reviewer's lessons therefore enter and leave by score, with no new rule.

A change to `REVIEW.md` or to the reviewer's spec is a change to the reviewer, so it must not lower the score:

- `wev specialists score wev-reviewer --compare <rev>` scores the reviewer as it is at `<rev>` (its spec and `REVIEW.md` read from git) and as it is in the working tree, on the same pinned case set. It records both pass counts with the tree fingerprint in `.wev/scores.jsonl`.
- `run finish` refuses a run whose diff touches `REVIEW.md` or the reviewer's spec unless `.wev/scores.jsonl` holds a comparison for the current tree in which `improves(baseline, current)` is true. Scoring stays person-only, so this is the one other case where a person acts. It happens only when the reviewer itself changes.

### H. Measuring noise

Every resolution records its outcome (`fixed`, `wrong`, `intentional`, `does-not-matter`) in the run state and in `.wev/reviews.jsonl` (local, like `.wev/scores.jsonl`). `wev review stats` prints the trend per depth: findings per round, the share by outcome, rounds per run, and runs that passed after one round. These are the article's measures. They let the owner see whether the reviewer is getting quieter without missing bugs. A finding a person dismissed as `wrong` is printed as a candidate clean case. Turning it into a case is still a committed change.

### I. Configuration and text that must change

- A new `review` section in the configuration schema, with tests and docs in both languages: `agent` (the reviewer specialist), `depth` (`off`, `quick`, `standard`, `deep`; default `off`), `finders`, `verifiers`, `quorum`, `max_rounds` (3), `full_rounds` (2), `max_runs_per_round` (default 12, enough for `deep` plus a margin of 2), `timeout_seconds` per harness run.
- Text to update in both languages in the same change: `SECURITY.md` (review rounds are unattended `claude -p` runs with read-only tools; findings and votes are untrusted text; `review dismiss` is human-only; grants for commands with an external effect are tied to `HEAD` and the tree), `CLAUDE.md` (the human-operator list gains `review dismiss`), `docs/guides/orchestration.md`, the new `docs/guides/review.md`, `docs/guides/evaluation.md` (review cases), `docs/guides/specialists.md` (the reviewer and `--compare`), `docs/guides/configuration-and-providers.md`, `docs/glossary.md`, `skills/wev-orchestrate/SKILL.md` (when to start a round, in the background, and how to resolve findings), and the locale keys.

## Tests

- Unit, with no network and no model: the fingerprint on reviews (a review stops counting after an edit); grants for commands with an external effect go stale on a new commit or tree change, while ordinary grants keep their binding; `REVIEW.md` parsing in both languages, the nit cap, skip globs, unproven file or line; the count-first summary, including "Nothing to fix"; a round with fake finder and verifier answers (malformed JSON, an operator command in a finding, quorum met and not met, a style-only vote, Pre-existing tagging from the diff, repeats dropped); `resolve_conflict` with a quorum, and unanimity unchanged by default; the cap and the `review_rounds` guard trip; diff-only rounds; `run finish` refusing an open Important finding, a stale round, or a changed reviewer without an improving comparison; `plan set` refusing a medium- or high-risk plan without `risk_notes` and `revert`; the review-case schema and the pass rule for bug and clean cases; the run cap. Each test is broken on purpose once to see it fail.
- The first review cases: a unit test confirms, from the committed files alone, that each `expect` range lies inside the diff's touched lines. Applying `base_commit..head_commit` needs history, so it is a local check, `wev cases validate --at-base`.
- A real round and a real reviewer score with `claude -p` are run by the owner, spend tokens, and are reported as untested until they have run.

## Constraints

- Standard library only, Python 3.14 or newer, mypy strict, frozen dataclasses, functions under 50 lines, files under 400.
- Every user-facing string goes through i18n with the same keys in `en` and `pt-BR`. Docs change in both languages in the same commit.
- The core never imports an adapter. Rounds use the agent-runner port from PR #18.
- `make test` never calls a model, the network or a real harness.
- Security text follows `SECURITY.md`: these are guardrails for a fallible agent, not a boundary against an adversarial agent in the same account. The agent's own file tools can still edit the run state, including findings.
- Never push, publish or release without the owner's explicit authorization.

## What is left to the builder

- Module names and layout, within the package responsibilities in `CLAUDE.md` (likely a `review/` package or modules under `governance/` and `evaluation/`).
- The prompt templates for finders and verifiers, the duplicate-merge rule ("nearby lines" and "same claim"), and how a round stores its tree for the later diff (a git tree object written with a temporary index, or a copy under the run directory using `evaluation/snapshot.py`).
- Which classifier flag counts as "external effect" for binding grants, as long as `git push`, `gh pr merge` and the `publish` entries are covered and ordinary local commands are not.
- The output shape of `wev review show` and `wev review stats`.
- Which merged commits serve as the first clean cases, with the reason recorded in each case.

## Calls I made without the owner

- Reviews run locally on the run's diff. Nothing posts to GitHub.
- Task review stays per task and runs beside the rounds. It is bound to the task's own latest verification, not to the whole tree.
- The run gets a fixed `base`: the tree at run start, including uncommitted changes, which are not counted as the author's.
- Pre-existing is always measured against the run diff, including in diff-only rounds.
- A fix is proven by a verifier re-check of the changed lines, not by a finding's absence. Each `guard acknowledge` after the cap allows one more round.
- A reviewer is scored at the pinned `review.depth`, and every finder and verifier run counts toward the score cap.
- The reviewer is named by `review.agent`. No role field is added to the agent schema.
- The engine runs the review through the agent runner, so the record is engine evidence, not a self-declared subagent.
- `review.depth` defaults to `off` in the product and is `standard` in wev-skills' own configuration. The agent may start a round without a person, because the configuration is the consent.
- A high-risk run reviews at least at `standard` when review is on.
- Finders and verifiers get Read, Glob and Grep only, with no Bash.
- The quorum is a majority by preset, and `resolve_conflict` keeps unanimity as its default.
- Pre-existing is decided by code from the diff's touched lines, not by the model, and never blocks.
- Only an Important finding blocks `run finish`, and only a person may dismiss one. The agent may resolve Nits and Pre-existing findings on its own.
- At most 3 rounds, the first 2 full, then diff-only. The cap trips a guard that a person acknowledges.
- Grants are tied to `HEAD` and the tree only for commands with an external effect.
- High- and medium-risk plans must state `risk_notes` and `revert`.
- The reviewer is a project specialist scored with project 2's machinery on `kind: review` cases. A change to `REVIEW.md` or to the reviewer's spec needs an improving comparison before `run finish`.
- The first review cases are the commits that introduced the three bugs of 2026-10-22, plus two or three clean commits.
- One root `REVIEW.md`, with headings in English or Portuguese, and a default nit cap of 3.
- Noise outcomes use the article's four labels and stay local in `.wev/reviews.jsonl`.
