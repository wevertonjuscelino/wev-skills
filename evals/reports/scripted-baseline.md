> Notice: these results come from a scripted agent that replays fixed trajectories; no model was called. They measure harness mechanics only. Exercised for real: the context manager, the execution guard, the model router and the local decision policy (classification, strategy, escalation decisions). Scripted or reimplemented by the harness itself, not run through the orchestration engine: the attempt loop and retries, task scheduling and parallelism, and whether a step or a verification passes. No command is executed, and the engine's run and task flow, baselines, approvals, permission policy and verification engine are not exercised. Cost and duration are simulated units. The results are not evidence about the performance of any model or of the engine's orchestration. Scripted results say nothing about model quality, and tool-definition token figures are estimates from rough constants, not measurements.

# Scripted evaluation report

Evidence label: simulated with mocks.

Simulated cost: tokens in context at each step multiplied by a per-tier constant (economy = 1, standard = 3, premium = 15). Simulated duration: one unit per scripted step, plus one unit when a plan is made. Neither is money or time.

## Aggregated per configuration

| Config | Runs | Successes | Success rate | Criteria met | Criteria rate | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 49600 | 336898 | 104 |
| `planning-off` | 8 | 5 | 0.6250 | 10/15 | 0.6667 | 21 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 5 | 0 | 46500 | 46500 | 291301 | 93 |
| `planning-auto` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 49600 | 315178 | 98 |
| `context-none` | 8 | 5 | 0.6250 | 9/15 | 0.6000 | 21 | 3 | 2 | 11 | 2 | 0 | 0 | 0 | 6 | 0 | 46500 | 46500 | 262444 | 94 |
| `context-elide-aggressive` | 8 | 5 | 0.6250 | 9/15 | 0.6000 | 21 | 3 | 2 | 11 | 1 | 7 | 0 | 1 | 6 | 0 | 46500 | 46500 | 246433 | 97 |
| `context-elide-summarize` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 0 | 3 | 9 | 1 | 4 | 0 | 49600 | 49600 | 327904 | 105 |
| `routing-fixed-standard` | 8 | 5 | 0.6250 | 9/15 | 0.6000 | 21 | 3 | 0 | 12 | 1 | 3 | 0 | 0 | 5 | 0 | 46500 | 46500 | 290421 | 101 |
| `routing-fixed-premium` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 20 | 2 | 0 | 10 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 49600 | 1377930 | 96 |
| `parallel-3` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 49600 | 336898 | 91 |
| `attempts-1` | 8 | 4 | 0.5000 | 8/15 | 0.5333 | 15 | 0 | 0 | 9 | 1 | 3 | 0 | 0 | 5 | 0 | 46500 | 46500 | 243763 | 84 |
| `attempts-2` | 8 | 5 | 0.6250 | 9/15 | 0.6000 | 19 | 6 | 0 | 10 | 1 | 3 | 0 | 0 | 5 | 0 | 46500 | 46500 | 275341 | 96 |
| `attempts-4` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 23 | 4 | 3 | 12 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 49600 | 340798 | 105 |
| `guard-off` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 25 | 4 | 4 | 0 | 1 | 3 | 0 | 0 | 1 | 0 | 49600 | 49600 | 695668 | 169 |
| `profile-economy` | 8 | 5 | 0.6250 | 9/15 | 0.6000 | 21 | 3 | 0 | 12 | 1 | 3 | 0 | 0 | 5 | 0 | 46500 | 46500 | 96327 | 100 |
| `profile-premium` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 20 | 2 | 0 | 10 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 32800 | 1271730 | 90 |
| `tools-lean` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 32800 | 336898 | 104 |
| `tools-selection-off` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 4 | 0 | 49600 | 49600 | 336898 | 104 |
| `tools-selection-local` | 8 | 6 | 0.7500 | 11/15 | 0.7333 | 22 | 3 | 2 | 11 | 1 | 3 | 0 | 0 | 4 | 1 | 49600 | 46150 | 336898 | 104 |

## Guard trips by rule

