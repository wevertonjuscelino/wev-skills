# Testable hypotheses for wev-skills

Portuguese version: [hypotheses.pt-BR.md](hypotheses.pt-BR.md).
Evidence source: [harness-design-paper.md](harness-design-paper.md) (arXiv:2609.20804v1). Planned tests: [experiments.md](experiments.md). Consulted: 2026-10-13.

These are hypotheses, not findings. For every one the status is the same: **mechanism implemented; effect not measured with a real model**. "Implemented" means the code and its tests exist; it says nothing about whether the hypothesis holds. The paper studied a different harness and different models, so its results motivate a default or a configuration option; they do not justify a claim that the default works. "Support" below rates how directly the paper bears on the decision: strong, moderate, weak or none.

## Status at a glance

| Hypothesis | Mechanism | Implemented in (module, config key) | Status |
|---|---|---|---|
| H1 | Staged compaction | `context.manager.ContextManager` (`compact`, stage 1 and stage 2); config keys `context.elide_at`, `context.summarize_at`, `context.budget_tokens`; CLI `wev context compact` | Mechanism implemented; effect not measured with a real model |
| H2 | Compaction only when the budget binds | `context.manager.ContextManager.compact` (acts only on the usage ratio); config key `context.budget_tokens` | Mechanism implemented; effect not measured with a real model |
| H3 | Optional recall | `context.manager.ContextManager.recall` and `context.manager.recall_archived`; CLI `wev context recall`. No config key: the archive is always written when an archive directory is set | Mechanism implemented; effect not measured with a real model |
| H4 | Conditional planning | `decisions.local.LocalPolicyProvider.select_strategy` (table `PLAN_FROM_COMPLEXITY`), tier passed in by `core.orchestrator.Orchestrator.start` through `models.router.executor_tier`; config keys `harness.planning` and `harness.executor_tier`; CLI `wev strategy --executor-tier` | Mechanism implemented; effect not measured with a real model |
| H5 | Tool interface per agent and profile | `agents.spec.AgentSpec.tools`, `agents.tool_profile` (`resolve_profile`, `apply_profile`), applied in `core.planning.build_contract` and by `wev agent export`; config key `harness.tool_profile`; CLI `wev agent export --tool-profile` | Mechanism implemented; effect not measured with a real model |
| H6 | Redundant verification guard | `guards.execution.evaluate` (repeated-verification rule, fed by `core.task_exec.check_task` with a working-tree fingerprint). No config key of its own; the rule advises and the caller decides | Mechanism implemented; effect not measured with a real model |
| H7 | Stuck detection and caps | `guards.execution` (`evaluate`, `GuardLimits.from_config`) and `core.progress.task_verdict`; config keys `limits.max_identical_commands`, `limits.max_consecutive_failures`, `limits.max_attempts`, `limits.task_timeout_seconds`, `limits.budget_units` | Mechanism implemented; effect not measured with a real model |
| H8 | Plan reminder | `core.brief` (`build_brief`), `core.orchestrator.Orchestrator.brief` and `finish`, `state.store.active_run`, `adapters.claude_code.hooks` (`session_context`, `prompt_reminder`), `hooks/hooks.json`; config keys `harness.plan_reminder` and `harness.plan_reminder_max_chars`; CLI `wev run brief`, `wev run finish`, `wev hook session-context`, `wev hook prompt-reminder` | Mechanism implemented; effect not measured with a real model |
| H9 | Capability profile | `models.router.executor_tier`, `decisions.local.LocalPolicyProvider.select_strategy`, `agents.tool_profile.resolve_profile`; config keys `harness.executor_tier`, `harness.planning`, `harness.tool_profile`; scripted configurations `profile-economy`, `profile-premium` and `tools-lean` in `evals/baselines/configs.json` | Mechanism implemented; effect not measured with a real model |
| H10 | Per-task tool selection | `decisions.tool_selection` (`enforce`, the floor and the candidate rules), `decisions.local_tools` and `LocalPolicyProvider.select_tools`, `decisions.jev_tools` and `JevProvider.select_tools`, `core.tool_select` (compute, store, restore), `tools.registry.ToolSpec.approx_definition_tokens`; config key `harness.tool_selection` (`off` by default, `local`, `provider`); CLI `wev select-tools` and `wev task tools`; scripted configurations `tools-selection-off` and `tools-selection-local` and the task `tool-selection-miss` | Mechanism implemented; effect not measured with a real model |

