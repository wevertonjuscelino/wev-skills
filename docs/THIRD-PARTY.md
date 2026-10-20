# Third-party provenance

Portuguese version: [THIRD-PARTY.pt-BR.md](THIRD-PARTY.pt-BR.md).

This file records where third-party material came from and how it is used in wev-skills.

wev-skills is not affiliated with, endorsed by, or sponsored by Anthropic, Addy Osmani, or the authors of the paper cited below. Names are used only to identify sources.

## Reused code

None. No third-party source file has been copied into this repository.

## Adapted material

| Source | Version | License | What was adapted | Where it lives |
|---|---|---|---|---|
| andrej-karpathy-skills, `CLAUDE.md`, https://github.com/multica-ai/andrej-karpathy-skills, a copy of the project by forrestchang, https://github.com/forrestchang/andrej-karpathy-skills | Copy at commit `2c606141936f1eeef17fa3043a72095b4765b9c2`, checked 2026-10-13 | The README says "License: MIT" and the plugin manifest says `"license": "MIT"` with author `forrestchang`. There is no LICENSE file and no copyright line, and the GitHub API reports no detected license. The templates cite the MIT statement in the README and nothing stronger | The four-section structure (Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution) and the substance of each point, plus the tradeoff note and the closing "working if" line, rewritten in this project's own wording and translated to Brazilian Portuguese. Section 5, "Evidence before claims", is original to wev-skills. The upstream describes the guidelines as derived from Andrej Karpathy's public observations on LLM coding pitfalls | `src/wev_skills/adapters/claude_code/guidelines/guidelines.en.md` and `guidelines.pt-BR.md`, inserted into users' `CLAUDE.md` files by `wev claude-md`. Rationale and attribution in `skills/wev-claude-md/references/guidelines-source.md` |
| `create-readme` skill, `skills/create-readme/SKILL.md`, https://github.com/github/awesome-copilot | Commit `156736fb63e965b2f547a1460f3b5972c46e6b24`, consulted 2026-10-13 | MIT. "Copyright GitHub, Inc." (from the repository's LICENSE file) | The ideas of the skill's rules: review the whole project before writing, a concise and appealing README, no sections that duplicate dedicated files (license, contributing, changelog), GitHub Flavored Markdown with GitHub admonition syntax, and the project logo in the header. Rewritten in this project's own wording and extended with rules that are original to wev-skills (no emoji, English and Brazilian Portuguese twins, credits last, evidence labels, a deterministic checker). The example READMEs the skill points at were not fetched | `skills/wev-readme/SKILL.md`, enforced by `wev readme check` (`src/wev_skills/adapters/claude_code/readme_check.py`). Attribution in `skills/wev-readme/references/readme-standard-source.md` |

The text of each entry is an adaptation, not a copy. No affiliation with or endorsement by forrestchang, multica-ai, Andrej Karpathy, GitHub, Inc. or the authors of awesome-copilot is implied.

## Architectural inspiration

Ideas and conventions studied, not copied. Details are in [research/agent-skills-reference.md](research/agent-skills-reference.md), [research/harness-design-paper.md](research/harness-design-paper.md) and [research/sources.md](research/sources.md).

| Source | Version | License | How it informs wev-skills |
|---|---|---|---|
| addyosmani/agent-skills, https://github.com/addyosmani/agent-skills | Commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe` (2026-10-10) | MIT. "Copyright (c) 2025 Addy Osmani" | Compatible conventions for `SKILL.md`, persona-style agents, plugin manifests and eval tiers. Architectural inspiration only |
| "An Empirical Study of Harness Design for Coding Agents", arXiv:2609.20804, https://arxiv.org/abs/2609.20804 | v1, submitted 17 Sep 2026 | Not checked. The arXiv listing was not examined for a reuse license, and no text or figure from the paper is reproduced | Source of testable hypotheses about context management, planning and tool interface. Findings are treated as hypotheses, not guarantees |
| Agent Skills specification, https://agentskills.io/specification | Not pinned; consulted by a research pass on 2026-10-13 | Not checked | The skill file format that wev-skills's skills follow |

Official Claude Code documentation pages (see [research/sources.md](research/sources.md)) were consulted to learn interfaces. No text from them is reproduced.

## Rule for adding third-party files

Before any third-party file, snippet, schema, prompt or dataset is added to this repository, the contributor must:

1. Identify its license and confirm it is compatible with this project's license, the PolyForm Noncommercial License 1.0.0 (see [LICENSE](../LICENSE)). Material under a permissive license such as MIT is compatible when its notices are kept. If the license is missing, unclear or incompatible, do not add the file.
2. Preserve the original copyright and license notices in the file or alongside it, and add a `NOTICE` entry when the license requires one.
3. Record it in this file in the same change: source URL, commit or version, license, copyright line, the files affected, and whether the use is reuse, adaptation (what changed) or inspiration.
4. Never imply affiliation with or endorsement by the source's author or organization.

A change that adds third-party material without a matching entry here should not be merged.

## External maintenance reference

Netresearch DTT GmbH's [skill-repo-skill](https://github.com/netresearch/skill-repo-skill),
version 2.4.0 at commit `42a5e85798a8cdfda2866afb0de9aadb04e187f3`, consulted 2026-10-13,
is an external dependency for repository-structure guidance. Copyright (c) 2025-2026
Netresearch DTT GmbH. Content: CC-BY-SA-4.0; scripts/configuration: MIT. Its files are
installed separately and are not redistributed in this repository. The original
`skills/wev-skill-maintenance/`, licensed with the rest of wev-skills, coordinates review and local exceptions; it records provenance
in `references/upstream.json` and links to the guide without copying its instructions or scripts.
The project's licensing, branding, engine dependencies and CI are not migrated by this reference.
No affiliation or endorsement is implied.
