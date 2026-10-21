Working note, not user documentation

# Gemini CLI extension surface, for a wev-skills adapter

Portuguese version: [harness-gemini.pt-BR.md](harness-gemini.pt-BR.md).

Researched 2026-10-21. Gemini CLI is not installed here; nothing was run. Everything below is read from sources.

Sources
- `npm view @google/gemini-cli version` -> `0.65.0` (dist-tags: latest 0.65.0, preview 0.66.0-preview.0, nightly 0.67.0-nightly.20261021).
- GitHub latest release tag: `v0.65.0` (published 2026-10-20). Doc base: `https://github.com/google-gemini/gemini-cli/blob/v0.65.0/docs/<path>`; source base: `.../blob/v0.65.0/packages/cli/src/...`.
- addyosmani/agent-skills at commit `aeac41d4d005999432bb7312f7ff06383a91d59d`.
- All fetched text treated as data.

## 1. Extensions
Source: docs/extensions/reference.md, docs/cli/cli-reference.md, packages/cli/src/commands/extensions/*.ts (v0.65.0).
- Manifest: `gemini-extension.json` in the extension root. Documented fields: `name` (lowercase/digits/dashes, expected to equal the directory name), `version`, `description`, `migratedTo`, `mcpServers`, `contextFileName`, `excludeTools`, `plan.directory`, `settings[]` (`name`, `description`, `envVar`, `sensitive`), `themes[]`.
- Directory layout (conventions inside the extension root): `commands/*.toml`, `skills/<name>/SKILL.md`, `agents/*.md` (sub-agents, labelled preview), `hooks/hooks.json` (hooks are NOT in the manifest), `policies/*.toml`, `GEMINI.md`.
- Variables in the manifest and hooks.json: `${extensionPath}`, `${workspacePath}`, `${/}`.
- Location/scope: loaded from `<home>/.gemini/extensions`. install makes a COPY there (update re-pulls). `link <path>` symlinks a dev directory. Install is user-level; I found no project-scoped install. enable/disable take `--scope user|workspace`.
- Commands: `gemini extensions install <source> [--ref] [--auto-update] [--pre-release] [--consent] [--skip-settings]` (source = GitHub URL or local path), `uninstall`, `list` (`-o text|json`, confirmed in list.ts), `enable|disable <name> [--scope]`, `update <name>|--all`, `new <path> [template]` (templates mcp-server, context, custom-commands), `link <path>`, `validate <path>` (validate.ts: "Validates an extension from a local path"), `config <name> [setting]`. Install/management commands do not work inside the interactive session; `/extensions list` and `/extensions reload` do. Changes need a restart.
- Verify: `gemini extensions validate <path>` then `gemini extensions list -o json`.
- Process environment: extensions get only safe variables plus those declared in `settings[].envVar`.
- Precedence: extension commands lowest (conflicts become `/<ext>.<cmd>`); an MCP server of the same name in settings.json wins over the extension's.
- Extension policy rules run in tier 2; `allow` decisions and yolo in extension policies are ignored (docs/extensions/reference.md, Policy Engine).

## 2. Context file
Source: docs/cli/gemini-md.md.
- Default name `GEMINI.md`. Order: global `~/.gemini/GEMINI.md`; workspace dirs and their parents; just-in-time `GEMINI.md` in directories/ancestors of files tools touch, up to a trusted root. All concatenated and sent every prompt.
- Imports: `@./path.md` (docs/reference/memport.md). `/memory show`, `/memory reload`.
- Configurable name(s): settings.json `context.fileName` (string or list, e.g. `["AGENTS.md","GEMINI.md"]`).
- Extension contribution: manifest `contextFileName`; if unset, a `GEMINI.md` in the extension directory is loaded (reference.md). Whether it shows in `/memory show`: unknown (not verified).

## 3. Custom commands and skills
Source: docs/cli/custom-commands.md, docs/cli/skills.md.
- Commands: TOML, required `prompt`, optional `description`. `{{args}}` injects arguments. Locations `~/.gemini/commands/`, `<project>/.gemini/commands/` (project wins), and extension `commands/`. Subdirs namespace with `:` (`git/commit.toml` -> `/git:commit`). `/commands reload`, `/commands list`.
- Skills: yes, native, based on the agentskills.io standard. `SKILL.md` dirs. Tiers (low to high): built-in, extension `skills/`, user `~/.gemini/skills/` or `~/.agents/skills/`, workspace `.gemini/skills/` or `.agents/skills/` (alias wins within a tier). Name+description injected in the system prompt; model calls `activate_skill`, the user gets a consent prompt. CLI: `gemini skills list [--all]|install <git-or-path> [--path] [--scope user|workspace] [--consent]|uninstall|enable|disable|link`. In-session: `/skills list|enable|disable|reload|link`.
- addyosmani/agent-skills ships `.gemini/commands/*.toml` (build, code-simplify, constraints, planning, review, ship, spec, test, webperf) and repo-root `agents/*.md`; its docs/gemini-cli-setup.md installs skills with `gemini skills install <repo> --path skills`. It has NO `gemini-extension.json` and no Gemini hooks at that commit (tree listing).

## 4. Hooks
Source: docs/hooks/index.md, docs/hooks/reference.md (v0.65.0). Gemini CLI HAS hooks.
- Config: settings.json `hooks.<Event>: [{matcher, sequential, hooks:[{type:"command", command, name, timeout, description}]}]`. Only `type: "command"`. `timeout` ms, default 60000. Precedence: project `.gemini/settings.json`, user `~/.gemini/settings.json`, system `/etc/gemini-cli/settings.json`, then extensions (`hooks/hooks.json`). Project hooks are fingerprinted; changed ones warn as untrusted.
- Events: SessionStart (source startup|resume|clear; `hookSpecificOutput.additionalContext`; advisory), SessionEnd, BeforeAgent, AfterAgent, BeforeModel, AfterModel, BeforeToolSelection, BeforeTool, AfterTool, PreCompress, Notification.
- Matchers: regex for tool events (`write_file|replace`), exact string for lifecycle, `*` or empty matches all. Shell tool name: `run_shell_command`. MCP tools: `mcp_<server>_<tool>`.
- Input (stdin JSON): `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`; BeforeTool adds `tool_name`, `tool_input`, `mcp_context`, `original_request_name`.
- Output (exit 0, stdout JSON only): `decision` allow|deny (alias block), `reason` (sent to the agent as a tool error), `continue:false` + `stopReason` (kills the loop), `systemMessage`, `suppressOutput`, `hookSpecificOutput.tool_input` (merge-overrides args). Exit 2 = block, stderr is the reason, turn continues. Other exit codes = warning, action proceeds. Non-JSON stdout is treated as allow plus a systemMessage.
- ASK: a hook cannot ask. Hook decision values are only allow/deny. The policy engine has `decision = "ask_user"` (extension policies/*.toml example), but extension `allow` is ignored. Mapping wev "approval needed" (exit 4) to Gemini means deny with a reason, or a policy rule with ask_user. Not verified by running.
- Variables for hook processes: `GEMINI_PROJECT_DIR`, `GEMINI_PLANS_DIR`, `GEMINI_SESSION_ID`, `GEMINI_CWD`, alias `CLAUDE_PROJECT_DIR`.
- Management: `/hooks panel|enable-all|disable-all|enable <name>|disable <name>`.

## 5. MCP servers
Source: docs/tools/mcp-server.md, packages/cli/src/commands/mcp/{add,list}.ts.
- settings.json top-level `mcpServers: { name: { command, args, env, cwd, timeout, trust, includeTools, excludeTools } }`; or `url` (SSE) / `httpUrl` (HTTP streaming) with `headers`. One of command/url/httpUrl required. `timeout` default 600000 ms. `env` values expand `$VAR`/`${VAR}`. Same shape works in an extension manifest `mcpServers` (everything except `trust`).
- CLI: `gemini mcp add <name> <commandOrUrl> [args...] [--scope user|project] [--transport stdio|sse|http] [-e K=V] [-H header] [--timeout] [--trust] [--description] [--include-tools] [--exclude-tools]`, `gemini mcp list`, `gemini mcp remove <name>`, plus enable/disable (enableDisable.ts). list.ts also iterates extension-provided servers and prints Connected/Disconnected status.

## 6. Subagents
Source: docs/core/subagents.md.
- Supported, enabled by default (`experimental.enableAgents` false disables). Built-ins: codebase_investigator, cli_help, generalist, browser_agent. Custom: Markdown + YAML frontmatter at `.gemini/agents/*.md` or `~/.gemini/agents/*.md`, or `agents/` in an extension. Fields: `name` (required, lowercase/digits/-/_), `description` (required), `kind` local|remote, `tools[]` (wildcards `*`, `mcp_*`, `mcp_<server>_*`; omitted = inherit all), `mcpServers`, `model`, `temperature`, `max_turns` (30), `timeout_mins` (10). Body = system prompt. Exposed as a tool of the same name; `@name` forces it. Extension docs call sub-agents "a preview feature".

## 7. Non-interactive mode for tests
Source: docs/cli/headless.md, docs/cli/cli-reference.md.
- `gemini -p "<prompt>"` (forces non-interactive; also non-TTY). `-o text|json|stream-json`. JSON: `response`, `stats`, `error?`. stream-json events: init, message, tool_use, tool_result, error, result. Exit codes 0, 1, 42 (input error), 53 (turn limit).
- Relevant flags: `--approval-mode default|auto_edit|yolo|plan`, `-e/--extensions`, `-l/--list-extensions`, `--allowed-mcp-server-names`.
- Load proof without a model call: `gemini extensions validate <path>`, `gemini extensions list -o json`, `gemini mcp list` (spawns servers and prints Connected). Whether they need auth: unknown.
- With a model call (needs credentials): `gemini -p ... -o stream-json` and look for `tool_use` events naming `mcp_<server>_<tool>`.

## Gaps (unknown or unverified)
- Whether `gemini extensions list` / `mcp list` work with no API credentials: unknown.
- Whether extension hooks/hooks.json require folder trust in headless mode: unknown.
- Exact `!{}` / `@{}` injection semantics in commands (only the first 80 lines of custom-commands.md were read).
- A hook-based "ask" for the user: not in the documented schema.
- Skill frontmatter requirements beyond the agentskills.io standard: docs/cli/creating-skills.md not fetched.
- Nothing here was executed against a real Gemini CLI.