## H1. Staged compaction: elide first, summarize later

- **Hypothesis.** Under a tight token budget, compacting in two stages (elide stale tool output at 0.6 of the budget, summarize remaining unpinned items at 0.85) gives success comparable to single-stage compaction at lower cost and fewer summarizer calls.
- **Paper evidence.** T4 had success comparable to T1-T3 with the lowest mean cost at every window budget, the lowest peak-context ratio, and fewer summarization calls than T3 (Section 3.2, Figures 4 and 5). Thresholds 0.6 and 0.85 are the paper's own settings (Section 3.1).
- **Support: moderate.** The paper reports no significance tests among managed tiers, tested one pair of thresholds, and its T4 includes recall, so staging is not isolated from recall.
- **Design decision.** `ContextManager` defaults `elide_at=0.6`, `summarize_at=0.85`, both configurable. Stage 1 replaces the oldest large `tool_output` items with a stub; originals are archived and recoverable by id; stage 2 runs only when a summarizer is injected. Requirements, decisions and test results are pinned. The pinning rule is wev-skills's own and is not from the paper.
- **Implemented in.** `context.manager.ContextManager` (`compact`, stage 1 and stage 2); config keys `context.elide_at`, `context.summarize_at`, `context.budget_tokens`; CLI `wev context compact`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Compare no compaction, elide only, summarize only, and staged, plus threshold variants (for example 0.5/0.8 and 0.7/0.9), on long-trajectory tasks at several budgets. Metrics: task success, peak context ratio, summarizer calls, cost, information-loss failures (a later step needs content that was elided or summarized). See E2 and E4 in [experiments.md](experiments.md).

## H2. Compaction pays off only when the budget binds

- **Hypothesis.** Compaction matters when the budget is tight and adds little when it is loose, so it should not be forced on short runs.
- **Paper evidence.** The managed-versus-T0 gap shrinks from 35.7 to 2.7 points on SWE-Bench and from 9.5 to 2.8 on Terminal-Bench as the window grows from 32k to 128k, tracking T0 overflow (Section 3.2, Figure 3, Tables 3 and 4).
- **Support: strong within the paper, weak for transfer.** wev-skills's `ContextManager` governs only context the engine assembles, not Claude Code's own window, so the mapping from the paper's window to wev-skills's budget is an analogy.
- **Design decision.** Compaction triggers by usage ratio only; there is no fixed schedule. Budget is a configuration value.
- **Implemented in.** `context.manager.ContextManager.compact` (acts only on the usage ratio); config key `context.budget_tokens`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Budget sweep on the same tasks with compaction on and off (E2). Metric: overflow failures and success per budget.

## H3. Explicit recall is cheap to offer, rarely used: optional, not central

- **Hypothesis.** A `recall(id)` capability does not improve success over elision alone and will be called rarely, so it is an optional tool and not part of the main flow.
- **Paper evidence.** T2 vs T1: 15 wins, 14 losses, 3 ties, mean -0.36 points over 32 comparisons; 36 of 64 recall-enabled settings never call recall; mean calls per task 0.540 at 32k down to 0.007 at 128k (Section 3.2, Table 13).
- **Support: moderate for "no measured accuracy gain", weak for "never needed".** Use was concentrated in the smallest model under the tightest window, and Claude models were not tested. A lossless archive may still matter for audit and resume independent of the model calling it.
- **Design decision.** Archive originals always (they are needed for audit and resume anyway) and expose `recall` by id, but do not require agents to use it and do not build flow steps around it.
- **Implemented in.** `context.manager.ContextManager.recall` and `context.manager.recall_archived`; CLI `wev context recall`. No config key: the archive is always written when an archive directory is set.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Same tasks with recall exposed and hidden. Metrics: recall calls per task, success, cost, and cases where a failure traces to an elided item (E3).

