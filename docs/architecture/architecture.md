# wev-skills architecture

Status: description of the MVP as implemented and tested (`make test`); how the pieces behave in a live Claude Code session has not been observed. Sections marked "future" are not implemented.
Portuguese version: [architecture.pt-BR.md](architecture.pt-BR.md).

## 1. Shape of the system

wev-skills has two layers.

- **Engine** (`src/wev_skills/`): a dependency-free Python package (Python 3.14+, standard library only) that holds every deterministic part of the harness: classification, strategy, agent specs, model routing, permissions, state, context budgeting, loop detection, command execution, verification, approvals, remote tmux control, tool selection and evaluation. It is driven through a CLI (`python3 -m wev_skills ...`, or `bin/wev`) that reads and writes JSON.
- **Adapters and skills**: thin, environment-specific pieces. The Claude Code adapter consists of the skills in `skills/` (Markdown instructions that tell Claude when to call the engine CLI), an exporter that renders agent specs into Claude Code subagent files, the CLAUDE.md guidelines block (`wev claude-md`, section 4.15), and three plugin hooks (`hooks/hooks.json`, section 4.14). The core (`core`, `decisions`, `security`, `state`, ...) never imports an adapter; only command modules do.

The model does the reasoning and the editing. The engine does the bookkeeping and applies the rules in code. This split exists because rules written only in Markdown can be ignored by a model, while a CLI that refuses to record an unapproved high-risk step does not depend on the model's wording.

What the engine is, and is not, is stated once and the rest of this document depends on it: **the engine is a guardrail for a fallible agent and a recorder of decisions. It is not a security boundary against an adversarial agent in the same user account.** The human gate is Claude Code's permission prompt, reached through the plugin's `PreToolUse` hook; without the hooks, approvals are records. The agent's own file tools can rewrite the state, the approvals, the audit log and the run registry. See [ADR 0006](decisions/0006-guardrail-not-boundary.md), [SECURITY.md](../../SECURITY.md) and section 4.5.

Delegation is centralized: the orchestrating session asks the engine for the next task contract, hands it to one agent, and records the result. Agents do not spawn agents through the engine.

## 2. Flow

`REQUEST → DISCOVER → CLASSIFY → PLAN → DECIDE → EXECUTE → VERIFY → REVIEW → DELIVER`

| Phase | Engine responsibility | Module |
|---|---|---|
| REQUEST | Create a run with objective and mode | `core.orchestrator`, `state.store` |
| DISCOVER | Record repository facts (git state, detected check commands) | `state.resume`, `core.discovery` |
| CLASSIFY | Score complexity, risk, uncertainty, scope | `decisions` |
| PLAN | Validate and persist the plan and its dependency graph | `core.planning`, `core.plan_flow` |
| DECIDE | Choose strategy, agent and model per task; gate on approvals | `decisions`, `agents`, `models`, `governance` |
| EXECUTE | Issue task contracts; run commands; watch for loops | `core.task_flow`, `core.task_exec`, `execution`, `guards` |
| VERIFY | Run checks, attach evidence, evaluate acceptance criteria | `core.task_exec`, `verification` |
| REVIEW | Require independent review when the strategy says so | `core.task_outcomes` |
| DELIVER | Produce the final report with evidence labels | `core.report`, `core.report_markdown` |

Modes: `plan` (no mutating step may be recorded or executed), `execute`, `auto` (flow chosen from the classification). A run starts in one of those three, and its mode never changes. Resuming is an operation on an existing run (`wev run resume`): it reloads the state and compares it with the real git state before continuing; the run keeps the mode it started with.

The *active run* is the run of a repository whose phase is not `done`. A repository has at most one: `wev run start` is refused (`run_active`, exit 5) while another is active. Commands that take `--run` default to the active run. `wev run finish` sets the phase `done`, after which the run can be read but not changed.

A run **pins its configuration** when it starts (section 4.13): every later command uses the pinned one and refuses a different `--config`.

## 3. Shared contracts (`core/contracts.py`)

All contracts are frozen dataclasses with `to_dict()` and a `from_dict()` classmethod. Enums are `str` enums so they serialize as plain strings.

```python
class RiskLevel(str, Enum): LOW, MEDIUM, HIGH            # values "low" | "medium" | "high"
class Complexity(str, Enum): TRIVIAL, SIMPLE, MODERATE, COMPLEX
class Mode(str, Enum): PLAN, EXECUTE, AUTO, RESUME
class Flow(str, Enum): DIRECT, PLANNED, GATED            # GATED = approval before impact
class TaskStatus(str, Enum): PENDING, READY, RUNNING, VERIFIED, PARTIAL, BLOCKED, FAILED, NOT_EXECUTED
class RunStatus(str, Enum): RUNNING, PASSED, FAILED, BLOCKED, UNKNOWN
class GuardAction(str, Enum): CONTINUE, CHANGE_STRATEGY, REDUCE_SCOPE, ESCALATE, ASK_HUMAN, STOP
class EvidenceLabel(str, Enum): TESTED, UNTESTED, MOCKED, DOCUMENTED_ONLY, BLOCKED

@dataclass(frozen=True)
class TaskSignals:            # input to classification
    objective: str
    files_touched_estimate: int = 0
    touches_remote: bool = False
    touches_production: bool = False
    destructive: bool = False
    external_side_effects: bool = False     # push, publish, send, deploy
    has_tests: bool = True
    reversible: bool = True
    unknowns: int = 0                       # count of open questions
    independent_subtasks: int = 1

@dataclass(frozen=True)
class Classification:
    complexity: Complexity
    risk: RiskLevel
    uncertainty: float          # 0.0 to 1.0
    parallelizable: bool
    reasons: tuple[str, ...]    # human-readable, one per rule that fired
    source: str                 # provider id, e.g. "local-policy" or "jev"

@dataclass(frozen=True)
class Strategy:
    flow: Flow
    needs_plan: bool
    needs_independent_review: bool
    needs_approval: bool
    max_parallel: int
    max_attempts: int
    reasons: tuple[str, ...]

@dataclass(frozen=True)
class TaskContract:
    task_id: str
    objective: str
    context: str
    scope: tuple[str, ...]
    exclusions: tuple[str, ...]
    constraints: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    checks: tuple[str, ...]            # commands expected to verify the work
    response_format: str
    permissions: tuple[str, ...]       # tool names granted
    agent_id: str
    model: str
    risk: RiskLevel
    # filled from the plan and the agent spec; all have defaults:
    check_links: tuple[CheckLink, ...] = ()    # checks tied to specific criteria
    required_checks: tuple[str, ...] = ()
    read_only: bool = False
    may_mutate: bool = True
    may_use_remote: bool = False
    max_attempts: int | None = None
    timeout_seconds: float | None = None
    budget_units: float | None = None
    success_criteria: tuple[str, ...] = ()     # instructions only
    stop_conditions: tuple[str, ...] = ()      # instructions only
    escalation: str = ""                       # instructions only

@dataclass(frozen=True)
class Evidence:
    kind: str            # "command" | "file" | "note" | "remote"
    summary: str
    ref: str = ""        # path to the full log or artifact
    exit_code: int | None = None
    label: EvidenceLabel = EvidenceLabel.UNTESTED

@dataclass(frozen=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    summary: str
    evidence: tuple[Evidence, ...] = ()
    changed_files: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
```

