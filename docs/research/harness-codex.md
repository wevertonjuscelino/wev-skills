Working note, not user documentation.

# Codex CLI extension surface (for a wev-skills adapter)

Portuguese version: [harness-codex.pt-BR.md](harness-codex.pt-BR.md).

Scope: what the OpenAI Codex CLI 0.160.0 exposes for skills/plugins, instructions, hooks, MCP, subagents and non-interactive runs.

## Sources and method

- Local binary: `codex --version` prints `codex-cli 0.160.0`. Help read with `codex --help`, `codex exec --help`, `codex mcp --help`, `codex mcp add --help`, `codex plugin --help`, `codex plugin marketplace --help`, `codex features list`, `codex debug --help`.
- Source: the openai/codex tag `rust-v0.160.0` (exists; `rust-v0.160.1` also exists, not used). Files read via `gh api repos/openai/codex/contents/...?ref=rust-v0.160.0`:
  - `codex-rs/core/src/agents_md.rs`
  - `codex-rs/ext/skills/src/host_roots.rs`
  - `codex-rs/config/src/config_toml.rs`, `mcp_types.rs`, `hook_config.rs`
  - `codex-rs/hooks/src/engine/discovery.rs`, `command_runner.rs`, `output_parser.rs`, `events/pre_tool_use.rs`, `events/session_start.rs`, `types.rs`
  - `codex-rs/core-plugins/src/manifest.rs`, `codex-rs/utils/plugins/src/plugin_namespace.rs`
  - `codex-rs/agent-roles/src/discovery.rs`, `agent_role_config.rs`
