# Harness Adapters Implementation Plan

Portuguese version: [2026-10-21-harness-adapters.pt-BR.md](2026-10-21-harness-adapters.pt-BR.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install the wev skills, subagents and guard hooks into Codex, Gemini CLI and OpenCode, as Claude Code already gets them, through `wev harness export|install|uninstall --target codex|gemini|opencode`.

**Architecture:** The guard logic stays where it is. A thin codec per harness converts that harness's hook input to the payload `adapters/claude_code/hooks.py` already reads, then converts the Claude Code answer back to the harness's output format. A per-target package builder renders the repository's skills (replacing `"${CLAUDE_PLUGIN_ROOT}/bin/wev"` with the absolute path of this clone's `bin/wev`) and agents into a directory. `install` builds that package under the user data directory and registers it with the harness, through the harness's own CLI where one exists, and records every path it writes in a manifest so that `uninstall` removes only those.

**Tech Stack:** Python 3.14 standard library, `unittest`; fake harness CLIs in `tests/fixtures/` for install tests. Node is used only by one OpenCode plugin test, which is skipped when `node` is absent.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.md), Part 3, the "Calls I made without the owner" section (calls 4, 8, 9), and decision 14. Interface facts come from the working notes [docs/research/harness-codex.md](../../research/harness-codex.md), [harness-gemini.md](../../research/harness-gemini.md) and [harness-opencode.md](../../research/harness-opencode.md). Every format detail an implementer uses must come from those notes, with the source they cite. A detail the notes mark "unknown" is not guessed: the task reports NEEDS_CONTEXT.

## Global Constraints

- Standard library only, Python >= 3.14, mypy strict, frozen dataclasses, functions < 50 lines, files < 400 lines.
- Every user-facing string goes through i18n with identical keys in `en` and `pt-BR`. Docs change in EN and pt-BR in the same commit.
- Unit tests make no network calls and never run a real harness. Real harness runs belong to the e2e part (spec "End-to-end tests").
- Owner ruling (2026-10-21), for harnesses whose hooks cannot ask (Codex, Gemini; and OpenCode unless its notes show a verified ask): a guard `ask` becomes **allow plus a warning** to the agent, and a guard `deny` stays deny. SECURITY.md (EN and pt-BR) must state that for these harnesses the guard's asks are reminders only.
- Capability labels: "implemented and tested with fake harness CLIs" until the e2e part runs the real ones. Never write "compatible with X" in docs before that.
- Hook commands written into a harness config call this clone's `bin/wev` by absolute path, never a bare `wev`.
- The manifest of written paths lives at `$XDG_DATA_HOME/wev-skills/harness/<target>/manifest.json`, else `~/.local/share/...`. `uninstall` removes only manifest entries and never edits a file it did not create, except to remove the exact entries it added.
- Commit subjects `<type>: <description>`, at most 72 characters, no AI attribution. No push without the owner's ok.

## Review Focus

1. A harness hook payload with an unexpected shape (missing `tool_input`, a non-shell tool, non-JSON stdin) must give the harness's "no opinion" answer or the internal-error path, never a crash and never a stack trace. Tested in Task 1.
2. A guard `deny` must reach each harness as that harness's deny, exactly as documented (Codex exit/JSON, Gemini `{"decision":"deny"}`, OpenCode thrown error). Tested in Tasks 1 and 5.
3. A clone path with spaces or quotes must still produce a working hook command line in every generated config (quoting). Tested in Task 2.
4. `install` run twice must not duplicate entries; `uninstall` after a user edited the harness config must leave the user's own entries. Tested in Tasks 3 to 5.
5. A failing harness CLI during install (non-zero exit) must stop with a clear error and roll back the files written so far. Tested in Task 3.

---

### Task 1: Hook codecs for Codex, Gemini and OpenCode

**Files:**
- Create: `src/wev_skills/adapters/harness_hooks.py`
- Modify: `src/wev_skills/commands/hook.py` (add `--harness {claude,codex,gemini,opencode}`, default `claude`)
- Modify: `src/wev_skills/locales/hooks.en.json`, `hooks.pt-BR.json`
- Test: `tests/unit/test_harness_hooks.py`, fixtures `tests/fixtures/harness_payloads/{codex,gemini,opencode}_*.json`

