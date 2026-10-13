# ADR 0004: Decision providers, with JEV as an optional adapter

Portuguese version: [0004-decision-providers-and-jev.pt-BR.md](0004-decision-providers-and-jev.pt-BR.md).

Status: accepted (2026-10-13)

## Context

The brief asks for a vendor-neutral decision interface and for JEV as an optional first-class integration, without inventing capabilities. The JEV client found on the development machine (`jev.mjs`) was inspected on 2026-10-13. What it actually offers:

- Two commands: `jev ask --questions q.json (--state "text" | --state-file file)` and `jev batch --questions q.json --items items.jsonl --out results.jsonl`. There is no `--help`.
- Three question types: `noul` (yes or no), `choice` (2 to 255 options), `score` (2 to 10 levels).
- `ask` prints a JSON object of answers keyed by question. The client code does not define its shape: the remote service produces it, so it may change without notice.
- Every call sends the `state` text to a remote API. Exit code 0 means success, 1 an error, and 2 a batch with failed items.

## Decision

- Define `DecisionProvider` with seven methods: `classify_task`, `select_strategy`, `route_agent`, `evaluate_result`, `resolve_conflict`, `should_escalate`, and `select_tools` (added later, see Tool selection).
- Ship `LocalPolicyProvider`, a deterministic rule set with no network access. It is the default and the fallback.
- Ship `JevProvider` as an opt-in adapter that uses `jev ask` for `classify_task` and, when enabled, for `select_tools`, because typed questions map directly onto classification (`score` for complexity, `choice` for risk, `noul` for parallelism). The other five methods delegate to the local policy.
- The adapter parses the answers strictly, in the shape observed (see Observed answer shape). An answer it cannot interpret, a non-zero exit, a timeout or a missing binary all fall back to the local policy, and the fallback reason is recorded in the classification.
- Confidence is used conservatively. A `score` or `choice` answer with `confidence` below 0.6 (or none) is not trusted, and a `noul` value strictly between 0.35 and 0.65 is treated as uncertain; the local value is used for that dimension and a reason says so. The classification's `uncertainty` is the maximum of the local uncertainty and 1 minus the lowest confidence among trusted answers.
- An external provider may raise the locally computed risk level and may never lower it.

## Consequences

