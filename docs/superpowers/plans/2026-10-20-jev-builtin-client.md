# Built-in JEV Client Implementation Plan

Portuguese version: [2026-10-20-jev-builtin-client.pt-BR.md](2026-10-20-jev-builtin-client.pt-BR.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** wev talks to the JEV service itself (no Node, no external `jev` program, no `exec_path` edits), reads the key from the environment, the user's `.env` or the macOS keychain, and tells the skills whether wev or the harness orchestrates.

**Architecture:** A new HTTP asker in `decisions/` returns the same answers JSON string that the external `jev ask` prints, so `JevProvider` and `jev_tools` keep their parsing unchanged. `decision.jev.command` gets a new default, `builtin`, that selects the HTTP asker. Any other value keeps the existing external-program path. A new CLI group, `wev jev status|ask|batch`, exposes the client, and `wev-orchestrate` reads `wev jev status` to choose between the wev flow and the harness's own.

**Tech Stack:** Python 3.14 standard library (`urllib.request`, `http.server` for the test fake, `concurrent.futures`), `unittest`.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.md), Part 2, decisions 4, 5 and 14, and the "Calls I made without the owner" section.

## Global Constraints

- Standard library only, Python >= 3.14. mypy strict, frozen dataclasses, functions < 50 lines, files < 400 lines.
- Every user-facing string goes through i18n, with identical keys in `en` and `pt-BR`. Docs change in EN and pt-BR in the same commit.
- Unit tests use no network beyond loopback (`127.0.0.1`) and no paid service. The real JEV call is out of scope here (Part 6, e2e).
- The key is never printed, logged, written to state, or put in an error message or URL.
- The state text is passed through the existing redactor (`core/wiring.py` `redact`) before it leaves the machine, as the program path does today.
- Endpoint default `https://api.typesafe.ai/v1/systemone`, model `jev-latest`, keychain service `typesafe-api-key`, env var `TYPESAFE_API_KEY`, override `JEV_API_URL`. These values are copied from `~/.claude/tools/jev/jev.mjs`.
- Retry only on HTTP 429 and 529. Backoff `0.5 * 2**(attempt-1)` seconds, at most 4 attempts, all inside one deadline of `decision.jev.timeout_seconds` (default 10.0).
- Commit subjects `<type>: <description>`, at most 72 characters, no AI attribution. No push without the owner's ok.
- The project name always keeps its final `s`: `wev-skills`.

## Review Focus

1. A `.env` written by hand: `export TYPESAFE_API_KEY=...`, quoted values, CRLF line endings, comments and blank lines must all parse to the bare key. Test in Task 1.
2. A `.env` readable by group or others (mode not `600`): the key is refused with a reason that names the file and the fix (`chmod 600`), never silently used. Test in Task 1.
3. An invalid or revoked key (HTTP 401): no retry, falls back to the local policy with a reason that says the key was rejected, and the key does not appear in the reason. Test in Task 2.
4. A 429 storm or a slow server must not block a classification past `timeout_seconds`. Test in Task 2.
5. `JEV_API_URL` set to a plain `http://` non-loopback host, or a URL with credentials: refused before any request. Test in Task 2.

---

### Task 1: Key resolution

**Files:**
- Create: `src/wev_skills/decisions/jev_key.py`
- Modify: `src/wev_skills/locales/decisions.en.json`, `src/wev_skills/locales/decisions.pt-BR.json`
- Test: `tests/unit/test_jev_key.py`

