Working note, not user documentation

# rea (morluto/rea, npm rea-agents) integration research

Portuguese version: [rea-integration.pt-BR.md](rea-integration.pt-BR.md).

Scope: read-only interface research for part 5 of wev-skills. Sources: `gh api repos/morluto/rea/contents/...` (default branch, fetched 2026-10-22) and `npm view rea-agents` (latest 6.7.0, modified 2026-10-18). Nothing was installed or executed. Paths are repository paths; "docs/" means `docs/` in morluto/rea. Docs describe `main`, which can be ahead of 6.7.0; statements that are main-only are marked.

Labels: documented (read in rea's docs, not run by us); unknown (not found in the fetched sources).

## 1. Setup and agent registration

Entry points: `npx rea-agents setup` (docs/installation.md, "Start setup"). `install.sh` (repo root) checks Node (22.19+, 24.11+ or 26+), curl and npm, installs the npm package globally (`npm install --global`, or `--prefix ~/.local`), then runs `rea setup` only when a terminal is available. `--no-setup` or `--no-prompt` skips setup. Documented.

Agents setup can register (docs/installation.md, "Supported agents"; `--client` values): claude_code, claude_desktop, codex, cursor, gemini_cli, windsurf, devin, opencode, antigravity, copilot_cli, commandcode, qwen_code, kimi, vscode, grok_build, omp, pi, hermes, qoder, droid, trae, workbuddy, zcode, dsh. Seven of them (droid, dsh, kimi, qoder, trae, workbuddy, zcode) need rea-agents 6.5.0 or later. Documented.

What it writes (docs/client-configuration.md):
- Claude Code: `mcpServers.rea` in `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`); skill under `~/.claude/skills`. JSON.
- Claude Desktop: `mcpServers.rea` in `claude_desktop_config.json` (macOS `~/Library/Application Support/Claude`; Linux `$XDG_CONFIG_HOME/Claude`; Windows `%APPDATA%\Claude`). Quit the app before approving. JSON.
- Codex: MCP table in `$CODEX_HOME/config.toml` (default `~/.codex`), with `startup_timeout_sec = 30` and a `tool_timeout_sec`. TOML.
- Gemini CLI: `mcpServers.rea` in `$GEMINI_CLI_HOME/.gemini/settings.json`. Workspace or system entries replace the user entry. JSON.
- OpenCode: `mcp.rea` (V1) or `mcp.servers` (V2) in its JSON or JSONC config, honoring `OPENCODE_CONFIG_DIR`. JSON.
- Grok Build: `[mcp_servers.rea]` and `[mcp_servers.rea.env]` in `$GROK_HOME/config.toml` (default `~/.grok`). TOML.
- Hermes: `mcp_servers.rea` in `config.yaml`. YAML.
- Qwen Code: `mcpServers` in `~/.qwen/settings.json`. JSON.
- Pi: `mcpServers.rea` (type stdio) in `~/.pi/agent/mcp.json`. JSON.
- OMP: `~/.omp/agent/mcp.json`. JSON.
- Qoder: `mcpServers.rea` in `~/.qoder/settings.json`. JSON.
- Factory Droid: `mcpServers.rea` in `~/.factory/mcp.json`. JSON.
- Trae: user-scope `mcp.json` in the VS Code-style user directory. JSON.
- WorkBuddy: `~/.workbuddy/mcp.json`. JSON.
- ZCode: `~/.zcode/cli/config.json`. JSON.
- DeepSeek Harness (dsh): entry in `$DSH_HOME/cordis.patch.yml` (default `~/.dsh`). YAML.
- Devin: `devin/mcp_config.json` (non-Windows, honors XDG_CONFIG_HOME). JSON.
- Kimi Code: `~/.kimi-code/mcp.json` (or `$KIMI_CODE_HOME`). JSON.
- GitHub Copilot CLI: `mcpServers.rea` in `mcp-config.json` (full path not stated in the fetched text).
- Cursor, Windsurf, VS Code, Antigravity MCP paths: unknown from the fetched docs. Cursor appears only in the supported-clients table.