`core/errors.py` defines `WevError(code: str, message: str, details: dict)` and subclasses `ValidationError`, `PermissionDenied`, `ApprovalRequired`, `StateConflict`, `NotFound`, `GuardTripped`, `RemoteError`, `ProviderError`. `Mode.RESUME` exists as a value, but `wev run start` accepts only `auto`, `plan` and `execute`. The CLI maps a `WevError` to a JSON error on stderr and a non-zero exit code (see section 6).

## 4. Modules and their public interfaces

Every module below has tests under `tests/unit/` (and `tests/security/` or `tests/integration/` where noted).

### 4.1 `schema` (validation)

`schema.validate(instance, schema) -> list[str]` returns error strings with JSON-pointer paths (empty list when valid). `schema.load(name) -> dict` loads `src/wev_skills/schemas/<name>.schema.json`. Supported keywords: `type`, `enum`, `const`, `required`, `properties`, `additionalProperties`, `items`, `minItems`, `maxItems`, `uniqueItems`, `minLength`, `maxLength`, `pattern`, `minimum`, `maximum`, and local `$ref` into `$defs`. The schema files are valid JSON Schema (draft 2020-12) restricted to that subset, so external validators accept them too.

Schemas: `agent`, `config`, `plan`, `state`, `eval-task`.

### 4.2 `decisions`

```python
class DecisionProvider(Protocol):
    provider_id: str
    def classify_task(self, signals: TaskSignals) -> Classification: ...
    def select_strategy(self, classification: Classification, mode: Mode, executor_tier: str = "standard") -> Strategy: ...
    def route_agent(self, task: PlanTask, agents: Sequence[AgentLike], default_agent: str = "") -> str: ...   # returns agent id
    def evaluate_result(self, contract: TaskContract, result: TaskResult) -> Verdict: ...
    def resolve_conflict(self, verdicts: Sequence[Verdict]) -> Verdict: ...
    def should_escalate(self, history: Sequence[AttemptRecord], max_attempts: int | None = None) -> EscalationDecision: ...
    def select_tools(self, task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec], tier: str) -> ToolSelection: ...
```

`AgentLike` (`core.ports`) is anything with `id`, `description` and `specialties`; `AgentSpec` satisfies it.

- `decisions.local.LocalPolicyProvider(limits: LimitsConfig, harness: HarnessSettings | None = None)`: deterministic rules, no network, always available.
  - Classification: the explicit signals, plus a **lexical floor** (`decisions.lexicon`) read from the objective text in English and Portuguese: whole words and fixed phrases that name production, destructive operations, external effects, remote systems, credentials and data or schema changes. A hit raises the matching signal and is reported with the matched term. The floor never lowers anything and a flag cannot clear it. It is a word list: it has false positives and misses paraphrases.
  - Strategy: only the plan step depends on the executor tier and on `harness.planning`. With `auto`, economy plans anything above trivial, standard and premium plan from moderate complexity up, and any tier plans above low risk; `always` and `never` override; plan mode and gated flows always plan. Risk, approval, review and limits are the same for every tier, and the reasons name the tier and the rule. `models.router.executor_tier(configured, routed)` gives the tier: `harness.executor_tier`, or with `auto` the tier the router picked.
  - Routing: whole-word match (lower case, a small stop-word list, a trailing plural `s` ignored) between the task's title and objective and each agent; a specialty word weighs 3, a specialty matched in full 2 more, a description word 1; ties break by id. A task that is about remote systems keeps the agents with `may_use_remote`. When nobody scores above zero the task goes to `default_agent` if it is a candidate, else to the first id. `core.planning.default_agent` passes `agents.default_agent` (default `senior-engineer`) when that agent may change files, else the first candidate by id that may.
  - Escalation: `should_escalate` answers "escalate" after half of the attempts limit (rounded up) or on a repeated error signature, whichever comes first, so the stronger model still has an attempt left; at the limit it answers ASK_HUMAN.
  - Tool selection: `select_tools` (section 4.16).
- `decisions.jev.JevProvider(runner, local, command="jev", timeout_seconds=30.0, *, redactor, program_resolver=None)`: optional; runs the real `jev ask` CLI for `classify_task` and, through `decisions.jev_tools`, for `select_tools`; the other methods are the local policy's. The state sent to JEV goes through `redactor` first. The configured program is resolved on the same safe path the executor uses (`permissions.exec_path`, system directories by default) or must be the absolute path of an existing, regular, executable file outside the run root; when it cannot be resolved (the reason names the two fixes: an absolute `decision.jev.command`, or the directory in `permissions.exec_path`), or on any other failure (missing binary, non-zero exit, timeout, unparseable output), the call falls back to the local policy and records the reason.
- `decisions.factory.build_provider(config, runner, redactor) -> DecisionProvider`, chosen by `decision.provider` (`local` or `jev`).

Hard rule in every provider: a model or external service may raise the risk and the complexity computed by the local rules, never lower either, so it can never remove a review or an approval.

### 4.3 `agents`