## H4. Planning is conditional on task and model

- **Hypothesis.** A mandatory plan step helps weaker models and costs extra on stronger ones; for trivial tasks it is ceremony. Therefore `auto` mode skips the plan step for trivial and simple tasks, and the planning requirement is configurable per agent and mode.
- **Paper evidence.** Planning raised the weakest model's SWE-Bench success by 11.6 points (the only planning contrast marked significant) and mostly lowered cost, with success changes of -2.0 and -0.4 points, for the two strongest models (Section 3.2, Figure 6, Tables 3, 4, 5, 6).
- **Support: moderate for model dependence, weak for task dependence.** The paper varies model capability, not task difficulty. Its planning is a model-maintained persistent plan, whereas wev-skills's PLAN phase is an engine-validated plan with a dependency graph. The step from "weaker model needs a plan" to "trivial tasks do not" is an extrapolation.
- **Design decision.** `Strategy.needs_plan` is derived from the classification (complexity, risk) and the executor tier, and `harness.planning` (`auto`, `always`, `never`) overrides it; `plan` mode and gated flows always plan. The tier rule is described under H9.
- **Implemented in.** `decisions.local.LocalPolicyProvider.select_strategy` (table `PLAN_FROM_COMPLEXITY`), tier passed in by `core.orchestrator.Orchestrator.start` through `models.router.executor_tier`; config keys `harness.planning` and `harness.executor_tier`; CLI `wev strategy --executor-tier`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Plan required, plan off, and `auto`, across tasks tagged trivial, moderate and complex, with at least two model tiers. Metrics: success, turns, cost, post-edit verification turns (E5).

## H5. Tool interface value depends on model capability

- **Hypothesis.** A structured tool set helps models that are weak with shell commands and adds overhead for models that compose shell commands well. The tool registry and permissions are therefore defined per agent in configuration, not fixed.
- **Paper evidence.** Full tools beat bash-only by 15.0 and 10.1 points for the 30B model, while bash-only beat full tools by 3.6 and 5.6 points for 550B at 53% and 30% lower cost; Mistral reversed between benchmarks (Section 3.2, Figure 7, Tables 3, 4, 7).
- **Support: moderate for the direction of the crossover, weak for any specific threshold.** Only some contrasts are marked significant (30B both benchmarks, 550B on SWE-Bench, Mistral on SWE-Bench). The intervention bundled tools, prompts, file-state tracking and diagnostics.
- **Design decision.** `AgentSpec.tools.allow/deny` and the registry's `mutating`/`remote` flags are per-agent configuration. Permission checks stay in the engine regardless of the tool set; only the tool surface varies. `harness.tool_profile` (`structured` by default, `lean`, `auto`) can shorten an editing agent's allow list to the shell plus minimal read and edit tools; it never adds a tool, never touches the deny list and never changes permissions.
- **Implemented in.** `agents.spec.AgentSpec.tools`, `agents.tool_profile` (`resolve_profile`, `apply_profile`), applied in `core.planning.build_contract` and by `wev agent export`; config key `harness.tool_profile`; CLI `wev agent export --tool-profile`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Per agent, compare a minimal shell-only registry with the full registry on matched tasks, split by shell-centric versus edit-centric tasks (E6).

## H6. Redundant verification can be detected and skipped