**Interfaces:**
- Produces:
  - `HARNESSES = ("claude", "codex", "gemini", "opencode")`
  - `def to_claude_payload(harness: str, payload: Mapping[str, Any]) -> dict[str, Any] | None`, which returns the Claude-shaped `{"tool_name": "Bash", "tool_input": {"command": ...}, "cwd": ...}` for that harness's shell tool. Shell tool names: Codex from its note (its note marks the name "unknown"; report NEEDS_CONTEXT if it is still unknown after reading source), Gemini `run_shell_command`, OpenCode `bash`. For any other tool it returns `None`, which means no opinion.
  - `def from_claude_answer(harness: str, answer: str) -> HookOutput`, where `@dataclass(frozen=True) class HookOutput: stdout: str; stderr: str; exit_code: int`. Mapping:
    - Claude `deny` → that harness's deny format, exactly as its note documents;
    - Claude `ask` → allow plus a warning (owner ruling): the warning goes in the harness's documented context or system-message field if its note shows one, else in stderr with exit 0;
    - `""` → empty stdout, exit 0.
- `wev hook pre-tool-use --harness X` reads stdin, applies `to_claude_payload`, calls the existing `hooks.pre_tool_use`, and prints `from_claude_answer`. Errors follow the existing `run_hook` contract, with the ask fallback mapped through the same rule.
- `wev hook session-context --harness X` prints the same brief text in the harness's SessionStart context format from its note. For OpenCode the plugin consumes the plain text (Task 5).

- [ ] **Step 1: Write fixtures** from the payload examples in each research note (one shell call, one non-shell call per harness), with the note section cited in a comment line of the test.
- [ ] **Step 2: Write the failing tests:**
  - `test_shell_payload_maps_to_claude_shape` (one per harness);
  - `test_non_shell_tool_is_no_opinion`;
  - `test_deny_maps_to_harness_deny` (each harness, exact output);
  - `test_ask_becomes_allow_with_warning` (each harness: exit 0, no deny, warning text present in the documented channel);
  - `test_malformed_stdin_never_crashes`;
  - `test_claude_default_unchanged`: no flag gives byte-identical output to today.
- [ ] **Step 3: Run** `PYTHONPATH=src python3 -m unittest tests.unit.test_harness_hooks -v`. Expected: FAIL, module missing.
- [ ] **Step 4: Implement** the module and the flag. Add i18n key `hooks.reason.ask_as_warning` (en and pt-BR: "wev would ask before this command; this harness cannot ask, so it was allowed: {reason}").
- [ ] **Step 5: Run** the module tests and the existing hook tests (`tests.unit.test_hooks`, `test_hook_bypasses`). Expected: OK. Break the deny mapping for one harness on purpose and confirm a test fails.
- [ ] **Step 6: Commit** `feat: translate guard hooks for codex, gemini and opencode`

### Task 2: Package builder and `wev harness export`

**Files:**
- Create: `src/wev_skills/adapters/harness_package.py`, `src/wev_skills/commands/harness.py`, `src/wev_skills/locales/harness.en.json`, `harness.pt-BR.json`
- Test: `tests/unit/test_harness_package.py`