| Config | Trips by rule |
| --- | --- |
| `baseline` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `planning-off` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `planning-auto` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `context-none` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `context-elide-aggressive` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `context-elide-summarize` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `routing-fixed-standard` | attempts: 2, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `routing-fixed-premium` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 1 |
| `parallel-3` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `attempts-1` | attempts: 6, consecutive_failures: 1, handoff_cycle: 1, identical_commands: 1 |
| `attempts-2` | attempts: 3, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 3 |
| `attempts-4` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 5, repeated_error: 2 |
| `guard-off` | - |
| `profile-economy` | attempts: 2, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `profile-premium` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 1 |
| `tools-lean` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `tools-selection-off` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |
| `tools-selection-local` | attempts: 1, consecutive_failures: 3, handoff_cycle: 1, identical_commands: 4, repeated_error: 2 |

## Per task

### `agent-loop` (agent-loop)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `planning-off` | standard | no | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 14130 | 16 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `planning-auto` | standard | no | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 14130 | 16 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `context-none` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `context-elide-aggressive` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `context-elide-summarize` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `routing-fixed-standard` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 0 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 18210 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `routing-fixed-premium` | premium | yes | structured: 6 | no | 0/3 | 6 | 2 | 0 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 91050 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `parallel-3` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 21330 | 7 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `attempts-1` | standard | yes | structured: 6 | no | 0/3 | 3 | 0 | 0 | 6 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 15720 | 14 | retry-loop: failed (guard:consecutive_failures); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `attempts-2` | standard | yes | structured: 6 | no | 0/3 | 5 | 3 | 0 | 9 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 17430 | 16 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `attempts-4` | standard | yes | structured: 6 | no | 0/3 | 7 | 3 | 2 | 11 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 25230 | 18 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `guard-off` | standard | yes | structured: 6 | no | 0/3 | 9 | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 9300 | 9300 | 380100 | 82 | retry-loop: failed (verify_failed); status-loop: failed (verify_failed); handoff-loop: failed (verify_failed) |
| `profile-economy` | economy | yes | structured: 6 | no | 0/3 | 6 | 2 | 0 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 6070 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `profile-premium` | premium | no | lean: 3 | no | 0/3 | 6 | 2 | 0 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 6150 | 62250 | 16 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `tools-lean` | standard | yes | lean: 3 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 6150 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `tools-selection-off` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 9300 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |
| `tools-selection-local` | standard | yes | structured: 6 | no | 0/3 | 6 | 2 | 1 | 10 | 0 | 0 | 0 | 0 | 3 | 0 | 9300 | 8400 | 21330 | 17 | retry-loop: failed (guard:identical_commands); status-loop: failed (guard:identical_commands); handoff-loop: failed (guard:handoff_cycle) |

### `context-overload` (context-overload)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `planning-off` | standard | no | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 111819 | 15 | investigate: verified; handover: verified |
| `planning-auto` | standard | no | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 111819 | 15 | investigate: verified; handover: verified |
| `context-none` | standard | yes | structured: 6 | no | 0/2 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 2 | 0 | 3100 | 3100 | 42765 | 6 | investigate: failed (context_overflow); handover: not_executed (dependency_failed) |
| `context-elide-aggressive` | standard | yes | structured: 6 | no | 0/2 | 1 | 0 | 0 | 0 | 0 | 6 | 0 | 1 | 2 | 0 | 3100 | 3100 | 21132 | 8 | investigate: failed (info_loss); handover: not_executed (dependency_failed) |
| `context-elide-summarize` | standard | yes | structured: 6 | no | 1/2 | 2 | 0 | 0 | 0 | 0 | 3 | 2 | 1 | 1 | 0 | 6200 | 6200 | 98046 | 15 | investigate: verified; handover: failed (info_loss) |
| `routing-fixed-standard` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `routing-fixed-premium` | premium | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 586095 | 16 | investigate: verified; handover: verified |
| `parallel-3` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `attempts-1` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `attempts-2` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `attempts-4` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `guard-off` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `profile-economy` | economy | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 39073 | 16 | investigate: verified; handover: verified |
| `profile-premium` | premium | no | lean: 3 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 4100 | 559095 | 15 | investigate: verified; handover: verified |
| `tools-lean` | standard | yes | lean: 3 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 4100 | 117219 | 16 | investigate: verified; handover: verified |
| `tools-selection-off` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 6200 | 117219 | 16 | investigate: verified; handover: verified |
| `tools-selection-local` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 0 | 6200 | 5600 | 117219 | 16 | investigate: verified; handover: verified |

