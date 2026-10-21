# Configuration and providers

Portuguese version: [configuration-and-providers.pt-BR.md](configuration-and-providers.pt-BR.md).

The engine works with no configuration file. A file only overrides defaults. This guide lists every section with its default (read from `src/wev_skills/schemas/config.schema.json` and `src/wev_skills/config.py`, and confirmed with `wev config show`), explains model tiers and routing, the `harness` section and the decision providers, and says exactly what leaves the machine when JEV is enabled.

## How a configuration is loaded

- **Resolution.** `wev run start` takes the configuration from `--config PATH` (given before the command group: `wev --config my.json run start ...`), else from `<repository root>/wev.config.json` if that file exists, else from the defaults. The repository root is the nearest enclosing directory with a `.git` entry.
- **Pinning.** `run start` stores the effective configuration, its digest and its source in the run state (the `config` field of the `run start` and `run status` answers shows the source and digest). Every later command of that run uses the stored configuration, and a `--config` whose content differs is refused with `config_pinned`. To change a setting, finish the run (`wev run finish`) and start another. A `--config` identical to the pinned one is accepted.
- **Outside a run**, commands such as `wev classify` resolve the same way, and so do `wev config show` and `wev config validate PATH`. `show` prints the configuration that the other commands would use here, with the key `config_source` saying where it came from (`defaults`, or the path of the file). When a run is active for the working directory, `show` prints that run's pinned configuration instead, sets `config_source` to `run:<run id>` and adds `pinned_by_run`; a different `--config` is refused with `config_pinned`, as for every command. `validate PATH` checks that file with the same rules a run applies (including what a configuration may not name, below) and prints `config_source`. Both print a `warnings` list, empty unless `decision.provider` is `jev` and the program does not resolve (see the `jev` section).
- The file is JSON. It is deep-merged over the defaults: nested objects merge key by key; lists and scalars are replaced.
- The merged result is validated against the schema. Unknown keys are rejected.
- **What a configuration may not name.** `decision.jev.command` must be a bare program name (not a shell or an interpreter such as `sh`, `bash`, `env`, `python`, `node`) or an absolute path outside the repository. Each entry of `agents.directories` must stay inside the repository root or the user's configuration directory (`$XDG_CONFIG_HOME/wev-skills`, else `~/.config/wev-skills`). A file in the repository must not pick what runs. A violation is reported as `invalid_config`.
- The Claude Code hooks judge a command under the pinned configuration of the run they find, not the defaults. Commands that carry `--config` are sent to the person's permission prompt when the hook can read the command line.
- The state directory is added to `permissions.protected_paths` whatever the file says.
- Language of messages: `--lang en|pt-BR`, then `WEV_LANG`, then the `language` key of the configuration when a configuration file sets it explicitly (the built-in default `en` does not count), then `LANG` (a value starting with `pt` selects Portuguese), then English. `run brief` and `run report` have a `--lang` of their own, which wins for their output. A run uses the language it pinned when it started, also for its reports, briefs and the output of the Claude Code hooks, so editing the file mid-run does not change it.

`examples/config.example.json` is a valid file with a remote inventory; `tests/unit/test_skills.py` validates it.

## Sections and defaults

Defaults shown are the real output of `wev config show`.

### `language`