- The system works with no decision service configured.
- Enabling JEV sends the task objective to a third-party API. The adapter redacts secrets before sending, the configuration guide says so explicitly, and it is off by default.
- Tests use a fake `jev` executable that serves the recorded real response (`tests/fixtures/jev_ask_response_2026-10-13.json`) and derives its other modes from it. Live calls are not part of the test suite.
- Evidence label for classification: implemented; parser verified against one recorded real response; live calls are not part of the test suite.
- The JEV program is resolved like the executor resolves programs: a bare name is looked up only in `permissions.exec_path`, and an absolute path must be an existing, regular, executable file outside the run root. The safe-path rule is kept on purpose: a repository or an agent must not choose what runs by editing a file in a directory it controls. The cost is that a JEV installed in a user directory (`~/.local/bin`) is not found by its bare name, because `exec_path` holds system directories by default. When the program cannot be resolved the local policy is used and the reason is recorded in the classification or the tool selection: the program was not found on the allowed path, with the two fixes (set `decision.jev.command` to the program's absolute path, or add its directory to `permissions.exec_path`). `wev config validate` and `wev config show` print a warning when `decision.provider` is `jev` and the command does not resolve, so the fallback is no longer silent. A relative `decision.jev.command` with a directory component is rejected when the configuration is loaded. Evidence label: implemented and tested with a fake executable.

## Observed answer shape

On 2026-10-13 one real call was made: `jev ask --questions q.json --state "<text>"`, where `q.json` was the output of the adapter's `build_questions()` (three questions: `complexity` as `score` with 4 levels, `risk` as `choice` with `low`/`medium`/`high`, `parallelizable` as `noul`) and the state was a single synthetic input (renaming one local variable in a small Python utility with tests). Exit code 0, JSON on stdout, one object per question:

- `score`: `type`, `score` (0-based integer index into the levels), `confidence` (0 to 1), `legend`, `probabilities`.
- `choice`: `type`, `choice` (the option key), `confidence` (0 to 1), `probabilities`.
- `noul`: `type`, `noul` (a number from 0 to 1, read as the probability of yes). No `confidence` field in this sample.

This is a single observation made with one synthetic input. Fields beyond those above, and the behavior for other inputs, are unknown. Because the client does not define the shape, it may change without notice; the adapter validates types and ranges strictly and falls back to the local policy when anything deviates.

## Tool selection

Added on 2026-10-13. `select_tools(task, agent, available, tier)` chooses, per task, the smallest set of the agent's tools the task needs (hypothesis H10 in [hypotheses.md](../../research/hypotheses.md)). It runs only when `harness.tool_selection` is `local` or `provider`; the default is `off`. JEV is used only in `provider` mode with `decision.provider: jev`.

- **What is asked.** One `jev ask` call per task. One `noul` question per candidate tool that is not in the floor ("Does this task need the <tool> tool: <one-line description from the tool registry>?"), and one `choice` question for the tool profile (`structured` or `lean`, with both meanings spelled out) only when `harness.tool_profile` is `auto`.
- **What is sent.** The state text is the task's title, objective and acceptance criteria, passed through the same redactor as classification. No file contents, file names, repository data or command output are sent. Tool names and their one-line registry descriptions are part of the questions.
- **Conservative thresholds, and why.** Dropping a tool the task needed fails the task or costs a recovery, while keeping one it did not need only costs context. So a tool is dropped only when the `noul` value is at or below 0.2 (`DROP_THRESHOLD`); any higher value keeps it. A `choice` answer with confidence below the existing 0.6 trust threshold keeps the locally resolved profile. The floor (the read tools the agent had, the edit tool when the task changes files, the shell when the task has checks) is never asked about and never dropped.
- **What JEV cannot do.** Its answer passes the same function as the local policy's. It can only narrow the agent's allow list minus its deny list, it cannot add a denied or unlisted tool, and it cannot change permissions.
- **Failures.** A missing binary, a timeout, a non-zero exit, invalid JSON, a wrong shape or a missing answer fall back to the local selection with the reason recorded, exactly as classification does. More than 12 tool questions (`MAX_TOOL_QUESTIONS`) also use the local policy, without a call. Nothing is cached between calls.
- **Recovery.** A tool dropped by mistake is restored for a running task with `wev task tools TASK --add TOOL --reason TEXT`, only from the agent's candidate set, and the report counts it as a selection miss.
- **Evidence label: implemented; answer format verified against two real responses on 2026-10-13; not part of the test suite.** The answer shapes are the ones recorded for classification (`noul` as a number in [0, 1] without a `confidence` field, `choice` with `choice` and `confidence`). The two real observations are described under Observed tool-selection answers. Whether the service answers per-tool questions usefully, and whether selection saves tokens or keeps tasks succeeding, is not known. The token figures shown next to a selection are rough per-tool constants, labeled "estimated definition tokens (approximate)"; they are not a measured saving.

## Observed tool-selection answers

On 2026-10-13 two real `jev ask` calls were made for tool selection, each with one synthetic task. The responses were not saved as fixtures, so the test suite does not exercise them.

- A read-only review task: Write 0.06, Bash 0.26, WebFetch 0.36, WebSearch 0.14, and tool profile `structured` at confidence 0.56. That confidence is below the 0.6 trust threshold, so the locally resolved profile was used. Only Write (0.06) and WebSearch (0.14) are at or below the 0.2 drop threshold.
- A feature task: Write 0.76, Bash 0.58, WebFetch 0.06, WebSearch 0.12, and tool profile `structured` at confidence 0.86.

The `noul` answers carried no `confidence` field. These two calls verify the answer format for this use and nothing about token savings or task success.

## Independent judgment

`evaluate_result` and `resolve_conflict` exist so that a result can be judged by something other than its author. In the MVP the judge is the deterministic local policy over recorded evidence, plus an independent reviewer agent that the strategy requires for medium and high risk work. Several personas running on the same model are not statistically independent, and the documentation does not claim otherwise.