### `failing-test` (failing-test)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `planning-off` | standard | no | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 34704 | 12 | repair: verified |
| `planning-auto` | standard | no | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 34704 | 12 | repair: verified |
| `context-none` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `context-elide-aggressive` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `context-elide-summarize` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `routing-fixed-standard` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `routing-fixed-premium` | premium | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 195120 | 13 | repair: verified |
| `parallel-3` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `attempts-1` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 19512 | 7 | repair: failed (attempt_gate) |
| `attempts-2` | standard | yes | structured: 6 | yes | 1/1 | 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `attempts-4` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `guard-off` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `profile-economy` | economy | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 13008 | 13 | repair: verified |
| `profile-premium` | premium | no | lean: 3 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2050 | 173520 | 12 | repair: verified |
| `tools-lean` | standard | yes | lean: 3 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2050 | 39024 | 13 | repair: verified |
| `tools-selection-off` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 39024 | 13 | repair: verified |
| `tools-selection-local` | standard | yes | structured: 6 | yes | 1/1 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2800 | 39024 | 13 | repair: verified |

### `multi-file-feature` (multi-file-feature)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `planning-off` | standard | no | structured: 6 | no | 3/4 | 6 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 12400 | 12400 | 79002 | 22 | tests: blocked (dependency_unmet); model: verified; api: verified; cli: verified; docs: partial |
| `planning-auto` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `context-none` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `context-elide-aggressive` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `context-elide-summarize` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `routing-fixed-standard` | standard | yes | structured: 6 | no | 2/4 | 6 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 0 | 12400 | 12400 | 51258 | 23 | tests: not_executed (dependency_failed); model: verified; api: failed (tier_gate); cli: verified; docs: partial |
| `routing-fixed-premium` | premium | yes | structured: 6 | yes | 4/4 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 182115 | 18 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `parallel-3` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 23 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `attempts-1` | standard | yes | structured: 6 | no | 2/4 | 4 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 12400 | 12400 | 30546 | 15 | tests: not_executed (dependency_failed); model: verified; api: failed (tier_gate); cli: verified; docs: partial |
| `attempts-2` | standard | yes | structured: 6 | no | 2/4 | 5 | 1 | 0 | 1 | 0 | 0 | 0 | 0 | 1 | 0 | 12400 | 12400 | 40902 | 19 | tests: not_executed (dependency_failed); model: verified; api: failed (tier_gate); cli: verified; docs: partial |
| `attempts-4` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `guard-off` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `profile-economy` | economy | yes | structured: 6 | no | 2/4 | 6 | 1 | 0 | 2 | 0 | 0 | 0 | 0 | 1 | 0 | 12400 | 12400 | 17086 | 23 | tests: not_executed (dependency_failed); model: verified; api: failed (tier_gate); cli: verified; docs: partial |
| `profile-premium` | premium | yes | lean: 3 | yes | 4/4 | 5 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 10250 | 182115 | 18 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `tools-lean` | standard | yes | lean: 3 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 10250 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `tools-selection-off` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |
| `tools-selection-local` | standard | yes | structured: 6 | yes | 4/4 | 7 | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 15500 | 15500 | 98559 | 26 | tests: verified; model: verified; api: verified; cli: verified; docs: partial |

### `remote-diagnosis` (remote-diagnosis)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `planning-off` | standard | no | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 32310 | 12 | diagnose: failed (context_overflow) |
| `planning-auto` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `context-none` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `context-elide-aggressive` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 1 | 0 | 0 | 1 | 0 | 3100 | 3100 | 42252 | 14 | diagnose: failed (context_overflow) |
| `context-elide-summarize` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 7 | 0 | 0 | 0 | 3100 | 3100 | 46809 | 15 | diagnose: verified |
| `routing-fixed-standard` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `routing-fixed-premium` | premium | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 183150 | 13 | diagnose: failed (context_overflow) |
| `parallel-3` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `attempts-1` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `attempts-2` | standard | yes | structured: 6 | no | 0/1 | 1 | 1 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `attempts-4` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `guard-off` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `profile-economy` | economy | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 12210 | 13 | diagnose: failed (context_overflow) |
| `profile-premium` | premium | yes | lean: 3 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 2050 | 183150 | 13 | diagnose: failed (context_overflow) |
| `tools-lean` | standard | yes | lean: 3 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 2050 | 36630 | 13 | diagnose: failed (context_overflow) |
| `tools-selection-off` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 3100 | 36630 | 13 | diagnose: failed (context_overflow) |
| `tools-selection-local` | standard | yes | structured: 6 | no | 0/1 | 1 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 | 0 | 3100 | 2800 | 36630 | 13 | diagnose: failed (context_overflow) |

