# Maintaining the repository

Portuguese version: [maintaining.pt-BR.md](maintaining.pt-BR.md).

This guide is for the owner and for anyone who merges changes: the commit format, the branch and pull request flow, how to cut a release, and the intended GitHub configuration, which cannot be set from the working tree. The repository is <https://github.com/wevertonjuscelino/wev-skills>. The settings section is the source of truth for how the repository should be configured; it is documented only, and a setting counts as applied only after someone confirms it in GitHub.

## Commit format

```
<type>: <description>
<type>(<scope>): <description>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`. The subject is at most 72 characters and has no trailing period. Merge and revert commits that git generates are allowed. The `commit-msg` hook in `.githooks/` checks this after `make hooks` (see [CONTRIBUTING.md](../../CONTRIBUTING.md)). Do not name any tool as author or co-author, and add no co-author trailer.

## Branches and pull requests

1. Work on a branch, never on `main`: `git switch -c <type>/<short-name>`.
2. Push the branch and open a pull request against `main`. Fill in the pull request template, including the evidence label of each claim.
3. Wait for the CI checks to pass (`test` on Ubuntu and macOS, `lint`, `skills`, `git hooks and documents`, `secrets-scan`). CodeOwners asks the owner for review.
4. Merge with squash or rebase, so `main` keeps a linear history of well-formed commit subjects. For a squash, the pull request title becomes the subject and has to follow the commit format.
5. Once branch protection is on, nobody pushes directly to `main`. The `pre-push` hook already refuses a push to `main` with uncommitted changes to tracked files, but a hook is a convenience, not a control.

## Release steps

1. Update [CHANGELOG.md](../../CHANGELOG.md): move the entries of `[Unreleased]` under a new `## [X.Y.Z] - YYYY-MM-DD` heading, leave `[Unreleased]` empty above it, and update the compare and tag links at the bottom of the file.
2. Bump the version everywhere it is written, in one commit: `pyproject.toml` (`version`), `.claude-plugin/plugin.json` (`version`) and `src/wev_skills/__init__.py` (`__version__`). `.claude-plugin/marketplace.json` has no version field. `tests/unit/test_repo_hygiene.py` fails when the three differ.
3. Run `make test` and `make lint`, and `bin/wev readme check`. Record the result lines in [mvp-status.md](../mvp-status.md) and its twin, and in the READMEs, in the same commit.
4. Merge that commit through a pull request.
5. Tag the merge commit with an annotated tag: `git tag -a vX.Y.Z -m "wev-skills X.Y.Z"` and `git push origin vX.Y.Z`.
6. The push of a `v*.*.*` tag starts [`.github/workflows/release.yml`](../../.github/workflows/release.yml). Its `verify` job checks that the tag equals `v` plus the `pyproject.toml` version and runs `make test`. Its `release` job (the only job with write access to contents) takes the `[X.Y.Z]` section of the changelog through `scripts/changelog_section.py` and runs `gh release create` with `--verify-tag`, adding `--prerelease` when the major version is `0` or the version has a `-` suffix. The release uses that changelog section as its notes; the categories of `.github/release.yml` apply only if you ask GitHub to generate notes instead. If the changelog has no section for the version, the job fails and no release is created.
7. Check the release page and the workflow run. If the workflow failed before `release`, fix the cause, delete the tag locally and on the remote (`git tag -d vX.Y.Z` and `git push origin :refs/tags/vX.Y.Z`; the tag ruleset below blocks the remote deletion until the owner lifts the rule for the occasion) and tag again.

Pushing a tag publishes the project. Do it deliberately.

The first tag, `v0.1.0`, is created retroactively on the commit that was published as 0.1.0 (`4ab225b`): `git tag -a v0.1.0 4ab225b -m "wev-skills 0.1.0"`. That commit has no `release.yml`, so pushing the tag starts no release workflow; create the release by hand from the `[0.1.0]` changelog section and mark it as a pre-release.

## Repository settings

This is the intended configuration of `wevertonjuscelino/wev-skills`, kept here so that it is reviewable and can be re-applied. Evidence today: documented only. Nothing here is known to be applied until the owner confirms it in GitHub, and the [MVP status](../mvp-status.md) lists it as "to apply".

**General** (Settings, General):

- Description and topics: a one-line description of the engine and the plugin, and topics such as `claude-code`, `claude-code-plugin`, `ai-agents`, `agent-orchestration`, `cli` and `python`.
- Features: Issues on, Discussions on (with a Q&A category, which [SUPPORT.md](../../SUPPORT.md) points to), Wiki off, Projects off. Documentation lives in the repository.
- Merge settings: allow squash merging and rebase merging; do not allow merge commits; delete the head branch on merge.

**Security** (Settings, Code security):

- Private vulnerability reporting on: the route [SECURITY.md](../../SECURITY.md) tells reporters to use. Without it the "Report a vulnerability" button does not appear.
- Secret scanning and push protection on. They complement `scripts/scan_secrets.py`, which is a narrow tripwire.
- Dependabot alerts and Dependabot security updates on. `.github/dependabot.yml` separately asks for weekly pull requests that update pinned GitHub Actions.

**Branch ruleset on `main`** (Settings, Rules):

- Block deletion and block force pushes.
- Require linear history.
- Require a pull request before merging, with 0 required approvals (one maintainer cannot approve their own pull request).
- Require these status checks, named as `ci.yml` reports them: `test (ubuntu-latest, Python 3.14)`, `test (macos-latest, Python 3.14)`, `lint`, `skills`, `git hooks and documents` and `secrets-scan`. The last has no `name:` in the workflow, so its check name is the job id.
- Bypass list: repository admin, so the owner can still push directly. A bypass is for the owner's convenience, not a control against the owner.

**Tag ruleset** (Settings, Rules): target `v*`; block deletion and block update of matching tags. Creation stays allowed, because creating the tag is what starts the release workflow.

**Labels**: create the labels of [`.github/labels.json`](../../.github/labels.json) (name, color, description) by hand or with a script run by the owner. The issue forms use `bug`, `enhancement`, `documentation` and `status: needs-triage`, and [`.github/release.yml`](../../.github/release.yml) groups generated notes by label; create the labels before the first issue arrives. Create one milestone per planned version, as the [roadmap](../../ROADMAP.md) describes.

**Owner account settings** (the account, not the repository):

- Keep my email address private (Settings, Emails): commits then use a GitHub no-reply address.
- Block command line pushes that expose my email (Settings, Emails): refuses a push whose commits carry a private address.

Check the author of your commits before the first push: `git log -1 --format='%an <%ae>'`.
