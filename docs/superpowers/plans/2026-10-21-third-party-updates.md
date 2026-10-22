# Third-Party Skill Updates Implementation Plan

Portuguese version: [2026-10-21-third-party-updates.pt-BR.md](2026-10-21-third-party-updates.pt-BR.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** wev installs the newest version of each third-party skill (rea, agent-skills) and of wev itself, checks upstream once a day at the first session of the day, asks the person before updating, installs the new version next to the current one, runs a health check, and switches only when it passes; the person can roll back or freeze a source.

**Architecture:** A `third_party` package under `src/wev_skills/` holds a fixed registry of sources (kind `npm` or `github`), a per-user state file (active version, previous version, frozen flag, last check) that is validated as data, version lookups over HTTPS with short timeouts, side-by-side installs under the user data directory, one health check per source kind, and the switch/rollback/freeze operations. A new CLI group `wev skills` exposes them. The Claude Code `SessionStart` hook gains a `startup` entry that runs `wev skills check --daily`: it exits silently unless a day has passed, then injects one short paragraph (`additionalContext`) naming the updates and telling the model to ask the person once. The `wev-skill-maintenance` skill carries the "ask once, update on yes" instruction. Activation of agent-skills into harnesses uses symlinks in the harnesses' shared user skill roots, tracked by a manifest like Part 3's.

**Tech Stack:** Python 3.14 standard library (`urllib.request`, `tarfile` with `filter="data"`, `json`, `subprocess` without a shell), `unittest`; a local fake HTTP server fixture for the registries and a fake `npx` script that speaks MCP JSON-RPC over stdio.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.md), Part 4, decisions 7, 8, 16, and the calls "shared third-party installs", "newest = latest GitHub release, else HEAD", "refusing an update waits for the next version". Claude Code hook facts: SessionStart matchers `startup|resume|clear|compact|fork`, `hookSpecificOutput.additionalContext` capped at 10,000 chars, no decision control, default timeout 600 s, no built-in once-per-day (source: https://code.claude.com/docs/en/hooks.md, read 2026-10-21).

## Global Constraints

- Standard library only, Python >= 3.14, mypy strict, frozen dataclasses, functions < 50 lines, files < 400 lines.
- Every user-facing string goes through i18n with identical keys in `en` and `pt-BR`. Docs change in EN and pt-BR in the same commit.
- Unit tests make no network calls beyond loopback and never run the real `npx`, `npm`, `gh` or GitHub. Real downloads belong to the e2e part.
- Sources, exact values: `rea` = npm package `rea-agents`, newest = `dist-tags.latest` from `https://registry.npmjs.org/rea-agents`; `agent-skills` = GitHub `addyosmani/agent-skills`, newest = `tag_name` of `/releases/latest`, tarball = that release's `tarball_url`; `wev-skills` = GitHub `wevertonjuscelino/wev-skills`, same rule. A source with no release uses the default branch HEAD (`/commits/HEAD` sha) and the branch tarball. Changelog link = the release `html_url` (npm: `https://github.com/morluto/rea/releases/tag/rea-agents-<version>`).
- Everything downloaded is untrusted data: tar extraction uses `tarfile.extractall(filter="data")` into a fresh directory, refuses members outside it, caps the archive at 50 MiB, and the directory is never executed from. The GitHub tarball has no checksum; the docs say so.
- Data layout: `$XDG_DATA_HOME/wev-skills/third-party/` (else `~/.local/share/wev-skills/third-party/`): `state.json`, `<source>/<version>/` per installed version, `<source>/current` symlink to the active version, `manifest.json` for activation symlinks. The state file is data: unknown keys, wrong types or a version string that is not `[A-Za-z0-9._-]+` are rejected with `ValidationError`.
- Network timeouts: 5 s per request for the check, 120 s for a download, 60 s for a health check. The daily check never blocks a session start longer than 10 s in total and never fails loudly: on any error it prints nothing and leaves no marker.
- The hook asks (Claude Code `RUN_COMMANDS`) for `skills update`, `skills rollback`, `skills freeze` and `skills install`; `skills check`, `skills list` and `skills show` are not asked. On harnesses without an ask decision these four are `person_only` → deny (Part 3 marker).
- Commit subjects `<type>: <description>`, at most 72 characters, no AI attribution. No push without the owner's ok.

## Review Focus

1. A registry or GitHub answer with an unexpected shape (missing `tag_name`, a non-string version, HTML instead of JSON, a 5xx) must leave the state untouched and report `check_failed` for that source, never crash or write a marker. Tested in Task 2.
2. A tarball with a member outside the target (`../x`, an absolute path, a symlink to `/etc`) must be refused before anything is written, and the partial directory removed. Tested in Task 3.
3. A health check that passes on a broken install (empty tools list, zero `SKILL.md` files, `wev version` printing another version) must fail; the previous version stays active. Tested in Task 4.
4. Running `skills update` twice, or `rollback` with no previous version, must not corrupt the state or the `current` symlink. Tested in Task 5.
5. A frozen source is never updated and never nagged about; the daily check skips it and says so once in `skills list`. Tested in Tasks 2 and 5.

---

### Task 1: Registry and state

**Files:**
- Create: `src/wev_skills/third_party/__init__.py`, `src/wev_skills/third_party/sources.py`, `src/wev_skills/third_party/state.py`
- Create: `src/wev_skills/commands/skills.py`, `src/wev_skills/locales/skills.en.json`, `skills.pt-BR.json`
- Test: `tests/unit/test_third_party_state.py`, `tests/unit/test_cli_skills.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Source: name: str; kind: Literal["npm", "github"]; package: str; health: Literal["mcp", "skills", "wev"]; changelog: str` (changelog is a format string with `{version}`).
  - `SOURCES: tuple[Source, ...]` with exactly `rea` (npm, `rea-agents`, `mcp`), `agent-skills` (github, `addyosmani/agent-skills`, `skills`), `wev-skills` (github, `wevertonjuscelino/wev-skills`, `wev`).
  - `def source(name: str) -> Source` raising `ValidationError("unknown_source")`.
  - `@dataclass(frozen=True) class SourceState: active: str | None; previous: str | None; frozen: bool; last_check: str | None; latest_seen: str | None; declined: str | None` (`declined` = the version the person said no to; the check nags again only when `latest != declined`).
  - `@dataclass(frozen=True) class State: sources: Mapping[str, SourceState]; checked_at: str | None` with `load(path) -> State` (missing file = empty state; invalid = `ValidationError("state_invalid")`) and `save(path, state)` through `atomic_write_text` with mode 0600.
  - `def data_home() -> Path` (`$XDG_DATA_HOME/wev-skills/third-party`, else `~/.local/share/...`).
- CLI: `wev skills list` prints `{"sources": [{"name", "kind", "active", "previous", "frozen", "latest_seen", "changelog"}]}`.

- [ ] **Step 1: Failing tests:** `test_sources_are_exactly_the_three`; `test_state_roundtrip`; `test_missing_state_is_empty`; `test_invalid_state_rejected` (bad version string `../x`, non-bool `frozen`, unknown key); `test_list_cli` (in-process through `cli.main`, isolated XDG/HOME).
- [ ] **Step 2: Run, see them fail. Step 3: Implement. Step 4: Run, pass; break the version regex on purpose, confirm, restore.**
- [ ] **Step 5: Commit** `feat: add the third-party source registry and state`

### Task 2: Version check and the daily hook

**Files:**
- Create: `src/wev_skills/third_party/check.py`
- Modify: `src/wev_skills/commands/skills.py`, `hooks/hooks.json`, `src/wev_skills/adapters/claude_code/hooks.py` (a `skills_check` hook handler) or `commands/hook.py`
- Create: `tests/fixtures/fake_registry_server.py` (loopback HTTP server scripted per path), test `tests/unit/test_third_party_check.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `def latest(source: Source, opener: Callable[[str, float], bytes], base_urls: Mapping[str, str]) -> Release` where `@dataclass(frozen=True) class Release: version: str; url: str; tarball: str | None`. `base_urls` has `npm` and `github` roots so tests point at the fake server; defaults `https://registry.npmjs.org` and `https://api.github.com`. Any failure raises `CheckFailed(code)`.
  - `def check(state: State, now: datetime, opener, base_urls, *, force: bool) -> tuple[State, list[Update]]` with `@dataclass(frozen=True) class Update: source: str; active: str | None; latest: str; url: str`. Skips frozen sources; skips a source whose `latest == declined`; records `latest_seen`, `last_check`; `checked_at` is set only when `force` or a day has passed (24 h since `checked_at`).
  - `def daily_context(updates: Sequence[Update]) -> str`: the `additionalContext` paragraph, i18n key `skills.hook.updates`, under 1,000 chars, naming each source, versions and changelog URL, and the instruction "ask the person once whether to update; on yes run `wev skills update <source>`; on no run `wev skills decline <source>`".
- CLI: `wev skills check [--daily] [--json]`. `--daily`: exit 0 silently when not due; when due, performs the check with a 10 s total budget and prints the Claude `SessionStart` JSON (`hookSpecificOutput.additionalContext`) or nothing. Without `--daily`: always checks and prints `{"updates": [...], "checked": [...], "failed": [...]}`.
- `wev skills decline <source>` records `declined = latest_seen`.
- `hooks/hooks.json`: add a `SessionStart` entry with matcher `startup` running `"${CLAUDE_PLUGIN_ROOT}/bin/wev" skills check --daily`, timeout 15. The existing `compact|resume` entry stays.

- [ ] **Step 1: Write the fake server fixture** (scripted responses by path: npm doc, GitHub releases/latest, commits/HEAD, a 500, HTML).
- [ ] **Step 2: Failing tests:** `test_latest_npm`, `test_latest_github_release`, `test_github_without_release_uses_head`, `test_bad_shape_is_check_failed` (Review Focus 1: 4 shapes), `test_frozen_skipped`, `test_declined_skipped_until_new_version`, `test_daily_not_due_prints_nothing_and_writes_nothing`, `test_daily_due_prints_session_json_under_10k`, `test_daily_network_error_prints_nothing_leaves_no_marker`, `test_hooks_json_has_startup_entry`, `test_hook_does_not_ask_for_check`.
- [ ] **Step 3–5:** run/fail, implement, run/pass, break the 24 h rule on purpose, restore. **Commit** `feat: check third-party versions daily and ask through the session hook`

### Task 3: Fetch and install side by side

**Files:**
- Create: `src/wev_skills/third_party/fetch.py`
- Modify: `src/wev_skills/commands/skills.py`
- Test: `tests/unit/test_third_party_fetch.py` (tarballs built in the test with `tarfile`)

**Interfaces:**
- Produces:
  - `def install_version(source: Source, release: Release, home: Path, opener, runner: Runner) -> Path`: for `github`, downloads `release.tarball` (cap 50 MiB, `CheckFailed("too_large")`), extracts with `filter="data"` into `home/<source>/<version>.tmp-<pid>`, strips the single top-level directory GitHub adds, verifies no member escaped, then renames to `home/<source>/<version>`; for `npm`, writes `home/rea/<version>/npm-ref.json` with `{"package": "rea-agents", "version": ...}` and runs nothing (npx resolves the pinned version at use; the health check in Task 4 warms it).
  - `def mcp_argv(version: str) -> tuple[str, ...]` = `("npx", "-y", f"rea-agents@{version}", "mcp")`, the argv Part 5 writes into MCP configs.
  - Already-installed version: returns the existing path without downloading.
- CLI: `wev skills install <source> [--version V]` (default: latest from a fresh check) installs without switching, prints `{"source", "version", "path", "active": false}`.

- [ ] **Step 1: Failing tests:** `test_github_tarball_extracted_under_version_dir`, `test_member_outside_target_refused_nothing_left` (Review Focus 2: `../x`, absolute, symlink to `/etc`, hardlink), `test_too_large_refused`, `test_existing_version_not_redownloaded`, `test_npm_install_writes_ref_only`, `test_hook_asks_for_skills_install`.
- [ ] **Step 2–5** as before; break the escape check on purpose. **Commit** `feat: install third-party versions side by side`

### Task 4: Health checks

**Files:**
- Create: `src/wev_skills/third_party/health.py`, `tests/fixtures/fake_npx_mcp.py` (speaks JSON-RPC `initialize` and `tools/list` over stdio; env-scripted failures)
- Test: `tests/unit/test_third_party_health.py`

**Interfaces:**
- Produces `def health(source: Source, version: str, home: Path, runner: Runner, *, npx: str = "npx", python: str = sys.executable) -> HealthReport` with `@dataclass(frozen=True) class HealthReport: ok: bool; code: str; detail: str`:
  - `mcp`: runs `mcp_argv(version)` (with `npx` replaceable for tests), sends `initialize` then `tools/list` as JSON-RPC over stdio with a 60 s budget; ok when the tools list has at least one tool. Codes: `spawn_failed`, `timeout`, `bad_jsonrpc`, `no_tools`.
  - `skills`: under `home/agent-skills/<version>/skills/`, at least one `*/SKILL.md`, and every one has frontmatter with `name` equal to its directory and a non-empty `description`. Codes: `no_skills`, `bad_skill:<dir>`.
  - `wev`: runs `[python, home/wev-skills/<version>/bin/wev, version]` and requires the printed version to equal `<version>` with its leading `v` stripped. Codes: `spawn_failed`, `version_mismatch`.
- Nothing from the installed directory is imported into this process; everything runs as a subprocess without a shell.

- [ ] **Step 1: Failing tests** with the fake npx and temp dirs: ok paths for all three kinds; `test_empty_tools_list_fails`, `test_zero_skill_files_fails`, `test_skill_name_mismatch_fails`, `test_wrong_wev_version_fails` (Review Focus 3), `test_mcp_timeout_fails`.
- [ ] **Step 2–5**; break `no_tools` on purpose. **Commit** `feat: add health checks for mcp, skill and wev versions`

### Task 5: Update, rollback, freeze and activation

**Files:**
- Create: `src/wev_skills/third_party/switch.py`, `src/wev_skills/third_party/activate.py`
- Modify: `src/wev_skills/commands/skills.py`, `src/wev_skills/adapters/claude_code/engine_cli.py` (`skills update|rollback|freeze|install` in `RUN_COMMANDS`, person_only on other harnesses), `skills/wev-skill-maintenance/SKILL.md`
- Test: `tests/unit/test_third_party_switch.py`, `tests/unit/test_third_party_activate.py`, hook tests

**Interfaces:**
- `def update(source, home, state, opener, runner, base_urls) -> tuple[State, UpdateResult]`: check → `install_version` → `health` → on ok: `previous = active`, `active = new`, repoint `home/<source>/current` (symlink replaced atomically: create `current.tmp` then `os.replace`), `declined = None`; on failure: state unchanged, the new directory kept for inspection, `UpdateResult(ok=False, code=...)`. Frozen → `ValidationError("frozen")`. Already at latest → no-op result.
- `def rollback(source, home, state) -> State`: swaps `active` and `previous` and repoints `current`; no previous → `StateConflict("no_previous")`.
- `def freeze(source, state, on: bool) -> State`.
- Activation (agent-skills only): `def activate(home, manifest_path, roots: Sequence[Path]) -> Manifest` creates, for each `skills/<name>/` in `current`, a symlink `<root>/<name>` → that directory, in each of the roots that exist: `~/.claude/skills` and `~/.agents/skills` (the root shared by Codex, OpenCode and Gemini per the research notes). It refuses an existing entry it does not own (StateConflict naming it), records every link in the manifest, and `deactivate` removes only manifest links. Re-run after an update refreshes the links (they point at `current`, so usually nothing changes).
- CLI: `wev skills update [SOURCE] [--yes]` (no SOURCE = every non-frozen source; `--yes` only skips the "already declined" guard, the person's consent is given in chat or by typing the command), `wev skills rollback SOURCE`, `wev skills freeze SOURCE [--off]`, `wev skills activate`, `wev skills deactivate`, `wev skills show SOURCE` (prints state and, for rea, `mcp_argv`).
- Skill text (`wev-skill-maintenance/SKILL.md`): when the session context names available updates, ask the person once ("update X from A to B? changelog: URL"); on yes run `wev skills update X`; on no run `wev skills decline X`; never update without the person's yes; a frozen source is left alone; report the health result to the person; on failure say the previous version stays active.

- [ ] **Step 1: Failing tests:** update ok switches and keeps previous; update with failing health keeps active and reports; `test_update_twice_is_noop_and_state_stable`, `test_rollback_without_previous_is_conflict` (Review Focus 4); frozen refused (Review Focus 5); activation creates only owned links, refuses a foreign entry, deactivate removes only its links; hook asks for update/rollback/freeze/install and denies them on codex/gemini/opencode; `test_skills.py` still passes (the skill names only real commands and flags).
- [ ] **Step 2–5**; break the "switch only on health ok" rule on purpose. **Commit** `feat: update, roll back, freeze and activate third-party skills`

### Task 6: Docs

**Files:** `README.md` + pt-BR (one line each: third-party updates); `docs/guides/installation.md` + pt-BR (section "Third-party skills: install, daily check, update, rollback, freeze"); `SECURITY.md` + pt-BR (section: downloads are untrusted data; the GitHub tarball has no checksum; the health check catches a broken update, not a malicious one; an update runs only after the person's yes, through a command the hook asks about; `~/.claude/skills` and `~/.agents/skills` links are tracked by a manifest; the daily check does network at session start with a 10 s budget and fails silently); `docs/THIRD-PARTY.md` + pt-BR (rea and agent-skills as installed dependencies, MIT, with versions resolved at install time, not vendored); `CHANGELOG.md`; `docs/mvp-status.md` + pt-BR.

Labels, exactly: "implemented and tested with a local fake registry, a fake npx and local tarballs"; "the real registries, downloads and the real rea server are not run in this change (e2e part)". No "compatible with", "prevents", "guarantees".

- [ ] **Step 1: Edit.** **Step 2:** `PYTHONPATH=src python3 -m unittest tests.unit.test_skills tests.unit.test_docs tests.unit.test_repo_hygiene`, `bin/wev readme check`, `bin/wev claude-md check`, `make check`. **Step 3: Commit** `docs: document third-party skill updates`
