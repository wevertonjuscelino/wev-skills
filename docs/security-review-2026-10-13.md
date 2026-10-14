# Security review — 2026-10-13

[Português brasileiro](security-review-2026-10-13.pt-BR.md).

This is a local source review and regression check performed while preparing the public
repository. It is not an external audit, penetration test or certification. The working tree
contained other ongoing changes; the results describe the files inspected at review time.

## Scope and approach

The review inspected execution and command classification, the read-only allowlist, protected
paths, state persistence and locking, approval binding and consumption, audit redaction,
untrusted-output handling, SSH command construction and repository workflows. The primary
references are [the security policy](../SECURITY.md) and the tests in `tests/security/`.
Reproductions used temporary directories and synthetic data. No project data was submitted to
an external classification service, and no remote host was contacted.

## Findings

| Finding | Severity in the documented threat model | Status |
|---|---|---|
| Append-only logs acquired private permissions after writing | Low; conditional local disclosure | Fixed |
| Explicit Git diff helpers were classified as ordinary commands | Medium; approval bypass in execute mode | Fixed |
| Git helpers enabled by existing repository configuration | Medium; residual read-only limitation | Open, documented here |

### 1. Private permissions were applied too late

`core/fsutil.py:append_line` previously used `open(path, "a")`, wrote and flushed the record,
then changed its mode to `0600`. With umask `022`, a newly created file was `0644` while the
content was already persisted. Existing permissive files had the same timing problem.
Another local account could read during that window if it could traverse the parent directory.
New engine-created directories are `0700`, which reduces exposure; pre-existing directories
retain their permissions, so the issue is conditional rather than universal. Logs may contain
operational information and secrets that best-effort redaction does not recognize.

The fix creates append files with `os.open(..., 0600)` and tightens permissive owned files using
their descriptor before writing. It uses the same helper for lock files. A regression test
checks the file's descriptor permissions during `fsync`, for both new and existing files.
Running the previous implementation from `HEAD` with synthetic data observed mode `0644` at
that point; the corrected regression suite passes with `0600`.

### 2. Explicit Git helpers did not require approval

The classifier did not flag `git diff --ext-diff` or `git show --textconv` as commands that
execute configured helper programs. The read-only allowlist already rejected `--ext-diff`,
but execute mode at low/medium risk could still permit it without an approval. `--textconv`
was also missed by the read-only decision.

The fix classifies explicit helper options, including recognized long-option prefixes, as
unanalyzable for `diff`, `show`, `log`, `blame`, `grep` and `cat-file`. This routes them through
approval and prevents read-only treatment. Explicit `--no-ext-diff --no-textconv` remains
unflagged. Replaying `HEAD`'s classifier showed `needs_approval=False` for the two examples;
the corrected classifier returns `True`. Tests cover these examples and related subcommands.

### 3. Existing Git configuration can still execute implicit helpers

A temporary repository with `.gitattributes` and `diff.synthetic.textconv` configured to a
synthetic script executed that script on plain `git diff`, without `--textconv`. Plain Git
read commands remain allowed by the engine's heuristic. Other configuration/environment
features may also execute helpers; this review did not exhaust them.

The explicit-option correction does not solve implicit configuration. Inspect an unfamiliar
repository's configuration and attributes before trusting Git read commands, and use OS-level
isolation where arbitrary helper execution is unacceptable. A future implementation should
define how to disable helpers for approved read commands without changing execution and
approval semantics silently.

## Controls confirmed by inspection and tests

- Execution uses argv rather than a shell, and bare executable resolution uses the configured
  execution path. This does not sanitize the environment of child programs.
- Approvals bind exact argv, working directory and run, expire and are consumed under a lock.
  Matching audit records provide tamper evidence, not proof of a human identity.
- State writes use atomic replacement and advisory locks; safe run identifiers constrain paths.
- Secret redaction covers known patterns and whole argv records. Control characters and forged
  output fences are neutralized in the CLI's untrusted output.
- SSH construction quotes argv and requests strict host-key checking and batch mode.
- Workflow action references are pinned to commit SHAs, permissions are read-only and checkout
  does not persist credentials. Pinning is not a review of the actions themselves.

## Validation and limitations

Python used: **3.14.7**.

- `PYTHONPATH=src python3 -m unittest discover -s tests/security -v`: **291 tests passed**.
- `PYTHONPATH=src python3 -m unittest tests.unit.test_fsutil tests.security.test_classification_gaps -q`:
  **30 tests passed**, including the new regressions.
- Synthetic before/after checks confirmed the former permission window and helper-option miss.
- A synthetic local Git reproduction confirmed implicit textconv execution remains possible.

No real SSH host, paid model or live agent permission prompt was exercised. GitHub repository
settings, private vulnerability reporting, branch protection and secret scanning were not
verified. The complete suite and lint are reported separately by the repository preparation
work, rather than inferred from these focused checks.

The engine shares the agent's OS account and is not a sandbox: a malicious same-account
process can rewrite state and audits, use a pseudo-terminal for operator prompts, or execute
scripts outside the classifier's visibility. Symlink time-of-check races, unrecognized secret
formats and injection paraphrases remain documented limits in the security policy. Other
ongoing intake/specialist changes were preserved and were not independently certified here.