Default `"en"`; allowed `en`, `pt-BR`. The language of messages, reports, briefs and hook output when neither `--lang` nor `WEV_LANG` is given. It counts only when a configuration file sets it: with `{"language": "pt-BR"}` in `wev.config.json`, messages are in Portuguese even if `LANG` is English, and `{"language": "en"}` keeps English even if `LANG` starts with `pt`. A configuration that does not set it leaves the choice to `LANG`, then English. The run pins the value when it starts (`implemented and tested`; see `tests/unit/test_language_config.py`). The order is in [How a configuration is loaded](#how-a-configuration-is-loaded).

### `state_dir`

Default `".wev"`. Where runs, approvals and the audit log are written. A relative path is taken from the repository root, not from the directory you run in. It holds `approvals.json`, `audit.jsonl` and `runs/<run id>/` with `state.json`, `events.jsonl` and `logs/`. It creates its own `.gitignore` that ignores everything in it, directories with mode 0700 and files with mode 0600. State written by an earlier layout does not load. It is always a protected path, which stops a command that names it but not the agent's own file tools.

### `decision`

| Key | Default | Meaning |
|---|---|---|
| `provider` | `"local"` | `local` or `jev` |
| `jev.command` | `"builtin"` | The JEV client. `builtin` uses the HTTP client inside wev-skills. Any other value runs an external program: a bare program name, resolved on `permissions.exec_path` only, or the absolute path of an existing executable regular file outside the repository. A relative path with a directory component is rejected when the configuration is loaded |
| `jev.timeout_seconds` | `10.0` (minimum 0.1) | How long to wait for one call before falling back to the local policy. For the built-in client it also bounds the retries |

See [Decision providers](#decision-providers).

### `models`

```json
"models": { "tiers": {
  "economy":  ["claude-haiku-5-5"],
  "standard": ["claude-sonnet-5-5"],
  "premium":  ["claude-opus-5-5", "claude-sonnet-5-5"] } }
```

Each tier is a non-empty list of model ids in fallback order. See [Model tiers and routing](#model-tiers-and-routing). The ids are defaults of the project, not a statement about which models you have access to; replace them with yours.

### `limits`

| Key | Default | Meaning |
|---|---|---|
| `max_attempts` | `3` | Attempts allowed per task |
| `max_parallel` | `3` | Tasks offered together, when the classification says the work is parallelizable (otherwise 1) |
| `max_consecutive_failures` | `3` | Guard: consecutive failing commands before it advises a change of strategy |
| `max_identical_commands` | `3` | Guard: runs of the same command with no progress in between |
| `task_timeout_seconds` | `3600.0` | Guard: time since a task's first event before it asks a human |
| `budget_units` | `100.0` | Guard: total of the budget events in a history; an agent's `budget.max_units` replaces it for that agent's task |
| `max_polling_commands` | `60` | Guard: consecutive `--polling` commands of one task before a person is asked |
| `lock_timeout_seconds` | `30.0` | How long a command waits for another process to release the state file |

`max_attempts` limits how many times a task may start (every `task start` counts), and an agent's own `max_attempts` can lower it. Escalation to a higher model tier fires at half the attempts (rounded up) or on a repeated error signature; at the limit the task is `BLOCKED` until a person runs `wev task reopen`. Observed: `max_identical_commands` of 3 tripped on the fourth `wev exec -- false` (see the [orchestration guide](orchestration.md)). A live run does feed the guard real events: commands and checks spend budget units, progress is detected from a working-tree fingerprint, and attempts are counted. `wev guard evaluate --events-file` can judge any recorded history.

### `context`

| Key | Default | Meaning |
|---|---|---|
| `budget_tokens` | `100000` | Token budget of the context manager |
| `elide_at` | `0.6` | Usage ratio at which old large tool outputs are replaced by a stub that points to the archived original |
| `summarize_at` | `0.85` | Usage ratio at which an injected summarizer folds the remaining unpinned items |

These settings drive `wev context compact` and the evaluation harness, and nothing else: the orchestration flow (`wev run`, `wev task`) does not use the context manager. They do not control Claude Code's own context window. Without a summarizer, the second stage is skipped and reported. Requirements, decisions and evidence items are pinned and never elided.

### `permissions`

| Key | Default | Meaning |
|---|---|---|
| `allowed_commands` | `[]` | If non-empty, a command that does not match a pattern needs approval (it is not denied) |
| `denied_commands` | `[]` | A command that matches is denied, also when it is behind `sudo`, `env` or `sh -c` |
| `allow_shell` | `false` | Whether the executor accepts a shell command string. Leave it off |
| `protected_paths` | `[".git", ".env", ".wev", "<absolute state dir>"]` | An argument naming one of these (or a glob that may match one) is denied |
| `approval_ttl_seconds` | `900.0` (minimum 1) | How long a grant stays usable after the person gives it; a grant is single use and bound to one argv, directory and run |
| `exec_path` | `["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin"]` | The only directories `wev exec` (and the JEV client) look in for a program named without a path. `$PATH` is never used. A program that resolves inside the working tree is refused |

Patterns are token-by-token prefixes of the command: `"git status"` matches `git status -s`. A list in the file replaces the default list for that key, so when you set `protected_paths` repeat `.git` and `.env`; the state directory is re-added for you. If you set `exec_path`, list every directory that holds a program you need. See the [security guide](security.md) for what the policy does and does not catch.

### `remote`

`hosts`, default `[]`: a list of `{ "alias": "staging-1", "environment": "staging", "allow_mutating": false }`. `alias` is required and must be a `Host` name from your SSH configuration; `environment` is a label (`production` makes every command on that host need a human approval for the exact action); `allow_mutating` defaults to false and limits the host to commands the policy considers read-only. See the [remote operations guide](remote-ops.md).

### `agents`

| Key | Default | Meaning |
|---|---|---|
| `directories` | `[]` | Extra directories of agent specs; later ones override earlier ones |
| `default_agent` | `"senior-engineer"` | The agent a task goes to when no agent matches its words (it must be able to change files) |
| `allow_override` | `false` | Let a spec from a configured directory replace a built-in agent with the same id. Off, such a spec is refused |

### `harness`

| Key | Default | Allowed | Meaning |
|---|---|---|---|
| `planning` | `"auto"` | `auto`, `always`, `never` | Whether a run makes a plan |
| `executor_tier` | `"auto"` | `auto`, `economy`, `standard`, `premium` | The tier the strategy assumes for whoever does the work; `auto` uses the tier the router picked |
| `plan_reminder` | `true` | boolean | Whether the prompt hook injects the brief |
| `plan_reminder_max_chars` | `600` | 80 to 20000 | Length cap of the brief |
| `tool_profile` | `"structured"` | `auto`, `structured`, `lean` | How many tools an exported or contracted agent lists |
| `tool_selection` | `"off"` | `off`, `local`, `provider` | Per-task tool selection: `off` hands out the agent's tool list as it is, `local` narrows it with the offline policy, `provider` asks `decision.provider` |
| `baseline_checks` | `true` | boolean | Run a task's checks once when it starts, so that checks that already passed before any work are not taken as evidence of the work. Off: only the starting tree is recorded |

These mechanisms are configurable defaults motivated by a research paper (see `docs/research/hypotheses.md`, H4, H5, H8, H9, H10). **Their effect has not been measured with a real model.** In particular, with the default `executor_tier: auto` the capability-aware planning rule changes nothing in practice: the router assigns the economy tier only to trivial tasks (low risk, one file at most, no unknowns), and a trivial task is not planned under any tier; and the premium rule currently equals the standard one (both plan from moderate complexity up). The rule only changes the plan decision when you set `executor_tier` yourself. Real examples with `wev strategy --files 2 --executor-tier ...`: `economy` gives a `planned` flow, `standard` and `premium` give `direct`.

Tool selection (`tool_selection`, hypothesis H10) always keeps a floor (the read tools, the edit tool when the task changes files, the shell when the task has checks), only chooses among tools the agent already has, and cannot change permissions. A dropped tool can be restored during the task with `wev task tools --add`, and each restore is counted as a miss. The report shows approximate definition-token estimates (sums of rough per-tool constants). Whether it saves tokens or affects task success has not been measured.

How `planning: auto` decides: economy plans anything above trivial; standard and premium plan from moderate complexity; any tier plans above low risk; `always` and `never` override; plan mode and gated flows always plan. Risk, approval, review and limits are the same for every tier. `tool_profile: lean` is described in the [agent guide](creating-agents.md); it is a cost option, and it never adds a tool or changes permissions.

## Model tiers and routing

The router (`wev route-model`) picks a tier from the classification, then a model from that tier:

1. Starting tier: `premium` for high risk or complex work; `economy` for low-risk trivial work; `standard` otherwise.
2. Failures raise the tier. Real output for a moderate task: attempts 0 and 1 pick `standard` (`claude-sonnet-5-5`); attempts 2 and 3 pick `premium` (`claude-opus-5-5`).
3. An agent's `model_policy` (`min_tier`, `max_tier`) clamps the result, and an agent that pins a concrete `model` wins while that model is available.
4. An unavailable model (`--unavailable`) falls to the next entry of its tier, then to a neighbouring tier.

Each result lists its reasons. The routing is a rule, not a measurement of which model suits a task. The model id that appears in a task contract is also the agent's model when the agent pins one, so a run can show a `standard` model for a task that the router would have sent to `economy`.

## Decision providers

The interface has seven methods: `classify_task`, `select_strategy`, `route_agent`, `evaluate_result`, `resolve_conflict`, `should_escalate`, `select_tools` (see the [architecture](../architecture/architecture.md), 4.2, and [ADR 0004](../architecture/decisions/0004-decision-providers-and-jev.md)).

### `local` (default)

Deterministic rules, no network, always available, every decision explained. Status: implemented and tested. It is also the fallback for every other provider. Hard rule for every provider: an external service may raise the risk level the local rules computed and never lower it.

### `jev` (optional, off by default)

JEV is a third-party decision service. By default wev-skills reaches it with its own HTTP client (`decision.jev.command` is `builtin`); setting `command` to a program name or an absolute path keeps the older path through an external command-line client. The adapter uses it for `classify_task`, mapping typed questions onto classification (`score` for complexity, `choice` for risk, `noul` for parallelism), and, when `harness.tool_selection` is `provider`, for `select_tools`; the other methods are the local policy's. A provider can only raise risk and complexity above what the local rules (including the lexical floor read from the objective) computed; it can never lower either, so it can never remove a review or an approval.

#### The built-in client

Selected when `decision.jev.command` is `builtin` (the default). Everything below applies only to it; the external-program path that follows is unchanged.

- **Key lookup, in this order:** the `TYPESAFE_API_KEY` environment variable; the file `~/.config/wev-skills/.env` (or `$XDG_CONFIG_HOME/wev-skills/.env`), which is refused when group or others can read it (`chmod 600` fixes that) or when it cannot be read (that stops the lookup with an error; it does not fall through to the keychain); then, if the file does not exist or has no key, the macOS keychain service `typesafe-api-key`. The keychain lookup has its own 10-second limit, which `decision.jev.timeout_seconds` does not cover. A key with control characters or characters outside latin-1 is rejected. No key is printed or put in a failure reason.
- **Endpoint:** `https://api.typesafe.ai/v1/systemone`, overridden by `JEV_API_URL`. Any non-loopback URL must be `https` and carry no user name or password; a malformed URL is `endpoint_invalid`. A loopback URL needs no key. Redirects are never followed.
- **Retry and deadline:** only HTTP 429 and 529 are retried, after 0.5, 1 and 2 seconds, at most 4 attempts. The whole call stays under `decision.jev.timeout_seconds` (default 10.0), which bounds the retries and each socket timeout. A server that sends bytes very slowly, or a slow DNS lookup, can still run past it.
- **Failure:** any failure falls back to the local policy and records the reason, which never contains the key. At most 1 MiB of a response is read; a longer one is the failure `response_too_large`. `wev config show` and `wev config validate` warn when the provider is `jev` and no key was found (no key warning for a loopback endpoint).
- **Commands:** `wev jev status` prints `provider`, `client` (`builtin` or `program`), `key_source`, `key_error`, `endpoint` and `orchestration`. It makes no network call, never prints the key and, when the provider is not `jev`, does no key lookup. `orchestration` is `wev` only when `decision.provider` is `jev` and JEV is usable (the built-in client with a key or a loopback endpoint, or a program that resolves), and `harness` otherwise, so a default install (provider `local`) reports `harness`; the `wev-orchestrate` skill reads it first. `wev jev ask --questions FILE (--state TEXT | --state-file FILE)` asks one set of typed questions, and `wev jev batch --questions FILE --items FILE --out FILE` asks them for every `{"id","state"}` line of a JSONL file and writes one result line per item, exiting 8 when any item failed. Both redact the state first. Unlike a classification, `ask` and `batch` do not fall back to the local policy: `ask` exits 2 on invalid questions and 8 on a JEV failure, and `batch` records the failure per item and exits 8 when any item failed. `ask` and `batch` always use the built-in client and ignore `decision.provider` and `decision.jev.command`. The Bash hook answers `ask` for both, since they send data off the machine.
- **Without JEV** only the orchestration flow is off. The Bash guard hook stays active: without a run it judges commands under the built-in default policy (execute mode, medium risk) and does not read a repository configuration. Approvals and loop detection need a run, so they are not in use in harness mode.

Status: the built-in client is implemented and tested against a local fake server. The live TypeSafe service was not run in this change.

The external program is resolved like any program the engine runs: a bare name is looked up only in `permissions.exec_path` (never `$PATH`), or `decision.jev.command` is an absolute path to an existing, regular, executable file outside the repository. `exec_path` holds system directories by default, so a JEV installed in a user directory such as `~/.local/bin` is **not found** under the name `jev`. When the program cannot be resolved, the call falls back to the local policy and records the reason in the classification (or the tool selection): it says the program was not found on the allowed path and names the two fixes. Either set `decision.jev.command` to the program's absolute path, or add its directory to `permissions.exec_path`. `wev config validate` and `wev config show` print a warning in `warnings` when `decision.provider` is `jev` and the command does not resolve, so the silent fallback is visible before a run.

Status: implemented and tested against a fake `jev` executable. The answer format was verified against three real calls made on 2026-10-13 with synthetic inputs (one classification, two tool selections); the responses were not saved as fixtures and the live calls are not part of the test suite, so behavior for other inputs and over time is untested. The service defines the response shape, not this project, and it can change without notice; the adapter validates types and ranges strictly and falls back to the local policy on anything unexpected.

To enable it:

```json
{ "decision": { "provider": "jev", "jev": { "command": "/absolute/path/to/jev", "timeout_seconds": 10 } } }
```

The other fix keeps the bare name and extends the search path: `"permissions": { "exec_path": ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin", "/absolute/path/to/directory-of-jev"] }`. The list replaces the default, so repeat the system directories you still need. Replace `/absolute/path/to/...` with the real location on your machine.

```text
wev --config jev.json run start --objective "..." --files 3
```

**What leaves the machine.** When the provider is `jev`, each classification runs `jev ask` (the built-in client makes the same call itself), and the client sends a text to a remote service. That text is built from the task signals and nothing else:

```text
Task: <the objective you gave>
files_touched_estimate=<n> unknowns=<n> independent_subtasks=<n>
touches_remote=<bool> touches_production=<bool> destructive=<bool> external_side_effects=<bool> has_tests=<bool> reversible=<bool>
```

The objective is free text that you or the agent wrote, so it is the part to think about: do not put secrets, personal data of customers or private details in an objective when JEV is on. The adapter passes the text through the engine's redactor first, which masks recognizable secrets only (see the [security guide](security.md)). It does not send file contents, command output, plans or run state. Check the JEV client's own documentation for what it does with the text; this project does not control that. The typed questions sent with it are the three listed above.

**Tool selection with JEV.** With `harness.tool_selection: provider` there is one `jev ask` call per task. It asks a `noul` question per candidate tool outside the floor ("is this tool needed for this task?"), plus a `choice` question for the tool profile when `harness.tool_profile` is `auto`. The text sent is the task's title, objective and acceptance criteria and nothing else: no file contents, no file names. A tool is dropped only when the answer is a probability of 0.2 or below; the floor is never asked about; an empty or unusable answer falls back to the local selection. Two real calls on 2026-10-13 with synthetic tasks: a read-only review task returned Write 0.06, Bash 0.26, WebFetch 0.36, WebSearch 0.14 and profile `structured` at confidence 0.56, which is below the trust threshold of 0.6, so the local profile was used; a feature task returned Write 0.76, Bash 0.58, WebFetch 0.06, WebSearch 0.12 and profile `structured` at 0.86. The `noul` answers carried no confidence field. This verifies the answer format for this use and says nothing about token savings or task success.

How answers are used: a `score` or `choice` answer with confidence below 0.6 (or none) is not trusted, and a `noul` value strictly between 0.35 and 0.65 counts as uncertain; for such a dimension the local value is used and a reason says so. The classification's `uncertainty` becomes the larger of the local uncertainty and 1 minus the lowest trusted confidence. A missing binary, a non-zero exit, a timeout or an unparseable answer falls back to the local policy and records why in the classification's reasons. Check `classification.source` in the `run start` answer: it says `jev` or `local-policy`.

### Adding another provider

The `DecisionProvider` interface is vendor-neutral and `build_provider` chooses by `decision.provider`. A new provider is code in `src/wev_skills/decisions/`, a value in the schema's `enum` and a test; there is no plugin mechanism for providers.