- `agents.spec.AgentSpec`: frozen dataclass mirror of `agent.schema.json` (`schema_version`, `id`, `name`, `description`, `specialties`, `instructions`, `responsibilities`, `extends`, `model`, `model_policy`, `tools.allow`, `tools.deny`, `skills`, `permissions`, `budget`, `timeout_seconds`, `max_attempts`, `success_criteria`, `escalation`, `required_checks`, `output_format`, `stop_conditions`). Free-text fields are `LocalText`: a string or a `{"en": ..., "pt-BR": ...}` object; `spec.localized(lang)` resolves them. `model` is a concrete model id or a tier name.
- **Enforced by the engine** (`core.agent_rules` and its callers): `required_checks` (they join the task's checks and must pass), `budget.max_units` (the task's budget), `max_attempts` and `timeout_seconds` (the lower of the agent's and the run's wins), `permissions.may_mutate` (an agent with `false` may run through `wev exec` only read-only commands, the task's own declared checks and the check commands discovered at `run start`, by exact argv match; everything else is refused with `agent_read_only`, and those commands still go through the policy), `permissions.modes` and `permissions.max_risk` (an agent cannot take a task outside them), `permissions.may_use_remote` (checked by `wev remote start`), and `permissions.ceiling` (checked when specs are loaded). **Carried as instructions only**: `stop_conditions`, `success_criteria`, `escalation` and `output_format` reach the agent in its contract or its exported prompt and nothing in the engine checks them.
- `agents.registry.AgentRegistry(specs=())`: immutable. `discover(dirs)` and `register(spec)` return a new registry; `get(id)`, `list()`, `in`. Later directories override earlier ones, but a spec outside the built-in catalog cannot reuse a built-in agent id unless `agents.allow_override` is set; duplicates within one directory are an error. `agents.directories` must stay inside the repository or the user's configuration directory.
- `agents.factory.AgentFactory(registry)`: `resolve(spec) -> AgentSpec` (applies `extends`, detects cycles, fills conservative permission defaults), `create(template_id, overrides) -> AgentSpec`, `child_data(template_id, overrides) -> dict`, `compose(ids) -> list[AgentSpec]`, `validate(data) -> list[str]`. Conflict rules: a tool in both allow and deny is denied and a child cannot drop a parent's deny entry. Permissions are plain inheritance (the child's value wins) unless an ancestor sets `permissions.ceiling: true`; from there on every descendant must stay within that ancestor's `modes`, `max_risk`, `may_mutate` and `may_use_remote` and cannot unset the ceiling (`permission_widening`, `ceiling_unset`). `base-reviewer` and the read-only reviewers set a ceiling.
- `agents.registry` remembers the file each spec came from (`source(id)`), and skips, with an entry in `skipped`, any `*.json` that is not an object or has neither `schema_version` nor `id`; a file that has either must be a valid spec.
- `agents.tool_profile`: `resolve_profile(profile, tier)` and `apply_profile(tools, permissions, profile)`. `structured` (default of `harness.tool_profile`) keeps the allow list, because individually permission-checked tools are easier to govern; `lean` reduces an agent that may mutate and has `Bash` to `Bash`, `Read` and `Edit` as far as it had them, an option motivated for strong models on cost grounds only; `auto` is `lean` for the premium tier. A profile never adds a tool, never changes the deny list or the permissions. It is applied to task contracts and by `wev agent export`.

### 4.4 `models`

`models.router.ModelRouter(models_config).select(classification, agent_model=None, agent_tier_bounds=None, attempt=0, unavailable=()) -> ModelChoice`. Tiers `economy`, `standard`, `premium` map to concrete model ids in configuration. High risk or `COMPLEX` selects `premium`; failures beyond the first move up one tier each; `agent_tier_bounds` clamps the result; a pinned `agent_model` wins while it is available; an unavailable model falls to the next entry of its tier, then to a neighbouring tier. `ModelChoice` carries `model`, `tier`, and `reasons`.

### 4.5 `tools` and `security`

- `tools.registry.ToolRegistry` (immutable; `default()`, `of(specs)`, `register(spec)`, `get(name)`, `list()`) holds `ToolSpec(name, mutating, remote, network, min_risk_for_approval, description)` and a rough per-tool definition size used only for the tool-selection estimates.
- `security.permissions.PermissionPolicy(permissions_config, tool_registry=None, approvals=None)` implements the `CommandGate` port:
  - `check_command(argv, cwd, mode, risk, *, consume=True) -> PermissionDecision` with outcome `ALLOW`, `DENY` or `NEEDS_APPROVAL` and a reason. `plan` mode denies everything that is not on the read-only list (`security.readonly`: common diagnostics, refused with options that write, execute, reach another machine or change state; `sed`, `awk`, `tee`, `xargs` and `env` are never on it); an argument naming a protected path is denied; when a grant is what allows the command, `consume=True` spends it.
  - `resolve_program(argv, cwd)` looks a bare program name up only in `permissions.exec_path`, never in `$PATH`, refuses a program that resolves inside the run's working tree, and treats a program named by a relative path as needing approval.
  - `enforce_command(...)` raises `PermissionDenied` or `ApprovalRequired` instead of returning.
  - `check_tool(tool, mode, risk, agent_tools_allow=(), agent_tools_deny=(), *, consume=True) -> PermissionDecision`.
  - `check_path(path, cwd) -> PermissionDecision` denies a protected path named outside an argv (a redirection target).
- `security.shell.split_commands(line) -> tuple[SimpleCommand, ...] | None` splits a shell command line at its control operators, respecting quotes, and lifts redirections out of each argv. It returns `None` for anything it cannot split with certainty. Only the Bash hook uses it; the executor never runs a shell.
- `security.commands`: `parse(command, allow_shell=False) -> tuple[str, ...]` (rejects shell metacharacters unless the policy allows a shell), `expand(argv) -> Expansion` (unwraps `sudo`, `env`, `sh -c`, `nohup`, `timeout`, `script`, `nice` and similar), `classify(argv) -> CommandRisk` (`destructive`, `external_effect`, `privileged`, `network`, `unanalyzable`), and pattern helpers `matches`, `first_match`, `is_allowed`. Classification covers unique-prefix abbreviations of git long options, git configuration given on the command line and unknown git subcommands. `ssh`, `scp` and `sftp` are external effect, so they need approval as local commands.
- `security.paths`: `resolve_within(root, path) -> Path` raises `PermissionDenied` on traversal or symlink escape; `is_protected(path, root, protected_paths) -> bool`.
- `security.redact`: `redact(text) -> str`, `redact_mapping(mapping) -> dict` and `redact_argv(argv)` mask secrets before anything is logged or stored; `redact_argv` looks at the argv as a whole (values after secret-named flags, `Authorization` headers, URLs with credentials), also on refused paths, and any audit event that stores a list under the key `argv` is masked as one command line. `tests/integration/test_refused_redaction.py` searches every file under the state directory for a canary after allowed, denied, approval-required and guard-refused executions, for the event types `exec.ran`, `exec.denied`, `exec.approval_requested`, `guard.tripped`, `task.checked`, `approval.requested` and `task.recorded`. Redaction is best effort and has known misses (see [SECURITY.md](../../SECURITY.md)).
- `security.untrusted`: `wrap(text, source, nonce=None) -> str` fences external content as data; `scan(text) -> tuple[Finding, ...]` reports instruction-like patterns, which only informs. `core.textsafe` strips control characters and escape sequences first. Command output tails, remote capture, the run brief, the report and the discovery output returned by `wev run start` (check commands and file names read from the repository) are cleaned and fenced this way.

