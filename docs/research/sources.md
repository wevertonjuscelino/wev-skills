# Sources

All entries accessed 2026-10-13. Not affiliated with or endorsed by any source listed. Provenance of reused material is in [../THIRD-PARTY.md](../THIRD-PARTY.md); nothing has been reused.

## Read directly for the research records

| Source | URL | Version | Used for |
|---|---|---|---|
| "An Empirical Study of Harness Design for Coding Agents" (Fan, Zhang, Ma, Hu, Wang, Song, Liu, Zamani, Wang) | https://arxiv.org/abs/2609.20804 (PDF and HTML copies downloaded; the DOI shown on the arXiv page is https://doi.org/10.48550/arXiv.2609.20804 and is listed there as pending registration) | arXiv v1, submitted 17 Sep 2026, 43 pages per the arXiv listing | [harness-design-paper.md](harness-design-paper.md), [hypotheses.md](hypotheses.md). Main text read in full; appendix read only in part |
| addyosmani/agent-skills | https://github.com/addyosmani/agent-skills | Commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe`, 2026-10-10; plugin version 0.6.12 in its manifests; MIT, "Copyright (c) 2025 Addy Osmani" | [agent-skills-reference.md](agent-skills-reference.md). Selected files read; see that file for the list |

The downloaded copies of the paper and the repository live outside this repository (a session scratch directory) and are not committed.

## Official documentation consulted by a research pass

Each page below was consulted by a research pass on 2026-10-13; not re-read for this file. Statements in the wev-skills documents that depend on them should be re-checked against the live page before being relied on, and no platform compatibility is claimed without an adapter and an integration test.

| Page | URL | Informs |
|---|---|---|
| Agent Skills specification | https://agentskills.io/specification | `SKILL.md` format, frontmatter keys |
| Claude Code skills | https://code.claude.com/docs/en/skills.md | Skills in Claude Code |
| Plugin manifest reference | https://code.claude.com/docs/en/plugins/manifest-reference.md | Plugin manifest fields |
| Plugin marketplace reference | https://code.claude.com/docs/en/plugins/marketplace-reference.md | Marketplace manifest |
| Plugin CLI reference | https://code.claude.com/docs/en/plugins/cli-reference.md | Plugin commands |
| Subagents | https://code.claude.com/docs/en/sub-agents.md | Exporting agent specs to subagent files |
| Hooks | https://code.claude.com/docs/en/hooks | Hook events and configuration |
| Headless mode | https://code.claude.com/docs/en/headless.md | Non-interactive runs |
| Context window | https://code.claude.com/docs/en/context-window.md | Claude Code context behavior |

## Referenced, not exercised

| Source | URL | Note |
|---|---|---|
| tmux | https://github.com/tmux/tmux | Referenced for the optional remote module. tmux was not installed on the development machine, so its behavior was not exercised locally. Consulted by a research pass on 2026-10-13; not re-read for this file |

## Cited by sources but not read

- "WikiSkill", arXiv:2608.27454, cited in `docs/skill-anatomy.md` of agent-skills. Not read.
- The works cited in the harness paper (SWE-Bench, Terminal-Bench, Nemotron-3, Mistral Medium 3.5, and others). Not read; nothing in the wev-skills documents depends on them beyond what the paper states.
