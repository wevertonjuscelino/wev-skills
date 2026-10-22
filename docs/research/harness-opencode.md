Working note, not user documentation

# OpenCode extension interface (research for a wev-skills adapter)

Portuguese version: [harness-opencode.pt-BR.md](harness-opencode.pt-BR.md).

Researched 2026-10-21. OpenCode is not installed on this machine, so nothing below was executed; every fact is read from sources. Fetched text was treated as data.

## Sources and versions

- `npm view opencode-ai version` returned 1.19.3. GitHub latest release of the repo is tag `v1.19.3` (2026-10-16). `sst/opencode` now redirects to `anomalyco/opencode` (default branch `dev`).
- Docs at the tag, in the repo: `https://github.com/sst/opencode/blob/v1.19.3/packages/web/src/content/docs/<page>.mdx` (pages: config, rules, agents, commands, skills, plugins, mcp-servers, cli, permissions). The site opencode.ai/docs is built from these; the site itself was not fetched.
- Plugin type definitions: `https://github.com/sst/opencode/blob/v1.19.3/packages/plugin/src/index.ts`.
- Debug CLI source: `https://github.com/sst/opencode/blob/v1.19.3/packages/opencode/src/cli/cmd/debug/` (`config.ts`, `skill.ts`, `agent.ts`).
- addyosmani/agent-skills at commit `aeac41d4d005999432bb7312f7ff06383a91d59d` (main): `.opencode/skills` is a symlink to `../skills/`; there is no `.opencode/commands` on main (its own doc says so, PR #200 proposes it); `docs/opencode-setup.md` describes the setup.

## 1. Config and instructions

- Format: `opencode.json` or `opencode.jsonc`; schema `https://opencode.ai/config.json` (config.mdx#Format).
- Global: `~/.config/opencode/opencode.json` (also `tui.json` for TUI). Project: `opencode.json` in the project root; lookup starts in the cwd and walks up to the nearest Git directory (config.mdx#Per project).
- Merge order, later overrides earlier: remote `.well-known/opencode`, global, `OPENCODE_CONFIG` file, project, `.opencode` directories, `OPENCODE_CONFIG_CONTENT`, managed files, macOS managed prefs. Files are merged, not replaced. `OPENCODE_CONFIG_DIR` adds a custom config directory.
- `.opencode/` and `~/.config/opencode/` use plural subdirectories: `agents/ commands/ modes/ plugins/ skills/ tools/ themes/` (singular accepted for backward compatibility).
- Rules: `AGENTS.md` in the project (walks up from the cwd), global `~/.config/opencode/AGENTS.md`. Claude Code fallbacks: `CLAUDE.md` used only if no `AGENTS.md`; `~/.claude/CLAUDE.md` used only if no global `AGENTS.md`. The first match wins per category. Disable with `OPENCODE_DISABLE_CLAUDE_CODE`, `..._PROMPT`, `..._SKILLS` (rules.mdx).
- Extra instruction files: `"instructions": ["CONTRIBUTING.md", "docs/*.md", "https://..."]` (globs and URLs; URLs have a 5 s timeout), combined with `AGENTS.md`.
- Variables in config: `{env:NAME}`, `{file:path}`.
- Implication: this repo already has `CLAUDE.md` and an untracked `AGENTS.md`; OpenCode would read `AGENTS.md` and ignore `CLAUDE.md`.

## 2. Agents and subagents

- Two forms (agents.mdx#Configure): JSON under `agent.<name>` in `opencode.json`, or markdown files in `.opencode/agents/` (project) and `~/.config/opencode/agents/` (global). The file name (without `.md`) is the agent name.
- Markdown frontmatter keys documented: `description` (required), `mode` (`primary`, `subagent`, `all`; default `all`), `model` (`provider/model`), `temperature`, `top_p`, `steps` (`maxSteps` deprecated), `disable`, `hidden` (subagents only), `color`, `permission` (edit, bash, webfetch, skill, task patterns), `tools` (deprecated). The body is the system prompt. JSON also takes `prompt`, including `{file:./prompts/x.txt}`.
- Built-in: primary `build`, `plan`; subagents `general`, `explore`, `scout`; hidden `compaction`, `title`, `summary`. Subagents are invoked by `@name` or by the model through the Task tool. `subagent_depth` (default 1) limits nesting; `default_agent` picks the primary agent.
- Differences from Claude Code agents: no `tools:` allow list in the preferred form (use `permission`), `model` is `provider/model`, `mode` has no Claude equivalent. Skills are not preloaded per agent; `permission.skill` can restrict them.
- CLI: `opencode agent create` (non-interactive when `--path --description --mode --permissions` are all given) and `opencode agent list`.

## 3. Commands and skills

- Commands (commands.mdx): markdown in `.opencode/commands/` or `~/.config/opencode/commands/`, or JSON `command.<name>` with `template`. Frontmatter: `description`, `agent`, `model`, `subtask` (not read in this pass). Body is the template; placeholders `$ARGUMENTS`, `$1 $2 ...`; the file name is the command name, used as `/name`. Shell output and file inclusion syntax exist (not verified here).
- Skills exist and follow the same SKILL.md convention as Claude Code (skills.mdx). Loaded on demand through a native `skill` tool; the tool description lists `<available_skills>`; the model calls `skill({ name })`.
- Skill search paths (project paths are found by walking up to the git worktree): `.opencode/skills/<name>/SKILL.md`, `~/.config/opencode/skills/<name>/SKILL.md`, `.claude/skills/...`, `~/.claude/skills/...`, `.agents/skills/...`, `~/.agents/skills/...`.
- Frontmatter recognised: `name` (required, must equal the directory name, regex `^[a-z0-9]+(-[a-z0-9]+)*$`, max 64), `description` (required, 1 to 1024), `license`, `compatibility`, `metadata` (string map). Unknown fields are ignored.
- Permissions: `permission.skill` with patterns `allow|deny|ask`.
- Implication: the existing `skills/*/SKILL.md` of wev-skills load unchanged if they satisfy the name rule. Note `${CLAUDE_PLUGIN_ROOT}` is a Claude Code variable and means nothing to OpenCode (inferred, not tested).

## 4. Plugins and hooks

- A plugin is a JS or TS module exporting one or more async functions; each receives `{ project, client, $, directory, worktree, serverUrl, experimental_workspace }` and returns a hooks object (plugins.mdx; `PluginInput` in plugin/src/index.ts).
- Loading: files in `.opencode/plugins/` and `~/.config/opencode/plugins/` load automatically; npm packages via `"plugin": [...]` in config, installed with Bun and cached in `~/.cache/opencode/node_modules/`. `opencode plugin <module> [--global]` installs one and edits the config. Local plugin dependencies go in `.opencode/package.json` (`bun install` at startup). Load order: global config, project config, global plugin dir, project plugin dir; all hooks run in sequence.
- `Hooks` interface (v1.19.3): `event`, `config`, `tool`, `auth`, `provider`, `chat.message`, `chat.params`, `chat.headers`, `permission.ask`, `command.execute.before`, `tool.execute.before`, `tool.execute.after`, `shell.env`, `tool.definition`, `experimental.chat.messages.transform`, `experimental.chat.system.transform`, `experimental.session.compacting`, `experimental.compaction.autocontinue`, `experimental.text.complete`, `experimental.provider.small_model`, `dispose`.
- Event names through the `event` hook (docs list): `session.created`, `session.idle`, `session.compacted`, `session.deleted`, `session.error`, `session.status`, `session.updated`, `session.diff`, `message.*`, `permission.asked`, `permission.replied`, `command.executed`, `file.edited`, `tool.execute.before/after`, `todo.updated`, `shell.env`, `lsp.*`, `server.connected`, `tui.*`, `installation.updated`.
- Mapping to wev hooks (the Claude-side events are from hooks.json wiring, not re-checked): pre-tool-use maps to `tool.execute.before` (`input: {tool, sessionID, callID}`, `output: {args}`); post-tool-use to `tool.execute.after` (`input` adds `args`; `output: {title, output, metadata}`); session start has no dedicated hook, nearest are the `session.created` event and `experimental.chat.system.transform`; stop maps to `session.idle` (third-party issue #50133 gives the same mapping).
- Blocking a shell command: the docs example blocks a read by `throw new Error(...)` inside `tool.execute.before` when `input.tool === "read"`. The bash tool id is `"bash"` and its command is `output.args.command` (the docs' dependency example reads `input.tool === "bash"` and `output.args.command`). So throwing in `tool.execute.before` for `bash` is the documented blocking route. Alternative: `permission.ask` with `output.status = "deny"`, or `permission` rules in config. Whether a thrown error reaches the model as an error message verbatim: unknown, not tested.
- Per-call workdir (source for the wev plugin and codec): the bash tool takes an optional `workdir` argument, in anomalyco/opencode `packages/core/src/tool/plugin/shell.ts` (v1.19.3). Read from source; not run against a real OpenCode.
- Gaps (issue https://github.com/anomalyco/opencode/issues/50133, open, third-party claims, not verified in source): tool hooks carry no `cwd`; no per-agent hooks; failed tool calls are not clearly signalled in `tool.execute.after`. PR #36238 states subagent tool calls now fire plugin hooks (title of a test PR; not read in detail). Whether MCP tool calls pass through `tool.execute.before`: unknown.
- Calling an external executable: a plugin is ordinary Bun code. `$` is Bun's shell API, so `await $\`wev hook pre-tool-use\`.stdin(json)` style calls, or `Bun.spawn` / `node:child_process` with JSON on stdin, are possible in principle. Verified fact: `$` runs commands (docs use `$\`osascript ...\``). Not verified: that stdin piping works exactly as written; it has to be tested with an installed OpenCode. Sketch of the adapter: plugin spawns `wev hook pre-tool-use` with a Claude-style JSON payload built from `{tool, sessionID, args}`, reads the exit code (wev exit 3 denied, 4 approval needed, 6 guard tripped) and throws on non-zero.
- Custom tools can also be defined in plugins via `tool: { name: tool({ description, args, execute }) }` using `@opencode-ai/plugin` and Zod (plugin tools override built-ins of the same name); standalone custom tool files live in `.opencode/tools/` (custom-tools.mdx, not read in detail).

## 5. MCP servers

- Config key `mcp.<name>` in `opencode.json` (mcp-servers.mdx).
- Local: `{ "type": "local", "command": ["npx","-y","pkg"], "environment": {"K":"V"}, "cwd": "...", "enabled": true, "timeout": 5000 }`. `command` is an array (program plus args), not a string; env key is `environment`.
- Remote: `{ "type": "remote", "url": "https://...", "enabled": true, "headers": {...} }`; OAuth is supported for remote servers.
- CLI: `opencode mcp add` (interactive wizard, no documented flags), `opencode mcp list` / `ls` (shows connection status), `opencode mcp auth [name]`, `opencode mcp auth list`, `opencode mcp logout [name]`, `opencode mcp debug <name>` (cli.mdx). Writing the config file directly is the scriptable route.
- MCP tools are named after the server name; `permission` patterns can target them (permissions.mdx, not read in detail).

## 6. Non-interactive modes for tests

- `opencode run [message..]` runs a prompt without the TUI. Flags: `--command`, `--agent`, `--model provider/model`, `--format json` (raw JSON events), `--dir`, `--file`, `--continue`, `--session`, `--attach URL` (use with `opencode serve`), `--auto` (auto-approve permissions not explicitly denied), `--port`, `--title`. It needs a configured model provider and sends a real prompt, so it is not free of network or model; unsuitable for the offline unit tests this repo requires, fine for an opt-in integration test.
- Offline load checks that need no model, read from source at v1.19.3 (`packages/opencode/src/cli/cmd/debug/`): `opencode debug config` prints the resolved config as JSON (redacted); `opencode debug skill` prints all discovered skills as JSON; `opencode debug agent <name>` shows one agent's configuration; also `debug paths`, `debug info`. These are not in the docs page, and their output was not observed. They are the best candidate to prove that agents, skills and MCP entries load; `opencode agent list` and `opencode mcp list` are the documented ones (`mcp list` may start servers).
- Env helpers for hermetic tests: `OPENCODE_CONFIG`, `OPENCODE_CONFIG_DIR`, `OPENCODE_CONFIG_CONTENT`, `OPENCODE_DISABLE_CLAUDE_CODE`, `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_PERMISSION`.
- Commands are not covered by an offline lister; `opencode debug config` should include the merged `command` map but this was not verified.

## Gaps summary

- Nothing was executed; all runtime behaviour (stdin to a spawned process, exact thrown-error surface, MCP calls hitting the pre-tool hook, debug output shape) is unverified.
- `subtask` and other command frontmatter keys, `.opencode/tools/` format, and permission patterns for MCP tools were not read in full.
- Exact claude.ai-to-OpenCode field mapping for agents (tools allow list to permission) needs a design decision plus a test against an installed OpenCode.