`config.protect_state_dir(config, base=None)` adds the state directory to `permissions.protected_paths` whatever the configured list says; `load_config` applies it. Approvals live there, so a command that could write them could approve itself. This protects against a command that names the path; it does not stop the agent's own file tools (section 4.10).

### 4.6 `state`

`state.store.StateStore(run_dir, clock=None)` persists `state.json` (validated against `state.schema.json`, carries `schema_version` and an integer `revision`) and an append-only `events.jsonl`. Runs live under `<state_dir>/runs/<run_id>/` (`run_dir`, `list_runs`, `active_run`, `new_run_id`). The state directory resolves at the repository root, not at the current directory; it has its own `.gitignore`, directories are created with mode 0700 and files, lock files included, with mode 0600. State written by an earlier layout does not load (`state_version_unsupported`).

- `create(objective, mode, run_id=None, config, config_digest, config_source) -> RunState`, `load() -> RunState`, `update(mutator, expected_revision=None) -> RunState`, `append_event(type, data)`, `events()`.
- Writes take an exclusive lock file (waiting at most `limits.lock_timeout_seconds`), re-read, check the revision, write to a temporary file, `fsync`, then `os.replace`. A revision mismatch raises `StateConflict`. `core.engine.Engine.commit(change, ..., base=state)` makes a write **conditional on the revision that was loaded and validated**: a change made by another process in between is refused, and the caller repeats read, validate and write a bounded number of times (`Engine.retry`).
- `state.model.RunState` is frozen. Changes are pure helpers that return a new state (`with_plan`, `with_task_status`, `with_result`, `with_attempt`, `with_decision`, `with_command`, `with_evidence`, `with_guard_event`, `with_pending_approval`, `with_remote_run`, `reopen`, ...). `with_task_status` enforces the legal task transitions and that dependencies are verified. `RunState` carries the pinned configuration (`config`, `config_digest`, `config_source`) and the remote runs the run started (`remote_runs`, an optional field, so states without it load).
- `state.records`: `VerificationRecord`, `ReviewRecord`, `TaskBaseline`, `ToolMiss`, stored in `RunState` and its task records.
- `state.resume`: `snapshot_repo(root, runner) -> RepoSnapshot | None` and `check_drift(state, runner, root=None) -> DriftReport`, which compares recorded HEAD, branch, dirty files and reported files with the real repository and lists tasks still recorded as running.
- `core.run_registry`: a per-user file (`$XDG_STATE_HOME/wev-skills/active-runs.json`, else under `~/.local/state`) listing the repository root, state directory and id of each active run, so that the hook can find a run from a path named in a command. It is a convenience for the hook; the agent's file tools can edit it (section 4.14).

### 4.7 `context`

`context.manager.ContextManager(budget_tokens, elide_at=0.6, summarize_at=0.85, summarizer=None, archive_dir=None, min_elide_tokens=200, keep_recent=3)` is immutable.

- `add(item) -> ContextManager`, `usage() -> float`, `total_tokens() -> int`, `render() -> list[ContextItem]`, `recall(item_id) -> str`, `compact() -> tuple[ContextManager, CompactionReport]`. `recall_archived(archive_dir, item_id)` reads an archived original without a manager.
- Items have a `kind` (`requirement`, `decision`, `error`, `evidence`, `tool_output`, `note`). Requirements, decisions and evidence are pinned and are never elided or summarized.
- Stage 1 (at `elide_at`): replace the oldest large `tool_output` items with a stub that points to the archived original. Stage 2 (at `summarize_at`): call the injected summarizer on remaining unpinned items. With no summarizer, stage 2 is skipped and reported.
- **Who uses it.** `wev context compact` and `wev context recall` (a JSON file of items in, a compacted list and a report out), and the evaluation harness. The orchestration flow (`wev run`, `wev task`) does not use it. It manages only the context that a caller hands to it; it does not and cannot control Claude Code's own context window.

### 4.8 `guards`

`guards.execution.evaluate(events, limits, now=None, unresolved_dependencies=()) -> GuardVerdict` is a pure function over recorded `GuardEvent`s (`command`, `agent_handoff`, `task_attempt`, `verification`, `progress`, `budget`, `reset`; built with `command_event`, `handoff_event`, `attempt_event`, `verification_event`, `progress_event`, `budget_event`, `reset_event`). `ExecutionGuard(limits).observe(history, event) -> (new_history, GuardVerdict)` appends and judges. `GuardLimits.from_config(limits_config)` takes the thresholds from configuration (`GuardLimits().task_timeout_seconds` and `LimitsConfig().task_timeout_seconds` share `config.DEFAULT_TASK_TIMEOUT_SECONDS`, 3600); an agent spec lowers `max_attempts` and `timeout_seconds` for its task and sets the task's budget (`core.agent_rules.task_limits`).

It detects identical repeated commands, **alternating command cycles** (for example A, B, A, B with no progress), consecutive failures, exhausted attempts and repeated errors, agent hand-off cycles, no observable progress (read-only `wev exec` commands do not count toward the no-progress window, though a repeated identical command is still a loop, and reading in plan mode does not trip `no_progress`), budget and timeout overruns, unresolved dependencies, repeated verification with no change in between, and **polling** beyond `limits.max_polling_commands`. Commands flagged `polling=True` are exempt from the repetition rule only for a running task that has already run a command, and the cap above still applies; a flaky-test allowance is configurable. The guard never stops anything itself: it returns a verdict (`action`, `rule`, `reasons`, `details`) and the caller decides.