- **Hypothesis.** A guard that flags verification repeated with no intervening change reduces cost without lowering success.
- **Paper evidence.** For the stronger models, planning's cost saving came mostly from fewer post-edit verification turns, with little change in success (Section 4, Table 6, Figure 8).
- **Support: weak and indirect.** The paper attributes the saving to planning, not to a guard, and does not test any guard of this kind.
- **Design decision.** `ExecutionGuard` includes a "repeated verification with no change in between" rule (architecture section 4.8). Whether it should block or only warn is open.
- **Implemented in.** `guards.execution.evaluate` (repeated-verification rule, fed by `core.task_exec.check_task` with a working-tree fingerprint). No config key of its own; the rule advises and the caller decides.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Guard in warn-only, block, and off modes on tasks that need a final verify. Metrics: verification calls, cost, success, false positives where a repeat was legitimate (E7).

## H7. Stuck detection and step caps are fixed safety features

- **Hypothesis.** Stuck detection, step caps and timeouts are safety mechanisms that are always on, not performance options. They are not tuned per experiment.
- **Paper evidence.** None for their effect. The paper held stuck detection fixed in every ablation (Section 2.4) with the values: reminder at 5 identical calls or 5 identical failing calls, termination at 8 identical failing calls, 300 steps maximum (Section 3.1). No result in the paper measures what these settings contribute.
- **Support: none.** The decision rests on engineering judgment. The paper's values are a documented starting point, not tuned numbers.
- **Design decision.** `ExecutionGuard` limits are configurable but cannot be disabled by an agent spec; a `polling=True` exemption and a flaky-test allowance exist.
- **Implemented in.** `guards.execution` (`evaluate`, `GuardLimits.from_config`) and `core.progress.task_verdict`; config keys `limits.max_identical_commands`, `limits.max_consecutive_failures`, `limits.max_attempts`, `limits.task_timeout_seconds`, `limits.budget_units`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Mechanics only with a scripted agent: injected loops must trip the guard at the configured count. With a real model, measure false-positive trips on legitimate repeated commands (E7).

## H8. A plan re-shown to the model keeps it on the plan

- **Hypothesis.** Re-showing a compact brief of the recorded plan (objective, task statuses, current acceptance criteria, next step) after context compaction and with each prompt helps a weaker executor finish the planned work, and for a stronger one mainly shortens the trajectory. It is therefore a switch, on by default, with a size cap.
- **Paper evidence.** The planning variant the paper studied is a persistent plan the model maintains with `update_plan` and that is injected each turn (Section 2.1). With it, Nemotron-3 30B reached 25.2 against 13.6 on SWE-Bench (+11.6 points, the only planning contrast marked significant) and 13.48 against 8.99 on Terminal-Bench; without it the 30B median SWE-Bench trajectory dropped from 40 to 5 turns and 68.6% of runs ended without an edit, against 27.8% with planning. For Nemotron-3 550B and Mistral-Medium-3.5-128B success changed by -2.0 and -0.4 points while cost fell by about 30% and 32% on SWE-Bench, with median trajectories shortened from 108 to 74 and from 68 to 53 turns (Section 3.2, Section 4, Figure 6, Figure 8, Tables 3 to 6).
- **Support: moderate for "a re-shown plan matters most to the weakest model", weak for this mechanism.** The paper's plan is written and updated by the model and injected every turn. The wev-skills brief is engine-recorded state, built by `wev run brief`, and Claude Code hooks inject it after compaction and once per user prompt, not once per model turn. The paper did not test Claude models, a per-prompt cadence, or a size cap.
- **Design decision.** `wev run brief` prints the brief, truncated on whole lines to a character limit. The plugin hooks print it on SessionStart after `compact` or `resume` and, while `harness.plan_reminder` is true, on every UserPromptSubmit, capped at `harness.plan_reminder_max_chars` (default 600). The brief says it is recorded state and points at `wev run resume` for the real repository state. `wev run finish` ends the run so the reminder stops.
- **Implemented in.** `core.brief` (`build_brief`), `core.orchestrator.Orchestrator.brief` and `finish`, `state.store.active_run`, `adapters.claude_code.hooks` (`session_context`, `prompt_reminder`), `hooks/hooks.json`; config keys `harness.plan_reminder` and `harness.plan_reminder_max_chars`; CLI `wev run brief`, `wev run finish`, `wev hook session-context`, `wev hook prompt-reminder`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** Same tasks with the reminder on and off, at two or more model tiers, with long sessions that cross a compaction. Metrics: success, turns, cost, tasks finished after a compaction, tokens added by the reminder (E10).