**Interfaces:**
- Produces:
  - `ENV_VAR = "TYPESAFE_API_KEY"`, `KEYCHAIN_SERVICE = "typesafe-api-key"`, `ENV_FILE_NAME = ".env"`
  - `@dataclass(frozen=True) class ApiKey: value: str; source: str` where `source` is `"env" | "env_file" | "keychain"`. `__repr__` must not include `value`.
  - `def env_file_path() -> Path`, which returns `user_config_home() / ".env"` (reuse `config.user_config_home`).
  - `def read_env_file(path: Path) -> dict[str, str]`, which raises `JevUnavailable("env_file_insecure", ...)` when `path.stat().st_mode & 0o077`.
  - `def resolve_api_key(env: Mapping[str, str], env_file: Path, keychain: Callable[[], str | None]) -> ApiKey | None`
  - `def macos_keychain() -> str | None`, which runs `/usr/bin/security find-generic-password -s typesafe-api-key -w`. It returns `None` off darwin, on a non-zero exit, or on `OSError`, and strips the trailing newline.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_jev_key.py`, using a temporary directory for the `.env` (`os.chmod(path, 0o600)`) and a lambda for the keychain:
  - `test_env_var_wins_over_file_and_keychain`: env `{"TYPESAFE_API_KEY": "k-env"}` plus a file `TYPESAFE_API_KEY=k-file` plus keychain `"k-chain"` gives `ApiKey("k-env", "env")`.
  - `test_file_used_when_env_missing`: gives `source == "env_file"`.
  - `test_keychain_used_last`: gives `source == "keychain"`.
  - `test_none_when_nothing_found`: returns `None`.
  - `test_env_file_formats`: the lines `# c`, a blank line, `export TYPESAFE_API_KEY="k1"\r` resolve to `"k1"`; `TYPESAFE_API_KEY='k2'` resolves to `"k2"`; `TYPESAFE_API_KEY = k3 ` resolves to `"k3"`.
  - `test_insecure_env_file_refused`: with mode `0o644`, `resolve_api_key` raises `JevUnavailable` whose `code == "env_file_insecure"` and whose message contains the path and `chmod 600`.
  - `test_missing_env_file_is_not_an_error`: a nonexistent path falls through to the keychain.
  - `test_repr_hides_key`: `"k-env" not in repr(ApiKey("k-env", "env"))`.
  - `test_keychain_off_darwin_is_none`: patch `sys.platform` to `"linux"`, and `macos_keychain()` returns `None` without running anything (patch `subprocess.run` to fail if called).

- [ ] **Step 2: Run them and see them fail**
  Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_jev_key -v`
  Expected: ERROR, `ModuleNotFoundError: wev_skills.decisions.jev_key`.

- [ ] **Step 3: Implement `jev_key.py`** with the interfaces above. Add the i18n key `decisions.jev.why.env_file_insecure` (params `path`) to both locales. pt-BR: "o arquivo {path} pode ser lido por outros usuários; rode chmod 600 {path}".

- [ ] **Step 4: Run them and see them pass**, the same command. Expected: OK. Then break the permission check on purpose (comment out the mode test), confirm `test_insecure_env_file_refused` fails, and restore it.

- [ ] **Step 5: Commit**
  ```bash
  git add src/wev_skills/decisions/jev_key.py src/wev_skills/locales/decisions.*.json tests/unit/test_jev_key.py
  git commit -m "feat: resolve the JEV key from env, .env or keychain"
  ```

### Task 2: HTTP asker

**Files:**
- Create: `src/wev_skills/decisions/jev_http.py`
- Create: `tests/fixtures/fake_jev_server.py`
- Modify: `src/wev_skills/locales/decisions.en.json`, `src/wev_skills/locales/decisions.pt-BR.json`
- Test: `tests/unit/test_jev_http.py`

**Interfaces:**
- Consumes: `ApiKey`, `resolve_api_key`, `env_file_path`, `macos_keychain` (Task 1); `JevUnavailable` from `decisions/jev_wire.py`.
- Produces:
  - `DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"`, `MODEL = "jev-latest"`, `RETRYABLE = (429, 529)`, `MAX_ATTEMPTS = 4`, `BASE_BACKOFF_SECONDS = 0.5`
  - `@dataclass(frozen=True) class Endpoint: url: str; local: bool`
  - `def resolve_endpoint(env: Mapping[str, str]) -> Endpoint`, which reads `JEV_API_URL`. It raises `JevUnavailable("endpoint_insecure")` for a non-https non-loopback URL and `JevUnavailable("endpoint_credentials")` for a URL with a user or password. Loopback is `127.0.0.1`, `localhost` or `::1`.
  - `def validate_questions(questions: Mapping[str, Any]) -> None`, which raises `ValidationError("invalid_questions", ...)` (exit 2). It enforces the rules of `jev.mjs` `validateQuestions`: a non-empty object; `type` in `noul|choice|score`; non-empty `instructions`; `choice` takes 2 to 255 `criteria` keys; `score` takes 2 to 10 `criteria` items.
  - `class HttpAsker:` with `__init__(self, endpoint: Endpoint, key: ApiKey | None, timeout_seconds: float, *, opener: Callable[[urllib.request.Request, float], tuple[int, bytes]] = _urlopen, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic)` and `__call__(self, questions: Mapping[str, Any], state: str) -> str`. The call returns `json.dumps(body["answers"])`, so the caller gets the same text the external program prints.
  - `def build_http_asker(timeout_seconds: float, env: Mapping[str, str] | None = None) -> HttpAsker`, which uses `os.environ`, `env_file_path()` and `macos_keychain`. It raises `JevUnavailable("key_missing")` when the endpoint is not loopback and there is no key.