In a run, the engine feeds it real events: every `wev exec` and every check is a command event with a working-tree fingerprint, a progress event is added when the fingerprint changes, command and check executions spend budget units, and each recorded attempt adds an attempt event. While a task's or the run's verdict is STOP or ASK_HUMAN, `wev exec` and `wev task check` are refused (`GuardTripped`, exit 6) and `wev task next` hands out no work. Every trip is stored in the run (`guard_trips`) and stays in the report. Only a person clears it with `wev guard acknowledge` (section 4.10).

### 4.9 `execution` and `verification`

- `execution.executor.CommandExecutor(gate, runner, log_dir, redactor, clock=None, resolver=None)`.`run(command, cwd, mode, risk, timeout=None, task_id=None, track_changes=True) -> CommandRecord` with `argv`, `cwd`, `duration_ms`, `exit_code`, `status: RunStatus`, `stdout_ref`, `stderr_ref`, `stdout_tail`, `stderr_tail`, `changed_files`, `timed_out`, `task_id`, `started_at`, `program`. It asks the gate first and raises `PermissionDenied` or `ApprovalRequired`. The program is resolved on the fixed safe path (`permissions.exec_path`) and the **resolved path is recorded** in `program`; the argv is redacted as a whole before it is logged or returned; output is redacted before it is written, and the tails are cleaned and fenced as untrusted data. The child process inherits the caller's environment. A `Runner` protocol wraps `subprocess` so tests inject a fake. A timeout yields `UNKNOWN`, never `PASSED`; a command that could not start is `BLOCKED`. `to_evidence(record, label)` and `to_guard_event(record, polling, flaky)` convert a record.
- `verification.engine.VerificationEngine(executor).verify(contract, checks, cwd, mode, stop_on_failure=True, manual_evidence=(), baseline_passed=None, tree_unchanged=False) -> VerificationReport`: runs checks cheapest first, stops early on failure when configured, and marks each acceptance criterion as `met`, `unmet` or `unverified`. A criterion with no evidence is `unverified`; `all_met` is false when there are no criteria. `checks_from_contract(contract)` builds the checks and `build_result(contract, report, changed_files, manual_evidence=())` a `TaskResult`.
- What counts as evidence for a criterion (`verification.engine`, `verification.trivial`, `core.evidence`):
  - A check that **a plan tied to the criterion** (a check object with `criteria`) supports only those criteria. A plain command string supports every criterion and is labeled **untied**: weaker evidence, and the report and the warnings say so.
  - A **no-op check** (`true`, `:`, `echo`, `printf`, `test` on constants, `sh -c 'exit 0'` and similar, recognized in `verification.trivial`) carries no evidence. This is a floor, not a proof: a cleverer vacuous check is not caught, and the engine does not judge whether checks are sufficient.
  - A check that **already passed at the task's baseline**, with no change to the working tree since the task started, carries no evidence. A read-only task is exempt.
  - **Manual evidence** (`wev task record --evidence-file`) counts for a criterion only when it is labeled tested and its `ref` is an existing file under the run's log directory, under the run's evidence directory (`<state dir>/runs/<id>/evidence/`) or one of the files the task lists in the plan; any other existing file is refused and the error says so (to show a file or an output, run it through `wev exec` and reference the log). It is the agent's claim and the report labels it so.
  - `verified` also needs the working-tree fingerprint, **recomputed at `task record`**, to equal the one the passing verification saw (`tree_changed` otherwise). A verified task that is not `read_only` and changed no file since it started does not make the run complete.
- `core.baseline`: at `task start` the task's checks run once as a baseline (`harness.baseline_checks`, default on), through the same executor and policy and without spending an approval. The commands are marked baseline in the log and are not guard events. With the setting off, only the starting fingerprint is recorded.

### 4.10 `governance`

- `governance.approvals.ApprovalStore(path, clock=None, ttl=...)`: `request(action, risk, reason, requested_by, cwd=..., reopen_denied=False) -> ApprovalRequest`, `grant(id, by, terminal)`, `deny(id, by, terminal)`, `get(id)`, `list(status=None)`, `is_granted(action, cwd)`, `is_denied(action, cwd)`, `consume(action, cwd) -> bool`, `verify() -> tuple[Mismatch, ...]`. Statuses: `pending`, `granted`, `denied`, `consumed`, `expired`.
  - A grant is bound to the exact argv (token for token), the resolved working directory and the run (for a remote action the first token is the host alias). It is **single-use**, **expires** after `permissions.approval_ttl_seconds` (default 900) and the execution that uses it consumes it. There are no reusable grants.
  - A denial is final for that action in that run. "The same action" means the same words in the same order within the run: every token of the argv is split like a command line and blank tokens are dropped, so the working directory, the stated risk, the reason, quoting, whitespace and token grouping do not produce a fresh request; `wev approval request` returns the denied record and `wev exec` answers denied. For a remote action the host alias is the first word, so a denial is per host. A new run starts clean. The comparison is on words and does not resolve paths (`build` and `./build` differ), and the record is a file in the agent's account. Only `wev approval request --reopen-denied`, a human-operator command, replaces it with a fresh pending request.
  - A request records `requested_by`, a name the caller supplies (self-declared); a decision records the operating-system user, the terminal device and the time. Nothing compares the two, because inside one account the engine cannot tell requester from operator.
  - A command whose text redaction would alter is **refused** instead of being sent for approval, so the operator sees exactly what would run.
  - `approval grant`, `approval deny`, `guard acknowledge`, `task reopen` and `approval request --reopen-denied` are **human-operator commands**: they need a terminal on stdin and stdout, show the full action and ask for a word printed on the screen. There is no flag that bypasses this. The record holds the operating-system user, the terminal device and the time, not an identity. An agent that needs one stops and asks the person to run it in their own terminal.
  - **Tamper evidence, not proof.** Every decision is also appended to the audit log, a grant is honored only when a matching `approval.granted` event exists there, and `wev approval verify` lists mismatches (exit 1). That catches accidents and a grant written straight into `approvals.json`. It does not catch an agent that rewrites both files with its own tools.
