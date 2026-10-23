# Layered review

[Português brasileiro](review.pt-BR.md).

Layered review is an optional check between "the task checks pass" and `run finish`. Several read-only agents (finders) look for defects in what the run changed, other agents (verifiers) vote on each candidate, and `run finish` refuses to close a run that still holds an open Important finding. It is off by default (`review.depth: off`).

Status of each part (labels follow [the glossary](../glossary.md)):

| Part | Label |
|---|---|
| `REVIEW.md` format, findings, voting, rounds, round cap, `review` commands, finish gate, stats, plan and PR rules | implemented and tested, with fake agents (no model, no network) |
| A real round with `claude -p` finders and verifiers | implemented but untested until the owner runs it |
| A real reviewer score on the review cases (`specialists score`, `--compare`) | implemented but untested until the owner runs it |
| Scoping the finders' file reads to the workspace | documented only (a follow-up; see "Limits") |

## Turn it on

In `wev.config.json` (the keys are in [configuration and providers](configuration-and-providers.md), section `review`):

```json
{ "review": { "agent": "wev-reviewer", "depth": "standard" } }
```

`agent` is required when `depth` is not `off`. Depth presets, finders / verifiers / quorum: `quick` 1/1/1, `standard` 3/3/2, `deep` 5/5/3. A high-risk run uses at least `standard` when review is on; `off` stays off whatever the risk. The configuration is pinned by `run start`, like every other key.

`run start` also records a base tree: HEAD plus uncommitted and untracked changes, written with a temporary index and no filters or attribute drivers. It is an unreachable git object, so `git gc --prune` can delete it. A run older than the prune window (two weeks by default) with review on fails closed (`review_tree_failed`).

## Write `REVIEW.md`

`REVIEW.md` at the repository root tells the reviewers what a defect means here. It is repository content, so reviewers treat it as untrusted text. A missing file means defaults. Check it with `wev review md check`. The recognized second-level headings (the Portuguese names also work) and nothing else:

```markdown
# Review guide for <project>

## What failure looks like

- A user-facing string sits outside the translation files.
- A rule that matters exists only in prose, with no code or test enforcing it.

## Skip

- generated/*
- evals/reports/*

## Nits

max: 3

Report a nit only when it would mislead a reader.

## Important

A defect in authentication, payments or data deletion, and a limit that rejects valid input.
```

- `What failure looks like` (`Como é uma falha`): what to hunt for.
- `Skip` (`Ignorar`): path globs, one per bullet; matching files are not reviewed (the round reports how many were skipped).
- `Nits`: `max: N` caps the Nit findings kept per round (0 to 50, default 3); the rest of the section is guidance.
- `Important` (`Importante`): what counts as Important in this repository.

The file is read up to 20,000 characters; an unknown heading or a bad `max` is refused with the line number. This repository's own [REVIEW.md](../../REVIEW.md) is a working example.

## Run a round

```sh
bin/wev review run     # one round over the changes of the active run
bin/wev review show    # the last round and the findings still open
bin/wev review stats   # noise per depth, from .wev/reviews.jsonl
```

A round starts the finders and then the verifiers as unattended `claude -p` runs, each with `Read`, `Glob` and `Grep` only. It can take a long time, so start `review run` from a terminal or in the background, not in a short Bash call. Before the first agent run it prints the planned run count and the cap `review.max_runs_per_round` (default 12); a round over the cap runs nothing (`review_over_cap`, exit 6). A task must not be running, and the run needs its recorded base tree.

- Each finding is tagged Important, Nit or Pre-existing. A finding stays when its verifier votes reach the quorum.
- The model's text is untrusted: it is redacted and fenced before it is stored or shown, and a finding that does not parse is dropped.
- A round where nobody really reviewed fails (`review_incomplete`, or `review_agent_failed` when every finder ended without an answer) instead of reporting "nothing to fix", and it records no round.
- At most `review.max_rounds` rounds (default 3) per run. The first `review.full_rounds` (default 2) run every finder over the whole change; later rounds are diff-only and narrow to what changed since the last round.
- Reaching the round cap trips the `review_rounds` guard (exit 6, visible in `wev guard check`). A person clears it with `guard acknowledge`, which allows one more round.

## Close findings

```sh
bin/wev review resolve <finding> --as wrong|intentional|does-not-matter --reason "<words>"
bin/wev review dismiss <finding> --as wrong|intentional|does-not-matter --reason "<words>"
```

An agent may `resolve` a Nit or a Pre-existing finding. An Important finding can only be closed by `review dismiss`, a human-operator command: it needs a terminal, shows the finding and asks for a typed word (the same friction as `approval grant`). An agent that believes an Important finding is wrong stops and asks a person. A finding the engine sees fixed in a later round is closed as `fixed`. The outcome labels are exactly `wrong`, `intentional`, `does-not-matter` (and `fixed`, set by the engine). `.wev/reviews.jsonl` keeps ids, tags, outcomes and counts only, never finding text; `review stats` reads it.

## The finish gate

With review on, `run finish` refuses:

| Code | When |
|---|---|
| `review_open_important` | an Important finding is still open |
| `review_stale` | no round yet, or the tree changed since the last round |
| `reviewer_unscored` | `REVIEW.md` or the reviewer spec changed and no improving `specialists score --compare` record exists for the current tree |
| `review_config_weakened` | the re-resolved review configuration is lower than the pinned one |

With review off, `run finish` does no git work for review.

## Plans and the pull request body

A plan for a medium or high-risk run needs `risk_notes` and `revert` (refused with `plan_needs_revert`); the one-task plan the engine synthesizes when planning is `never` is exempt, and its PR body says "Not given.". `wev run report --format pr` prints Summary, What was tested, Risk (tier, reasons, notes), How to revert and Review.

## Review cases and scoring the reviewer

Review cases live next to the others in `evals/cases/` with `kind: review`, a `head_commit`, an `expect` list of file and line ranges (empty for a clean change) and a stored `change.diff`; commit ids must be hex. `wev cases validate --at-base` regenerates the diff. This repository ships 3 bug cases and 2 clean cases for `wev-reviewer`.

```sh
bin/wev specialists score wev-reviewer             # person-only; scores review cases at the pinned depth
bin/wev specialists score wev-reviewer --compare <rev>   # person-only; reviewer at <rev> against the working tree
```

`--compare` works for `review.agent` only and records the resolved revision; `run finish` reads that record for `reviewer_unscored`. Both spend tokens and are person-only: Claude Code asks, other harnesses deny, an agent never runs them.

## Limits

- Review is a guardrail for a fallible agent, not a boundary against an adversarial one. The agent's file tools can still edit the run state, the findings and `.wev/reviews.jsonl` (see [SECURITY.md](../../SECURITY.md)).
- `Read`, `Glob` and `Grep` are granted unscoped, so a finder can read files outside the repository, as scoring's unattended runs can; finding text is redacted before it is stored. Scoping reads to the workspace is a follow-up.
- A run started with an explicit `--config` can edit the repository's `wev.config.json` to lower review for later runs that do not pass `--config`. Only the person reviewing the PR sees it.
- Model verdicts are signals, not proof: a vote that agrees is not a correct finding. Check the findings with low agreement.
