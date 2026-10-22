# Installer Implementation Plan

Portuguese version: [2026-10-22-installer.pt-BR.md](2026-10-22-installer.pt-BR.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** one `install.sh` that a person runs as `curl -fsSL <url>/install.sh | bash` (or `bash install.sh` from a clone), which asks a few questions, takes the JEV key without echo, installs wev-skills at its latest release plus the third-party skills at their newest versions, registers everything in the harnesses the person picked, configures rea, shows a summary, and can run again safely or uninstall.

**Architecture:** the script is thin. It checks the system, asks the questions, and then calls the `wev` CLI for everything that has rules: `wev skills update` (Part 4) installs wev-skills itself, rea and agent-skills side by side with health checks; `wev harness install` (Part 3) and the Claude Code plugin commands register the harnesses; `wev rea mode|build-image` (Part 5) configure rea; a new `wev jev key set` writes the key file; `wev config validate` checks the user-level configuration the script writes. Two small engine changes make that possible: a **user-level configuration tier** (`~/.config/wev-skills/wev.config.json`, read below a repository's `wev.config.json` and above the defaults) so that "JEV on" and the language persist for the whole account, and the `jev key set` command. Bootstrap: the script clones the latest release tag into a temporary directory and runs that clone's `bin/wev skills update wev-skills`, which installs the release under Part 4's layout and points `current` at it; from then on the script uses `<data>/wev-skills/third-party/wev-skills/current/bin/wev` and deletes the temporary clone. The Claude Code marketplace is added from the `current` directory, so a later `wev skills update wev-skills` is picked up without touching the plugin registration.

**Tech Stack:** bash (POSIX where it costs nothing; bash 3.2 on macOS is the floor, so no associative arrays, no `mapfile`), `curl`, `git`, Python 3.14 (required by the engine; the script may call `python3` only after it checked the version), the `wev` CLI. Tests: Python `unittest` running `bash install.sh --yes …` with fake `claude`, `codex`, `gemini`, `opencode`, `docker`, `git` and `curl` on `PATH` and `--source <this clone>` instead of a download.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.md), Part 1, decisions 1–8, 12, 14, 16, and "Calls I made without the owner" (mode switching at use time; the setup does not touch `~/.claude/CLAUDE.md`). Interfaces: `docs/guides/installation.md` (Claude Code plugin commands, read from `claude plugin --help`), `docs/research/harness-{codex,gemini,opencode}.md`, Part 4 (`wev skills`), Part 3 (`wev harness`), Part 5 (`wev rea`).

## Global Constraints

- The script is one file, `install.sh` at the repository root, under 400 lines, `set -euo pipefail`, no `eval`, no word-splitting of user input into commands; every external call is a literal command with quoted arguments. It never writes outside `$XDG_DATA_HOME/wev-skills`, `$XDG_CONFIG_HOME/wev-skills`, the harness directories the `wev` CLI already writes, and the temporary directory it creates with `mktemp -d` and removes on exit (`trap`).
- **Questions read from `/dev/tty`,** never from stdin: under `curl | bash` stdin is the script itself. Without a tty and without `--yes`, the script stops with one message naming `--yes` and the flags; it never guesses an answer.
- The key is read with `read -rs` from `/dev/tty` and passed to `wev jev key set` on stdin only. It never appears in an argument, an environment variable, a log line or the summary. The script does not echo it back and does not print its length.
- Messages: a two-language table inside the script (`msg <key>`), English and Brazilian Portuguese with identical key sets; a test compares the two sets. The language is asked first (or `--lang`), defaults to the `LANG` prefix, and is passed to every `wev` call as `--lang`.
- Nothing the script downloads is executed before its version is pinned: the release tag comes from the GitHub releases API (`curl` to `api.github.com/repos/wevertonjuscelino/wev-skills/releases/latest`, parsed with `python3 -c` after the Python check), the clone is `git clone --depth 1 --branch <tag> https://github.com/wevertonjuscelino/wev-skills.git`, and the script uses the clone only to run `bin/wev skills update wev-skills`, which re-downloads the release tarball through Part 4's checks. `--source DIR` skips the download and uses `DIR/bin/wev` for everything (developer and test route; also the e2e route for an unpublished branch); the summary then says the install is "from a local source, not self-updating".
- Missing Python 3.14 or Node: the script says which one is missing and offers to run exactly one known installer command that it found on the machine (`uv python install 3.14`, `brew install python`, `brew install node`, `sudo apt-get install …`, `sudo dnf install …`), shown in full before the yes/no. With `--yes` it does not install system packages: it stops and names the command. It never pipes a remote script into a shell to install a dependency.
- Licence: the first lines of `LICENSE` (title and URL) and the sentence "noncommercial use only" are shown before anything is installed; the person confirms (`--yes` counts as read, and the summary repeats the licence line).
- Human-operator steps the script cannot do for the person are printed as next steps, never automated: Codex hook trust, `gemini extensions link`, `codex mcp add rea -- …`.
- Re-run: every step is idempotent through the CLI's own rules (`skills update` is a no-op at the newest version, `harness install` replaces wev's own files, `jev key set` overwrites only the `TYPESAFE_API_KEY` line, `rea mode` rewrites one file). A re-run with different answers reconfigures. The summary says what changed.
- Uninstall (`--uninstall`): `wev harness uninstall --target …` for every manifest present, `claude plugin uninstall wev-skills` and `claude plugin marketplace remove wev-skills-marketplace` when `claude` exists, `wev skills deactivate`, then removes `$XDG_DATA_HOME/wev-skills`. It asks before removing `$XDG_CONFIG_HOME/wev-skills` (the key file and the user config); with `--yes` it keeps that directory unless `--purge` is also given. It prints what it removed and what it kept.
- Hosting the script (the `<url>`) is the owner's call. The docs show `bash install.sh` from a clone, and the `curl` line with the raw GitHub URL of `main` labeled "after the owner publishes it".
- Python side: standard library, mypy strict, frozen dataclasses, functions < 50 lines, files < 400, i18n keys identical in `en` and `pt-BR`, docs EN + pt-BR in the same commit. Commit subjects `<type>: <description>`. No push without the owner's ok.