- `governance.audit.AuditLog(path, clock=None)`: `append(event_type, data)` writes one redacted JSON line; `read(limit=None)`.
- Why the files are not protected from the agent: the engine runs in the same user account as the agent it constrains, so it cannot authenticate who is typing and any key it kept in that account could be read by the agent. The gate a person can rely on is Claude Code's own permission prompt, reached by the hook (section 4.14). Without the hooks, approvals are records. See [ADR 0006](decisions/0006-guardrail-not-boundary.md).

### 4.11 `remote` (optional)

- `remote.inventory.Inventory`: the allowed SSH aliases and their environment label (`staging`, `production`, ...). Hosts not in the inventory are refused.
- `remote.transport.SshTransport(runner, connect_timeout=10, redactor=None)`: builds `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=<n> -- <alias> <command>`; never passes passwords or key material.
- `remote.tmux.TmuxController(transport, inventory, gate, approval_check, redactor, clock, base_dir="~/.wev/remote", command_timeout=30.0)`: `preflight(alias)`, `start(alias, task_id, argv, mode, risk, timeout_seconds=None) -> RemoteRun`, `status(alias, task_id) -> RemoteStatus`, `capture(alias, task_id, lines=200) -> str`, `stop(alias, task_id)`, `list_owned(alias)`. Session names are `wev-<task>-<hosthash>`; ownership is proven by a marker option set at creation; unknown sessions are never touched; `kill-server` is never issued.
- Approval logic lives in `governance`, not here: the gate, the approval check and the approval requester are injected. A start is governed by the controller's own checks, in order: inventory, mode (`plan` refuses), the gate on the remote argv, a read-only check for hosts without `allow_mutating`, and a grant for the exact action `<alias> <command>` when the gate asks for approval or the host is production. When the grant is missing the controller files the approval request for that host-qualified action (so it can never be satisfied by an approval of the same command run locally) and raises `ApprovalRequired` with `approval_id` and a `next_step` for the human. The controller's `ssh` is transport, not a command run through the executor, so the rule that a local `ssh` needs approval does not apply to it.
- **During an active run** (`remote.run_scope`): the mode, the risk and the host inventory come from the run and the command line can only repeat them or be more restrictive; a different `--config` is refused; a `--task` must be in the run's plan and its agent must have `permissions.may_use_remote`. Without a run, `--mode` is required for `start`.
- **Run records.** With an active run, a start is recorded in the run's state (`RunState.remote_runs`, written with `with_remote_run`), one record per task and host. Without an active run nothing is recorded. `status` trusts an exit file only with matching ownership: the session still exists and carries this task's marker, or, once it is gone, a recorded start of this task on this host exists; otherwise the answer is `unknown` and names the missing evidence. A damaged record is an error, not an empty list.
- Captured output is cleaned, redacted and fenced as untrusted remote data before the CLI returns it.

### 4.12 `evaluation`

`evaluation.harness.run(tasks, configs, agent=ScriptedAgent) -> EvalReport`. Tasks are JSON fixtures in `evals/tasks/`. The default agent is a deterministic script, so the harness itself is testable without a model. It runs the real context manager, execution guard, model router and local decision policy; it has its own attempt loop and scheduler and does **not** call the orchestration engine, so baselines, approvals, the permission policy and the verification engine are not exercised by its results. Metrics: success rate, acceptance criteria met, attempts, escalations, guard trips, context overflows, unexecuted checks, tool-selection misses, estimated tool-definition tokens (offered and selected), simulated cost and duration. See [evals/README.md](../../evals/README.md).

### 4.13 `core`: wiring and orchestrator

`core.wiring` is the composition root. From a `Config` and a repository root it builds the real collaborators: `build_approval_store`, `build_audit_log`, `build_policy` (policy plus approval store and tool registry, state directory protected), `build_executor` (redacting), `build_provider` (through `decisions.factory`, so `decision.provider` takes effect), `build_model_router`, `build_agents -> AgentCatalog` (registry, factory, template ids), `build_remote_controller`, and `build_services -> Services`, which bundles them for one CLI invocation. A relative `state_dir` is taken from the repository root.

**Configuration resolution and pinning** (`config.resolve_config`). Outside a run, the configuration is `--config PATH` if given, else `<repository root>/wev.config.json` if it exists, else the defaults. `wev run start` stores the effective configuration, its digest and its source in the run state; every later command of that run uses the stored one, and a `--config` whose content differs is refused (`config_pinned`). `wev config show` resolves the configuration the same way (and prints its source, the pinned configuration while a run is active for the directory, and warnings); `wev config validate PATH` checks that file under the same rules. A configuration may not name a program or a directory the repository controls: `decision.jev.command` is a bare program name (not a shell or an interpreter) or an absolute path outside the repository, and `agents.directories` stays inside the repository or the user's configuration directory.

`core.orchestrator.Orchestrator(store: StateStore, services: Services)` is a service over one run. Each method performs one validated transition and returns plain data for the CLI; nothing is kept between calls. Every change goes through `StateStore.update` and appends one audit event, and text is redacted before it is stored.

