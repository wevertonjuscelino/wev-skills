# Maintaining the repository

Portuguese version: [maintaining.pt-BR.md](maintaining.pt-BR.md).

This guide is for the owner and for anyone who merges changes: the commit format, the branch and pull request flow, how releases are cut and numbered, and the intended GitHub configuration, which cannot be set from the working tree. The repository is <https://github.com/wevertonjuscelino/wev-skills>. The settings section is the source of truth for how the repository should be configured; it is documented only, and a setting counts as applied only after someone confirms it in GitHub.

## Commit format

```
<type>: <description>
<type>(<scope>): <description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`. Pull request titles use the same format, except that `security` is also allowed and `revert` is not; the bot commits `chore(release): vX.Y.Z`. The subject is at most 72 characters and has no trailing period. Merge and revert commits that git generates are allowed. The `commit-msg` hook in `.githooks/` checks this after `make hooks` (see [CONTRIBUTING.md](../../CONTRIBUTING.md)). Do not name any tool as author or co-author, and add no co-author trailer.

## Branches, pull requests and versions

Two long-lived branches exist. `dev` is the quarantine branch where merged work waits; `main` holds released code and is the default branch, so plugin installs get released code. Contributors target `dev`.

1. Work on a branch cut from `dev`, never on `dev` or `main`: `git switch -c <type>/<short-name> origin/dev`.
2. Push the branch and open a pull request against `dev`. The title must be `<type>(<scope>): <description>` (types `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `security`; the scope is optional), because the changelog line comes from it. Fill in the pull request template, including the evidence label of each claim.
3. Wait for the checks (`test` on Ubuntu and macOS, `lint`, `skills`, `git hooks and documents`, `secrets-scan`, `pr-title`, `source-branch`). CodeOwners asks the owner for review.
4. Merge with a merge commit (the only method enabled). The merge commit is what counts the pull request in the version.
5. To release, open a pull request from `dev` to `main` and merge it with a merge commit. Nothing else is needed: the release workflow takes over (see "What is automatic").
6. Nobody pushes directly to `main` or `dev`. The `pre-push` hook already refuses a push to `main` with uncommitted changes to tracked files, but a hook is a convenience, not a control.

### Version formula

The version is `vX.Y.Z` and is computed from git history by `python3 scripts/versioning.py`; it is never written to a file per commit.

- `X` counts releases to `main`. Each merged pull request from `dev` into `main` publishes `v(X+1).0.0`, where `X` is the major of the latest release tag. The major does not signal breaking changes as in Semantic Versioning; read the changelog for that.
- `Y` counts the pull requests merged into `dev` since the latest release tag (merge commits on the first-parent chain from the ref back to the tag).
- `Z` counts the commits of the pull request in progress, and starts over when that pull request is merged into `dev`.

Worked example, with `v2.0.0` as the latest release and `dev` fast-forwarded to it: dev is `2.0.0`. A pull request with 3 commits is merged: dev is `2.1.3`. A second one with 2 commits: `2.2.2`. A branch cut from dev with 4 commits so far is `2.3.4`, which is exactly what dev becomes once it is merged (a commit pushed straight to dev after a merge counts as one more `Z` of the next pull request). The release pull request dev to main publishes `v3.0.0`; dev is fast-forwarded to it and reads `3.0.0`; the next merged pull request makes it `3.1.n`. `python3 scripts/versioning.py [--ref REF] [--next-release]` prints these, and CI prints them in the job summary of the `lint` job.

### What is automatic

[`.github/workflows/release.yml`](../../.github/workflows/release.yml) runs on every push to `main`. The `verify` job runs `make test`. The `release` job (the only job with `contents: write` and `issues: write`) proceeds only when the pushed commit is a merge commit whose subject is `Merge pull request #N from <owner>/dev`; for any other push (a direct admin push, the bot's own release commit) it logs "Not a dev->main merge, no release" and stops. A direct admin push to `main` therefore never releases. When it proceeds, it:

1. computes the next version with `scripts/versioning.py --next-release` and refuses if that tag exists;
2. gathers the pull requests merged into `dev` since the previous tag with `scripts/collect_release_prs.py` (merge subjects, then `gh pr view` for title, URL and labels; commits pushed to dev without a pull request are not listed);
3. creates the milestone of the following release if it does not exist;
4. runs `scripts/release_prep.py`, which rewrites `pyproject.toml`, `.claude-plugin/plugin.json`, `src/wev_skills/__init__.py`, the version marker in both READMEs and in `CLAUDE.md`, the plugin.json example of the installation guides, `CHANGELOG.md` (a new `## [X.Y.Z]` section from the pull request titles: feat is Added, fix is Fixed, a `security` label or type is Security, docs is Documentation, everything else is Changed, plus the compare links) and the generated `wev:release-status` blocks of the roadmaps and the MVP status documents; any pattern that does not match exactly once aborts the run before any file is written; it then runs `bin/wev readme check` and `bin/wev claude-md check`;
5. commits as `github-actions[bot]` with the subject `chore(release): vX.Y.Z`, creates the annotated tag and pushes `main` and the tag together;
6. creates the GitHub release with the changelog section as notes, as the latest release and never as a pre-release;
7. closes the milestone `vX.Y.Z` if it exists;
8. fast-forwards `dev` to `main` with a plain push (no force), so the first-parent chain of `dev` after the tag starts clean.

The bot commit is the only commit that edits the version files and the changelog sections; do not edit them by hand. Hand-written entries under `## [Unreleased]` are kept and merged into the new section. The job pushes over SSH with a deploy key (secret `RELEASE_DEPLOY_KEY`), so its pushes do start workflows: the release commit on `main` runs `release.yml` again, which logs that it is not a dev-to-main merge and releases nothing, and the fast-forward of `dev` runs CI there. Evidence: implemented but untested; it can only run on GitHub. The pure parts (version computation, file rewriting, pull request collection from merge subjects) are covered by unit tests against temporary repositories.

### If a release fails half-way

Read the run log first; each step is separate, and a run stops at the first failure.

- Failed before "Push main and the tag": nothing is published. Fix the cause and re-run the failed run, or push nothing and merge a new release pull request.
- Failed at or after the push but before the release: the commit and the tag exist. Create the release by hand from the changelog section: `python3 scripts/changelog_section.py X.Y.Z > notes.md` and `gh release create vX.Y.Z --title "wev-skills X.Y.Z" --notes-file notes.md --latest --verify-tag`. Do not re-run the workflow: it refuses because the tag exists.
- Failed at the milestone step: close the milestone by hand. It is cosmetic.
- Failed at the dev fast-forward (dev has commits main lacks, because a pull request was merged into dev while the release ran, or a ruleset refused the push): the release is published, but dev is behind in version terms. Until dev contains the release commit its computed version is wrong. As an administrator, put the release commit under the new work: rebase the commits dev gained onto `main` and push dev (the dev ruleset blocks force pushes, so this needs the admin bypass), or, if there is nothing to keep, `git push origin main:dev`. Avoid merging pull requests into dev while a release runs.
- A tag pushed by mistake: the tag ruleset blocks deletion until the owner lifts it for the occasion; delete the release and the tag, then start over.

## End-to-end tests

Run `make e2e` before a release, and after any change to `install.sh`, to the third-party skill commands (`wev skills ...`) or to the rea commands (`wev rea ...`). It spends network and, for some scenarios, Docker time or an account (see the [installation guide](installation.md#end-to-end-tests)). Commit the report it writes to `evals/reports/e2e-<date>.md` with the change, and say in the pull request which scenarios were skipped and why.

## Repository settings

This is the configuration of `wevertonjuscelino/wev-skills`, kept here so that it is reviewable and can be re-applied. It was applied through the GitHub API on 2026-10-15; the repository settings page is the current record.

**General** (Settings, General):

- Description and topics: a one-line description of the engine and the plugin, and topics such as `claude-code`, `claude-code-plugin`, `ai-agents`, `agent-orchestration`, `cli` and `python`.
- Features: Issues on, Discussions on (with a Q&A category, which [SUPPORT.md](../../SUPPORT.md) points to), Wiki off, Projects off. Documentation lives in the repository.
- Merge settings: allow merge commits (the version counts them); squash and rebase merging off. "Automatically delete head branches" off: merging the `dev` to `main` pull request deleted `dev` on 2026-10-22, because the owner's admin role bypasses the `dev` ruleset's deletion rule. The release job recreates `dev` by fast-forward, but anything opened against `dev` in between fails. Delete merged feature branches by hand. The default branch stays `main`.

**Security** (Settings, Code security):

- Private vulnerability reporting on: the route [SECURITY.md](../../SECURITY.md) tells reporters to use. Without it the "Report a vulnerability" button does not appear.
- Secret scanning and push protection on. They complement `scripts/scan_secrets.py`, which is a narrow tripwire.
- Dependabot alerts and Dependabot security updates on. `.github/dependabot.yml` separately asks for weekly pull requests that update pinned GitHub Actions.

**Branch ruleset on `main`** (Settings, Rules):

- Block deletion and block force pushes.
- Do not require linear history: the dev-to-main merge is a merge commit.
- Require a pull request before merging, with 0 required approvals (one maintainer cannot approve their own pull request); allowed merge method: merge only.
- Require these status checks, named as the workflows report them: `test (ubuntu-latest, Python 3.14)`, `test (macos-latest, Python 3.14)`, `lint`, `skills`, `git hooks and documents`, `secrets-scan` (from `ci.yml`, whose last job has no `name:` so its check name is the job id) and `source-branch` (from `pr-policy.yml`). The title of a dev-to-main pull request is free, so `pr-title` is not required here.
- Bypass list: repository admin and deploy keys. A repository owned by a user account cannot list the GitHub Actions app as a bypass actor, so the release job pushes the release commit and the tag to `main` and fast-forwards `dev` with a write deploy key (title "release bot (release.yml)", private key in the Actions secret `RELEASE_DEPLOY_KEY`). Any workflow that reads that secret can push past the rules; only `release.yml` reads it, and pull requests from forks get no secrets. Revoking it means deleting the deploy key and the secret; an admin bypass is for the owner's convenience, not a control against the owner, and a direct admin push to `main` does not release.

**Branch ruleset on `dev`**:

- Require a pull request before merging (0 approvals), merge method: merge only.
- Require the same CI status checks as `main` and `pr-title`. `source-branch` only matters for `main`.
- Block deletion and block force pushes.
- Bypass list: repository admin and deploy keys (for the fast-forward after a release).

**Tag ruleset** (Settings, Rules): target `v*`; block deletion and block update of matching tags. Creation stays allowed, because the release job creates the tag.

**Renumbering of the first releases.** The two releases published before this scheme (announced as 0.1.0 on commit `4ab225b` and 0.2.0 on commit `e6035b7`) are numbered `v1.0.0` and `v2.0.0` and are final releases. The owner retags them (the tag ruleset blocks deleting old tags until lifted for the occasion) and recreates their GitHub releases; the changelog sections say they were renumbered on 2026-10-15. `dev` is created from `main` once, before the first pull request.

**Labels**: create the labels of [`.github/labels.json`](../../.github/labels.json) (name, color, description) by hand or with a script run by the owner. The issue forms use `bug`, `enhancement`, `documentation` and `status: needs-triage`, and [`.github/release.yml`](../../.github/release.yml) groups generated notes by label; create the labels before the first issue arrives. Milestones are named after the release they feed (`v3.0.0` is the next one; the release job creates the one after it and closes the one it published). The old milestones `0.2.x` and `0.3.0` are renamed by hand. See the [roadmap](../../ROADMAP.md).

**Owner account settings** (the account, not the repository):

- Keep my email address private (Settings, Emails): commits then use a GitHub no-reply address.
- Block command line pushes that expose my email (Settings, Emails): refuses a push whose commits carry a private address.

Check the author of your commits before the first push: `git log -1 --format='%an <%ae>'`.
