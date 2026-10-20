---
name: wev-readme
description: "Writes or updates a project's README.md and its Brazilian Portuguese twin README.pt-BR.md to this project's README standard, then verifies them with the wev readme check command. Use when a user wants to create, rewrite, review or update a README, or asks whether a README meets the standard. Em português: criar, revisar e atualizar o README e o README.pt-BR do projeto."
argument-hint: "<project directory or what to change, optional>"
---

# wev-readme

Request: $ARGUMENTS

A README is the first thing a reader sees and the only part of the documentation most readers open. This skill is the README standard of this project: a short list of rules, a fixed structure, and a checker that enforces the rules a program can enforce. The rules that need judgment (is the sentence true, is the example real) are yours.

Answer the user in the language they write. When they write Portuguese, write the Portuguese README first or in the same pass and pass `--lang pt-BR` to the checker so its messages come out in Portuguese. Commands use `"${CLAUDE_PLUGIN_ROOT}/bin/wev"`. Outside a plugin the same commands work as `wev` when it is on PATH, or as `python3 -m wev_skills` with the package importable. The origin and attribution of the standard are in [references/readme-standard-source.md](references/readme-standard-source.md).

**Non-negotiable rule: follow YAGNI and prefer the solution with less code.** It applies to everything you write or change through this skill.

## Rules

1. Review the whole project before you write a word: the source tree, the manifests, the build and test commands, the existing documentation, the git state. A README written from the old README alone repeats its mistakes.
2. Every command, path, flag and number in the README comes from the repository or from a command you ran. Run what you document, in a temporary directory outside the repository when the command writes files, and paste the real output. Never write a command you did not execute. Commands that need a human at a terminal or a network you do not have are shown as the reader's step and labelled as not run.
3. Every statement about what the project can do carries one evidence label: implemented and tested; implemented but untested; simulated with mocks; documented only; blocked. Nothing is claimed without evidence. Never state a speed, quality or improvement figure that was not measured, and say how it was measured when one exists.
4. Be concise and appealing: short paragraphs, tables for facts that have columns, code blocks for commands. Plain statements, no marketing language, no superlatives.
5. Use no emoji and no emoji shortcodes.
6. Use GitHub admonitions (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`, `> [!WARNING]`, `> [!CAUTION]`) sparingly, for what a reader must not miss: pre-release status, a security limit, a result that must not be over-read. The marker sits alone on the first line of the quote, the text on the following quoted lines. Do not use any other kind.
7. Leave out the sections that have their own files: license, contributing, changelog, code of conduct and security. Give them one or two lines inside another section (for example "Project files") that link to `LICENSE`, `CONTRIBUTING.md`, `CHANGELOG.md`, `CODE_OF_CONDUCT.md` and `SECURITY.md`. The checker rejects headings with those names in either language.
8. Do not invent a repository URL, badge, package name, registry entry or release. If the project is not published, say so and write no URL, no badge and no clone command for it.
9. Use the project logo or icon in the header when one exists (`logo.*` or `icon.*` at the root or under `assets/`, `docs/assets/` or `.github/`). Do not create one, and do not mention a logo when none exists.
10. Write for the reader who knows nothing about the project, and keep detail in `docs/`: link to the guide instead of copying it.

## Structure

Follow this order. Drop a part only when it has nothing true to say.

1. Optional logo block, then the title (`# name`, the only first-level heading) and one sentence that says what the project is and who it is for.
2. A line linking the twin file (`README.pt-BR.md` or `README.md`), within the first lines.
3. Status: pre-release or released, an admonition for what a reader must not miss, and a table of capabilities with their evidence label and caveats.
4. Requirements.
5. Quick start with a real transcript from a run you made, and the exact commands.
6. A tour of the main features, each linking to its guide.
7. How to verify: the test and lint commands, with the summary line you observed and the date.
8. Limitations: what it does not do, stated plainly.
9. Roadmap: future work only, marked as not implemented.
10. Credits, always the last second-level section: each project, paper or specification the work is based on, with link, author and license, and a closing sentence saying the project is independent and not affiliated with them. Verify each license in the source before you write it; write "not checked" when you did not.

## Two languages

`README.md` is English and `README.pt-BR.md` is Brazilian Portuguese. They have the same structure: the same number of second-level headings in the same order, the same tables and admonitions, and code blocks that are identical character for character (so keep comments out of code blocks, or keep them in English in both). Edit both files in the same change. They link to each other in their first lines. The Credits heading is `Credits` in English and `Créditos` in Portuguese. Translate the prose; do not translate commands, paths, identifiers or the output of the program.

## Workflow

1. Look first: `"${CLAUDE_PLUGIN_ROOT}/bin/wev" readme check` prints a JSON report with the rule, file, line and message of every finding and exits 2 when there are findings. It never writes anything.
2. Read the existing README files and the project, as in rule 1. List the facts that need re-verifying.
3. Verify facts and run the quick start in a temporary directory; keep the output.
4. When a README already exists, edit it surgically: change only what is wrong or missing, keep the author's wording where it is still true, and do not reorder sections for taste. Write from scratch only when the user asks or when nothing usable exists.
5. Write both languages in the same pass.
6. Finish by running `"${CLAUDE_PLUGIN_ROOT}/bin/wev" readme check` and, in a repository that has them, the documentation tests (`python3 -m unittest tests.unit.test_docs`). Report both results as they are. Do not call the README finished while the checker reports a finding; if a finding is wrong, say so instead of working around it.

## What the checker does and does not do

It checks, per file: one first-level heading and it comes first (an image or logo block may precede it); no heading named after a dedicated file; no emoji or shortcode; every relative link and image exists inside the repository (absolute paths and anything that leaves the repository are findings, symbolic links are resolved first); admonitions use only the five kinds and the correct syntax; fenced code blocks are closed and declare a language; no placeholder text (TODO, TBD, lorem ipsum, "your-org", example.com addresses); a warning when the file is long. For the pair: the same number of second-level headings, links to each other in the first lines, identical code blocks. The Credits heading must be the last second-level heading, and a logo that exists must appear in the header. Options: `--dir <path>` for a subdirectory, `--no-twin` to skip the comparison, `--credits-last` to require a Credits section (`--no-credits-last` to skip the check).

It cannot tell whether a sentence is true, whether a command works or whether a label is earned. Those are the checks you do by hand, and the report to the user says which you did.

## Reporting

Say which files changed, the checker result, the test result, which commands you ran and which you only read, and anything you could not verify. Do not describe the README as better than before by any measure; nothing here has been measured.
