# Reference: addyosmani/agent-skills

Portuguese version: [agent-skills-reference.pt-BR.md](agent-skills-reference.pt-BR.md).
Source: https://github.com/addyosmani/agent-skills at commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe` (commit date 2026-10-10), MIT license, "Copyright (c) 2025 Addy Osmani" (`LICENSE`). Consulted 2026-10-13. Paths below are relative to that repository.

**As of this writing no file from that repository has been copied into wev-skills.** The relationship is architectural inspiration and compatible conventions. wev-skills is not affiliated with or endorsed by its author. Provenance is tracked in [../THIRD-PARTY.md](../THIRD-PARTY.md).

What was read: `docs/skill-anatomy.md`, `CONTRIBUTING.md`, `evals/README.md`, `docs/agents.md`, `agents/code-reviewer.md` (and the frontmatter of the other three personas), `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, root `plugin.json`, the header and configuration of `scripts/lib/skill-lint.js`, the headers of `scripts/validate-commands.js` and `scripts/validate-artifact-paths.js`, the opening of `scripts/validate-versions.js`, and one skill (`skills/test-driven-development/SKILL.md`). Not read: `scripts/validate-skills.js`, `scripts/validate-reference-links.js`, `scripts/run-evals.js`, the hooks, and the other 24 skills. Anything about those files below is taken from references to them in the files that were read.

## What was learned

**SKILL.md conventions** (`docs/skill-anatomy.md`, `scripts/lib/skill-lint.js`).
- Each skill is a directory `skills/<name>/` with a required `SKILL.md`; `scripts/` and `references/` are optional and should not be created empty.
- Frontmatter: `name` and `description` are required. Allowed top-level keys are exactly `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` (`SPEC_FRONTMATTER_KEYS` in `skill-lint.js`); vendor keys such as `model` or `max_turns` go under `metadata` or in a per-agent adapter file. The linter treats other keys as errors.
- `name` must equal the directory name and be lowercase-hyphenated (`KEBAB_CASE` in `skill-lint.js`).
- `description` is at most 1024 characters (`MAX_DESCRIPTION_LENGTH`). It states what the skill does in the third person, then a "Use when ..." trigger. The linter accepts "use when" and "use before/after/during" and rejects negated forms. The anatomy document says not to summarize the workflow in the description, because the agent may follow the summary instead of reading the skill.
- Body sections: Overview, When to Use, a core process, Common Rationalizations, Red Flags, Verification. The anatomy document calls the layout recommended; the linter lists five of them (`REQUIRED_SECTIONS`: Overview, When to Use, Common Rationalizations, Red Flags, Verification) as required, with a documented exemption table.
- Context economy: `SKILL.md` under 500 lines (a linter warning, `MAX_SKILL_LINES`), progressive disclosure, references one level deep, support files only when content exceeds about 100 lines.
- Shared checklists live in a repo-root `references/` directory. The document itself notes that a per-skill install loses them (issue #361 in that repository).
- "Write the Procedure, Not the Workaround": a step that needs a model name or one tool's private name to justify it does not belong in a skill.

**Personas** (`agents/*.md`, `docs/agents.md`). Four Markdown files (`code-reviewer`, `security-auditor`, `test-engineer`, `web-performance-auditor`) with `name` and `description` frontmatter and a system-prompt body. `docs/agents.md` states that the user or a slash command is the orchestrator and that personas do not call other personas.

**Claude Code plugin and marketplace manifests.** `.claude-plugin/plugin.json` carries `name`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `commands`, `skills` and `experimental.evals`. `.claude-plugin/marketplace.json` carries `$schema`, `name`, `description`, `owner` and a `plugins` array whose entry has a GitHub `source`. `scripts/validate-versions.js` checks that the version agrees across five manifests. The authoritative field list is the official manifest reference (see [sources.md](sources.md)), which was not re-read for this file.

**Validation scripts and eval tiers** (`evals/README.md`). Tier 1 is structural (frontmatter, naming, required sections, command parity). Tier 2 is a deterministic lexical routing check (stemmed TF-IDF over descriptions) that tests whether positive prompts rank their skill and whether two descriptions collide. Tier 3 is behavioral: it runs a headless `claude` in a throwaway git repository and grades the trace, which spends tokens and runs on demand. A separate `claude plugin eval` path scores cases with and without the plugin. Each skill needs `evals/cases/<skill>.json` with at least 3 positive triggers, 2 negative triggers and 1 behavioral eval (`CONTRIBUTING.md`). That repository reports its own routing numbers in its own documents; none are reused here.

**Contribution policy** (`CONTRIBUTING.md`, "Translations"). Translations of documentation and skills are not accepted; everything stays in English to avoid drift.

## How wev-skills relates to it

| wev-skills adopts as a convention | wev-skills does differently, and why | wev-skills does not take |
|---|---|---|
| `skills/<name>/SKILL.md` as the entry point, `name` equal to the directory name, lowercase-hyphenated | Bilingual user docs (English and Brazilian Portuguese) with one shared implementation, as the project requires (`CLAUDE.md`); upstream rejects translations to avoid drift, so wev-skills has to keep the pairs in sync itself | The 25 skills and their content; wev-skills has its own domain (orchestration), and nothing is copied |
| Frontmatter limited to the Agent Skills specification keys; vendor settings under `metadata` or in an adapter | A Python engine enforces rules in code (permissions, approvals, guards, state). Upstream skills are mainly Markdown instructions, which a model can ignore | Slash commands and hooks for many hosts (`.gemini`, `.codex-plugin`, `.opencode`); wev-skills targets Claude Code first and keeps the core host-independent |
| `description` of 1024 characters or fewer, third person, with a "Use when" trigger, without a workflow summary | Agents are defined by versioned, schema-validated YAML or JSON in configuration, not by Markdown persona files, so personas need no source change | The skill-change rejection ledger (`evals/skill-impact.md`) and the per-skill eval-case requirement in its present form |
| `SKILL.md` kept lean (under 500 lines), progressive disclosure, references one level deep | Delegation goes through the orchestrator with a task contract (objective, scope, acceptance criteria, permissions); upstream leaves orchestration to the user or a command | Root-level shared `references/` outside the skill directory, because of the portability gap upstream documents; wev-skills intends to keep each skill self-contained (to be confirmed) |
| "Personas do not call other personas"; no recursive agent invocation | Evals include a deterministic scripted-agent harness for the engine's mechanics, besides trigger and behavioral checks | The English-only contribution policy |
| Validation as code: a linter library with unit tests, run in CI (`scripts/lib/skill-lint.js` pattern) | Validators are intended to be Python standard-library code, matching the engine in `docs/architecture/architecture.md` (not yet implemented); upstream uses Node scripts | Any measured routing or impact number from upstream |
| Evidence-oriented Verification section in each skill; three eval tiers (structural, routing, behavioral) | Unit tests and CI run without a paid model; real-provider evals are optional | |
| Plugin plus marketplace manifests for Claude Code distribution | Plugin manifests are written against the official manifest reference; no compatibility with a platform is claimed before an adapter and an integration test exist (project constraint) | |

Rows list independent items; they are not paired across columns.

## Open questions

- Whether wev-skills requires the same five body sections or a subset. Not decided.
- Whether the shared-references layout or per-skill `references/` is used. Per-skill is intended, not yet implemented.
- Upstream cites "WikiSkill" (arXiv:2608.27454) for the claim that skills written against one model's failures can hurt stronger models. That paper was not read for this record, so the claim is not relied on here.
