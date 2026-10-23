# Installation guide

Portuguese version: [installation.pt-BR.md](installation.pt-BR.md).

wev-skills was first published on 2026-10-13 (v1.0.0, announced then as 0.1.0 and renumbered on 2026-10-15) at <https://github.com/wevertonjuscelino/wev-skills>. There is no package on PyPI and no listing in an official marketplace. Every route below starts from a clone of that repository or from the repository as a Claude Code marketplace source. Neither route has been run: cloning, the published marketplace route and the install commands are documented only, and the plugin has never been loaded in a live Claude Code session.

Status labels used here follow the project convention: implemented and tested, implemented but untested, simulated with mocks, documented only, blocked. See the [glossary](../glossary.md).

## Quick install

`install.sh` at the repository root asks a few questions and then calls the `wev` CLI for everything that has rules. From a clone:

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
cd wev-skills
bash install.sh
```

To keep using that clone as the installed copy (a developer route; the install is then "from a local source, not self-updating"):

```sh
bash install.sh --source "$WEV_HOME"
```

The one-line form, **after the owner publishes it (documented only)**:

```sh
curl -fsSL https://raw.githubusercontent.com/wevertonjuscelino/wev-skills/main/install.sh | bash
```

Under `curl | bash` stdin is the script itself, so every question is read from the terminal (`/dev/tty`). Without a terminal and without `--yes` the script stops and names the flags. Read the script before you pipe it into a shell; it is one file of fewer than 400 lines.

**What it asks, in order:** the language (`en` or `pt-BR`, default from `LANG`); the licence (PolyForm Noncommercial 1.0.0, noncommercial use only) and whether to install under it; which of the harnesses it found (`claude`, `codex`, `gemini`, `opencode`) to install into; whether to use JEV and, if yes, the API key (typed hidden); whether to build the rea container image now.

**What it does, in order:** system checks (macOS or Linux; `git` and `curl` unless `--source`; Python 3.14 or newer; Node and npm for rea) → licence → language → harness detection → bootstrap (the latest release tag from the GitHub releases API, a shallow clone of that tag in a temporary directory, then `wev skills update wev-skills`, which installs the release under `$XDG_DATA_HOME/wev-skills/third-party/` and points `current` at it; the temporary clone is deleted on exit) → JEV → third parties (`wev skills update rea`, `update agent-skills`, `activate`) → rea mode and image → harnesses → a summary.

| Flag | Effect |
|---|---|
| `--yes` | Answer yes to every question. Never installs system packages: when Python or Node is missing it stops and names the command |
| `--lang en\|pt-BR` | Message language (default: from `LANG`); passed to every `wev` call |
| `--harness LIST` | Comma list of `claude,codex,gemini,opencode` (default: the ones found, each confirmed) |
| `--jev` / `--no-jev` | Use JEV (asks for the key) or not (default: ask; `--yes` alone means no) |
| `--rea-mode isolated\|direct` | How rea runs (default: `isolated` when `docker` is found, else `direct`) |
| `--source DIR` | Use `DIR/bin/wev` instead of downloading the latest release |
| `--uninstall` | Remove what the installer put in place (below) |
| `--purge` | With `--uninstall`: also remove the configuration directory |
| `--help` | Print the flags |

**What it writes, and where:** the data directory `$XDG_DATA_HOME/wev-skills` (else `~/.local/share/wev-skills`: third-party versions, harness manifests); the configuration directory `$XDG_CONFIG_HOME/wev-skills` (else `~/.config/wev-skills`) with the key file `.env` (mode 0600, written by `wev jev key set`) and the user configuration `wev.config.json` (mode 0600; it sets `language`, and `decision.provider` `jev` only when the JEV probe succeeded); `rea.json` through `wev rea mode`; and, through the CLI, the harness directories (`wev harness install --target codex|gemini|opencode`; for Claude Code, `claude plugin marketplace add` of the `current` directory and `claude plugin install wev-skills@wev-skills-marketplace`). Nothing else.

**The JEV key.** `wev jev key set` reads the key from stdin (one line; it refuses a terminal on stdin), writes it to the key file and prints the path, `key_source` and `usable`, never the key. The installer reads the key with a hidden prompt on the terminal and pipes it to that command, so it is in no argument, no environment variable and no log. If an environment variable `TYPESAFE_API_KEY` is set, it shadows the file and the answer carries `shadowed_by_env`. `wev jev key set` is a person-only command: the Claude Code hook asks about it and the other harnesses deny it. You can run it yourself from a terminal: `wev jev key set < keyfile` or `pbpaste | wev jev key set`. After the key, the installer runs `wev jev ask` once as a probe; on failure it shows the error, offers one retry and otherwise continues with JEV off.

**What continues and what stops.** A failed `wev skills update rea|agent-skills|activate` or a failed harness registration is shown, marked `failed` in the summary and the script goes on; the summary then ends with "Finished with N failures" and the script exits 1. Only a run with zero failures exits 0. A failed bootstrap, `jev key set`, `rea mode`, `config validate` or a missing mandatory tool stops the script with that call's output. Declining the licence installs nothing.

**Re-run.** Run it again with other answers to reconfigure: `skills update` is a no-op at the newest version, `harness install` replaces wev's own files, `jev key set` replaces only the `TYPESAFE_API_KEY` line, `rea mode` rewrites one file, and the user configuration keeps its other keys. `--no-jev` on a later run turns JEV off (the `decision.provider` line is removed).

**Uninstall.** `bash install.sh --uninstall` runs `wev harness uninstall --target ...` for each manifest present, `claude plugin uninstall wev-skills` and `claude plugin marketplace remove wev-skills-marketplace` when `claude` exists, `wev skills deactivate`, then removes the data directory. It asks before removing the configuration directory (the key file and the user configuration); with `--yes` it keeps that directory unless `--purge` is also given. It prints what it removed and what it kept. If any `harness uninstall`, `claude plugin uninstall`, `marketplace remove` or `skills deactivate` fails, the data directory is kept (so the manifests remain for a retry) and the script exits 1; it also keeps the data directory and exits 1 when Python 3.14 or `current/bin/wev` is missing.

**Working directory and Python.** The script changes into its own temporary directory before any `wev` call, so a `wev.config.json` in the directory you ran it from has no effect; the user-level configuration applies. Every `python3 -c` it runs uses `-I`. wev is run as `<python3.14> <bin/wev>`, but the harness hooks use `#!/usr/bin/env python3`: when the `python3` first on `PATH` is older than 3.14 the summary says the hooks need a 3.14 first on `PATH` (a limit; the installer does not fix it).