- Request: `POST` with a JSON body `{"model", "state", "questions"}` and headers `Content-Type: application/json`, plus `Authorization: Bearer <key>` only when the endpoint is not loopback.
- Errors are `JevUnavailable` with these codes: `key_missing`, `key_rejected` (401, no retry), `http_status` (other non-2xx, message carries the number only), `retries_exhausted`, `timed_out` (the deadline passed or a socket timeout), `network` (`URLError` or `OSError`), `invalid_json`, `unparseable` (no `answers` object). The deadline is `clock() + timeout_seconds`. Each request's timeout is the remaining time. A backoff that would cross the deadline raises `timed_out` instead of sleeping.

- [ ] **Step 1: Write the fake server** `tests/fixtures/fake_jev_server.py`: a `ThreadingHTTPServer` on `127.0.0.1:0`, run in a daemon thread, used as a context manager that yields its URL. It takes a list of scripted responses `(status, body_bytes, delay_seconds)` served in order (the last one repeats) and records each request's headers and JSON body in a list.

- [ ] **Step 2: Write the failing tests** in `tests/unit/test_jev_http.py`, with `JEV_API_URL` pointing at the fake and the keychain set to `lambda: None`:
  - `test_returns_answers_as_json_text`: the fake returns `{"answers": {"risk": {"type": "choice", "choice": "low", "confidence": 0.9}}}`, and `json.loads(asker(q, "s"))["risk"]["choice"] == "low"`.
  - `test_body_has_model_state_questions`: the recorded body equals `{"model": "jev-latest", "state": "s", "questions": q}`.
  - `test_loopback_sends_no_authorization`: with a key present, the recorded headers have no `Authorization`.
  - `test_retries_429_then_succeeds`: the script is `[429, 429, 200]`, there are 3 recorded requests, and the recorded `sleep` calls equal `[0.5, 1.0]`.
  - `test_401_not_retried`: one request, `code == "key_rejected"`, and the key string is not in `str(exc)`.
  - `test_deadline_bounds_retry_storm`: the script is always 429, `timeout_seconds=1.0`, and `clock` and `sleep` are fakes that advance a counter. It raises `timed_out` and the total simulated time is <= 1.0.
  - `test_insecure_endpoint_refused`: `http://example.com/x` gives `endpoint_insecure`, `https://u:p@example.com/` gives `endpoint_credentials`, and neither makes a request.
  - `test_missing_key_for_remote_endpoint`: the default endpoint with no key makes `build_http_asker` raise `key_missing`.
  - `test_body_without_answers_is_unparseable` and `test_non_json_body_is_invalid_json`.
  - `test_validate_questions_rules`: a `choice` with 1 option, a `score` with 11 levels, an empty `instructions` and an unknown `type` each raise `ValidationError`.

