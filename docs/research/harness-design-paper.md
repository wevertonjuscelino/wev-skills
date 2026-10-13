# Research record: "An Empirical Study of Harness Design for Coding Agents"

Portuguese version: [harness-design-paper.pt-BR.md](harness-design-paper.pt-BR.md).
Consulted: 2026-10-13. This is a summary for wev-skills design work. It is not a substitute for the paper, and no result below is a guarantee for any other model, harness or task type.

## 1. Bibliographic facts and what was read

- Title: An Empirical Study of Harness Design for Coding Agents.
- Authors: Run-Ze Fan, Zihao Zhang, Simin Ma, Yebowen Hu, Shouju Wang, Kaiqiang Song, Fei Liu, Hamed Zamani, Xiaoyang Wang. Affiliations on the title page: UMass Amherst, Emory University, UNC Charlotte, and a third affiliation whose name did not survive text extraction. The paper marks three authors (Fan, Zhang, Wang) as having done the work during internships at Zoom Video Communications.
- Identifier: arXiv:2609.20804, version v1, subject cs.AI, submitted 17 Sep 2026. The arXiv listing gives 43 pages (arXiv abstract page, "Comments").
- Read for this record: the abstract page, the extracted text of the PDF (main text, pages 1-18, in full) and parts of the appendix (Table 13 on recall usage, the start of Appendix C). Appendix A (prompts), most of Appendix B (tool descriptions), Appendix C.2 (agreement between the LLM judge and human annotators) and the appendix figures and tables other than Table 13 were not read in full. Any claim below that cites only an appendix table was not re-derived.
- The paper is a preprint. Nothing in this record has been checked against peer review, released code or released data.

## 2. Experimental setup

**Harness.** A lightweight harness written by the authors, following a ReAct loop (Section 2, Figure 2). Its execution loop is fixed. Three components are varied: planning (Section 2.1), action space (Section 2.2), and context management (Section 2.3). Held fixed across all ablations (Section 2.4): workspace guard (path resolution, symlink escape rejection), read-before-write check, a permission layer (allow, ask, deny), post-edit diagnostics for Python files (ruff, pyflakes or a syntax-only fallback), and stuck detection.

**Models (Section 3.1).** Nemotron-3 at 30B, 120B and 550B (a within-family capability axis) and Mistral-Medium-3.5-128B (cross-family). Served locally with SGLang in BF16. Token prices used for cost, per 1M input/output tokens (OpenRouter, accessed August 2026): $0.05/$0.20, $0.08/$0.45, $0.50/$2.20, and $1.50/$7.50 respectively. Cost in the paper is therefore computed from token counts and these prices.