Command registered: package-runner form `npx -y rea-agents@<exact version> mcp` (or `bunx rea-agents@<version> mcp`; wrapped in `cmd.exe /d /c` on Windows). Setup pins the exact installed version. A global install can instead be registered directly: `npm install --global rea-agents`, then `rea setup` registers the installed entrypoint. Documented (docs/installation.md, "Package runners and global installation" and "MCP Registry").

Skills and workflow: yes. Setup installs the bundled skill and its references into each selected client's personal skill directory. `--skill=false` opts out. With no client selected, the skill goes to `~/.agents/skills`. Documented (docs/installation.md, "Skill destinations").

Consent and non-interactive use: setup shows a plan with exact paths and changes and needs approval; decline or Ctrl-C changes nothing. Prompts only appear when stdin, stdout and stderr are all TTYs. Non-interactive: `rea setup --client <id> --yes`, or `--all-detected --yes`. `--yes` alone touches only existing REA-owned registrations. `--dry-run` returns a plan with exit 0; `--json` reports the plan without applying it. An unapproved apply exits 1 with `needs_confirmation`. Installing Hopper also needs `--install-hopper`. Documented.

## 2. `rea mcp` runtime

Command: `rea mcp` (stdio; the client launches it). `rea mcp --http [--host H] [--port N]` serves streamable HTTP for one client at a time. Host and port default to `MCP_HOST` and `MCP_PORT`, then 127.0.0.1 and an ephemeral port. A non-loopback bind relaxes checks and is logged. Documented (docs/cli.md, "Serve MCP over streamable HTTP"; docs/mcp-contracts.md). `rea mcp doctor [--json]` checks production startup.

Environment variables named in the docs (not exhaustive):
- Logging and MCP: REA_LOG_LEVEL (an invalid value fails every scope), REA_MCP_INPUT_SCHEMA_PROFILE, REA_MCP_OUTPUT_SCHEMA_PROFILE (set `off` for hosts with small frames), REA_MCP_MAX_RESPONSE_BYTES, MCP_HOST, MCP_PORT, REA_ANALYSIS_PROVIDER.
- Provider paths and timeouts: REA_GHIDRA_STARTUP_TIMEOUT_MS, REA_HOPPER_STARTUP_TIMEOUT_MS, REA_JEB_MCP_TIMEOUT_MS, REA_JEB_MCP_URL, REA_JADX_OPERATION_TIMEOUT_MS, REA_ADB_PATH, REA_BROWSER_EXECUTABLE, REA_ELECTRON_EXECUTABLE, REA_GDB_COMMAND, REA_RIZIN_COMMAND, REA_OBJDUMP_COMMAND, REA_APKTOOL_COMMAND, REA_KUNA_COMMAND, REA_IDA_MCP_CONFIG, REA_GHIDRA_SEED_FILE, REA_GHIDRA_LANGUAGE_ID, REA_GHIDRA_COMPILER_SPEC_ID, REA_GHIDRA_DISABLED_ANALYZERS, REA_WABT_BIN_DIRECTORY, REA_WAKARU_COMMAND.
- External installs: GHIDRA_INSTALL_DIR, JAVA_HOME, HOPPER_LAUNCHER_PATH.
Documented across docs/installation.md, client-configuration.md, testing.md, adb-device-analysis.md.

Working directory: the CLI resolves relative paths against the cwd; MCP clients must pass absolute paths. Documented (docs/cli.md).

Artifacts and evidence: analysis Evidence is retained in the running session under an Evidence ID. `export_evidence_bundle` writes a complete bundle atomically to a caller-given path. REA state and cache live under `~/.rea`, removed only by `rea uninstall --purge-data`. Hopper release cache: `${XDG_CACHE_HOME:-$HOME/.cache}/rea/hopper-releases/`. Default evidence location for a plain session: unknown. Documented (docs/mcp-contracts.md; docs/installation.md).

Network at runtime: setup downloads (the official Hopper package; npm). At runtime, bundle analysis fetches source maps only when `fetch_source_maps` is selected, with exact-origin checks and no credentials. Browser observation attaches to a Chrome the user started with `--remote-debugging-port` on loopback; REA does not launch it. The complete list of runtime outbound calls: unknown.

