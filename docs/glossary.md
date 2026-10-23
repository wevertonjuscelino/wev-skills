# Glossary / Glossário

One file for both languages: each row gives the English term, the Brazilian Portuguese term used in the `.pt-BR.md` documents, and a one-line definition. The documentation keeps the English identifier (command, file, field, label) in code formatting wherever it quotes one.

## Evidence labels

These five labels describe the state of every piece of work in the project. Do not use other wording for them.

| English | Português | Definition |
|---|---|---|
| implemented and tested | implementado e testado | The code exists and an automated test that fails when the behavior breaks has run and passed. |
| implemented but untested | implementado mas não testado | The code exists and no test has exercised it. |
| simulated with mocks | simulado com mocks | Tested only against a fake or scripted stand-in for the real thing (a simulated host, a scripted agent). |
| documented only | apenas documentado | Described in a document; no code or no run backs it. |
| blocked | bloqueado | Cannot be done or verified until something outside the work changes. |

## Terms

| English | Português | Definition |
|---|---|---|
| engine | motor | The dependency-free Python package `wev_skills` and its JSON CLI `wev`; it enforces the rules. |
| skill | skill | A Markdown instruction file (`SKILL.md`) that tells a model when and how to call the engine; it instructs and enforces nothing. |
| adapter | adaptador | The environment-specific layer (skills, exporter, hooks) between the engine and an agent environment such as Claude Code. |
| plugin | plugin | The Claude Code package (`.claude-plugin/plugin.json`) that ships the skills, subagents and hooks. |
| marketplace | marketplace | A catalog file (`.claude-plugin/marketplace.json`) that lets Claude Code install the plugin by name. |
| hook | hook | A command that Claude Code runs on an event; here `wev hook <name>`. |
| fail open | falhar aberto | On an internal error, do nothing and let the action proceed. The hooks do this only while no run is known; once a run is known they answer `ask` instead. |
| fail closed | falhar fechado | On an internal error, refuse the action; `wev exec` behaves this way. |
| guardrail | proteção contra erros (guardrail) | What the engine is: a check on a fallible agent and a record of decisions. It is not a security boundary against an adversarial agent in the same user account (ADR 0006). |
| run | execução | One recorded orchestration, with an id, an objective, a mode and a state kept under the state directory. |
| active run | execução ativa | The latest readable run of a repository whose phase is not `done`. There is one per repository; commands without `--run` use it, its mode never changes, and `wev run finish` ends it. |
| pinned configuration | configuração fixada | The effective configuration, stored in the run state at `run start`. Later commands use it and refuse a different `--config`. |
| state directory | diretório de estado | `.wev/` by default, resolved at the repository root, with its own `.gitignore`: runs, approvals and the audit log. Protected from the engine's own file operations; the agent's file tools are not stopped from writing there. |
| run registry | registro de execuções | A per-user file (`active-runs.json` under the user's state home) that lets a hook find the run that owns a path outside the current directory. Entries are hints; the run state is checked. |
| mode | modo | `plan` (look, change nothing), `execute`, `auto` (flow chosen from the classification); `resume` is an operation on an existing run. |
| phase | fase | Where a run is in the flow (for example `plan`, `execute`, `deliver`, `done`). |
| flow | fluxo | The path the strategy picks: `direct`, `planned` or `gated`. |
| classification | classificação | Complexity, risk, uncertainty and parallelizability computed from the task signals. |
| signals | sinais | The estimates a caller supplies to `run start` (files, unknowns, remote, production, ...). |
| strategy | estratégia | The flow, whether to plan, whether review and approval are required, and the limits for one run. |
| risk level | nível de risco | `low`, `medium` or `high`; high needs explicit human approval before the impactful operation. |
| plan | plano | A JSON file of tasks with files, dependencies, acceptance criteria and checks, stored with `wev plan set`. |
| task | tarefa | One unit of a plan, handed to exactly one agent. |
| task contract | contrato de tarefa | Objective, context, scope, exclusions, constraints, acceptance criteria, checks, response format, permissions, agent, model and risk for one task. |
| acceptance criterion | critério de aceitação | A statement a check must be able to prove; `met`, `unmet` or `unverified`. |
| check | verificação | A command that verifies a task, run by `wev task check`. A plan may tie a check to specific criteria; a check given as a plain string is untied and is labeled so. |
| baseline check | verificação de linha de base | A check run once at `task start` (`harness.baseline_checks`). One that already passed with no change does not verify the task. |
| read-only task | tarefa somente leitura | A task marked `read_only` in the plan; the only kind that can be verified with no changed files. |
| next_steps | next_steps | The list of next actions that accompanies `next_step` in a command's JSON answer. |
| evidence | evidência | A recorded fact (command, exit code, log) that supports a claim. |
| verification | verificação (ato) | Running a task's checks and recording which criteria they prove. |
| independent review | revisão independente | A second agent, different from the one that did the work, accepts or rejects a verified task. |
| report | relatório | The delivery report (`wev run report`) with an evidence label on every claim; status `complete`, `incomplete` or `blocked`. |
| brief | resumo (brief) | The short plain-text summary of the active run that the hooks inject (`wev run brief`). |
| drift | divergência (drift) | Difference between the recorded state of a run and the real repository, found by `wev run resume`. |
| approval | aprovação | A record that binds a human decision to one exact command. |
| grant | concessão | The human decision that approves a pending approval. It is single-use, expires, and covers one argv in one directory of one run (and one host for a remote action). There are no reusable grants. |
| operator | operador | The human who reviews and grants approvals in their own terminal. Operator commands (`approval grant`, `approval deny`, `guard acknowledge`, `task reopen`, `specialists accept`, `specialists retire`, `run adopt`, `review dismiss`) need a terminal and a typed confirmation and have no bypass flag. |
| execution guard | guarda de execução | The pure function that detects loops, repeated failures, no progress and budget or time overruns. |
| guard trip | disparo da guarda | A guard verdict other than `continue`. |
| acknowledge | reconhecer (guard) | The human step (`wev guard acknowledge`) that lets the guard count again after a STOP or ASK_HUMAN verdict. |
| permission policy | política de permissões | The code that decides allow, deny or needs approval for a command, a tool or a path. |
| permission ceiling | teto de permissões | `permissions.ceiling: true` on an agent spec: descendants may narrow its permissions and never widen them. |
| protected path | caminho protegido | A path the engine refuses to touch (`.git`, `.env`, the state directory, ...). |
| redaction | mascaramento (redação) | Replacing recognizable secrets with a placeholder before anything is logged or stored. |
| untrusted data | dado não confiável | Repository content, logs, tool output and remote files: read as data, never followed as instructions. |
| agent spec | spec de agente | A versioned, schema-validated JSON file that defines one agent. |
| template | template | An agent spec meant to be extended (`base`, `base-engineer`, `base-reviewer`). |
| subagent | subagente | A Claude Code agent file generated from an agent spec by `wev agent export`. |
| model tier | nível de modelo | `economy`, `standard` or `premium`; each maps to concrete model ids in the configuration. |
| model router | roteador de modelos | The component that picks a model from the classification, the agent's bounds and the attempt number. |
| executor tier | nível do executor | The tier the strategy assumes for whoever does the work (`harness.executor_tier`). |
| tool selection | seleção de ferramentas | Per-task choice of the smallest set of the agent's tools the task needs (`harness.tool_selection`: `off`, `local` or `provider`); `wev task tools --add` restores a dropped tool. |
| tool profile | perfil de ferramentas | `structured`, `lean` or `auto`: how many tools an exported or contracted agent lists. |
| decision provider | provedor de decisão | The component that classifies, selects a strategy, routes, evaluates, resolves conflicts and escalates; `local` or `jev`. |
| JEV | JEV | An optional third-party decision service reached through its local `jev` client. |
| inventory | inventário | The list of SSH aliases in `remote.hosts` that the remote module may reach. |
| alias | alias | A `Host` name in the operator's SSH configuration. |
| preflight | pré-checagem (preflight) | The read-only remote check of hostname, user and tmux. |
| scripted agent | agente roteirizado | The evaluation agent that replays fixed steps; it calls no model. |
| simulated units | unidades simuladas | The cost and duration numbers of the evaluation harness; neither money nor time. |
| context manager | gerenciador de contexto | The component (`wev_skills.context`) that compacts context items under a token budget. It serves `wev context compact` and the evaluation harness; the orchestration flow does not use it. |
| harness | harness | Everything around the model that plans, constrains, checks and records its work. |
| scored case | caso pontuado | A real situation stored in `evals/cases/<id>.json` with a check that fails at its base commit; `wev specialists score` runs it to decide lessons. |
| score decision | decisão por nota | A lesson accepted or retired by `wev specialists score` (`accepted_by` `score`) because no case lost a pass and the total rose; a person's decision stays final. |
