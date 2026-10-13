# Maintaining the repository

Portuguese version: [maintaining.pt-BR.md](maintaining.pt-BR.md).

This guide is for the owner and for anyone who merges changes: the commit format, the branch and pull request flow, how to cut a release, and the GitHub settings that cannot be set from the working tree. The repository is <https://github.com/wevertonjuscelino/wev-skills>. Nothing in the settings section is already enabled: those are recommendations for the owner to turn on by hand, and each one is documented only until someone confirms it in GitHub.

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
5. Tag the merge commit: `git tag -a vX.Y.Z -m "wev-skills X.Y.Z"` and `git push origin vX.Y.Z`.
6. Create the GitHub release from the tag (Releases, "Draft a new release"). Use the changelog entry as the notes, and mark it as a pre-release while the version is `0.x`.

Pushing a tag and creating a release publish the project. Do them deliberately.

## Repository settings to turn on

These live in GitHub, not in the working tree, so no file in this repository can set them. They are recommendations; as of this commit none of them is known to be enabled.

Repository settings (Settings of `wevertonjuscelino/wev-skills`):

- **Branch protection or a ruleset on `main`** (Settings, Rules or Branches): require a pull request before merging, require the status checks of `ci.yml` to pass, block force pushes, and block deletion of the branch.
- **Private vulnerability reporting** (Settings, Code security): the route [SECURITY.md](../../SECURITY.md) tells reporters to use. Without it the "Report a vulnerability" button does not appear.
- **Secret scanning and push protection** (Settings, Code security): GitHub's scanner blocks a push that contains a recognized token. It complements `scripts/scan_secrets.py`, which is a narrow tripwire.
- **Dependabot alerts** (Settings, Code security): `.github/dependabot.yml` already asks for weekly pull requests that update pinned GitHub Actions; alerts are a separate switch.

Owner account settings (the account, not the repository):

- **Keep my email address private** (Settings, Emails): commits then use a GitHub no-reply address.
- **Block command line pushes that expose my email** (Settings, Emails): refuses a push whose commits carry a private address.

Check the author of your commits before the first push: `git log -1 --format='%an <%ae>'`.
