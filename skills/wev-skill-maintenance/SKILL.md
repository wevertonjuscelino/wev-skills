---
name: wev-skill-maintenance
description: "Use when maintaining skills, reviewing upstream skill updates, or reconciling skill standards across multiple repositories (multi-repo standardization). Coordinates the external Netresearch skill-repo guide with each repository's local rules. Em português: manter skills, revisar atualizações e padronizar múltiplos repositórios; conciliar padrões entre repositórios."
license: PolyForm-Noncommercial-1.0.0
disable-model-invocation: false
user-invocable: true
---

# Coordinated skill maintenance

The model may select this skill when a task involves skill updates, skill repository
structure, or reconciling conventions across repositories; no explicit slash command is
required. Select it only when relevant. Loading guidance does not grant permission to
change installations, publish changes, or bypass repository rules.

**Non-negotiable rule: follow YAGNI and prefer the solution with less code.** It applies to
everything you write or change through this skill.

Read [the maintenance policy](references/policy.md) and [the pinned source](references/upstream.json).
For Portuguese, read [a política de manutenção](references/policy.pt-BR.md).
Respond in the user's language; when running the local CLI for Portuguese output, use
`--lang pt-BR` before the command.

Use the external `skill-repo` skill as a repository-structure reference. Load the version
identified by the pin before relying on it. If absent, report the missing dependency and
follow the installation instructions in the policy. Never claim it is loaded merely because
this companion skill exists. Do not execute upstream scripts without inspecting them.

Before changing any repository, read its local agent instructions, manifest, license and
checks. Build a per-repository inventory and a conflict table. Agree on a common reviewed
upstream commit and shared applicable standards, while retaining explicit local exceptions.
Stage the proposed reconciliation as diffs in each repository; validate independently and
report each result. Keep existing work intact. A failed repository check prevents declaring
the entire group complete.

Updates are a maintenance workflow, not a background service: inspect upstream changes,
review licensing and commands, update the pin and policy together, validate, then synchronize
other repositories through reviewed changes. Do not infer permission to publish, tag, merge
or modify unrelated repositories. Evidence and human-operator restrictions still apply.