- [ ] **Step 3: Run them and see them fail**
  Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_jev_http -v`
  Expected: ERROR, module not found.

- [ ] **Step 4: Implement `jev_http.py`** with the interfaces above. Add i18n keys under `decisions.jev.why.` for each new code (`key_missing`, `key_rejected`, `http_status` with `{status}`, `retries_exhausted`, `network`, `endpoint_insecure`, `endpoint_credentials`) and `decisions.jev.error.invalid_questions` with `{why}`. The `key_missing` text names the three places a key is read from: `TYPESAFE_API_KEY`, `~/.config/wev-skills/.env`, and the macOS keychain service `typesafe-api-key`.

- [ ] **Step 5: Run them and see them pass.** Expected: OK. Break the deadline check on purpose and confirm `test_deadline_bounds_retry_storm` fails.

- [ ] **Step 6: Commit**
  ```bash
  git add src/wev_skills/decisions/jev_http.py tests/fixtures/fake_jev_server.py tests/unit/test_jev_http.py src/wev_skills/locales/decisions.*.json
  git commit -m "feat: ask JEV over HTTPS without an external program"
  ```

### Task 3: Make the built-in client the default provider path

**Files:**
- Modify: `src/wev_skills/config.py:48-50` (`JevConfig.command` default), `src/wev_skills/config.py:338-360` (`trust_errors`)
- Modify: `src/wev_skills/decisions/jev.py:164-213` (`JevProvider.__init__` and `ask`)
- Modify: `src/wev_skills/decisions/factory.py`, `src/wev_skills/decisions/jev_program.py` (`jev_warnings`)
- Test: `tests/unit/test_decisions_factory.py`, `tests/unit/test_decisions_jev.py`, `tests/unit/test_jev_program.py`

**Interfaces:**
- Consumes: `build_http_asker(timeout_seconds) -> HttpAsker` (Task 2), `resolve_api_key` (Task 1).
- Produces:
  - `BUILTIN = "builtin"` in `config.py`, which becomes the default of `JevConfig.command`.
  - `JevProvider.__init__` gains the keyword `asker: Callable[[Mapping[str, Any], str], str] | None = None`. When it is set, `ask()` returns `asker(questions, redactor(state))` and does not touch `runner`. When it is `None`, the current program path is unchanged.
  - The factory: when `jev.command == BUILTIN`, it passes `asker=LazyAsker(timeout)`, which calls `build_http_asker` on first use, so a missing key becomes a per-call `JevUnavailable` and a local fallback, not a startup failure.
  - `jev_warnings(config, root)`: with `BUILTIN`, it warns `decisions.jev.warning_key` when `resolve_api_key` returns `None` or raises. It keeps the current program check for any other command.
  - `trust_errors` skips the program-name rules when `command == BUILTIN`.

- [ ] **Step 1: Write the failing tests**
  - `test_decisions_factory.py::test_builtin_is_default_and_uses_http`: the default `Config()` with `provider="jev"` and `JEV_API_URL` pointing at the fake server (Task 2 fixture) makes `classify_task` record no `jev.unavailable` reason, and the fake saw 1 request.
  - `test_decisions_factory.py::test_builtin_without_key_falls_back_locally`: the default endpoint, no key and the keychain patched to `None` give a classification whose reasons include the `key_missing` text, and the provider id result is the local value.
  - `test_decisions_jev.py::test_asker_receives_redacted_state`: an asker that records its args, with a state containing `ghp_` followed by 36 characters, must not receive the token.
  - `test_jev_program.py::test_builtin_warns_when_no_key` and `test_builtin_no_warning_with_key`.
  - Keep all existing tests that set `command` to the fake program path. They must still pass unchanged.

- [ ] **Step 2: Run them and see them fail**
  Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_decisions_factory tests.unit.test_decisions_jev tests.unit.test_jev_program -v`
  Expected: the new tests FAIL; the old ones pass.

- [ ] **Step 3: Implement** the interface changes above. Add `decisions.jev.warning_key` to both locales: "decision.provider is jev but no JEV key was found ({why}); the local policy is used".

- [ ] **Step 4: Run them and see them pass**, plus `make test`. Expected: all green. The eval baseline test must still reproduce byte for byte. If it does not, the default change leaked into the evals: fix the code, never the baseline.

- [ ] **Step 5: Commit**
  ```bash
  git add src/wev_skills/config.py src/wev_skills/decisions/ src/wev_skills/locales/ tests/unit/
  git commit -m "feat: use the built-in JEV client by default"
  ```

### Task 4: `wev jev` command group

**Files:**
- Create: `src/wev_skills/commands/jev.py`
- Create: `src/wev_skills/locales/jev.en.json`, `src/wev_skills/locales/jev.pt-BR.json`
- Test: `tests/unit/test_cli_jev.py`

**Interfaces:**
- Consumes: Tasks 1 to 3; `commands/_scope.resolve_scope` for the effective config, as `commands/decide.py` does.
- Produces (CLI, JSON on stdout):
  - `wev jev status` returns `{"provider": "local"|"jev", "client": "builtin"|"program", "key_source": "env"|"env_file"|"keychain"|null, "key_error": str|null, "endpoint": str, "orchestration": "wev"|"harness"}`. `orchestration` is `"wev"` only when `provider == "jev"` and (for `builtin`) a key resolves or the endpoint is loopback. It is `"harness"` otherwise. The command never makes a network call and never prints the key. Exit 0 always.
  - `wev jev ask --questions FILE (--state TEXT | --state-file FILE)` returns `{"answers": {...}}`. It validates the questions (exit 2 on invalid) and redacts the state. A `JevUnavailable` exits 8.
  - `wev jev batch --questions FILE --items FILE.jsonl --out FILE.jsonl` takes items as `{"id", "state"}` per line (exit 2 on a bad line, naming the line number). It runs with a concurrency of 4 (`ThreadPoolExecutor(max_workers=4)`) and writes one JSON line per item, `{"id", "answers"}` or `{"id", "error"}`, in input order. Stdout is `{"ok": n, "failed": m, "out": path}`. Exit 8 when `m > 0`, else 0.