## H9. Harness defaults should follow the executor's capability tier

- **Hypothesis.** One capability setting should move several harness defaults together: a weaker executor gets a plan for anything above trivial and individually permission-checked tools; a stronger executor skips the plan on small tasks and may be given a lean shell-centred tool surface. Risk rules, approvals and independent review do not move with it.
- **Paper evidence.** The value of each varied component depended on the model: planning moved from an accuracy scaffold for the weakest model to a cost saver for the strongest (Section 3.2, Figure 6); full tools beat bash-only by 15.0 and 10.1 points for Nemotron-3 30B, while bash-only beat full tools by 3.6 points on SWE-Bench (marked significant) and 5.6 on Terminal-Bench for Nemotron-3 550B at 53% and 30% lower cost, and Mistral-Medium-3.5-128B reversed between benchmarks (Section 3.2, Figure 7, Tables 3, 4, 7). The authors call harness design "a conditional systems problem" (Conclusion).
- **Support: moderate for "defaults should be conditional", weak for the mapping.** The paper's capability axis is three sizes of one model family plus one other model, and its Limitations section says model size is an imperfect proxy for capability and that crossover points should be validated before transfer. Mapping its sizes to the `economy`, `standard` and `premium` tiers, and those tiers to Claude models, is this project's analogy and is not evidence. Planning and tools were ablated only at T4/128k.
- **Design decision.** `harness.executor_tier` (`auto`, `economy`, `standard`, `premium`) names the tier strategy selection assumes; `auto` is the tier the model router picks for the task. With `harness.planning: auto`, economy plans anything above trivial, standard keeps the rule that existed before tiers (plan from moderate complexity up or above low risk), and premium plans only from moderate complexity up or above low risk. Standard and premium therefore share a threshold today; they are separate table entries so that either can be changed alone. Under `executor_tier: auto` the router gives the economy tier only to trivial low-risk tasks and the premium tier only to complex or high-risk ones, so the tier rule changes an outcome only when the tier is set explicitly. `harness.tool_profile` defaults to `structured`, because tools that are permission-checked one by one are easier to govern; `lean` is offered for strong models on cost grounds only, and `auto` selects it for the premium tier. Gated and plan-mode flows always have a plan, and every strategy records the tier and the rule in its reasons.
- **Implemented in.** `models.router.executor_tier`, `decisions.local.LocalPolicyProvider.select_strategy`, `agents.tool_profile.resolve_profile`; config keys `harness.executor_tier`, `harness.planning`, `harness.tool_profile`; scripted configurations `profile-economy`, `profile-premium` and `tools-lean` in `evals/baselines/configs.json`.
- **Status.** Mechanism implemented; effect not measured with a real model.
- **How to test.** The same task set under the economy and premium profiles and under each profile with one default flipped (plan rule, tool profile), with real models at two or more tiers. Metrics: success, cost, turns, runs ending without an edit, calls to tools that are not offered (E11). The scripted harness shows only that the profile selects the expected plan step and tool list.

## H10. Per-task tool selection reduces tool-definition context at the risk of dropping a needed tool