Download or execute targets: yes, with the user's own permissions.
- `capture_process_scenario` runs one caller-selected command and records evidence (docs/process-capture.md). It is not a sandbox.
- Frida: `start_frida_session` attaches or spawns; `load_frida_script` runs JavaScript inside the target with its memory, filesystem and network authority (docs/frida-instrumentation.md).
- ADB: `install_adb_package`, `push_adb_file`, `uninstall_adb_package`, `start_adb_app`, `start_adb_activity`, `stop_adb_app` change device state (docs/adb-device-analysis.md).
- Browser: `capture_browser_scenario`, `observe_web_session`, `inspect_web_page` act on an attached browser; generic CDP evaluate is not exposed (docs/browser-observation.md).
- Electron: `capture_electron_scenario`.
- Native tools run local binaries: rizin, gdb, Cutter, objdump (`execute_rizin_command`, `gdb_console`, `cutter_command`, `inspect_with_objdump`).
- `analyze_web_bundle` parses without execution (docs/browser-observation.md).

## 3. Isolation and containers

- No official Docker image or documented container run for the MCP server was found in README, docs/installation.md, docs/cli.md, SECURITY.md or DISCLAIMER.md.
- The only Dockerfile in the docs is generated by `rea environment-export` for an agent-environment bundle: base `node:24.18.0-bookworm-slim`, installs `rea-agents@<version>`, runs `environment-serve` with `MCP_HOST=0.0.0.0` and `MCP_PORT=18765` (docs/agent-environments.md). It serves an environment; it is not an analysis sandbox.
- docs/installation.md says clean-room separation needs filesystem and network restrictions enforced by "a separate account or container", because an agent under the same OS account can still run REA and read its output.
- SECURITY.md: "This is not a sandbox" and it does not protect against same-user malicious processes.
- Host requirements, from the docs: Node.js 22.19+, 24.11+ or 26+ with npm (required). Hopper (commercial; macOS and Linux only) needs its own Python for its bridge (`bridge/hopper_bridge.py` ships in the package). Ghidra is user-managed and needs Java (`GHIDRA_INSTALL_DIR`, `JAVA_HOME`). IDA and Kuna have their own guides (docs/ida-provider.md, docs/kuna-provider.md; not read). ADB tools need adb and a device or emulator. Browser tools need a Chromium-family browser with a debugging port. Electron tools need an Electron executable. Frida needs native bindings.
- A container recipe judged against these needs: unknown; upstream does not provide one.

## 4. DISCLAIMER.md and SECURITY.md

DISCLAIMER.md, in short: REA is for lawful analysis (security research, malware analysis, vulnerability research, CTFs, interoperability, preservation, and auditing software you own or are authorized to examine). It declines DRM or license circumvention, game cheats, bypassing access controls on systems you are not authorized to test, copying proprietary code, evading AI provider policies, and reselling AI access. The user is responsible for authorization, legal compliance, and what they direct an agent to do. Inspection authorization does not necessarily cover execution, interception, device changes or interaction. Results may be incomplete or wrong. Output does not grant rights to the original program. Commercial tools (IDA, Hopper, JEB) must be legally obtained. Warranty: AS IS under MIT.
Quote (under 15 words), DISCLAIMER.md: "does not by itself establish permission for every operation".

SECURITY.md, in short: report vulnerabilities through GitHub's private advisory feature. Per-session capability tokens authenticate the Hopper and Ghidra bridges (Unix sockets, or authenticated loopback TCP on Windows). The file states it is not a sandbox and that opening an untrusted binary runs parsing with the user's permissions. Linux Hopper packages come only from Hopper's HTTPS origin, checked against a published SHA-1 value, which the file calls a corruption check rather than a signature.

Implication for wev: rea places authorization, containment and output rights on the user. wev must not describe rea as a clean-room or sandbox guarantee.

## 5. Tool catalog for the two uses

Tool names below come from the `mcp__rea__*` entries in this session's deferred tool list, a live catalog whose version is not verified. Docs name tools in docs/browser-observation.md, docs/adb-device-analysis.md, docs/frida-instrumentation.md, docs/mcp-prompts.md, docs/mcp-contracts.md and docs/client-configuration.md. A main-branch doc reports 172 tools at commit 04089d5be; the exact count for 6.7.0: unknown. `docs/tools.md` does not exist in the repo.