**The JEV probe** runs with `TYPESAFE_API_KEY` unset, so it validates the key you typed. If that variable is exported in your shell, the summary says the exported value will win over the stored key.

**What it never does.** It never pipes a remote script into a shell to install a dependency. It never installs a system package under `--yes`; without `--yes` it shows one known command (`uv python install 3.14`, `brew install python`, `brew install node`, `sudo apt-get install -y ...`, `sudo dnf install -y ...`) and runs it only after you say yes. It does not trust Codex hooks, run `gemini extensions link` or `codex mcp add` for you: those are printed as next steps in the summary.

Status: **implemented and tested** with fake harness CLIs and a local source (unit tests, offline: `tests/unit/test_install_sh.py`, `tests/unit/test_jev_key_set.py`, `tests/unit/test_config_user_tier.py`). **Not run in this change (e2e part):** the download route (releases API, `git clone` of the tag), a real `claude plugin install`, real Codex, Gemini CLI and OpenCode, a real JEV probe, and the interactive dependency-install path. Also unverified until then: whether a real `claude plugin marketplace add` accepts a re-run, and whether it records the `current` link or its resolved target. The `curl | bash` line is documented only. `shellcheck` is not a dependency. See [SECURITY.md](../../SECURITY.md#installer).

## Requirements

| Requirement | Needed for | Notes |
|---|---|---|
| Python 3.14 or newer | The engine and its tests | Standard library only; there is nothing to `pip install`. Older interpreters, including the stock macOS `/usr/bin/python3` (3.9), are not supported. The suite last ran on Python 3.14.7 (see [mvp-status.md](../mvp-status.md)) |
| macOS or Linux | The state store | It uses POSIX file locks. Windows is not supported |
| `git` | `wev run start`, `wev run resume`, `wev state drift` | The engine snapshots the repository state. Outside a git repository the runs still work, with less to compare |
| Claude Code | The plugin: skills, subagents, hooks | Only for the plugin steps. The CLI works without it. Tested with Claude Code 2.1.296 for `claude plugin validate`; nothing else was run through Claude Code |
| `claude` CLI | `wev specialists score` and `score_on_finish` only | Starts `claude -p` unattended and spends tokens. Implemented but untested until the owner runs it; confirm on the first real run that the wev hooks fire (see [SECURITY.md](../../SECURITY.md), "Unattended scoring") |
| `ssh` and `tmux` on the host | The optional remote module | See the [remote operations guide](remote-ops.md) |
| `ruff`, `mypy` (or `uvx`) | `make lint` only | Optional; see [Running the tests and lint](#running-the-tests-and-lint) |

## Install from a local clone

Clone the repository (status: documented only; the command was not run). In the examples, `$WEV_HOME` is the clone.

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
export WEV_HOME="$PWD/wev-skills"
"$WEV_HOME/bin/wev" version
```

Real output (the launcher was run for this guide):

```text
{
  "version": "7.0.0"
}
```

`bin/wev` is a launcher that adds `src/` to the import path and runs the CLI, so it needs no installation. Three equivalent ways to call it:

1. By path: `"$WEV_HOME/bin/wev" ...`.
2. Through a symlink on your `PATH`. The launcher resolves its own real path, so a symlink works (run for this guide with a symlink in a temporary directory):

   ```sh
   mkdir -p ~/.local/bin
   ln -s "$WEV_HOME/bin/wev" ~/.local/bin/wev
   wev version
   ```

3. As a module, from the repository root: `PYTHONPATH=src python3 -m wev_skills ...`. The `Makefile` and the shipped evaluation README use this form.

`pyproject.toml` declares a `wev` console script for `pip install`. Installing the package with `pip` was not run for this guide, so treat it as implemented but untested. If you install it, note that the evaluation harness and the examples look for `evals/` next to the source tree and fail with `evals_dir_not_found` without it (pass `--tasks-dir` and `--configs`).

State is written to `.wev/` at the root of the git repository you run in (the nearest enclosing directory with a `.git` entry; the current directory if there is none), not in the directory you happen to be in. `.wev/` has its own `.gitignore` that ignores everything in it, so nothing needs to be added to the project's. A run also adds an entry to a per-user registry, `$XDG_STATE_HOME/wev-skills/active-runs.json` (else under `~/.local/state`), which the hook uses to find a run from a path named in a command. The configuration is read from `--config`, else `<repository root>/wev.config.json`, else the defaults, and is pinned in the run when it starts (see the [configuration guide](configuration-and-providers.md)).

## Load the plugin for one session

```sh
claude --plugin-dir "$WEV_HOME"
```

`--plugin-dir` loads a plugin from a directory for that session only. The plugin consists of:

| Part | Where | Status |
|---|---|---|
| Manifest | `.claude-plugin/plugin.json` | `claude plugin validate` passes, with one warning (below) |
| Seven skills | `skills/wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md`, `wev-readme`, `wev-skill-maintenance` | Format checked by unit tests and by `claude plugin validate`; never exercised in a live Claude Code session |
| Ten subagents | `agents/*.md`, generated from `agent-specs/` | Generation is implemented and tested; never exercised in a live session |
| Three hooks | `hooks/hooks.json` | Implemented and tested with unit and subprocess tests; never exercised in a live session |

The model may choose `wev-skill-maintenance` from its description for skill updates and
cross-repository standardization, or the user may invoke
`/wev-skills:wev-skill-maintenance`. Its frontmatter explicitly enables model invocation.
The plugin exposes the skill through `skills/wev-skill-maintenance/SKILL.md`; the engine
's `select-tools` command narrows operation tools and does not select skills. The external
`skill-repo` guide remains a separately installed dependency checked against the source pin.
Selection depends on task relevance and host settings; it is not guaranteed.
Selection loads guidance; it does not authorize maintenance or publication.
See the [host invocation reference](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill).

The hooks call `"${CLAUDE_PLUGIN_ROOT}/bin/wev"`, which starts with `#!/usr/bin/env python3`, so `python3` must be on the `PATH` that Claude Code sees, and it must be Python 3.14 or newer. The stock macOS `/usr/bin/python3` is 3.9 and, like any older interpreter, is not supported: with an older `python3` first on `PATH` the hooks exit quietly (one line on stderr) and check nothing. Check with `python3 --version`, and with `command -v python3` to see which one is used.

Whether a skill, a subagent or a hook behaves as these documents describe once Claude Code has loaded it has not been observed. The first live session is the first test; see "After publishing" in [mvp-status.md](../mvp-status.md).

## Add the marketplace and install

These routes install the plugin so that it is available in every session, instead of one.

Published route, from GitHub (status: documented only; not run, because it changes the Claude Code configuration of the machine):

```sh
claude plugin marketplace add wevertonjuscelino/wev-skills
claude plugin install wev-skills@wev-skills-marketplace
```

The same two steps inside a Claude Code session are `/plugin marketplace add wevertonjuscelino/wev-skills` and `/plugin install wev-skills@wev-skills-marketplace` (documented only).

Local route, from your clone:

```sh
claude plugin marketplace add "$WEV_HOME"
claude plugin install wev-skills@wev-skills-marketplace
```

The names come from `.claude-plugin/marketplace.json` (marketplace `wev-skills-marketplace`, plugin `wev-skills`, source `./`). Status (both routes): documented only. The commands and their options were read from `claude plugin --help`, `claude plugin marketplace add --help` and `claude plugin install --help`; they were not run, because they change the Claude Code configuration of the machine they run on.

Both commands accept `--scope user|project|local` (the default is user). The marketplace name and the plugin name are the same for both routes. The manifests use the relative plugin source `./`, so a marketplace added from the GitHub repository installs the plugin from that same repository.

## Update

| How you installed | Update |
|---|---|
| `--plugin-dir` | Change the files in the directory (or `git pull` in your clone) and start a new session |
| Marketplace | Refresh the marketplace, then update the plugin; Claude Code asks for a restart to apply it |

```sh
claude plugin marketplace update wev-skills-marketplace
claude plugin update wev-skills@wev-skills-marketplace
```

Status: documented only (from `claude plugin update --help`; not run). Run records in `.wev/` are not touched by an update. Resuming a run with a different version of the engine than the one that started it has not been tested; `state.json` carries a `schema_version`, and a state file written by an incompatible layout does not load (`state_version_unsupported`), so check the changelog before you do it.

## Uninstall

```sh
claude plugin uninstall wev-skills
claude plugin marketplace remove wev-skills-marketplace
```

Status: documented only (not run). Uninstalling the plugin leaves your `.wev/` directories and any agent files you exported into `.claude/agents/`. Delete those yourself if you want them gone: `.wev/` holds run records, approvals and the audit log of that project, and the per-user registry `active-runs.json` (see above) keeps entries for runs that were never finished. If you created the symlink above, remove it with `rm ~/.local/bin/wev`.

## Codex, Gemini CLI and OpenCode

Claude Code uses the plugin above. The other three harnesses get the same skills, the guard hooks and (Gemini CLI and OpenCode) the agents through `wev harness`. Status: implemented and tested with fake harness CLIs; not run against the real harnesses yet (e2e part). Nothing below was run against a real Codex, Gemini CLI or OpenCode. Claude Code asks you before it runs `harness install` and `harness uninstall`; `harness export` is not asked.

```sh
bin/wev harness export --target codex --out ./pkg
bin/wev harness install --target codex
bin/wev harness uninstall --target codex
```

- `export --target codex|gemini|opencode --out DIR [--wev PATH]` writes the package files and installs nothing. The result lists `files` and `skipped` with the reason: Codex subagents are skipped (format unknown), Gemini and OpenCode agents omit tools and model, and the Gemini hooks wrapper shape is inferred.
- `install --target ...` writes the files, registers them and records every path in a manifest at `$XDG_DATA_HOME/wev-skills/harness/<target>/manifest.json` (else `~/.local/share/wev-skills/harness/<target>/manifest.json`). Hook commands call this clone's `bin/wev` by absolute path (`--wev` overrides it), run by the interpreter that ran `install`; after a Python upgrade or a move of the interpreter or the clone, run `install` again. A failed reinstall leaves no previous install (the error says `previous_removed`); run `install` again. The result carries `next_steps`. A failure rolls back what was written, and running `install` twice does not duplicate entries.
- `uninstall --target ...` removes only what the manifest lists. It never edits a file wev did not create, except to remove the exact entries it added.

What you do yourself, per harness:

| Harness | wev does | You do |
|---|---|---|
| Codex | `codex plugin marketplace add` and `plugin add` | Trust the hooks once in Codex's own trust prompt. wev does not bypass that gate |
| Gemini CLI | `gemini extensions list -o json` (first install: refuses when a `wev-skills` extension that wev did not install exists) and `gemini extensions validate` | Run `gemini extensions link <package path>` yourself (it shows a security warning that wev never accepts for you), then check with `gemini extensions list -o json`. A strict `uninstall` exits 8 and keeps the files and the manifest if you never linked |
| OpenCode | Writes `plugins/wev-guard.js`, `skills/wev-*` and `agents/wev-*.md` into `$XDG_CONFIG_HOME/opencode` (else `~/.config/opencode`) | Nothing, there is no CLI to call. wev refuses to overwrite a file it did not create |

Limits you should know before relying on it (details in [SECURITY.md](../../SECURITY.md#other-harnesses)):

- On these three harnesses a policy `ask` of the guard becomes allow plus a warning (whether the agent sees it is unverified), so the guard's asks are reminders. These run with only that warning: `git push`, `rm -rf build`, globs, `$VAR` words, environment prefixes, `wev run start|finish`, `wev ... --config` and `wev jev ask|batch` (sends file content to the JEV service). A deny can be routed around with a variable or a glob (`D=.wev; rm -rf $D` was allowed with a warning). Internal failures are a deny.
- Human-operator commands (`approval grant|deny`, `approval request --reopen-denied`, `guard acknowledge`, `task reopen`, `specialists accept|retire|score`, `run adopt`) and `harness install|uninstall` are denied there: run them in your own terminal. The exported skills say so in their first paragraph.
- If the hook cannot run, Gemini CLI warns and the action proceeds, Codex reports a hook error, and OpenCode denies.
- OpenCode gets no session context: the run brief is not injected there.
- On Codex, a plugin of yours named `wev-skills` is not detected and `uninstall` would remove it.
- Codex does not pass the model-chosen workdir to its hook, so Codex commands are judged under the session directory.
- The OpenCode plugin is tested under node with a fake `wev`; it has never run inside OpenCode.

## Verify the installation

Each check says what it proves.

1. The CLI starts: `"$WEV_HOME/bin/wev" version`. It proves Python and the launcher work.
2. The shipped agents load: `"$WEV_HOME/bin/wev" agent list`. It proves the agent specs validate.
3. The configuration is valid: `"$WEV_HOME/bin/wev" config show`. It prints the effective configuration, including the state directory it will use.
4. The test suite passes: `make test` from `$WEV_HOME`. It proves the engine behaves as its tests say on your machine and Python version. The exact result lines of the last runs, with the date, are in [mvp-status.md](../mvp-status.md); the number of tests grows as tests are added. The 8 skipped tests are the local tmux integration tests, skipped because tmux was not installed there. Your numbers will differ once tests are added.
5. The plugin manifests are valid: `claude plugin validate "$WEV_HOME"`. It proves the manifests and layout parse. At the last run it passed with one warning, that a `CLAUDE.md` at the plugin root is not loaded as project context, and it fails under `--strict` for that warning only. The warning is about the repository's own project file and has no effect on the skills.
6. The hooks stay quiet outside a run: from any directory where no run is known, `echo '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp"}' | "$WEV_HOME/bin/wev" hook pre-tool-use` prints nothing and exits 0. It proves the hook entry point runs; it does not prove Claude Code calls it.

After a real session with the plugin, `claude plugin list` shows whether it is installed and enabled. Whether Claude Code then uses the skills as intended is not covered by any check here.

## Roll back

- Plugin loaded with `--plugin-dir`: start the session without the flag.
- Plugin installed from the marketplace: `claude plugin disable wev-skills` turns it off without removing it, and the uninstall commands above remove it.
- Source tree: in your clone, check out the previous tag or commit (`git checkout v1.0.0`, for example) and update the plugin as above. Every release has a tag `vX.0.0`; `git tag --list` shows them.
- Run state: `.wev/runs/<id>/` is plain files. A bad run can be left alone (it stops being the active run after `wev run finish`) or deleted by removing its directory. Nothing outside `.wev/` is written by the engine except the per-user run registry and the files a task changes.

## Third-party skills: install, daily check, update, rollback, freeze

`wev skills` manages three sources: `rea` (the npm package `rea-agents`, newest is its `dist-tags.latest`), `agent-skills` (GitHub releases of `addyosmani/agent-skills`) and `wev-skills` (GitHub releases of this repository). A GitHub source with no release uses the HEAD of its default branch, named by the first 12 characters of the sha. Registry requests go only to `api.github.com` and `registry.npmjs.org`; tarball downloads go only to `api.github.com`, `codeload.github.com` and `github.com`; redirects are checked against the same lists. The tarball URL is built from the repository and the tag, never taken from the registry's answer. A version must have the shape of its source: strict semver for `rea` (`1.2.3`, `1.2.3-rc.1`), a release tag `v1.2.3` or `1.2.3` for GitHub, 7 to 40 hex characters for a HEAD sha; `latest`, `next` or `1.x` are refused. Status: implemented and tested with a local fake registry, a fake npx and local tarballs; the real registries, downloads and the real rea server are not run in this change (e2e part).

```sh
wev skills list
wev skills check
wev skills install agent-skills
wev skills update agent-skills
wev skills rollback agent-skills
wev skills freeze agent-skills
wev skills freeze agent-skills --off
wev skills activate
wev skills deactivate
wev skills show rea
wev skills decline agent-skills
```

- **Where things live.** `$XDG_DATA_HOME/wev-skills/third-party/` (else `~/.local/share/wev-skills/third-party/`): `state.json`, `<source>/<version>/` for every installed version, `<source>/current` (a symlink to the active one) and `manifest.json` for activation links.
- **`install`** puts a version (`--version` picks one) beside the others without making it active, and prints the next step (`wev skills update SOURCE`). For `rea` it downloads nothing: it records `npm-ref.json` (after the registry confirms a `--version`) and `npx` fetches the package into npm's own cache during the health check. For `agent-skills` and `wev-skills` it downloads a tarball. **`update SOURCE`** installs the newest version, runs its health check and repoints `current` (atomically) only when the check passes; the previous version stays. `update --yes` offers a version you declined. `update` without a source skips frozen, declined and never-installed sources. Version names `current` and `*.tmp-*` are refused. After an update, only the active and the previous version stay on disk; when a health check fails, the failed version stays too, for inspection, but only the newest failed one per source.
- **`rollback`** swaps the active and the previous version, and records the version it left as declined, so the daily check does not offer it and `update` without `--yes` does not reinstall it. **`freeze`** stops checks and updates for a source (`--off` undoes it). **`decline`** records that the newest version was refused; only that exact version stops being offered, and any different version is offered again.
- **Daily check.** The Claude Code `SessionStart` `startup` hook runs `wev skills check --daily`. Status of the engine part: implemented and tested with a local fake registry, a fake npx and local tarballs. It prints nothing unless a day has passed since the last check, has a 10 second wall-clock budget, fails silently and injects one short paragraph when a newer version exists. A failure does not advance the daily marker; when only some sources fail, the sources that succeeded still save their `last_check` and `latest_seen`, and a budget timeout saves nothing. Frozen sources are skipped, and a source you never installed is not offered; run `wev skills update SOURCE` for it, which installs, health-checks and activates its first version (`install` alone leaves it inactive). The model asking you once (yes runs `wev skills update SOURCE`, no runs `wev skills decline SOURCE`) is an instruction to the model: documented only. The daily check is wired only for Claude Code so far.
- **Health check before the switch.** `rea`: `npx -y rea-agents@<version> mcp` is started without a shell, with a reduced environment, 60 seconds of wall clock and the whole process group killed afterwards; it must answer `initialize` and `tools/list` with at least one tool. `agent-skills`: every `skills/*/SKILL.md` has a `name` equal to its directory and a description. `wev-skills`: `bin/wev version` of the new directory must print the installed version when that is a release tag (`v` and a digit first); for a default-branch HEAD install, named by a sha, it only has to run and print a version made of numbers and dots. This catches a broken update, not a malicious one.
- **`activate`** (agent-skills only) links `<root>/<name>` to `current/skills/<name>` in `~/.claude/skills` and `~/.agents/skills` when those directories exist (Codex, OpenCode and Gemini CLI read the second one, per the notes in `docs/research/`). Only skill directories with a `SKILL.md` are linked. It refuses to replace anything it did not create, including a file you put where a wev link was and a wev link you repointed elsewhere. `deactivate` removes only the links the manifest lists that still point where wev made them. Once you have activated, `update` and `rollback` of `agent-skills` re-run the activation: links of dropped skills go and new skills are linked; an entry that is not wev's is reported in the result's `activation` (exit 8 for `update`, 5 for `rollback`) and left alone.
- **Approvals.** Claude Code asks before `skills install|update|rollback|freeze|activate|deactivate`; `list`, `check`, `decline` and `show` are not asked. On Codex, Gemini CLI and OpenCode these six are denied: run them in your own terminal.
- **Limits.** A wev self-update installs and health-checks the new directory only; a wev-skills update does not switch the running plugin: the installer does, and `skills update` does not. `check` and `update` read the state again just before saving and merge in only what the check saw, so a `freeze` or an update saved meanwhile is kept. The health check reads at most 32 MiB per reply line from the MCP server (the real server's `tools/list` is about 3.2 MB) and refuses a longer one. The health-check child keeps only `PATH`, `HOME`, `LANG`, `LC_*`, `XDG_*`, `npm_config_*` and `NODE_*` from your environment. With `HOME` kept, npm reads `~/.npmrc`, `npm_config_*` may carry npm tokens, and `NODE_OPTIONS` can inject code into the child. A declined source still makes its registry call before it is skipped. The real registries, downloads and the real rea server are not run in this change (e2e part). See [SECURITY.md](../../SECURITY.md#third-party-skill-updates).

## rea: modes, image, registration

`rea` (npm `rea-agents`, installed by `wev skills install rea`) is an MCP server of reverse-engineering tools. wev starts it for the harness through `wev rea serve`, in one of two modes. Status: implemented and tested with fake `npx` and `docker` executables (unit tests); the real rea server, the real container build and the real harness loaders are not run in this change (e2e part). The `wev-reverse` skill that uses the tools is documented only.

```sh
bin/wev rea status
bin/wev rea mode isolated
bin/wev rea build-image
bin/wev rea serve --dry-run
```

- **`status`** prints the mode (and whether it is the default or came from your choice), the pinned version, the image tag, whether Docker was found and whether the image is present, with warnings.
- **`mode isolated|direct`** saves your choice in `rea.json` under `~/.config/wev-skills` (`$XDG_CONFIG_HOME` is honored). Without a saved choice the mode is `isolated` when Docker is found and `direct` otherwise.
- **Isolated mode** runs `docker run` on the image `wev-rea:<version>`, as your uid:gid, with the network on, the working directory mounted read-only at its own path and a wev-owned writable directory mounted at `/opt/rea-home` (rea's home). Static and web-bundle analysis work; the runtime tools (Frida, adb, browser and Electron capture, debuggers) are unavailable in the container.
- **Direct mode** runs `npx -y rea-agents@<version> mcp` on the host, with your permissions and no container.
- **`build-image [--version V]`** builds `wev-rea:<version>` from `docker/rea/Dockerfile` (base image `node:24-slim`, then `npm install -g rea-agents@<version>`). It needs Docker and the network. The pinned version is the one `wev skills` activated, so run `wev skills install rea` first.
- **`serve --dry-run`** prints the command that would start the server, as JSON, without starting it.

Registration, per harness:

| Harness | How `rea` is registered |
|---|---|
| Claude Code | The plugin's `.mcp.json` runs `${CLAUDE_PLUGIN_ROOT}/bin/wev rea serve`; nothing to do |
| Gemini CLI | `wev harness install --target gemini` writes `mcpServers.rea` in the extension's `gemini-extension.json` |
| OpenCode | `wev harness install --target opencode` writes `mcp.rea` in `opencode.json` under the OpenCode config directory. It refuses to run when an `mcp.rea` entry exists that wev did not write, or when `opencode.json` is a symlink; it keeps every other key, re-indents the file to 2 spaces and keeps its file mode |
| Codex | wev does not register it. Run it yourself: `codex mcp add rea -- <python> <path to bin/wev> rea serve` |

Limits: `rea mode` and `rea build-image` are asked about in Claude Code and denied on the other harnesses, so run them in your own terminal. See [SECURITY.md](../../SECURITY.md#rea-reverse-engineering-server) before pointing rea at a binary you do not trust.

## What needs network access

| Step | Network |
|---|---|
| Running the CLI, the tests, the evaluation harness, the hooks | None |
| Cloning the repository | Yes |
| `uvx ruff` and `uvx mypy` (what `make lint` uses without installed tools) | Yes, the first time, to fetch the tools. Cached afterwards |
| `pip install` | Yes, if you choose it |
| Claude Code itself and the models it uses | Yes, outside this project |
| `wev specialists score` (unattended `claude -p` runs) | Yes: the `claude` CLI calls its model provider |
| The JEV decision provider, if you enable it | Yes: sends the task objective (classification) or a task's title, objective and acceptance criteria (tool selection) to a third party (see the [configuration guide](configuration-and-providers.md)) |
| `wev skills check`, `install`, `update` (and the daily check at session start) | Yes: registry or GitHub requests (5 s per socket operation), tarball downloads (120 s for the whole download), a health check (60 s); one registry request of `check`, `install` or `update` stops at 30 s of wall clock, and the daily check stops at 10 s in total |
| The remote module | SSH to hosts you configured |
| GitHub Actions workflows | Yes, when run on GitHub; none has completed a run |

## End-to-end tests

`make e2e` runs the real installer, the real network and the real third-party skills, which `make test` never does. List the scenarios and what each spends, and answer `yes` when asked:

```sh
make e2e
WEV_E2E_CONFIRM=yes make e2e E2E="macos-core"   # no terminal: the variable answers for you
```

Without a terminal and without `WEV_E2E_CONFIRM=yes` nothing runs (exit 2). The runner uses the real network (the npm registry and GitHub releases) and never your real `HOME`: every scenario installs with `install.sh --source <this clone>` into a temporary `HOME` and `XDG_*` tree that it removes afterwards. It writes `evals/reports/e2e-<date>.md`, one section per scenario with one row per check (passed, failed, or skipped with the reason), and exits 1 if any check failed. The report is committed; the latest is [e2e-2026-10-22.md](../../evals/reports/e2e-2026-10-22.md).

| Scenario | Where | Spends | Status in the latest report |
|---|---|---|---|
| `macos-core` | this Mac, isolated `HOME` | network only | passed, 13 of 13 checks. macOS: tested with isolated HOME, not a clean machine |
| `linux-core` | blank container from `docker/e2e/Dockerfile` | network and one `docker build` (minutes) | skipped: Docker daemon not running. Linux: blank container, not yet run |
| `macos-isolated` | this Mac, Docker | network and one `docker build` (minutes) | skipped: Docker daemon not running |
| `claude` | isolated `HOME` and your Claude login | Claude Code account and tokens | not run; implemented but untested: never run against a real harness |
| `codex` | isolated `HOME` and your Codex login | Codex account and tokens | not run; implemented but untested: never run against a real harness |
| `gemini`, `opencode` | this Mac | you install the CLI first | not run; implemented but untested: never run against a real harness |
| `jev` | isolated `HOME` with a key you type | one `jev ask` call | not run; implemented but untested |
| `update-daily` | this Mac | network | not run; implemented but untested |

The harness, `jev` and `update-daily` scenarios are written but have never been executed, and each prints its own cost line before the confirmation. `macos-core` covers the install, a re-run, the update path (install an older `rea`, roll back, update), a broken install that must leave the active version unchanged, `rea serve` answering `initialize` and `tools/list`, and `install.sh --uninstall --purge`. The roll back step seeds the state, because the CLI cannot make an older release active; the report says so.

The documentation says "compatible with" a harness only after that harness's scenario passed. No harness scenario has run, so the harness sections keep "not run against the real harness". The first run also found three installer problems, fixed on their own branches (see the [changelog](../../CHANGELOG.md)).

## Running the tests and lint

```sh
make test   # unittest discover, no network, no model
make lint   # ruff check, ruff format --check, mypy strict on the package
```

`make lint` uses `ruff` and `mypy` from the `PATH`, otherwise runs them through `uvx`, otherwise prints that it skipped. The tools are not runtime dependencies.
