# README standard: source and attribution

## Adapted from

- Source: the `create-readme` skill of https://github.com/github/awesome-copilot.
- Path in that repository: `skills/create-readme/SKILL.md`.
- Commit: `156736fb63e965b2f547a1460f3b5972c46e6b24`, consulted on 2026-10-13.
- License: MIT, "Copyright GitHub, Inc.", from the repository's LICENSE file.

## What was adapted

The reference skill asks for a README that is comprehensive, well structured, appealing and easy to read, written after reviewing the whole project. It asks for concision and a restrained use of emoji, for no sections that duplicate dedicated files (license, contributing, changelog), for GitHub Flavored Markdown with GitHub admonition syntax where appropriate, and for the project logo or icon in the header when one exists.

Those ideas are the starting point of `SKILL.md` in this directory. The wording is this project's own: nothing was copied, the structure and the rules are rewritten, and the example READMEs the reference points at were not fetched or used. The "review the project first", "concise", "no dedicated-file sections", "admonitions" and "logo in the header" rules are adapted; the others are listed below.

## Rules that are this project's own

- No emoji and no emoji shortcodes at all, where the reference only says not to overuse them.
- Two files, `README.md` in English and `README.pt-BR.md` in Brazilian Portuguese, with the same structure, identical code blocks and links to each other.
- Credits as the last second-level section, naming each project, paper and specification with link, author and license, and ending with a statement of independence.
- Evidence labels on every capability statement, and no claim without evidence.
- No performance or improvement claims without measurements.
- No repository URL, badge or package name for something that does not exist.
- Every command and output in the README is run before it is written.
- The deterministic checker (`wev readme check`) and its rule names.

## What cannot be claimed

The reference skill and this standard aim at a README that is easy to read. No measurement has been made of whether they achieve it, so do not state any improvement figure. wev-skills is not affiliated with or endorsed by GitHub, Inc. or the authors of awesome-copilot. The provenance entry is in `docs/THIRD-PARTY.md` of the wev-skills repository.