- The repo `docs/*.md` files at that tag are stubs that only link to developers.openai.com. The docs site itself was NOT fetched (gap).
- Local smoke test (no model call): `codex debug prompt-input` in a temp project with an `AGENTS.md` containing a marker and a `.agents/skills/probe-skill/SKILL.md`. Output contained the AGENTS.md marker and the skill listed with its file path.
- addyosmani/agent-skills at commit `aeac41d4d005999432bb7312f7ff06383a91d59d` (2026-10-13): `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `docs/codex-setup.md`.
- User config `~/.codex/config.toml` and `~/.codex/hooks.json` were read for shape only. Values and secrets were not copied. Nothing was modified.

Labels: VERIFIED (read in source or observed locally), DOC-ONLY (stated in a repo file, not run), UNKNOWN.

## 1. Skills and plugins

- Skill format: directory with `SKILL.md`, frontmatter `name` and `description`, then instructions. Same format as Claude Code (addyosmani `docs/codex-setup.md`, DOC-ONLY). Codex loads name and description first and reads the body on demand (same doc).
- Skill roots (VERIFIED, `ext/skills/src/host_roots.rs`):
  - User: `$CODEX_HOME/skills` (deprecated, still read), `$HOME/.agents/skills`.
  - Repo: `.agents/skills` in the cwd and its ancestors (`repo_agents_skill_roots`), and `<project>/.codex/skills` for a project config layer.
  - System and Admin: `$CODEX_HOME/skills` under the system and admin layers.
  - Plugin skill roots, and extra roots.
  - Observed: `probe-skill` in `.agents/skills` appeared in `codex debug prompt-input` (VERIFIED).
- Plugin manifest (VERIFIED, `plugin_namespace.rs`, `core-plugins/src/manifest.rs`): `.codex-plugin/plugin.json` at the plugin root. Alternates accepted: `.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json`. Fields read by the parser: `name`, `version`, `description`, `keywords`, `skills` (path string or list, must start with `./`), `mcpServers`, `apps`, `hooks` (path, list, inline object, or list), `interface` (displayName, shortDescription, longDescription, developerName, category, capabilities, defaultPrompt, brandColor, logo, ...), `commands`, `extensions`.
  - Example (addyosmani, v0.6.13): `"skills": "./skills/"`, plus `interface`.
- Plugin install and marketplace (VERIFIED help output; addyosmani DOC-ONLY):
  - `codex plugin marketplace add <owner/repo | local path>` (add, list, upgrade, remove).
  - `codex plugin add <PLUGIN@MARKETPLACE>` (or `PLUGIN --marketplace M`), `codex plugin list`, `codex plugin remove`.
  - Marketplace file: `.agents/plugins/marketplace.json` with `name`, `plugins[]` (`name`, `source: {source: "local", path: "./"}`, `policy`, `category`).
  - Local config after install (VERIFIED in `~/.codex/config.toml` shape): `[marketplaces.<name>] source_type = "git" | "local"`, `source = ...`, and `[plugins."<plugin>@<marketplace>"] enabled = true`.
- Cache location observed locally (VERIFIED by `codex mcp list` output): `~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/`.
- Enable or disable: `[plugins."name@mkt"] enabled = true|false` in config.toml (VERIFIED shape). Install adds the marketplace and plugin entries.
- Verify it loaded: `codex debug prompt-input` lists the model-visible skills (VERIFIED with a project skill). `codex plugin list` lists plugins (VERIFIED help; output not inspected). Runtime skill use not verified.
- Project scope: `.agents/skills/` in the repo (VERIFIED). Project-scoped plugin install: UNKNOWN.

## 2. Instructions file (AGENTS.md)

- Names (VERIFIED, `agents_md.rs`): `AGENTS.md` (default), `AGENTS.override.md` (local override, checked first in each directory), plus `project_doc_fallback_filenames` from config.
- Project lookup (VERIFIED): find the project root by walking up from cwd until a `project_root_markers` entry is found (default `.git`). If none is found, only cwd is used. An empty marker list disables parent traversal. Then concatenate every AGENTS.md from the root down to cwd, in that order. Never walks above the root.
- Concatenation separator: `\n\n--- project-doc ---\n\n` (VERIFIED).
- Size limit (VERIFIED, `config_toml.rs`): `project_doc_max_bytes`, default `DEFAULT_PROJECT_DOC_MAX_BYTES = 32 * 1024` (32 KiB), a budget shared across the files. Truncation behavior past the limit: UNKNOWN beyond this.
- Untrusted projects: project AGENTS.md is skipped (VERIFIED, `load_project_instructions`: `config.active_project.is_untrusted()`).
- Global lookup: a user-level instruction layer exists (`user_instructions`, host-provided). A local `~/.codex/AGENTS.md` exists on this machine. Whether the global file is `$CODEX_HOME/AGENTS.md` or `AGENTS.override.md` was not read in source: UNKNOWN (only the 32 KiB limit and project logic were read).

## 3. Hooks

- Feature flag: `hooks` is `stable`, default `true` (VERIFIED, `codex features list`).
- Events (VERIFIED, `config/src/hook_config.rs`): `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`. So yes, there is a session-start hook and a before-tool hook. "Before shell command" is `PreToolUse` with a matcher on the shell tool name. The exact shell tool name (`Bash`, `shell`, ...) was not verified.
- Config file locations (VERIFIED, `engine/discovery.rs`): `hooks.json` in the config folder (`load_hooks_json`: `config_folder.join("hooks.json")`, so `~/.codex/hooks.json` and a project `.codex/hooks.json`). Hooks can also be declared inline in `config.toml`. The discovery code says "hooks from config TOML and hooks.json converge on the same trust identity."
- Format (VERIFIED, `hook_config.rs`): `{"hooks": {"<Event>": [{"matcher": "<regex>", "hooks": [{"type": "command", "command": "...", "commandWindows": "...", "timeout": 10, "async": false, "statusMessage": "...", "additionalContextLimit": 2500}]}]}}`. Other handler types exist in the schema: `mcp_tool`, `prompt`, `agent`. Their runtime support: UNKNOWN.
- Timeouts (VERIFIED, `normalize_command_hook`): default 600 s for every event except `SessionEnd` and `Interrupt`, which default to 1 s and are clamped to 1..3 s. Timeout on a command hook kills it and reports `hook timed out after Ns` (VERIFIED, `command_runner.rs`).
- Trust gate (VERIFIED, `discovery.rs`): an unreviewed hook is `Untrusted` and is not run. It runs when its hash matches `[hooks.state."<key>"] trusted_hash` (`Trusted`). A changed command gives `Modified`, which also does not run. `codex exec --dangerously-bypass-hook-trust` skips the check. Managed hooks are exempt. Admins can set `allow_managed_hooks_only = true` in `requirements.toml` (DOC-ONLY, `config.md` stub).
  - Consequence for an adapter: hooks written by the adapter will need one trust review, or a trusted hash written to config. How the hash is computed and written: UNKNOWN beyond the code path.
- Stdin JSON, PreToolUse (VERIFIED, `events/pre_tool_use.rs`): `session_id`, `turn_id`, `agent_id`, `agent_type`, `transcript_path` (nullable), `cwd`, `hook_event_name` ("PreToolUse"), `model`, `permission_mode`, `tool_name` (canonical name), `tool_input` (shell tools: `{"command": ...}`; MCP tools: their arguments), `tool_use_id`.
- Stdin JSON, SessionStart (VERIFIED partially, `events/session_start.rs`): request carries `session_id`, `cwd`, `transcript_path`, `model`, `permission_mode`, `source` (a `SessionStartSource` enum; its values were not read).
- Output and decisions, PreToolUse (VERIFIED, `output_parser.rs`, `pre_tool_use.rs` tests):
  - Exit code 2 blocks; the stderr text is the reason. Any other non-zero exit fails the hook with an error.
  - Stdout JSON deny: `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`.
  - `permissionDecision: "allow"` with `updatedInput` rewrites the tool input. `allow` without `updatedInput` fails open.
  - `permissionDecision: "ask"` is NOT supported: it fails open with a warning. So a hook cannot ask the user.
  - Deprecated `{"decision":"block","reason":"..."}` still blocks. `{"decision":"approve"}` is unsupported and fails open.
- SessionStart output (VERIFIED, tests in `session_start.rs`): `hookSpecificOutput.hookEventName = "SessionStart"` with `additionalContext`, which is injected into context. `continue: false` with `stopReason` is parsed, but the test `continue_false_preserves_context_for_later_turns` shows the context is still kept.
- Whether hooks run under `codex exec`: UNKNOWN (not run; the exec path would need a model call).

## 4. MCP servers

- Table shape (VERIFIED, `config_toml.rs` `mcp_servers: HashMap<String, McpServerConfig>` and `mcp_types.rs` `RawMcpServerConfig`):

```toml
[mcp_servers.<name>]
command = "npx"                       # stdio
args = ["-y", "some-package"]
cwd = "..."
env_vars = ["TOKEN_NAME"]             # names passed from the parent env
startup_timeout_sec = 30              # float; startup_timeout_ms also accepted
tool_timeout_sec = 120
enabled = true
required = false
enabled_tools = ["..."]
disabled_tools = ["..."]
supports_parallel_tool_calls = false
[mcp_servers.<name>.env]
KEY = "value"
# HTTP transport instead: url = "https://...", bearer_token_env_var = "...", http_headers = {}, env_http_headers = {}
[mcp_servers.<name>.tools.<tool>]
approval_mode = "..."
```

- Observed in the user config (shape only): `[mcp_servers.<name>]` with `command`, `args`, `startup_timeout_sec`, and `[mcp_servers.<name>.env]`. Values not copied.
- Defaults: `startup_timeout_sec` default was not found in the parsed source (`codex mcp list --json` shows `None` for stdio servers without it). Tool timeout observed as 120 s for one plugin server. The runtime default is UNKNOWN.
- CLI (VERIFIED help):
  - `codex mcp add <NAME> [--env KEY=VAL]... -- <COMMAND...>`, or `codex mcp add <NAME> --url <URL> [--bearer-token-env-var VAR]`.
  - `codex mcp list [--json]` (JSON: `name`, `enabled`, `disabled_reason`, `transport{type: stdio|streamable_http, command, args, env, env_vars, cwd | url, ...}`, `startup_timeout_sec`, `tool_timeout_sec`, `auth_status`).
  - `codex mcp get`, `codex mcp remove`, `codex mcp login`, `codex mcp logout` (help lists them; `get` and `remove` args not inspected).
- Project scope: a project `.codex/config.toml` was not loaded in the smoke test (`codex mcp list` showed 0 matches for the probe server). The cause was not isolated; most likely the project is untrusted. Trust-state handling: UNKNOWN beyond this.

## 5. Subagents and custom agents

- Supported: yes. Built-in spawning, controlled in config (VERIFIED, `config_toml.rs` `AgentsToml`): `[agents]` with `enabled`, `max_concurrent_threads_per_session`, `max_depth`, `default_subagent_model`, `default_subagent_reasoning_effort`, `interrupt_message`.
- User-defined roles (VERIFIED):

```toml
[agents.researcher]
description = "Research-focused role."
config_file = "./agents/researcher.toml"   # relative to the defining config.toml
nickname_candidates = ["..."]
```

- Role file format (VERIFIED, `agent-roles/src/agent_role_config.rs`): TOML with optional `name`, `description`, `nickname_candidates`, and a config layer (`config: TomlValue`) that overlays the child agent config.
- Directory scanning (VERIFIED, `agent-roles/src/discovery.rs` `collect_agent_role_files`): recursively collects `*.toml` files in a directory. Which directory the roles are scanned from by default: UNKNOWN (not traced).
- Features: `multi_agent` stable/true, `multi_agent_v2` stable/false (VERIFIED, `codex features list`).
- Subagent hooks exist: `SubagentStart`, `SubagentStop`. Their input carries `agent_id` and `agent_type` (VERIFIED, PreToolUse input fields).

## 6. Non-interactive mode and e2e checks

- `codex exec [PROMPT]` (VERIFIED help). Useful flags: `--json` (JSON event output), `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--output-schema <FILE>`, `-o/--output-last-message <FILE>`, `-C/--cd`, `--add-dir`, `-s/--sandbox`, `-p/--profile`, `-m/--model`, `-c key=value`, `--enable/--disable <FEATURE>`, `--dangerously-bypass-hook-trust`, `--skip-git-repo-check`. Subcommands: `resume`, `fork`, `review`.
- Cheap, no-model checks (VERIFIED):
  - `codex debug prompt-input "<prompt>"` renders the model-visible input. It showed AGENTS.md content and the skill list. Good for proving instructions and skill discovery in e2e.
  - `codex mcp list --json` shows configured servers and their transport. It does not prove the server starts.
  - `codex features list`, `codex plugin list`, `codex doctor`.
- Proving an MCP server starts and answers a tool call: needs a model run (`codex exec`), or a direct MCP client test outside Codex. Not run. Whether `codex exec` needs network and auth: UNKNOWN (not run).
- Proving a hook fires: `codex exec` with a hook that writes a marker file. Not run; depends on the trust gate above and on exec running hooks (UNKNOWN).

## Gaps

- Official docs site (developers.openai.com/codex/*) not fetched. All behavior above comes from source at `rust-v0.160.0` and local `--help`/`debug` output, not the published docs.
- Global AGENTS.md file name and precedence: not read.
- Default MCP startup timeout: not found in source.
- Exact shell tool name for matchers (`Bash` or other): not verified.
- Hook trust hash computation and how to write `trusted_hash`: not traced.
- Hooks under `codex exec`, and an end-to-end run of a real skill, hook, or MCP call: not run (needs model and auth).
- Project-level MCP and hooks: depend on project trust; trust mechanics not traced.
- Plugin install scope (user vs project) and cache layout beyond the observed path: not verified.
- addyosmani: the repo uses a plugin (`.codex-plugin/`) plus a marketplace file, not AGENTS.md. Its root `AGENTS.md` targets the repo itself, not a Codex install. Its hooks (`hooks/session-start.sh`) are a standalone helper, not wired by either plugin (DOC-ONLY, `docs/codex-setup.md`).