- [ ] **Step 1: Write the failing tests** in `tests/unit/test_cli_jev.py`, which run `bin/wev` in a subprocess with `XDG_CONFIG_HOME` set to a temporary directory, `JEV_API_URL` set to the fake server and `HOME` set to a temporary directory:
  - `test_status_local_by_default`: no config gives `provider == "local"` and `orchestration == "harness"`.
  - `test_status_jev_with_env_file_key`: a `wev.config.json` with `{"decision": {"provider": "jev"}}` in the cwd repo, the default endpoint and a `.env` (mode 600) with the key give `key_source == "env_file"`, `orchestration == "wev"`, and the key string absent from stdout and stderr.
  - `test_status_jev_without_key_is_harness`: `orchestration == "harness"` and `key_error` is non-null.
  - `test_ask_prints_answers`, `test_ask_invalid_questions_exit_2`.
  - `test_batch_keeps_order_and_counts_failures`: 3 items with the fake scripted `[200, 500, 200]` (served without retry for 500) give an output file with ids in input order, `failed == 1`, and exit 8.

- [ ] **Step 2: Run them and see them fail**
  Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_cli_jev -v`. Expected: FAIL (no `jev` group).

- [ ] **Step 3: Implement `commands/jev.py`** with `register(subparsers)`, following `commands/decide.py` for structure and the help strings in `jev.<lang>.json`. Check that `adapters/claude_code/engine_cli.py` needs no new class: `jev` is neither an operator nor a run command. The existing hook tests must stay green.

- [ ] **Step 4: Run them and see them pass**, plus `make test`. Expected: green.

- [ ] **Step 5: Commit**
  ```bash
  git add src/wev_skills/commands/jev.py src/wev_skills/locales/jev.*.json tests/unit/test_cli_jev.py
  git commit -m "feat: add wev jev status, ask and batch"
  ```

### Task 5: Orchestration switch in the skill, and docs

**Files:**
- Modify: `skills/wev-orchestrate/SKILL.md` (the section before the run flow, near line 20 to 34)
- Modify: `docs/guides/configuration-and-providers.md` and `.pt-BR.md` (the `decision` table and the `jev` section, near line 37 to 41 and 141 to 175)
- Modify: `CHANGELOG.md` (`[Unreleased]`), `docs/mvp-status.md` and `.pt-BR.md` (JEV row)
- Test: `tests/unit/test_skills.py` (existing; it checks every command and flag a skill names)

**Interfaces:**
- Consumes: `wev jev status` (Task 4).

- [ ] **Step 1: Edit the skill.** First step of every session: run `"${CLAUDE_PLUGIN_ROOT}/bin/wev" jev status`.
  - If `orchestration` is `"wev"`, follow the run flow as written.
  - If it is `"harness"`, do not run `run start` or the task commands. Plan and track work with the harness's own tools.
  - The guard hooks, approvals and loop detection stay active in both modes (spec decision 14). Name `key_error` to the user when it is set, and tell them that rerunning setup turns JEV on.

- [ ] **Step 2: Edit the guides**, EN and pt-BR, with the same changes.
  - `jev.command` default `builtin`.
  - Key lookup order: `TYPESAFE_API_KEY`, `~/.config/wev-skills/.env` (mode 600, refused otherwise), macOS keychain `typesafe-api-key`.
  - `JEV_API_URL` rules.
  - Retry and deadline.
  - The external-program path is still available by setting `command`.
  - `wev jev status|ask|batch`.
  - Status labels: built-in client "implemented and tested against a local fake server". Live service "not run in this change".
  - What leaves the machine: the redacted state and the questions, as before.

- [ ] **Step 3: Run the documentation checks**
  Run: `PYTHONPATH=src python3 -m unittest tests.unit.test_skills tests.unit.test_docs -v && bin/wev readme check && bin/wev claude-md check`
  Expected: OK, and each `check` exits 0.

- [ ] **Step 4: Full check**
  Run: `make check`. Expected: tests OK, ruff and mypy clean.

- [ ] **Step 5: Commit**
  ```bash
  git add skills/wev-orchestrate/SKILL.md docs/guides/configuration-and-providers*.md docs/mvp-status*.md CHANGELOG.md
  git commit -m "docs: switch orchestration on JEV status and document the client"
  ```
