---
name: wev-claude-md
description: "Creates or improves a project's CLAUDE.md: inserts a managed block of behavioral guidelines with the wev claude-md commands, then fills the project sections (commands, architecture, project rules) by reading the repository. Use when a user wants to create, review, trim or update a CLAUDE.md, or asks for the Karpathy-style guidelines in a project. Em português: criar, revisar e atualizar o CLAUDE.md de um projeto."
argument-hint: "<project directory, optional>"
---

# wev-claude-md

Request: $ARGUMENTS

A project's `CLAUDE.md` is loaded into context at the start of every session, so every line has a cost. This skill uses the `claude-md` commands for the part a tool can do reliably (a managed block of behavioral guidelines, detected check commands, a report of what is missing) and leaves the part that needs judgment (what is true about this repository) to you.

Answer the user in the language they write; when they write Portuguese, pass `--lang pt-BR` to the commands that take it, so the block and the section headings come out in Portuguese. Commands use `"${CLAUDE_PLUGIN_ROOT}/bin/wev"`. Outside a plugin the same commands work as `wev` when it is on PATH, or as `python3 -m wev_skills` with the package importable.

## What the tool does and does not do

- The guidelines live between `<!-- wev-skills:guidelines:start v1 -->` and `<!-- wev-skills:guidelines:end -->`. Everything outside those markers belongs to the author. The tool never changes it, never reorders it and never rewrites it.
- `init` on a missing file creates a header, the block and a skeleton with the headings Commands, Architecture and Project rules. Commands is pre-filled with the check commands found in `Makefile`, `package.json`, `pyproject.toml`, `Cargo.toml` or `go.mod`, each with the file it came from. Nothing is executed. Those are suggestions: confirm each one before keeping it.
- `init` on an existing file inserts only the block (after the `# CLAUDE.md` header, or at the top) and changes nothing else. If the block is already there, `init` behaves as `update`.
- `update` replaces only the text between the markers with the current template. Use it after the tool is upgraded, or to switch the block's language.
- Duplicate or unbalanced markers make the tool refuse to modify the file. Tell the user to fix the markers by hand; do not try to repair them yourself.
- The tool writes only a file named exactly `CLAUDE.md`, inside the repository, and refuses symbolic links.

## Workflow

1. Look first: `"${CLAUDE_PLUGIN_ROOT}/bin/wev" claude-md check` prints a JSON report and exits 2 when something is missing or stale (`ok` false). The report lists `sections_missing`, `sections_placeholder`, `undocumented_commands`, `lines`, `line_warning` and `marker_error`. It works on a missing file too.
2. Preview, always: `"${CLAUDE_PLUGIN_ROOT}/bin/wev" claude-md init --dry-run` (or `update --dry-run`) prints the diff and writes nothing. Show the diff to the user and say what it will and will not touch.
3. Write it: run the same command without `--dry-run`. Add `--dir <path>` for the directory that holds `CLAUDE.md` (default: the current directory); `--lang en|pt-BR` sets the block's language for `init` and `update`.
4. Fill the project sections from the repository itself (next section). Edit the file surgically with your editing tool; never rewrite sections the user wrote unless they ask.
5. Run `"${CLAUDE_PLUGIN_ROOT}/bin/wev" claude-md check` again and report what it says, including anything still a placeholder and any line-count warning. Do not call the file finished while the report says otherwise.

To read the block without touching any file: `"${CLAUDE_PLUGIN_ROOT}/bin/wev" claude-md show`. The reasoning behind the guidelines and their attribution are in [references/guidelines-source.md](references/guidelines-source.md).

## Filling the project sections

Read the repository before writing. Every statement must come from a file you opened or a command whose output you saw.

- Commands: the real build, lint and test commands, including how to run a single test or a single test file. Check them against `Makefile`, `package.json` scripts, CI configuration and the contributing guide. Drop any detected command that does not exist or does not work as listed.
- Architecture: the big picture that takes reading several files to understand: the main flow, how the parts depend on each other, which boundaries must hold. A short paragraph or a few bullets.
- Project rules: rules specific to this project that a newcomer would break by accident: required checks before a commit, files that must not be edited, naming or language conventions, approval requirements.

Leave out:

- Generic advice that applies to any project ("write clean code", "add tests").
- Exhaustive file or directory listings; the model can list them itself.
- Anything you did not verify. If you cannot tell, leave the placeholder comment or ask the user. Never invent a command, a path or a rule.
- Text that duplicates what the guidelines block already says.

Keep the file short. `check` warns above 200 lines; if the file is longer, propose moving detail into separate documents and pointing to them, and wait for the user's decision before cutting anything they wrote.

## Reporting

The guidelines aim to reduce common mistakes and trade speed for caution. Do not claim they improve results by any amount; nothing here has been measured. When you finish, say which files changed, show the final `check` report, and state which commands you confirmed by running them and which you only read from configuration.
