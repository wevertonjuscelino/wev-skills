# Installation guide

Portuguese version: [installation.pt-BR.md](installation.pt-BR.md).

wev-skills was first published on 2026-10-13 (v1.0.0, announced then as 0.1.0 and renumbered on 2026-10-15) at <https://github.com/wevertonjuscelino/wev-skills>. There is no package on PyPI and no listing in an official marketplace. Every route below starts from a clone of that repository or from the repository as a Claude Code marketplace source. Neither route has been run: cloning, the published marketplace route and the install commands are documented only, and the plugin has never been loaded in a live Claude Code session.

Status labels used here follow the project convention: implemented and tested, implemented but untested, simulated with mocks, documented only, blocked. See the [glossary](../glossary.md).

## Requirements

| Requirement | Needed for | Notes |
|---|---|---|
| Python 3.14 or newer | The engine and its tests | Standard library only; there is nothing to `pip install`. Older interpreters, including the stock macOS `/usr/bin/python3` (3.9), are not supported. The suite last ran on Python 3.14.7 (see [mvp-status.md](../mvp-status.md)) |
| macOS or Linux | The state store | It uses POSIX file locks. Windows is not supported |
| `git` | `wev run start`, `wev run resume`, `wev state drift` | The engine snapshots the repository state. Outside a git repository the runs still work, with less to compare |
| Claude Code | The plugin: skills, subagents, hooks | Only for the plugin steps. The CLI works without it. Tested with Claude Code 2.1.296 for `claude plugin validate`; nothing else was run through Claude Code |
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
  "version": "5.0.0"
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

## What needs network access

| Step | Network |
|---|---|
| Running the CLI, the tests, the evaluation harness, the hooks | None |
| Cloning the repository | Yes |
| `uvx ruff` and `uvx mypy` (what `make lint` uses without installed tools) | Yes, the first time, to fetch the tools. Cached afterwards |
| `pip install` | Yes, if you choose it |
| Claude Code itself and the models it uses | Yes, outside this project |
| The JEV decision provider, if you enable it | Yes: sends the task objective (classification) or a task's title, objective and acceptance criteria (tool selection) to a third party (see the [configuration guide](configuration-and-providers.md)) |
| The remote module | SSH to hosts you configured |
| GitHub Actions workflows | Yes, when run on GitHub; none has completed a run |

## Running the tests and lint

```sh
make test   # unittest discover, no network, no model
make lint   # ruff check, ruff format --check, mypy strict on the package
```

`make lint` uses `ruff` and `mypy` from the `PATH`, otherwise runs them through `uvx`, otherwise prints that it skipped. The tools are not runtime dependencies.