**Interfaces:**
- Consumes: the repository's `skills/*/` (each `SKILL.md` and its `references/`), `agent-specs/` through the existing exporter (`adapters/claude_code/subagent.py`) for agent text, and `bin/wev`.
- Produces:
  - `def render_skill_text(text: str, wev_path: Path) -> str`, which replaces every `"${CLAUDE_PLUGIN_ROOT}/bin/wev"` (and the unquoted form) with a shell-quoted absolute `wev_path` (`shlex.quote`).
  - `def build_package(target: str, out: Path, wev_path: Path) -> list[Path]`. It writes the target layout and returns every file written. Layouts follow the notes:
    - **codex:** `.codex-plugin/plugin.json` (fields from the note: name, version from `pyproject.toml`, `skills`, `hooks`), `skills/<name>/SKILL.md`, `hooks.json` with SessionStart and PreToolUse → `<wev> hook … --harness codex`.
    - **gemini:** `gemini-extension.json` (name, version, description, `contextFileName` only if a context file is shipped), `skills/<name>/SKILL.md`, `agents/<id>.md` (frontmatter name, description, tools, model as the note shows), `hooks/hooks.json` with SessionStart and BeforeTool (matcher `run_shell_command`).
    - **opencode:** `skills/<name>/SKILL.md`, `agents/<id>.md` (frontmatter `description`, `mode: subagent`), `plugins/wev-guard.js` (Task 5 writes its content; Task 2 writes a file from a template string defined in Task 5's module, so Task 2 only reserves the path).
  - Codex subagent roles: only when the note's `[agents.<role>]` format is fully known. Otherwise skip them and record "subagents not exported for codex: format unknown" in the export result.
- CLI: `wev harness export --target T --out DIR [--wev PATH]` prints `{"target", "out", "files": [...], "skipped": [...]}`. `--wev` defaults to this clone's `bin/wev` resolved.
- [ ] **Step 1: Failing tests:**
  - `test_render_replaces_every_placeholder` (all 7 skills; no `CLAUDE_PLUGIN_ROOT` left);
  - `test_render_quotes_a_path_with_spaces` (Review Focus 3);
  - `test_codex_layout`, `test_gemini_layout`, `test_opencode_layout`: exact file sets, and every JSON parses;
  - `test_hook_commands_use_absolute_wev`;
  - `test_export_is_deterministic`: two runs give byte-identical trees.
- [ ] **Step 2: Run them and see them fail.** **Step 3: Implement.** **Step 4: Run them and see them pass,** then break the placeholder replacement and confirm a test fails.
- [ ] **Step 5: Commit** `feat: build harness packages from the skills and agents`

### Task 3: Install and uninstall for Codex, with a manifest

**Files:**
- Create: `src/wev_skills/adapters/harness_install.py`
- Modify: `src/wev_skills/commands/harness.py`
- Test: `tests/unit/test_harness_install.py`, fake CLI `tests/fixtures/fake_codex.py`

**Interfaces:**
- Consumes: `build_package` (Task 2).
- Produces:
  - `@dataclass(frozen=True) class Manifest: target: str; files: tuple[str, ...]; registrations: tuple[tuple[str, ...], ...]`, where `registrations` are the harness-CLI argv used to register and their inverses, stored so uninstall can undo them;
  - `def install(target: str, runner: Runner, data_home: Path, wev_path: Path) -> Manifest`;
  - `def uninstall(target: str, runner: Runner, data_home: Path) -> Manifest`.
- Codex install:
  - build into `data_home/wev-skills/harness/codex/package`;
  - register with the commands from the Codex note (`codex plugin marketplace add <dir>`, then `codex plugin add <name>@<marketplace>`), run through the injected `Runner`, never through a shell;
  - write the manifest.
- Codex hook trust: hooks only run after the person trusts them (note §3). Install does NOT bypass trust. It prints, in the result `next_steps`, the exact action the person takes (from the note) and stops there.
- Idempotent: reinstall replaces the package and does not add a second registration (Review Focus 4).
- A non-zero harness CLI exit raises a WevError (exit 8). Already-written files are removed and earlier registrations undone (Review Focus 5).
- CLI: `wev harness install --target codex`, `wev harness uninstall --target codex`. These are added to the hook's RUN_COMMANDS (ask) in `engine_cli.py`, since they change the user's harness configuration, with hook tests.
- [ ] Steps:
  - failing tests with the fake CLI: it records argv, and can fail on demand;
  - cover install, re-install, uninstall, rollback on failure, the manifest contents and the hook asking for install/uninstall;
  - implement, verify, deliberate break;
  - commit `feat: install the wev package into codex`.

### Task 4: Install and uninstall for Gemini

**Files:** Modify `harness_install.py` and `commands/harness.py`. Test `tests/unit/test_harness_install.py` (Gemini cases), fake CLI `tests/fixtures/fake_gemini.py`.

**Interfaces:** Same functions as Task 3. Gemini registration is `gemini extensions link <package>` and the inverse is `gemini extensions uninstall <name>`, both from the note. Before linking, run `gemini extensions validate <package>`; a failed validation stops before any registration.

- [ ] Steps:
  - failing tests: validate-then-link order, a validation failure gives no registration, idempotent re-install, uninstall;
  - implement, verify, deliberate break;
  - commit `feat: install the wev package into gemini cli`.

### Task 5: OpenCode plugin and install

**Files:**
- Create: `src/wev_skills/adapters/opencode_plugin.py` (the JS template string and its renderer)
- Modify: `harness_install.py` and `commands/harness.py`
- Test: `tests/unit/test_opencode_plugin.py`, `tests/unit/test_harness_install.py` (OpenCode cases)

**Interfaces:**
- `def render_plugin(wev_path: Path) -> str` returns an ES module.
  - It exports a plugin function, in the shape from the OpenCode note §4. Its `tool.execute.before` handler, when `input.tool === "bash"`, spawns `[wev_path, "hook", "pre-tool-use", "--harness", "opencode"]` with no shell, writes `{"tool": input.tool, "args": output.args, "cwd": directory}` as JSON to stdin and reads stdout JSON.
  - On deny it throws `new Error(reason)`. On allow-with-warning it returns, and logs the warning through the documented client log if the note shows one, else `console.warn`.
  - Any failure to spawn or parse throws (fail closed), matching the guard's fail-safe rule.
  - The codec for `opencode` (Task 1) reads this exact JSON shape.
- OpenCode has no harness CLI to register plugins or skills. Install writes into `~/.config/opencode/` (or `$XDG_CONFIG_HOME/opencode/`):
  - `plugins/wev-guard.js`;
  - `skills/<name>/` (directories prefixed `wev-` to avoid clashes);
  - `agents/wev-<id>.md`.
  Every path goes in the manifest. Install refuses to overwrite a file it did not create (WevError exit 5, naming the file).
- [ ] Steps:
  - failing tests:
    - `test_plugin_spawns_absolute_wev_without_shell` (string checks on the rendered module);
    - `test_plugin_denies_on_guard_deny`: runs under `node` with a fake `wev` script that prints a deny JSON, and asserts the thrown error. Skipped when `node` is not on PATH;
    - `test_plugin_fails_closed_when_wev_missing` (node, skipped likewise);
    - the install, re-install, uninstall and refuse-to-overwrite tests;
  - implement, verify, deliberate break;
  - commit `feat: install the wev guard plugin and skills into opencode`.

### Task 6: Docs and security statements

**Files:**
- Modify: `SECURITY.md` and `.pt-BR.md` (new "Other harnesses" section)
- Modify: `docs/guides/installation.md` and `.pt-BR.md` (a "Codex, Gemini CLI and OpenCode" section)
- Modify: `README.md` and `README.pt-BR.md` (one line each, if the README lists harnesses)
- Modify: `CHANGELOG.md` [Unreleased]
- Modify: `docs/mvp-status.md` and `.pt-BR.md`

- [ ] **Step 1: Write the docs.**
  - The commands `wev harness export|install|uninstall`.
  - What each harness gets: skills, agents (Codex only if exported), hooks.
  - The owner ruling: asks become allow plus a warning in Codex, Gemini and OpenCode, so the guard's asks are reminders there, and denies stay denies.
  - Codex needs a one-time hook trust by the person.
  - OpenCode's guard runs in a plugin that calls `wev`, and fails closed if `wev` cannot run.
  - Labels: "implemented and tested with fake harness CLIs"; "not run against the real harnesses yet (e2e part)".
  - No "compatible with" claim.
- [ ] **Step 2: Run** `make check`, `bin/wev readme check` and `bin/wev claude-md check`. Expected: all pass.
- [ ] **Step 3: Commit** `docs: document harness adapters and their guard limits`