- **Hypothesis.** Handing an agent, for each task, only the tools that task needs lowers the context spent on tool definitions. The risk is the opposite error: a dropped tool that the task needed fails the task, or costs a recovery step, while a kept tool that was not needed only costs context.
- **Paper evidence.** The paper compared two fixed tool interfaces, full tools and bash-only, and found that the effect depends on the model: the structured tools helped the weakest model, and the lean interface cost less for the strongest ([harness-design-paper.md](harness-design-paper.md), section 3.3 "Tool interface", which cites the paper's Section 3.2, Figure 7 and Tables 3, 4 and 7). The same section records that the intervention was bundled and does not isolate tool count or granularity. The paper did not test choosing tools per task, did not test selection by an external decision service such as JEV, and did not test Claude models.
- **Support: weak.** The paper shows that the tool interface matters and that its effect is conditional on capability. It says nothing about per-task selection, about how often a selection drops a needed tool, or about how many tokens tool definitions take for any client. The per-tool token figures in this project are rough, hand-set constants (`approx_definition_tokens`), used to compare two tool sets and labeled "estimated definition tokens (approximate)" wherever they appear.
- **Design decision.** `harness.tool_selection` is `off` by default, and then contracts carry the agent's tool list exactly as before. With `local`, a deterministic policy starts from a floor and adds a tool only when the task text gives a reason. With `provider`, the configured decision provider is asked, which means JEV when `decision.provider` is `jev` (see [ADR 0004](../architecture/decisions/0004-decision-providers-and-jev.md)). Every result passes one function that holds the rules: the result is a subset of the agent's allow list minus its deny list, a floor is always kept (the read tools the agent had, the edit tool when the task changes files and the agent may, the shell when the task has checks), permissions are untouched, and an empty or malformed result falls back to the local policy. Every rule errs towards keeping a tool. A dropped tool can be restored for a running task with `wev task tools`, only from the agent's own candidate set, and the report counts each restore as a selection miss.
- **Implemented in.** `decisions.tool_selection` (`enforce`, the floor and the candidate rules), `decisions.local_tools` and `LocalPolicyProvider.select_tools`, `decisions.jev_tools` and `JevProvider.select_tools`, `core.tool_select` (compute, store, restore), `tools.registry.ToolSpec.approx_definition_tokens`; config key `harness.tool_selection` (`off` by default, `local`, `provider`); CLI `wev select-tools` and `wev task tools`; scripted configurations `tools-selection-off` and `tools-selection-local` and the task `tool-selection-miss`.
- **Status.** Mechanism implemented; effect not measured with a real model. The JEV path is tested with a fake provider only; no live call was made for tool selection.
- **How to test.** The same real tasks with a real model under `off`, `local` and `provider`, measuring task success, tool-selection misses, total input tokens as reported by the client, and cost (E12). The scripted harness shows only that selection narrows the list, that the estimate follows, and that a miss is recorded and recovered.

## What the paper gives no evidence for

wev-skills does the following anyway. These choices rest on engineering judgment and on risk reasoning, not on the paper.

- **Multi-agent delegation** with task contracts and centralized orchestration. The paper uses a single agent loop.
- **Independent review** as a distinct step (`needs_independent_review`). The paper evaluates no reviewer.
- **Governance and approvals**, including approval before high-risk steps and `plan` mode denying mutating actions. The paper's permission layer was held fixed and not measured.
- **Remote execution** over SSH and tmux. Not studied.
- **Decision providers** (local policy, optional JEV adapter). Not studied.

For each of these, a cost-benefit claim would need its own experiment (see E8 and E9 in [experiments.md](experiments.md)). Until then, wev-skills documents them as design decisions, not as measured improvements.

## Limits of the evidence

- Models: three Nemotron-3 sizes and one Mistral model, served locally. No Claude model was tested. The paper does not label them "open" or "mid-tier"; that is this record's shorthand for "not the frontier closed models wev-skills will mostly run on", and the transfer is unverified.
- Tasks: SWE-Bench Verified (Python only) and Terminal-Bench 2.1 (89 tasks). No other languages, no non-software tasks.
- Runs: one run per task per setting, temperature 0. Many Terminal-Bench contrasts are not significant. Run-to-run variance was not measured.
- Implementations: one implementation per component (one planning prompt, one threshold policy, one bundled tool interface).
- Coverage: planning and tools were ablated only at T4/128k.
- Cost: computed from token prices, not billed spend.
- The paper is a preprint (v1).