- Web app analysis (bundle, network, screenshot): analyze_javascript_application, analyze_web_bundle, inspect_web_page, inspect_web_network_capture, inspect_web_event_listeners, capture_web_screenshot, compare_web_screenshots, compare_web_captures, observe_web_session, observe_web_execution, list_browser_targets, capture_browser_scenario, discover_webmcp_tools, export_web_scripts, recover_javascript_sources, compare_bundles, compare_source_to_bundle, inspect_packet_capture, inspect_pcap_capture, inspect_wasm_artifact.
- Native and binary static: binary_overview, open_binary, binary_session, close_binary, list_procedures, procedure_pseudo_code, procedure_assembly, procedure_callers, procedure_callees, batch_decompile, search_strings, list_strings, xrefs, find_xrefs_to_name, get_call_graph, build_call_path, inspect_macho, inspect_pe_resources, inspect_go_binary, inspect_rust_binary, inspect_dart_aot, inspect_native_api, read_function_instructions, inspect_with_objdump, execute_rizin_command, cutter_command, gdb_console, start_gdb_session. Managed and Android: inspect_android_class, inspect_android_method, decode_android_resources, inspect_apktool_client, decompile_jeb_item, inspect_managed_artifact, compare_managed_members.
- Runtime observation (Frida, browser, Electron, ADB, native UI): list_frida_devices, list_frida_processes, start_frida_session, load_frida_script, unload_frida_script, resume_frida_session, close_frida_session, frida_session_status, instrument_with_frida, observe_native_calls, observe_native_ui, capture_native_ui_scenario, capture_process_scenario, observe_javascript_runtime, capture_electron_scenario, inspect_electron_page, inspect_electron_fuses, list_electron_targets, list_adb_devices, inspect_adb_package, capture_adb_screen, read_adb_logcat, collect_adb_bugreport. Device-changing ADB tools are listed in section 2.
- Evidence export and bundles: export_evidence_bundle, import_evidence_bundle, get_evidence_bundle, inspect_artifact, inspect_analysis_view, compare_artifacts, compare_process_captures, correlate_static_and_runtime, record_unknown, update_unknown, list_unknowns, verify_unknown_resolution.
- Reconstruction and verification: build_reconstruction_obligation_ledger, evaluate_reconstruction_coverage, verify_reconstruction, verify_managed_native_boundaries, import_managed_reconstruction, compare_functions, compare_javascript_export_shapes, compare_wasm_interfaces, find_changed_behavior, reconcile_javascript_runtime, trace_feature, trace_application_feature. Described in docs/reconstruction-coverage.md and docs/reconstruction-obligation-ledgers.md (not read in full).

## 6. Version pinning and registry manifest

- docs/installation.md (MCP Registry section) gives the manual config `{"command":"npx","args":["-y","rea-agents@<version>","mcp"]}` and says persistent registrations should use one exact version (6.7.0 at the time). Documented. Whether `npx -y rea-agents@<version> mcp` starts as a stdio server on a clean host: documented, not verified by us.
- npm: `rea-agents` latest 6.7.0. `bin` maps `rea` and `rea-agents` to `scripts/rea.mjs`. Engines: `^22.19.0 || ^24.11.0 || >=26.0.0`.
- `server.json` (repo root): name `io.github.morluto/rea`, title REA, version 6.7.0. One `packages` entry: registryType npm, identifier `rea-agents`, version 6.7.0, runtimeHint `npx`, transport stdio, packageArguments one positional `mcp`. It declares no `env` and no `runtimeArguments`. Schema 2025-12-11.

## Gaps

- Cursor, Windsurf, Antigravity and VS Code MCP file paths; Copilot's full path.
- Default evidence location for a plain session; full list of runtime network calls.
- Whether `npx -y rea-agents@<version> mcp` starts on a clean host (not run, by design).
- Exact tool count and list for 6.7.0 (`npm pack` was not used).
- Container recipe: none upstream.
- Not read in full: docs/ida-provider.md, docs/kuna-provider.md, reconstruction docs, most per-client sections.