**Benchmarks (Section 3.1).** SWE-Bench Verified (500 human-verified GitHub issues; the paper's Limitations section states it is Python-only) and Terminal-Bench 2.1 (89 command-line tasks). Metrics: task success rate (SR) and mean cost per task. Trajectory-level analysis uses an LLM judge to label each turn with a workflow phase (Section 4; agreement with humans is in Appendix C.2, not read).

**Run parameters (Section 3.1).** Temperature 0, top-p 0.95, output capped at 16,384 tokens per turn. Built on LangGraph, benchmarks driven through Harbor. At most 300 steps per task. Tool results truncated to 24k characters; up to eight read-only tools in parallel per step. Stuck detection: a reminder after five consecutive identical tool calls or five consecutive identical failing calls, termination after eight consecutive identical failing calls.

**The three varied components.**

| Component | Variants | Source |
|---|---|---|
| Planning | on (a persistent plan the model maintains with `update_plan`, injected each turn) or off | Section 2.1 |
| Action space | predefined tools (`read_file`, `write_file`, `edit_file`, `list_files`, `glob_files`, `grep_text`, `web_fetch`, `bash`) or bash-only | Section 2.2, Table 1 |
| Context management | five tiers, below | Section 2.3, Table 2 |

**Context tiers.** Three mechanisms: M1 elision (replace the body of a stale tool observation with a stub), M2 recall (store elided originals externally and expose `recall_event(id)`), M3 summarization (a separate tool-free call to the same model folds old turns into a running summary).

| Tier | M1 | M2 | M3 | Behaviour |
|---|---|---|---|---|
| T0 | no | no | no | No compaction; the run ends with an error when the window overflows |
| T1 | yes | no | no | Elision only, originals discarded; acts at the hard threshold |
| T2 | yes | yes | no | Elision plus recall |
| T3 | no | no | yes | Summarization only; acts at the hard threshold |
| T4 | yes | yes | yes | Staged: elide at soft threshold B1, summarize at hard threshold B2 (Algorithm 1) |

Thresholds are 0.6 (soft) and 0.85 (hard) of the usable window. The system prompt, the task description and a recent window (budget 0.3 of the window, at least two turns) stay verbatim; only the middle region is compacted (Section 3.1, Algorithm 1).

**Design and statistics.** Context window budgets of 32k, 64k, 96k and 128k tokens. T0 to T4 under each budget gives 20 settings per model-benchmark pair. Planning-off and bash-only are each run once, at T4/128k only. That is 22 settings per pair and 4 x 2 x 22 = 176 settings in total (Section 3.1). Each setting runs each task once. Comparisons are task-paired: two-sided exact McNemar tests, with Benjamini-Hochberg control of the false discovery rate at 0.05, within three families (managed tier vs T0, planning on vs off, full tools vs bash-only). An asterisk in Tables 3 and 4 marks a significant difference from the matched baseline.

**Percent versus percentage points.** The paper writes "%" in several success-rate differences in Section 3.2 (for example "raises success by 15.0%"). The tables show these are absolute differences: for Nemotron-3 30B on SWE-Bench, 25.20 minus 10.20 is 15.0; for 120B, 44.0 minus 42.4 is 1.6; for 550B, 69.4 minus 65.8 is 3.6; for Mistral, 68.6 minus 45.4 is 23.2 (Table 3). In this record such values are percentage points. Cost changes quoted as "%" (for example 53% lower cost) are relative changes.

## 3. Findings

### 3.1 Context management

- Value rises as the window tightens. The success-rate gap between managed tiers (T1 to T4) and T0, averaged over models, falls from 35.7 to 15.9, 5.5 and 2.7 points on SWE-Bench and from 9.5 to 7.5, 4.8 and 2.8 on Terminal-Bench, going from 32k to 128k (Section 3.2, Tables 3 and 4).
- The benefit tracks overflow. Model-averaged T0 overflow falls from 78.7% to 8.7% (SWE-Bench) and from 61.0% to 12.1% (Terminal-Bench) across the same budgets; managed tiers have zero overflow failures at every budget (Section 3.2, Figure 3).
- Staging is the most cost-efficient. T4 reaches success rates "comparable" to T1-T3 (the paper reports no significance tests among managed tiers; asterisks compare each tier with T0) with the lowest cost in seven of eight model-benchmark panels (Figure 4), the lowest mean peak-context ratio at all four budgets (Figure 5a), fewer M3 calls than T3 on average at every budget (Figure 5b), and the lowest mean cost at every budget (Figure 5c). The authors attribute this to early elision handling many cases before summarization is needed (Section 3.2).
- Recall adds no accuracy. Across 32 model-benchmark-window comparisons, T2 beats T1 in 15, loses in 14 and ties in 3; the equal-weight mean difference is -0.36 points (+0.40 SWE-Bench, -1.12 Terminal-Bench). Among the 64 T2 and T4 settings, 36 (56.3%) never call `recall_event`. Mean calls per task fall from 0.540 at 32k to 0.069, 0.011 and 0.007 at 64k, 96k and 128k. The 16 planning and action-space settings record no calls. Use is concentrated in Nemotron-3 30B; the heaviest case (30B, Terminal-Bench, 32k, T2) averages 4.326 calls per task and scores 3.37 points below T1 (Section 3.2, Table 13).
- Caveat on T4. T4 includes recall (T2 plus summarization). No tier combines elision and summarization without recall, so the paper cannot separate the effect of staging from the effect of recall inside T4.
- Trajectories. At 32k, T0 runs have median lengths of 20-30 turns and mostly end during localization; managed tiers have medians of roughly 50-180 turns. At 128k the tiers differ little in re-patch counts and in the share of runs ending without an edit (under four points for three of four models) (Section 4).

### 3.2 Planning

Measured at T4/128k with the full tool set (Section 3.2, Figure 6, Tables 3-5).

| Model | SWE-Bench SR with plan vs without | Cost effect of planning |
|---|---|---|
| Nemotron-3 30B | 25.2 vs 13.6 (+11.6 points, marked significant) | Higher on both benchmarks; on Terminal-Bench +75% (Section 4) |
| Nemotron-3 120B | 44.0 vs 46.6 (no consistent gain) | Higher on SWE-Bench, lower on Terminal-Bench (about -26%, Section 4) |
| Nemotron-3 550B | 65.8 vs 67.8 (-2.0 points) | About -30% on SWE-Bench |
| Mistral-Medium-3.5-128B | 68.6 vs 69.0 (-0.4 points) | About -32% on SWE-Bench; about -40% on Terminal-Bench (Section 4) |

- On Terminal-Bench the 30B gain is +4.5 points (13.48 vs 8.99). Only the 30B SWE-Bench planning contrast carries an asterisk in Tables 3 and 4.
- Mechanism (Section 4, Table 6, Figure 8). Without planning, the 30B median SWE-Bench trajectory drops from 40 to 5 turns, and 68.6% of runs end without an edit (27.8% with planning). For 550B and Mistral, planning shortens median SWE-Bench length (108 to 74 and 68 to 53 turns), mostly by removing post-edit verification turns, with little change in runs that never edit.
- The paper's own summary: planning moves from an accuracy scaffold for weaker models to a cost saver for stronger ones, and its value at intermediate capability "remains task-type-dependent". The planning studied is one prompt-and-tool mechanism (Section 2.1), not planning in general.

### 3.3 Tool interface

Measured at T4/128k with planning on (Section 3.2, Figure 7, Tables 3, 4, 7). Differences are full tools minus bash-only unless stated.

- Nemotron-3 30B: full tools better by 15.0 points (SWE-Bench) and 10.1 points (Terminal-Bench), both marked significant. On Terminal-Bench, 66% of bash-only trajectories end after emitting calls to tools that do not exist in that registry, and the average length drops from 71 to 15 turns.
- Nemotron-3 120B: full tools better by 1.6 and 4.5 points, not marked significant; average runs shorten from 101 to 77 turns (SWE-Bench) and 96 to 70 (Terminal-Bench).
- Nemotron-3 550B: bash-only better by 3.6 points on SWE-Bench (marked significant) and 5.6 on Terminal-Bench (not marked), at 53% and 30% lower cost, with 32% and 24% fewer calls.
- Mistral-Medium-3.5-128B: full tools better by 23.2 points on SWE-Bench (marked significant); bash-only better by 6.7 on Terminal-Bench (not marked). With all tools, 71.9% of its Terminal-Bench workspace actions go through bash against 40.4% on SWE-Bench. 32.8% of its bash-only SWE-Bench runs end without an edit against 1.2% with full tools (Table 12).
- Granularity (Section 4, Table 7): bash-only lowers mean re-patches per task for all four models (for example 3.3 to 0.4 for 30B) and shifts Terminal-Bench file writes toward create-or-replace (for example 28% to 64% for 30B).
- The intervention is bundled (tools, prompts, file-state tracking, post-edit diagnostics), so it does not isolate tool count or granularity (Section 2.2, Limitations).

## 4. Cost and trajectory length

- Context management lengthens trajectories without changing phase proportions much (Section 4). Its cost depends on the tier: T4 has the lowest mean cost at every budget (Figure 5c).
- Planning changes where trajectories stop (Section 4): it extends runs that would end early (30B) and trims post-edit verification and long tails (550B, Mistral, and 120B on Terminal-Bench). Cost moves with trajectory length (Table 5 gives percentage changes in turns, tool calls and input tokens).
- Bash-only shortens trajectories for capable models (for example 550B on Terminal-Bench, median 47 to 31 actions, Section 4) and raises the share of code-writing actions from 16% to 27%.
- Costs are computed from token counts at fixed prices, not from billed spend (Section 3.1).

## 5. Limitations stated by the authors (Limitations section)

1. Results describe the specific components as implemented: one planning prompt and update mechanism, one threshold-based context policy with fixed settings, and a bundled action-space change.
2. Planning and action space are ablated only at T4/128k; a full factorial design would be needed to see whether the effects persist elsewhere.
3. One run per task per setting; Terminal-Bench has only 89 tasks, so many contrasts there are not significant, and conclusions rest on consistent direction across models and budgets.
4. External validity is bounded by the models (three Nemotron-3 sizes and one Mistral model) and tasks; SWE-Bench Verified is Python-only. Model size is an imperfect proxy for capability. The crossover points should be validated before transfer to other model families, harnesses or non-software tasks.

## 6. What the paper does not claim

- It does not claim a universally optimal harness (Limitations).
- It does not evaluate Claude models, multi-agent delegation, independent review, approval workflows, remote execution, permission policies, stuck detection or post-edit diagnostics as variables; these were held fixed or absent.
- It does not test threshold values other than 0.6 and 0.85, or any recall design other than `recall_event(id)`.
- It reports no significance tests among the managed context tiers, and no separation of staging from recall inside T4.
- It does not show that planning helps or harms on tasks classified by difficulty; it varies model, not task triviality.
- It gives no evidence from languages other than Python or from tasks outside software engineering.
- It does not present results as guarantees; the authors call harness design "a conditional systems problem" (Conclusion).