### `simple-fix` (simple-fix)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `planning-off` | economy | no | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1492 | 4 | fix: verified |
| `planning-auto` | economy | no | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1492 | 4 | fix: verified |
| `context-none` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `context-elide-aggressive` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `context-elide-summarize` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `routing-fixed-standard` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 5916 | 5 | fix: verified |
| `routing-fixed-premium` | premium | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 29580 | 5 | fix: verified |
| `parallel-3` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `attempts-1` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `attempts-2` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `attempts-4` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `guard-off` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `profile-economy` | economy | no | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1492 | 4 | fix: verified |
| `profile-premium` | premium | no | lean: 3 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2050 | 22380 | 4 | fix: verified |
| `tools-lean` | economy | yes | lean: 3 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2050 | 1972 | 5 | fix: verified |
| `tools-selection-off` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 1972 | 5 | fix: verified |
| `tools-selection-local` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2800 | 1972 | 5 | fix: verified |

### `tool-selection-miss` (tool-selection)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `planning-off` | standard | no | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 9984 | 7 | review: verified; split: verified |
| `planning-auto` | standard | no | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 9984 | 7 | review: verified; split: verified |
| `context-none` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `context-elide-aggressive` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `context-elide-summarize` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `routing-fixed-standard` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `routing-fixed-premium` | premium | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 62520 | 8 | review: verified; split: verified |
| `parallel-3` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `attempts-1` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `attempts-2` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `attempts-4` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `guard-off` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `profile-economy` | economy | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 4168 | 8 | review: verified; split: verified |
| `profile-premium` | premium | no | lean: 3 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 4100 | 49920 | 7 | review: verified; split: verified |
| `tools-lean` | standard | yes | lean: 3 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 4100 | 12504 | 8 | review: verified; split: verified |
| `tools-selection-off` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 6200 | 6200 | 12504 | 8 | review: verified; split: verified |
| `tools-selection-local` | standard | yes | structured: 6 | yes | 2/2 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 6200 | 5450 | 12504 | 8 | review: verified; split: verified |

### `two-file-change` (simple-fix)

| Config | Executor tier | Planned | Tools offered (profile: count) | Success | Criteria met | Attempts | Escalations | Tier escalations | Guard trips | Context overflows | Items elided | Items summarized | Information-loss failures | Unexecuted verifications | Tool-selection misses | Est. tool-definition tokens offered (approximate) | Est. tool-definition tokens selected (approximate) | Cost (simulated units) | Duration (simulated units) | Subtasks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `planning-off` | standard | no | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 7860 | 5 | rename: verified |
| `planning-auto` | standard | no | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 7860 | 5 | rename: verified |
| `context-none` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `context-elide-aggressive` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `context-elide-summarize` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `routing-fixed-standard` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `routing-fixed-premium` | premium | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 48300 | 6 | rename: verified |
| `parallel-3` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `attempts-1` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `attempts-2` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `attempts-4` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `guard-off` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `profile-economy` | economy | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 3220 | 6 | rename: verified |
| `profile-premium` | premium | no | lean: 3 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2050 | 39300 | 5 | rename: verified |
| `tools-lean` | standard | yes | lean: 3 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2050 | 9660 | 6 | rename: verified |
| `tools-selection-off` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 3100 | 9660 | 6 | rename: verified |
| `tools-selection-local` | standard | yes | structured: 6 | yes | 1/1 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3100 | 2800 | 9660 | 6 | rename: verified |

## Tool selection per subtask