## Review Focus

1. Secrets: the key never reaches argv, the environment, a temp file, a log or the summary; the key file is 0600 in a 0700 directory; an interrupted `jev key set` leaves no partial file (write to a temp file in the same directory, `chmod`, then `rename`). Tested in Task 2 and Task 4.
2. `curl | bash` safety: all prompts read `/dev/tty`; without a tty the script refuses unless `--yes`; `set -e` plus `trap` removes the temp clone on every exit path; a failed `wev` call stops the script with that call's JSON error shown, never a half-installed silent success. Tested in Task 4.
3. Trust chain: the script runs code only from the pinned tag clone and from `current`; `--source` is the only way to run code from elsewhere and the summary says so; no `eval`, no `sh -c "$var"`. Tested in Task 4 (grep-level checks on the script plus behaviour checks).
4. The user-level configuration tier cannot lower a repository's rules: the repository file overrides the user file, `--config` overrides both, `trust_errors` applies to the merged result, a run pins the merged result and `config show` names both sources. Tested in Task 1.
5. Uninstall removes only what wev wrote (it goes through the CLI's manifests) and never the key file without an explicit yes or `--purge`. Tested in Task 4.

---

### Task 1: User-level configuration tier

**Files:**
- Modify: `src/wev_skills/config.py` (`resolve_config`, `ResolvedConfig.source`), `src/wev_skills/commands/config.py` (`config show` output), `src/wev_skills/locales/core.*.json` if a message changes
- Test: `tests/unit/test_config_resolution.py` (new or the existing config test module)

**Interfaces:**
- `user_config_path() -> Path` = `user_config_home() / "wev.config.json"`.
- `resolve_config(explicit, root)`: `explicit` → that file only (unchanged); else the user file (if it is a regular file) parsed first and the repository `wev.config.json` (if present) deep-merged over it, using the existing `deep_merge`/`parse_config(path, overrides)` machinery (read the repository file's JSON object and pass it as `overrides` over the user file, so one code path validates both); `source` becomes `"<user path> + <repo path>"`, `"<user path>"`, `"<repo path>"` or `"defaults"`. `config show` prints `config_source` as before and adds `config_sources: [...]` (list, possibly empty). The run pins the merged result exactly as today.
- `trust_errors` is applied to the merged configuration (already the case through the callers; add a test).
- The hook already protects `user_config_home()` (Part 5), so an agent cannot write the user file through Bash.

- [ ] **Step 1: Failing tests.** User file alone sets `decision.provider: jev` and `language`; repository file overrides one key and keeps the rest; `--config` ignores both; a user file that is a symlink or a directory is ignored (not followed); an invalid user file fails with the existing `config_invalid` error naming the user path; `config show` lists both sources; `run start` pins the merged digest.
- [ ] **Step 2–5:** run/fail, implement, run/pass; deliberate break: make the user file override the repository file and confirm a test fails; restore. **Commit** `feat: read a user-level wev.config.json below the repository one`

### Task 2: `wev jev key set`

**Files:**
- Modify: `src/wev_skills/decisions/jev_key.py` (`write_env_key(path, key)`), `src/wev_skills/commands/jev.py` (`key set`), `src/wev_skills/adapters/claude_code/engine_cli.py` (person-only set), locales `decisions.*.json` / `core.*.json`
- Test: `tests/unit/test_jev_key_set.py`, hook tests

**Interfaces:**
- `write_env_key(path: Path, key: str) -> None`: refuses an empty key, one with whitespace or control characters, or longer than 512 bytes (`ValidationError("jev_key_invalid")`); creates the parent 0700; writes the file atomically (temp file in the same directory, 0600, `os.replace`); keeps every other line of an existing file and replaces or appends `TYPESAFE_API_KEY=<key>`; refuses a symlinked file or directory (`ValidationError("env_file_refused")`).
- `wev jev key set` reads the key from stdin (one line, stripped of the trailing newline only), calls `write_env_key(env_file_path(), key)`, then runs the existing status logic and prints `{"written": "<path>", "key_source": "env_file", "usable": true|false}` — never the key. With a tty on stdin and no data, it says to pipe the key.
- Hook: `("jev", "key")` joins the person-only set (asked on Claude Code, denied elsewhere) with reason `engine_jev` or a new one; the skill texts do not mention it (the person runs it from the installer or a terminal).

- [ ] **Step 1: Failing tests.** Roundtrip, other lines preserved, mode 0600 and parent 0700, symlink refused, invalid keys refused, atomicity (patch `os.replace` to raise: no partial file, old file intact), the CLI payload has no key material (assert the key string is absent from stdout and stderr), hook ask/deny.
- [ ] **Step 2–5** as before; deliberate break: skip the `chmod` and confirm the mode test fails. **Commit** `feat: add wev jev key set for the installer`

### Task 3: `install.sh`

**Files:**
- Create: `install.sh` (executable bit set, `#!/usr/bin/env bash`)

**Behaviour, in order (each step prints one line of what it does and its outcome):**
1. Parse flags: `--yes`, `--lang en|pt-BR`, `--harness claude,codex,gemini,opencode` (default: the ones detected), `--jev` / `--no-jev` (default: ask), `--rea-mode isolated|direct` (default: isolated when `docker` is found), `--source DIR`, `--uninstall`, `--purge`, `--help`. Unknown flag → usage, exit 2.
2. Language (ask or `--lang`), then the licence block and confirmation.
3. System: `uname` is Darwin or Linux (else stop); `git` and `curl` present (else stop with the install hint); Python ≥ 3.14 found as `python3.14`, `python3` or `python` (compare with `python3 -c 'import sys; print(sys.version_info >= (3, 14))'`); Node/npm present (needed by rea's direct mode and health check; if missing and the person wants rea, offer the installer command, or skip rea with a note). Docker presence is detected, not required.
4. Harness detection (`command -v` for `claude`, `codex`, `gemini`, `opencode`), ask which to install into (`--yes`: the detected ones, or `--harness`).
5. Bootstrap wev (unless `--source`): latest tag from the releases API, shallow clone into the temp dir, `bin/wev --lang L skills update wev-skills`, then `WEV=<data>/wev-skills/third-party/wev-skills/current/bin/wev`; `"$WEV" version` must print the tag's version.
6. JEV: ask (or flags). Yes → `read -rs` from `/dev/tty`, pipe to `"$WEV" jev key set`, then a real probe `"$WEV" jev ask --questions <temp file with one noul question> --state "installer probe"`; on failure, show the error, offer to retry once, else continue with JEV off. On success write the user config `{"decision": {"provider": "jev"}, "language": "<lang>"}` to `$XDG_CONFIG_HOME/wev-skills/wev.config.json` (0600) and run `"$WEV" config validate` on it. No → write `{"language": "<lang>"}` only (so a previous `jev` setting is turned off on re-run).
7. rea: `"$WEV" rea mode <mode>`; isolated → ask to build the image now (`"$WEV" rea build-image`, which can take minutes), `--yes` builds.
8. Third parties: `"$WEV" skills update rea`, `"$WEV" skills update agent-skills`, `"$WEV" skills activate`. A failed health check is reported and the step continues (Part 4 leaves the previous version active).
9. Harnesses: `claude` → `claude plugin marketplace add "<current dir>"` then `claude plugin install wev-skills@wev-skills-marketplace` (with `--source`, the marketplace is the source dir); `codex|gemini|opencode` → `"$WEV" harness install --target X` and print its `next_steps`; for codex also print the `codex mcp add rea -- <python> <wev> rea serve` line.
10. Verify and summarize: `"$WEV" version`, `"$WEV" jev status` (`orchestration`), `"$WEV" rea status` (mode), `"$WEV" skills list` (active versions), the harness results; a table of installed / skipped (with the reason) / next steps you do yourself; the licence line again.
- `--uninstall`: as in the constraints.

- [ ] **Step 1:** write the script. **Step 2:** `bash -n install.sh`; `shellcheck` if available (not a dependency; say whether it ran). **Commit** with Task 4.

### Task 4: Tests for `install.sh`

**Files:**
- Create: `tests/unit/test_install_sh.py`, `tests/fixtures/fake_bin/` (small `claude`, `codex`, `gemini`, `opencode`, `docker`, `git`, `curl` shell scripts that append their argv to `$FAKE_LOG` and print the minimal JSON/text the script reads)
- Each test runs `bash install.sh --yes --source <repo root> …` with `PATH=<fake_bin>:<a dir with real bash, python3, coreutils>`, `HOME`, `XDG_*` in a temp dir, and `WEV_SKILLS_NO_NETWORK=1` honoured by Part 4's registry client only if such a switch exists; otherwise the tests pass `--source` and pre-seed the third-party state so `skills update` is a no-op (or patch the registry URL through the existing test hook in `tests/fixtures/fake_registry_server.py`, run in-process).

- [ ] **Tests (each named for the behaviour):** no tty and no `--yes` → exit 2 and the message naming `--yes`; `--help` prints every flag; message key sets EN/pt-BR identical (parse the table); the script has no `eval` and no unquoted `$` inside a command position (grep-level); licence text printed before the first install call (order in `FAKE_LOG` vs stdout); key via stdin lands in the key file 0600, dir 0700, absent from stdout/stderr/`FAKE_LOG`; JEV probe failure → user config has no `jev` and the summary says so; `--no-jev` on a machine where the user config had `jev` → turned off; `--rea-mode direct` writes rea.json; detected harnesses only → the fake `claude` log shows `marketplace add` + `install`, codex/gemini/opencode go through `harness install` (assert on the manifests Part 3 writes); re-run with the same flags → no duplicate registrations (fake logs show a second `install`, manifests unchanged); `--uninstall --yes` leaves the data dir gone and the config dir present; `--uninstall --yes --purge` removes both; a failing `wev` call (fake `docker` exit 1 during build-image) → non-zero exit, temp dir removed, the error JSON in the output.
- [ ] Deliberate break: remove the `/dev/tty` redirection from one `read`; confirm the no-tty test fails. **Commit** `feat: add the interactive installer and its tests`

### Task 5: Docs

**Files:** `docs/guides/installation.md` + pt-BR (new first section "Quick install" with the two lines and the flags table; a re-run and uninstall subsection; move the clone route below it); `README.md` + pt-BR (install line at the top, `claude plugin validate`'s README advisory wants the marketplace install line too); `SECURITY.md` + pt-BR (section "Installer": what it reads from the tty, where it writes, what it never does, the `--source` trust note, the operator steps it leaves to the person); `CHANGELOG.md`; `docs/mvp-status.md` + pt-BR.

Labels: "implemented and tested with fake harness CLIs and a local source (unit tests)"; "the download route, a real `claude plugin install`, real Codex/Gemini/OpenCode and a real JEV probe are not run in this change (e2e part)"; the `curl` line "after the owner publishes it".

- [ ] **Edit; run** `make check`, `bin/wev readme check`, `bin/wev claude-md check`, `claude plugin validate .` (the README advisory should be gone). **Commit** `docs: document the installer`