| Method | Command | Rule it enforces |
|---|---|---|
| `start(objective, mode, signals, run_id=None)` | `wev run start` | Refused while another run is active (`run_active`); pins the configuration; snapshot, discovery, classification and strategy are each recorded as a decision with reasons; the discovery output is returned sanitized and fenced as untrusted data |
| `status()` | `wev run status` | Read-only |
| `set_plan(path)`, `show_plan()` | `wev plan set`, `wev plan show` | Plan schema and `Plan.validate()`; checks may be strings or objects that tie a command to criteria; an agent (`agent_hint`, else `route_agent`) and a model per task, both recorded; a task's own risk can only raise its effective risk; a plan may not drop a task that already ran; for a task that has ever been started, changing its criteria, checks, files, risk or `read_only` flag needs `--amend --reason <text>` (recorded as a decision and a `plan.amended` audit event, resets that task's verification, listed in the report under "Plan amendments"; the engine does not judge whether the new criteria are weaker); prints `warnings` for a check that will need approval at execution time (for example inline interpreter code such as `python3 -c ...`), a check that will be refused, and a path git ignores |
| `next_tasks()` | `wev task next` | Refuses in `plan` mode and on a guard verdict of STOP or ASK_HUMAN; offers at most `max_parallel` tasks, none with unverified dependencies, never two whose `files` overlap (a task with no `files` runs alone); a gated or high-risk task waits for a human grant; computes the tool selection of each offered task when `harness.tool_selection` is on |
| `start_task(task_id)` | `wev task start` | Same rules; spends the grant; every start counts as an attempt and is refused past the limit; records agent, model, a hand-off guard event and the baseline (`core.baseline`) |
| `exec_command(argv, task_id, timeout, polling, flaky)` | `wev exec` | The command runs under the run's mode and the task's risk; refused while a STOP or ASK_HUMAN verdict stands; in an execute run the command acts for a task that is `RUNNING`: `--task` must name one (otherwise refused, naming the running tasks), without `--task` the only running task is used and the output says so (`task_implied: true`, `task_note`), and with none or several running only read-only commands are accepted; a `may_mutate: false` agent is limited as described in section 4.3; log entry and guard events are stored |
| `check_task(task_id, stop_on_failure)` | `wev task check` | Same guard refusal; stores the verification report, its evidence, the baseline state and guard events with a working-tree fingerprint |
| `record_task(task_id, status, summary, ...)` | `wev task record` | `verified` needs every criterion met by a fresh passing verification or by manual evidence with a real file ref, and an unchanged tree (section 4.9); `failed` needs a running task; a failure records an attempt with an error signature and asks `should_escalate`; when the attempts are used up the task becomes `BLOCKED` |
| `review_task(task_id, reviewer, accepted, summary)` | `wev task review` | The reviewer must be a known agent other than the one that ran the task; its identity is self-declared; a rejection reopens the task |
| `reopen_task(task_id, reason, ...)` | `wev task reopen` | Human operator only. Sends a blocked, failed or partial task back to `PENDING` with its attempt count reset; the history stays |
| `restore_tool(task_id, tool, reason)` | `wev task tools --add` | Only a tool the agent is allowed and that selection dropped, for a running task; counted as a selection miss |
| `guard_check(task_id=None)` | `wev guard check` | Read-only |
| `resume()` | `wev run resume` | Drift is recorded as a decision; a task recorded as running must be checked again before `verified` |
| `report(lang=None)` | `wev run report` | Read-only; `complete` only when every task is verified (and, if not read-only, changed something) and every required review accepted; guard trips and acknowledgements are listed. The tree is compared with the one at the latest `verified` record when the report is computed (also at `run finish`): if it differs and no task is running, verified tasks whose checks have not passed on the current tree are reported as "verified, then changed" and the status is `incomplete` until `wev task check` passes again. It is recomputed at report time, not continuously |
| `brief(max_chars=None, lang=None)` | `wev run brief` | Read-only; plain text within the limit, never cutting a line, fenced as data |
| `finish()` | `wev run finish` | Sets phase `done` with a decision saying whether the run was complete; every later change to the run is refused (`run_finished`) |

Attempts: every task start counts. Escalation to a higher model tier fires at half the limit (rounded up) or on a repeated error signature; at the limit the task is `BLOCKED` and only a person can reopen it.

Supporting modules: `core.discovery` (`discover_checks(root)` reads `Makefile`, `package.json`, `pyproject.toml`, `Cargo.toml` and `go.mod` as data and suggests commands from a fixed vocabulary; nothing is executed), `core.planning` (plan loading, synthesis of a single task when the strategy needs no plan, agent and model assignment, task selection, `build_contract`), `core.progress` (pure questions about a state: effective risk, fresh verification, review status, guard verdict, `next_steps`), `core.evidence`, `core.baseline`, `core.task_reopen`, `core.tool_select`, `core.report` and `core.report_markdown`.

Every output carries `next_step` (the first) and `next_steps` (a list of everything that can be done now): concrete command lines, or, when only a person can act (an approval, a task whose attempts are used up), an instruction to stop and ask the human operator. An instruction is also printed for: a pending approval; a denied gate ("denied by the operator", reopened with `wev approval request --reopen-denied`, never a grant command); an exhausted task (all attempts used, blocked), whose primary step is to ask the human to run `wev task reopen` and which cannot be recorded `not_executed`; plan mode once the plan is set ("ready for human review"; execution needs a new run in execute mode after `wev run finish`); and a check on a tree nothing changed in (do the work, or mark the task `read_only` with `--amend --reason`). A stale approval (its check was replaced and `task check` reports `all_met`) does not block `next_step` and is listed under `stale_approvals`. The engine never prints a grant command line as a step an agent could run. `core.brief` builds the plan reminder from a state: objective, phase, one line per task, the current task's acceptance criteria, pending approvals and the next step, fitted to a character limit by dropping whole lines, least important first, and fenced as data. When the guard only advises a change of strategy for a repeated command and the same command keeps running, `core.progress.task_verdict` turns the verdict into ASK_HUMAN so that `next_tasks` stops handing out work.

### 4.14 Claude Code hooks (`adapters.claude_code.hooks`, `adapters.claude_code.bash_guard`, `commands.hook`, `hooks/hooks.json`)

Three hooks run `wev hook <name>`, each reading the hook JSON on stdin (at most 1 MiB).

| Hook | Event and matcher | What it prints |
|---|---|---|
| `session-context` | `SessionStart`, `compact\|resume` | One line saying the text is the recorded state of the run and that `wev run resume` checks the real state, then the brief (fenced, sanitized) |
| `prompt-reminder` | `UserPromptSubmit` | The brief capped at `harness.plan_reminder_max_chars`, when `harness.plan_reminder` is true |
| `pre-tool-use` | `PreToolUse`, `Bash` | A `deny` or `ask` decision as one JSON object, or nothing |

