# Skill maintenance policy

Portuguese: `policy.pt-BR.md`. Source: `upstream.json`.

## Installation and provenance

The external guide is [netresearch/skill-repo-skill](https://github.com/netresearch/skill-repo-skill),
version 2.4.0, reviewed at commit `42a5e85798a8cdfda2866afb0de9aadb04e187f3`.
Its content is CC-BY-SA-4.0; scripts are MIT, copyright Netresearch DTT GmbH.
This plugin ships an original coordination skill and a source pin; it does not bundle the guide.
Installing wev-skills alone does not install this external dependency.

Use your environment's skill installer with `--repo netresearch/skill-repo-skill`,
`--path skills/skill-repo` and `--ref` equal to the pinned commit. Install in the environment's global skills directory and reload skills as required. Preserve the upstream license
files alongside downloaded material. Record the commit in the installed directory so its
version can be compared to the source pin. For Claude Code, install the external plugin
separately through the Netresearch marketplace; compare its source version to this pin.
A differing installed version needs a reconciliation review before use.

## Shared standards and local exceptions

The source pin in the designated coordination repository is the common reference for a
maintenance operation. Record that repository and commit before starting. Other repositories
may carry a copy of the pin, but updates originate in the coordination repository.
For each repository record: absolute path, branch, existing changes, installed skill version,
local instructions, manifests, licenses, required checks and applicable shared conventions.
Compare the inventory before writing. Use a table of standard, repository, current behavior,
proposed behavior, local exception and reason. Resolve conflicts explicitly; do not let task
ordering determine which repository's rules win. A skill is guidance, not authority to override
user instructions, local security requirements or human approval gates.

For wev-skills retain the standard-library-only Python engine, existing MIT licensing,
`.claude-plugin/plugin.json` as the current manifest, English and Brazilian Portuguese twins,
and existing tests and lint. Composer packaging, Netresearch branding, split licensing and
upstream CI are optional migration proposals, never automatic requirements here. Do not run
the Netresearch structure validator as a wev-skills acceptance check unless its assumptions
have first been reviewed and made applicable.

## Review updates and reconcile repositories

1. At the start of maintenance, compare the pin with upstream tags/commits. Report whether
   checked, unchanged, newer, unavailable or incompatible; never assert freshness without a check.
2. Fetch the candidate into a separate temporary checkout. Review its diff, licenses, scripts,
   references and release notes before execution. Retain the current installation during review.
3. Prepare a change to the source pin and document the applicable changes and local exceptions.
   Validate the coordination repository first. A rejected candidate leaves the previous pin active.
4. Apply the reviewed common commit to each in-scope repository in isolation. Do not overwrite
   dirty files or update global installed paths from competing parallel agents. One designated
   maintainer performs installation changes after review; keep a recoverable previous copy.
5. Run each repository's own checks. Report repository, before/after commit, exceptions, checks,
   failures and deferred work. Publish only within the user's authorized scope.

There is no scheduled polling or automatic cross-repository synchronization in this integration.
The workflow provides coordinated review; it does not guarantee perpetual freshness.