Rows exist only for configurations with tool selection on. The script names the tool a step stands for; no tool is called. The tool-definition token columns above are sums of rough, hand-set constants per tool: estimates for comparison, not measurements for any model or client.

| Task / configuration | Subtask | Tools selected (after restores) | Tools dropped | Tools restored (misses) |
| --- | --- | --- | --- | --- |
| `agent-loop` / `tools-selection-local` | retry-loop | Read, Grep, Glob, Edit, Bash | Write | - |
| `agent-loop` / `tools-selection-local` | status-loop | Read, Grep, Glob, Edit, Bash | Write | - |
| `agent-loop` / `tools-selection-local` | handoff-loop | Read, Grep, Glob, Edit, Bash | Write | - |
| `context-overload` / `tools-selection-local` | investigate | Read, Grep, Glob, Edit, Bash | Write | - |
| `context-overload` / `tools-selection-local` | handover | Read, Grep, Glob, Edit, Bash | Write | - |
| `failing-test` / `tools-selection-local` | repair | Read, Grep, Glob, Edit, Bash | Write | - |
| `multi-file-feature` / `tools-selection-local` | tests | Read, Grep, Glob, Edit, Write, Bash | - | - |
| `multi-file-feature` / `tools-selection-local` | model | Read, Grep, Glob, Edit, Write, Bash | - | - |
| `multi-file-feature` / `tools-selection-local` | api | Read, Grep, Glob, Edit, Write, Bash | - | - |
| `multi-file-feature` / `tools-selection-local` | cli | Read, Grep, Glob, Edit, Write, Bash | - | - |
| `multi-file-feature` / `tools-selection-local` | docs | Read, Grep, Glob, Edit, Write, Bash | - | - |
| `remote-diagnosis` / `tools-selection-local` | diagnose | Read, Grep, Glob, Edit, Bash | Write | - |
| `simple-fix` / `tools-selection-local` | fix | Read, Grep, Glob, Edit, Bash | Write | - |
| `tool-selection-miss` / `tools-selection-local` | review | Read, Grep, Glob, Bash | Edit, Write | - |
| `tool-selection-miss` / `tools-selection-local` | split | Read, Grep, Glob, Edit, Write, Bash | - | Write |
| `two-file-change` / `tools-selection-local` | rename | Read, Grep, Glob, Edit, Bash | Write | - |

## Configurations

| Config | Planning | Context policy | Elide at | Summarize at | Keep recent | Min elide tokens | Max attempts | Max parallel | Routing | Guard | Executor tier | Tool profile | Tool selection |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | off |
| `planning-off` | off | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | off |
| `planning-auto` | auto | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | off |
| `context-none` | on | none | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | off |
| `context-elide-aggressive` | on | elide | 0.3 | 0.85 | 0 | 50 | 3 | 1 | policy | on | auto | structured | off |
| `context-elide-summarize` | on | elide_and_summarize | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | off |
| `routing-fixed-standard` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | fixed: standard | on | auto | structured | off |
| `routing-fixed-premium` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | fixed: premium | on | auto | structured | off |
| `parallel-3` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 3 | policy | on | auto | structured | off |
| `attempts-1` | on | elide | 0.6 | 0.85 | 3 | 200 | 1 | 1 | policy | on | auto | structured | off |
| `attempts-2` | on | elide | 0.6 | 0.85 | 3 | 200 | 2 | 1 | policy | on | auto | structured | off |
| `attempts-4` | on | elide | 0.6 | 0.85 | 3 | 200 | 4 | 1 | policy | on | auto | structured | off |
| `guard-off` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | off | auto | structured | off |
| `profile-economy` | auto | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | fixed: economy | on | economy | auto | off |
| `profile-premium` | auto | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | fixed: premium | on | premium | auto | off |
| `tools-lean` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | lean | off |
| `tools-selection-off` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | off |
| `tools-selection-local` | on | elide | 0.6 | 0.85 | 3 | 200 | 3 | 1 | policy | on | auto | structured | local |

## Limits

Every outcome above is decided by the script, its conditions and the configuration. The tables hold raw counts and rates; differences between rows describe how the harness components reacted to the same fixed trajectory and say nothing about whether a configuration helps a model finish a task.