- **Finding the run.** From the hook's `cwd`, its enclosing directories up to the git root, and every path the command names (`cd`, `pushd` and `git -C` are followed), using `core.active.find_active_run` and the per-user run registry. Looking is read-only and creates nothing. The work is capped.
- **Bash pre-check.** The command is judged under the active run's **pinned** configuration, mode and the highest risk among its running tasks, without consuming approvals and **without reading the approval store**: a destructive command is `ask` every time and the person's answer in Claude Code's prompt is the approval for that call. Policy DENY becomes `deny`; NEEDS_APPROVAL becomes `ask`; ALLOW prints nothing. The hook never answers `allow`, so it can only tighten the user's permission settings.
- **What it routes to the human.** The engine's own sensitive commands, when the command line is one the hook can read: `approval grant`, `approval deny`, `approval request` (with or without `--reopen-denied`), `guard acknowledge`, `task reopen`, `run start`, `run finish`, `agent create`, `agent export`, `remote start`, `remote stop`, and anything carrying `--config`, recognized by words (the launcher by real path, the bare word `wev`, or `-m wev_skills`) directly, behind a wrapper the classifier knows, in an inline `sh -c`, `bash -c` or `zsh -c`, or as arguments handed to another program. The exemption from the ordinary policy still applies only to a program that resolves by real path to the plugin's `bin/wev` or to the running interpreter with `-m wev_skills`. The hook cannot see inside a script file or a program, so a script that types into a pseudo-terminal is not asked about. It also asks for abbreviated `rm` long options, `git rm -r`/`-f`, `git clean` that is not a dry run, `rsync --delete*` and a recursive reader given a directory that contains a protected path: a heuristic over a fixed list, capped at 20,000 entries. Assignments of shell variables before a command, the shell words that set variables, unresolved shell expansions, `eval`, `source`, wrappers it cannot analyze and one argument that holds a whole command line give `ask` (`deny` in plan mode). The full list is in [SECURITY.md](../../SECURITY.md).
- **Failure policy.** Silent only while no run is known. Once a run is known, an unreadable or forged state, an internal error, malformed or oversized input and a command too long to analyze become `ask` with a reason, never silence. `bin/wev` exits quietly, with a note on stderr, for the hook subcommands on a Python older than 3.10, which means nothing was checked (the stock macOS `/usr/bin/python3` is 3.9).
- **Limits.** Only the Bash tool passes through the hook. File edits made with Claude Code's own tools are not seen, including edits to the state directory, the approvals file, the audit log, the configuration and the run registry; an agent can remove a registry entry so that the hook finds no run. Scripts and interpreters (`python3 script.py`, `make`), `mv`, `sed -i`, redirections and unknown absolute-path programs are not gated in execute mode, and children inherit the caller's environment. Hooks act only when the plugin is installed and enabled. They are covered by unit tests and a subprocess test and have not been exercised inside a real Claude Code session.

### 4.15 CLAUDE.md guidelines (`adapters.claude_code.claude_md`, `commands.claude_md`)

`wev claude-md init|update|check|show` manages one block of a project's CLAUDE.md, delimited by markers, in English or Brazilian Portuguese (`guidelines/guidelines.<lang>.md`). `init` creates the file or inserts the block into an existing one; `update` rewrites only the block; `check` reports what is missing or stale and exits 2 when something is; `show` prints the block; `--dry-run` prints the diff and writes nothing. Check commands found by `core.discovery` are read as data. The skill `wev-claude-md` drives it. A README check is part of the scope and has its own skill (see the [spec](../spec.md)).

### 4.16 Tool selection (`decisions.tool_selection`, `decisions.local_tools`, `decisions.jev_tools`, `core.tool_select`)

Hypothesis H10: handing a task fewer tool definitions costs less context. It is off by default (`harness.tool_selection: off`); `local` narrows with the offline policy, `provider` asks `decision.provider`.

- Candidates are the agent's allow list minus its deny list. Whatever a provider proposes goes through `enforce`: the result is a subset of the candidates, a **floor** is always kept (the read tools the agent already had, the edit tool when the task changes files and the agent may change them, the shell when the task has checks), an empty or malformed proposal falls back to the local policy, a scoped pattern such as `Bash(git:*)` is treated by its base name, and selection cannot change permissions.
- The selection is computed once per task, when its contract is first built, and stored with the task and as a decision; every later contract of the task grants the same tools. `wev select-tools --task-file F --agent A` prints a selection without storing anything.
- A dropped tool that turns out to be needed is restored with `wev task tools TASK --add TOOL --reason R`, only from the agent's own candidates, and counted as a selection miss.
- With JEV as the provider, **one `jev ask` call per task** asks a `noul` question per candidate tool outside the floor, plus a `choice` question for the profile when `harness.tool_profile` is `auto`. The state sent is the task's title, objective and acceptance criteria. A tool is dropped only at a probability of 0.2 or below; a profile answer below the trust threshold (confidence 0.6) is ignored and the local profile is used. The question for each tool is built so that a description that already ends in a period does not produce a stray ".?".
- The run report has a section with the tools offered and selected and approximate definition-token estimates. The figures sum rough per-tool constants: estimates for comparison, not measurements for any model or client. No saving in tokens or in task success has been measured.

## 5. Repository layout

```text
src/wev_skills/        engine package (core, decisions, agents, models, tools, security,
                      state, context, guards, execution, verification, governance,
                      remote, evaluation, adapters, commands, schemas, locales,
                      cli.py, config.py, i18n.py, schema.py)
agent-specs/          agent spec catalog: templates/ and examples/ (JSON, schema-validated)
agents/               Claude Code subagent files generated from the specs by
                      `wev agent export` (output, not source)
skills/               Agent Skills (SKILL.md entry points)
hooks/                hooks.json: the Claude Code plugin hooks
evals/                eval task fixtures and recorded reports
tests/                unit, integration, security, fixtures
docs/                 architecture, research, guides, ADRs (English and pt-BR)
bin/wev               launcher that runs the CLI from a source checkout
```

## 6. CLI conventions

`wev <group> <command>` (`bin/wev`, or `python3 -m wev_skills`). Output is JSON on stdout; `wev run report --format md` prints Markdown. Errors are `{"error": {"code", "message", "details"}}` on stderr. Exit codes: `0` ok, `1` unexpected error, `2` usage or validation, `3` permission denied, `4` approval required, `5` state conflict, `6` guard tripped, `7` not found, `8` remote or provider failure. User-facing messages are available in English and Brazilian Portuguese (`--lang`, `WEV_LANG`, a `language` set in a configuration file, or `LANG`, in that order).

Each command group is a module in `wev_skills.commands` with a `register(subparsers)` function. A handler returns the payload, or a `cli.CommandResult(payload, exit_code=0, stream="stdout", raw=False)` when the outcome is an answer rather than an error and still needs its exit code: `wev check-command` prints its decision with exit `0` (allow), `3` (deny) or `4` (needs approval); `wev guard evaluate` and `wev guard check` print the verdict with exit `6` unless it is CONTINUE; `wev exec` prints the record and the verdict with exit `0` (passed), `1` (failed or unknown) or `6` (guard tripped).
