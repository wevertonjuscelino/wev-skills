# Arquitetura do wev-skills

Status: descrição do MVP como implementado e testado (`make test`); o comportamento das peças em uma sessão real do Claude Code não foi observado. As seções marcadas como "futuro" não estão implementadas.
Versão em inglês: [architecture.md](architecture.md).

## 1. Forma do sistema

O wev-skills tem duas camadas.

- **Motor** (`src/wev_skills/`): um pacote Python sem dependências (Python 3.14+, apenas biblioteca padrão) que reúne todas as partes determinísticas do harness: classificação, estratégia, specs de agentes, roteamento de modelos, permissões, estado, orçamento de contexto, detecção de laços, execução de comandos, verificação, aprovações, controle remoto via tmux, seleção de ferramentas e avaliação. É acionado por uma CLI (`python3 -m wev_skills ...`, ou `bin/wev`) que lê e escreve JSON.
- **Adaptadores e skills**: peças finas, específicas de cada ambiente. O adaptador do Claude Code é formado pelas skills em `skills/` (instruções em Markdown que dizem ao Claude quando chamar a CLI do motor), por um exportador que transforma specs de agentes em arquivos de subagentes do Claude Code, pelo bloco de diretrizes do CLAUDE.md (`wev claude-md`, seção 4.15) e por três hooks de plugin (`hooks/hooks.json`, seção 4.14). O núcleo (`core`, `decisions`, `security`, `state`, ...) nunca importa um adaptador; só os módulos de comando fazem isso.

O modelo raciocina e edita. O motor faz a contabilidade e aplica as regras em código. Essa divisão existe porque regras escritas só em Markdown podem ser ignoradas por um modelo, enquanto uma CLI que se recusa a registrar um passo de alto risco sem aprovação não depende da redação do modelo.

O que o motor é, e o que não é, fica dito uma vez aqui e o restante deste documento depende disso: **o motor é uma proteção para um agente falível e um registro de decisões. Não é uma fronteira de segurança contra um agente adversarial na mesma conta de usuário.** O portão humano é o prompt de permissão do Claude Code, alcançado pelo hook `PreToolUse` do plugin; sem os hooks, as aprovações são registros. As ferramentas de arquivo do próprio agente podem reescrever o estado, as aprovações, o log de auditoria e o registro de execuções. Ver o [ADR 0006](decisions/0006-guardrail-not-boundary.pt-BR.md), o [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md) e a seção 4.5.

A delegação é centralizada: a sessão orquestradora pede ao motor o próximo contrato de tarefa, entrega-o a um agente e registra o resultado. Agentes não iniciam agentes por meio do motor.

## 2. Fluxo

`REQUEST → DISCOVER → CLASSIFY → PLAN → DECIDE → EXECUTE → VERIFY → REVIEW → DELIVER`

| Fase | Responsabilidade do motor | Módulo |
|---|---|---|
| REQUEST | Criar uma execução com objetivo e modo | `core.orchestrator`, `state.store` |
| DISCOVER | Registrar fatos do repositório (estado do git, comandos de verificação detectados) | `state.resume`, `core.discovery` |
| CLASSIFY | Pontuar complexidade, risco, incerteza e escopo | `decisions` |
| PLAN | Validar e persistir o plano e seu grafo de dependências | `core.planning`, `core.plan_flow` |
| DECIDE | Escolher estratégia, agente e modelo por tarefa; condicionar a aprovações | `decisions`, `agents`, `models`, `governance` |
| EXECUTE | Emitir contratos de tarefa; executar comandos; vigiar laços | `core.task_flow`, `core.task_exec`, `execution`, `guards` |
| VERIFY | Executar verificações, anexar evidências, avaliar critérios de aceitação | `core.task_exec`, `verification` |
| REVIEW | Exigir revisão independente quando a estratégia pedir | `core.task_outcomes` |
| DELIVER | Produzir o relatório final com rótulos de evidência | `core.report`, `core.report_markdown` |

Modos: `plan` (nenhum passo que altere algo pode ser registrado ou executado), `execute`, `auto` (fluxo escolhido a partir da classificação). Uma execução começa em um desses três, e seu modo nunca muda. Retomar é uma operação sobre uma execução existente (`wev run resume`): ela recarrega o estado e o compara com o estado real do git antes de continuar; a execução mantém o modo com que começou.

A *execução ativa* é a execução de um repositório cuja fase não é `done`. Um repositório tem no máximo uma: `wev run start` é recusado (`run_active`, saída 5) enquanto outra estiver ativa. Os comandos que aceitam `--run` usam a execução ativa por padrão. `wev run finish` define a fase `done`, e depois disso a execução pode ser lida, mas não alterada.

Uma execução **fixa sua configuração** quando começa (seção 4.13): todo comando posterior usa a fixada e recusa um `--config` diferente.

## 3. Contratos compartilhados (`core/contracts.py`)

Todos os contratos são dataclasses congeladas com `to_dict()` e um classmethod `from_dict()`. Os enums são enums de `str`, então são serializados como strings simples.

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
    # preenchidos a partir do plano e da spec do agente; todos têm padrão:
    check_links: tuple[CheckLink, ...] = ()    # verificações amarradas a critérios
    required_checks: tuple[str, ...] = ()
    read_only: bool = False
    may_mutate: bool = True
    may_use_remote: bool = False
    max_attempts: int | None = None
    timeout_seconds: float | None = None
    budget_units: float | None = None
    success_criteria: tuple[str, ...] = ()     # apenas instruções
    stop_conditions: tuple[str, ...] = ()      # apenas instruções
    escalation: str = ""                       # apenas instruções

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

`core/errors.py` define `WevError(code: str, message: str, details: dict)` e as subclasses `ValidationError`, `PermissionDenied`, `ApprovalRequired`, `StateConflict`, `NotFound`, `GuardTripped`, `RemoteError`, `ProviderError`. `Mode.RESUME` existe como valor, mas `wev run start` aceita apenas `auto`, `plan` e `execute`. A CLI converte um `WevError` em um erro JSON no stderr e em um código de saída diferente de zero (ver a seção 6).

## 4. Módulos e suas interfaces públicas

Todo módulo abaixo tem testes em `tests/unit/` (e em `tests/security/` ou `tests/integration/` onde indicado).

### 4.1 `schema` (validação)

`schema.validate(instance, schema) -> list[str]` devolve strings de erro com caminhos em JSON Pointer (lista vazia quando válido). `schema.load(name) -> dict` carrega `src/wev_skills/schemas/<name>.schema.json`. Palavras-chave aceitas: `type`, `enum`, `const`, `required`, `properties`, `additionalProperties`, `items`, `minItems`, `maxItems`, `uniqueItems`, `minLength`, `maxLength`, `pattern`, `minimum`, `maximum` e `$ref` local para `$defs`. Os arquivos de schema são JSON Schema válidos (draft 2020-12) restritos a esse subconjunto, então validadores externos também os aceitam.

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

`AgentLike` (`core.ports`) é qualquer objeto com `id`, `description` e `specialties`; `AgentSpec` o satisfaz.

- `decisions.local.LocalPolicyProvider(limits: LimitsConfig, harness: HarnessSettings | None = None)`: regras determinísticas, sem rede, sempre disponível.
  - Classificação: os sinais explícitos, mais um **piso lexical** (`decisions.lexicon`) lido do texto do objetivo em inglês e em português: palavras inteiras e frases fixas que nomeiam produção, operações destrutivas, efeitos externos, sistemas remotos, credenciais e mudanças de dados ou de esquema. Um acerto eleva o sinal correspondente e é informado com o termo encontrado. O piso nunca reduz nada e uma flag não o desfaz. É uma lista de palavras: tem falsos positivos e não pega paráfrases.
  - Estratégia: apenas o passo de planejar depende do tier do executor e de `harness.planning`. Com `auto`, economy planeja tudo acima de trivial, standard e premium planejam a partir de complexidade moderada, e qualquer tier planeja acima de risco baixo; `always` e `never` prevalecem; o modo plan e os fluxos gated sempre planejam. Risco, aprovação, revisão e limites são os mesmos para todo tier, e os motivos nomeiam o tier e a regra. `models.router.executor_tier(configured, routed)` dá o tier: `harness.executor_tier` ou, com `auto`, o tier que o roteador escolheu.
  - Roteamento: correspondência de palavras inteiras (minúsculas, uma pequena lista de stop words, plural em `s` final ignorado) entre o título e o objetivo da tarefa e cada agente; uma palavra de especialidade pesa 3, uma especialidade casada por inteiro soma 2, uma palavra da descrição pesa 1; empates se resolvem pelo id. Uma tarefa sobre sistemas remotos mantém os agentes com `may_use_remote`. Quando ninguém pontua acima de zero, a tarefa vai para `default_agent` se ele for candidato, senão para o primeiro id. `core.planning.default_agent` passa `agents.default_agent` (padrão `senior-engineer`) quando esse agente pode alterar arquivos, senão o primeiro candidato por id que pode.
  - Escalonamento: `should_escalate` responde "escalar" na metade do limite de tentativas (arredondada para cima) ou diante de uma assinatura de erro repetida, o que vier primeiro, para que o modelo mais forte ainda tenha uma tentativa; no limite responde ASK_HUMAN.
  - Seleção de ferramentas: `select_tools` (seção 4.16).
- `decisions.jev.JevProvider(runner, local, command="jev", timeout_seconds=30.0, *, redactor, program_resolver=None)`: opcional; executa a CLI real `jev ask` em `classify_task` e, por meio de `decisions.jev_tools`, em `select_tools`; os demais métodos são os da política local. O estado enviado ao JEV passa antes pelo `redactor`. O programa configurado é resolvido no mesmo caminho seguro que o executor usa (`permissions.exec_path`, por padrão apenas diretórios do sistema) ou precisa ser o caminho absoluto de um arquivo regular executável existente fora da raiz da execução; quando não é possível resolvê-lo (o motivo nomeia as duas correções: um `decision.jev.command` absoluto, ou o diretório em `permissions.exec_path`), ou em qualquer outra falha (binário ausente, saída diferente de zero, tempo esgotado, saída ilegível), a chamada volta à política local e registra o motivo.
- `decisions.factory.build_provider(config, runner, redactor) -> DecisionProvider`, escolhido por `decision.provider` (`local` ou `jev`).

Regra rígida em todo provider: um modelo ou serviço externo pode elevar o risco e a complexidade calculados pelas regras locais, nunca reduzir nenhum dos dois, e por isso nunca consegue remover uma revisão ou uma aprovação.

### 4.3 `agents`

- `agents.spec.AgentSpec`: dataclass imutável que espelha `agent.schema.json` (`schema_version`, `id`, `name`, `description`, `specialties`, `instructions`, `responsibilities`, `extends`, `model`, `model_policy`, `tools.allow`, `tools.deny`, `skills`, `permissions`, `budget`, `timeout_seconds`, `max_attempts`, `success_criteria`, `escalation`, `required_checks`, `output_format`, `stop_conditions`). Os campos de texto livre são `LocalText`: uma string ou um objeto `{"en": ..., "pt-BR": ...}`; `spec.localized(lang)` os resolve. `model` é um id de modelo concreto ou o nome de um tier.
- **Aplicados pelo motor** (`core.agent_rules` e quem o chama): `required_checks` (entram nas verificações da tarefa e precisam passar), `budget.max_units` (o orçamento da tarefa), `max_attempts` e `timeout_seconds` (vale o menor entre o do agente e o da execução), `permissions.may_mutate` (um agente com `false` só pode rodar por `wev exec` comandos de somente leitura, as verificações declaradas da própria tarefa e os comandos de verificação descobertos em `run start`, por correspondência exata do argv; todo o resto é recusado com `agent_read_only`, e esses comandos ainda passam pela política), `permissions.modes` e `permissions.max_risk` (um agente não pega tarefa fora deles), `permissions.may_use_remote` (verificado por `wev remote start`) e `permissions.ceiling` (verificado quando as specs são carregadas). **Levados apenas como instruções**: `stop_conditions`, `success_criteria`, `escalation` e `output_format` chegam ao agente no contrato ou no prompt exportado, e nada no motor os verifica.
- `agents.registry.AgentRegistry(specs=())`: imutável. `discover(dirs)` e `register(spec)` devolvem um novo registro; `get(id)`, `list()`, `in`. Diretórios posteriores sobrepõem os anteriores, mas uma spec de fora do catálogo embutido não pode reutilizar o id de um agente embutido a menos que `agents.allow_override` esteja ativo; duplicatas dentro de um mesmo diretório são erro. `agents.directories` precisa ficar dentro do repositório ou do diretório de configuração do usuário.
- `agents.factory.AgentFactory(registry)`: `resolve(spec) -> AgentSpec` (aplica `extends`, detecta ciclos, preenche padrões conservadores de permissão), `create(template_id, overrides) -> AgentSpec`, `child_data(template_id, overrides) -> dict`, `compose(ids) -> list[AgentSpec]`, `validate(data) -> list[str]`. Regras de conflito: uma ferramenta em allow e em deny é negada e um filho não pode remover uma entrada deny do pai. As permissões são herança simples (vale o valor do filho), a menos que um ancestral defina `permissions.ceiling: true`; a partir daí todo descendente precisa ficar dentro dos `modes`, `max_risk`, `may_mutate` e `may_use_remote` desse ancestral e não pode desfazer o teto (`permission_widening`, `ceiling_unset`). `base-reviewer` e os revisores somente leitura definem um teto.
- `agents.registry` lembra o arquivo de onde veio cada spec (`source(id)`) e ignora, com uma entrada em `skipped`, qualquer `*.json` que não seja um objeto ou que não tenha `schema_version` nem `id`; um arquivo que tenha um dos dois precisa ser uma spec válida.
- `agents.tool_profile`: `resolve_profile(profile, tier)` e `apply_profile(tools, permissions, profile)`. `structured` (padrão de `harness.tool_profile`) mantém a lista allow, porque ferramentas verificadas individualmente pelas permissões são mais fáceis de governar; `lean` reduz um agente que pode alterar arquivos e tem `Bash` a `Bash`, `Read` e `Edit`, até onde ele os tinha, uma opção motivada apenas por custo para modelos fortes; `auto` é `lean` para o tier premium. Um perfil nunca adiciona uma ferramenta, nunca altera a lista deny nem as permissões. É aplicado aos contratos de tarefa e por `wev agent export`.

### 4.4 `models`

`models.router.ModelRouter(models_config).select(classification, agent_model=None, agent_tier_bounds=None, attempt=0, unavailable=()) -> ModelChoice`. Os tiers `economy`, `standard` e `premium` mapeiam para ids de modelos concretos na configuração. Risco alto ou `COMPLEX` seleciona `premium`; falhas além da primeira sobem um tier cada; `agent_tier_bounds` limita o resultado; um `agent_model` fixado vence enquanto estiver disponível; um modelo indisponível cai para a próxima entrada do seu tier e depois para um tier vizinho. `ModelChoice` traz `model`, `tier` e `reasons`.

### 4.5 `tools` e `security`

- `tools.registry.ToolRegistry` (imutável; `default()`, `of(specs)`, `register(spec)`, `get(name)`, `list()`) guarda `ToolSpec(name, mutating, remote, network, min_risk_for_approval, description)` e um tamanho aproximado de definição por ferramenta, usado só nas estimativas da seleção de ferramentas.
- `security.permissions.PermissionPolicy(permissions_config, tool_registry=None, approvals=None)` implementa a porta `CommandGate`:
  - `check_command(argv, cwd, mode, risk, *, consume=True) -> PermissionDecision` com resultado `ALLOW`, `DENY` ou `NEEDS_APPROVAL` e um motivo. O modo `plan` nega tudo o que não está na lista de somente leitura (`security.readonly`: diagnósticos comuns, recusados com opções que escrevem, executam, alcançam outra máquina ou mudam estado; `sed`, `awk`, `tee`, `xargs` e `env` nunca estão nela); um argumento que nomeia um caminho protegido é negado; quando é uma concessão que permite o comando, `consume=True` a gasta.
  - `resolve_program(argv, cwd)` procura um nome de programa simples somente em `permissions.exec_path`, nunca no `$PATH`, recusa um programa que se resolve dentro da árvore de trabalho da execução e trata um programa dado por caminho relativo como dependente de aprovação.
  - `enforce_command(...)` lança `PermissionDenied` ou `ApprovalRequired` em vez de devolver.
  - `check_tool(tool, mode, risk, agent_tools_allow=(), agent_tools_deny=(), *, consume=True) -> PermissionDecision`.
  - `check_path(path, cwd) -> PermissionDecision` nega um caminho protegido citado fora de um argv (alvo de redirecionamento).
- `security.shell.split_commands(line) -> tuple[SimpleCommand, ...] | None` divide uma linha de comando de shell em seus operadores de controle, respeitando aspas, e tira os redirecionamentos de cada argv. Devolve `None` para tudo o que não consegue dividir com certeza. Só o hook de Bash o usa; o executor nunca roda um shell.
- `security.commands`: `parse(command, allow_shell=False) -> tuple[str, ...]` (rejeita metacaracteres de shell a menos que a política permita um shell), `expand(argv) -> Expansion` (desembrulha `sudo`, `env`, `sh -c`, `nohup`, `timeout`, `script`, `nice` e similares), `classify(argv) -> CommandRisk` (`destructive`, `external_effect`, `privileged`, `network`, `unanalyzable`) e auxiliares de padrão `matches`, `first_match`, `is_allowed`. A classificação cobre abreviações únicas de opções longas do git, configuração do git passada na linha de comando e subcomandos desconhecidos do git. `ssh`, `scp` e `sftp` são efeito externo, então exigem aprovação como comandos locais.
- `security.paths`: `resolve_within(root, path) -> Path` lança `PermissionDenied` em travessia ou fuga por symlink; `is_protected(path, root, protected_paths) -> bool`.
- `security.redact`: `redact(text) -> str`, `redact_mapping(mapping) -> dict` e `redact_argv(argv)` mascaram segredos antes de qualquer coisa ser registrada ou armazenada; `redact_argv` olha o argv como um todo (valores depois de flags com nome de segredo, cabeçalhos `Authorization`, URLs com credenciais), também nos caminhos de recusa, e qualquer evento de auditoria que guarde uma lista sob a chave `argv` é mascarado como uma única linha de comando. O `tests/integration/test_refused_redaction.py` procura uma isca em todos os arquivos do diretório de estado depois de execuções permitidas, negadas, que exigem aprovação e recusadas pelo guarda, para os tipos de evento `exec.ran`, `exec.denied`, `exec.approval_requested`, `guard.tripped`, `task.checked`, `approval.requested` e `task.recorded`. A redação é de melhor esforço e tem falhas conhecidas (ver [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md)).
- `security.untrusted`: `wrap(text, source, nonce=None) -> str` cerca conteúdo externo como dado; `scan(text) -> tuple[Finding, ...]` informa padrões que parecem instruções, o que apenas informa. `core.textsafe` remove antes caracteres de controle e sequências de escape. As caudas da saída de comandos, a captura remota, o resumo da execução, o relatório e a saída de descoberta devolvida por `wev run start` (comandos de verificação e nomes de arquivos lidos do repositório) são limpos e cercados assim.

`config.protect_state_dir(config, base=None)` adiciona o diretório de estado a `permissions.protected_paths` seja qual for a lista configurada; `load_config` o aplica. As aprovações ficam lá, então um comando que pudesse escrevê-las poderia se aprovar sozinho. Isso protege contra um comando que cita o caminho; não impede as ferramentas de arquivo do próprio agente (seção 4.10).

### 4.6 `state`

`state.store.StateStore(run_dir, clock=None)` persiste `state.json` (validado contra `state.schema.json`, traz `schema_version` e um `revision` inteiro) e um `events.jsonl` somente de acréscimo. As execuções ficam em `<state_dir>/runs/<run_id>/` (`run_dir`, `list_runs`, `active_run`, `new_run_id`). O diretório de estado é resolvido na raiz do repositório, não no diretório atual; tem seu próprio `.gitignore`, os diretórios são criados com modo 0700 e os arquivos, inclusive os de trava, com modo 0600. Estado escrito por um layout anterior não carrega (`state_version_unsupported`).

- `create(objective, mode, run_id=None, config, config_digest, config_source) -> RunState`, `load() -> RunState`, `update(mutator, expected_revision=None) -> RunState`, `append_event(type, data)`, `events()`.
- As escritas pegam um arquivo de trava exclusivo (esperando no máximo `limits.lock_timeout_seconds`), releem, conferem a revisão, escrevem em um arquivo temporário, fazem `fsync` e depois `os.replace`. Uma revisão divergente lança `StateConflict`. `core.engine.Engine.commit(change, ..., base=state)` torna a escrita **condicional à revisão que foi carregada e validada**: uma mudança feita por outro processo nesse intervalo é recusada, e quem chamou repete leitura, validação e escrita um número limitado de vezes (`Engine.retry`).
- `state.model.RunState` é imutável. As mudanças são funções puras que devolvem um novo estado (`with_plan`, `with_task_status`, `with_result`, `with_attempt`, `with_decision`, `with_command`, `with_evidence`, `with_guard_event`, `with_pending_approval`, `with_remote_run`, `reopen`, ...). `with_task_status` impõe as transições legais de tarefa e que as dependências estejam verificadas. `RunState` traz a configuração fixada (`config`, `config_digest`, `config_source`) e as execuções remotas que a run iniciou (`remote_runs`, campo opcional, de modo que estados sem ele carregam).
- `state.records`: `VerificationRecord`, `ReviewRecord`, `TaskBaseline`, `ToolMiss`, guardados em `RunState` e nos registros das tarefas.
- `state.resume`: `snapshot_repo(root, runner) -> RepoSnapshot | None` e `check_drift(state, runner, root=None) -> DriftReport`, que compara HEAD, branch, arquivos modificados e arquivos reportados registrados com o repositório real e lista as tarefas ainda registradas como em execução.
- `core.run_registry`: um arquivo por usuário (`$XDG_STATE_HOME/wev-skills/active-runs.json`, senão sob `~/.local/state`) que lista a raiz do repositório, o diretório de estado e o id de cada execução ativa, para que o hook ache uma execução a partir de um caminho citado em um comando. É uma conveniência para o hook; as ferramentas de arquivo do agente podem editá-lo (seção 4.14).

### 4.7 `context`

`context.manager.ContextManager(budget_tokens, elide_at=0.6, summarize_at=0.85, summarizer=None, archive_dir=None, min_elide_tokens=200, keep_recent=3)` é imutável.

- `add(item) -> ContextManager`, `usage() -> float`, `total_tokens() -> int`, `render() -> list[ContextItem]`, `recall(item_id) -> str`, `compact() -> tuple[ContextManager, CompactionReport]`. `recall_archived(archive_dir, item_id)` lê um original arquivado sem precisar de um gerenciador.
- Os itens têm um `kind` (`requirement`, `decision`, `error`, `evidence`, `tool_output`, `note`). Requisitos, decisões e evidências são fixados e nunca são elididos nem resumidos.
- Estágio 1 (em `elide_at`): substitui os itens `tool_output` grandes mais antigos por um marcador que aponta para o original arquivado. Estágio 2 (em `summarize_at`): chama o resumidor injetado nos demais itens não fixados. Sem resumidor, o estágio 2 é pulado e informado.
- **Quem o usa.** `wev context compact` e `wev context recall` (um arquivo JSON de itens entra, uma lista compactada e um relatório saem) e o harness de avaliação. O fluxo de orquestração (`wev run`, `wev task`) não o usa. Ele gerencia apenas o contexto que quem chama lhe entrega; não controla nem consegue controlar a janela de contexto do próprio Claude Code.

### 4.8 `guards`

`guards.execution.evaluate(events, limits, now=None, unresolved_dependencies=()) -> GuardVerdict` é uma função pura sobre `GuardEvent`s registrados (`command`, `agent_handoff`, `task_attempt`, `verification`, `progress`, `budget`, `reset`; criados com `command_event`, `handoff_event`, `attempt_event`, `verification_event`, `progress_event`, `budget_event`, `reset_event`). `ExecutionGuard(limits).observe(history, event) -> (new_history, GuardVerdict)` acrescenta e julga. `GuardLimits.from_config(limits_config)` pega os limiares da configuração (`GuardLimits().task_timeout_seconds` e `LimitsConfig().task_timeout_seconds` compartilham `config.DEFAULT_TASK_TIMEOUT_SECONDS`, 3600); uma spec de agente reduz `max_attempts` e `timeout_seconds` da sua tarefa e define o orçamento da tarefa (`core.agent_rules.task_limits`).

Detecta comandos idênticos repetidos, **ciclos de comandos alternados** (por exemplo A, B, A, B sem progresso), falhas consecutivas, tentativas esgotadas e erros repetidos, ciclos de passagem entre agentes, ausência de progresso observável (comandos `wev exec` de somente leitura não contam para a janela de ausência de progresso, embora um comando idêntico repetido continue sendo um laço, e a leitura no modo plan não dispara `no_progress`), estouro de orçamento e de tempo, dependências não resolvidas, verificação repetida sem mudança entre elas e **polling** além de `limits.max_polling_commands`. Comandos marcados com `polling=True` ficam isentos da regra de repetição apenas para uma tarefa em execução que já rodou um comando, e o teto acima continua valendo; há uma tolerância configurável para testes instáveis. O guarda nunca interrompe nada: devolve um veredito (`action`, `rule`, `reasons`, `details`) e quem chamou decide.

Em uma execução, o motor o alimenta com eventos reais: cada `wev exec` e cada verificação é um evento de comando com a impressão digital da árvore de trabalho, um evento de progresso é acrescentado quando a impressão digital muda, a execução de comandos e de verificações gasta unidades de orçamento e cada tentativa registrada acrescenta um evento de tentativa. Enquanto o veredito da tarefa ou da execução for STOP ou ASK_HUMAN, `wev exec` e `wev task check` são recusados (`GuardTripped`, saída 6) e `wev task next` não entrega trabalho. Cada disparo fica guardado na execução (`guard_trips`) e permanece no relatório. Só uma pessoa o libera, com `wev guard acknowledge` (seção 4.10).

### 4.9 `execution` e `verification`

- `execution.executor.CommandExecutor(gate, runner, log_dir, redactor, clock=None, resolver=None)`.`run(command, cwd, mode, risk, timeout=None, task_id=None, track_changes=True) -> CommandRecord` com `argv`, `cwd`, `duration_ms`, `exit_code`, `status: RunStatus`, `stdout_ref`, `stderr_ref`, `stdout_tail`, `stderr_tail`, `changed_files`, `timed_out`, `task_id`, `started_at`, `program`. Consulta o portão primeiro e lança `PermissionDenied` ou `ApprovalRequired`. O programa é resolvido no caminho seguro fixo (`permissions.exec_path`) e o **caminho resolvido é registrado** em `program`; o argv é redigido como um todo antes de ser registrado ou devolvido; a saída é redigida antes de ser escrita e as caudas são limpas e cercadas como dado não confiável. O processo filho herda o ambiente de quem chamou. Um protocolo `Runner` envolve o `subprocess` para que os testes injetem um falso. Um tempo esgotado resulta em `UNKNOWN`, nunca em `PASSED`; um comando que não conseguiu iniciar é `BLOCKED`. `to_evidence(record, label)` e `to_guard_event(record, polling, flaky)` convertem um registro.
- `verification.engine.VerificationEngine(executor).verify(contract, checks, cwd, mode, stop_on_failure=True, manual_evidence=(), baseline_passed=None, tree_unchanged=False) -> VerificationReport`: executa as verificações das mais baratas às mais caras, para cedo na falha quando configurado e marca cada critério de aceitação como `met`, `unmet` ou `unverified`. Um critério sem evidência é `unverified`; `all_met` é falso quando não há critérios. `checks_from_contract(contract)` monta as verificações e `build_result(contract, report, changed_files, manual_evidence=())` um `TaskResult`.
- O que conta como evidência de um critério (`verification.engine`, `verification.trivial`, `core.evidence`):
  - Uma verificação que **o plano amarrou ao critério** (um objeto de verificação com `criteria`) sustenta apenas esses critérios. Uma string de comando simples sustenta todos os critérios e é rotulada **sem amarração**: evidência mais fraca, e o relatório e os avisos dizem isso.
  - Uma **verificação sem efeito** (`true`, `:`, `echo`, `printf`, `test` sobre constantes, `sh -c 'exit 0'` e similares, reconhecidas em `verification.trivial`) não conta como evidência. É um piso, não uma prova: uma verificação vazia mais esperta não é pega, e o motor não julga se as verificações bastam.
  - Uma verificação que **já passava na linha de base da tarefa**, sem mudança na árvore de trabalho desde o início da tarefa, não conta como evidência. Uma tarefa `read_only` fica isenta.
  - A **evidência manual** (`wev task record --evidence-file`) só vale para um critério quando está rotulada como testada e seu `ref` é um arquivo existente sob o diretório de logs da execução, sob o diretório de evidências da execução (`<diretório de estado>/runs/<id>/evidence/`) ou um dos arquivos que a tarefa lista no plano; qualquer outro arquivo existente é recusado e o erro diz isso (para mostrar um arquivo ou uma saída, rode-o por `wev exec` e referencie o log). É uma afirmação do agente e o relatório a rotula assim.
  - `verified` também exige que a impressão digital da árvore de trabalho, **recalculada em `task record`**, seja igual à que a verificação aprovada viu (`tree_changed` caso contrário). Uma tarefa verificada que não é `read_only` e não mudou nenhum arquivo desde que começou não torna a execução completa.
- `core.baseline`: em `task start` as verificações da tarefa rodam uma vez como linha de base (`harness.baseline_checks`, ligado por padrão), pelo mesmo executor e pela mesma política e sem gastar aprovação. Os comandos ficam marcados como linha de base no log e não são eventos do guarda. Com a opção desligada, só a impressão digital inicial é registrada.

### 4.10 `governance`

- `governance.approvals.ApprovalStore(path, clock=None, ttl=...)`: `request(action, risk, reason, requested_by, cwd=..., reopen_denied=False) -> ApprovalRequest`, `grant(id, by, terminal)`, `deny(id, by, terminal)`, `get(id)`, `list(status=None)`, `is_granted(action, cwd)`, `is_denied(action, cwd)`, `consume(action, cwd) -> bool`, `verify() -> tuple[Mismatch, ...]`. Status: `pending`, `granted`, `denied`, `consumed`, `expired`.
  - Uma concessão fica presa ao argv exato (token a token), ao diretório de trabalho resolvido e à execução (em uma ação remota o primeiro token é o alias do host). É de **uso único**, **expira** após `permissions.approval_ttl_seconds` (padrão 900) e a execução que a usa a consome. Não existem concessões reutilizáveis.
  - Uma negação é definitiva para aquela ação naquela execução. "A mesma ação" significa as mesmas palavras na mesma ordem dentro da execução: cada token do argv é separado como numa linha de comando e tokens em branco são descartados; assim, o diretório de trabalho, o risco declarado, o motivo, as aspas, os espaços e o agrupamento em tokens não produzem um pedido novo; o `wev approval request` devolve o registro negado e o `wev exec` responde negado. Para uma ação remota, o alias do host é a primeira palavra, então a negação vale por host. Uma execução nova começa limpa. A comparação é por palavras e não resolve caminhos (`build` e `./build` diferem), e o registro é um arquivo na conta do agente. Somente `wev approval request --reopen-denied`, um comando do operador humano, o substitui por um pedido novo pendente.
  - Um pedido registra `requested_by`, um nome que quem chama informa (autodeclarado); uma decisão registra o usuário do sistema operacional, o dispositivo do terminal e a hora. Nada compara os dois, porque dentro de uma conta o motor não distingue quem pede de quem opera.
  - Um comando cujo texto a redação alteraria é **recusado** em vez de ser enviado para aprovação, para que o operador veja exatamente o que seria executado.
  - `approval grant`, `approval deny`, `guard acknowledge`, `task reopen` e `approval request --reopen-denied` são **comandos do operador humano**: exigem um terminal em stdin e stdout, mostram a ação completa e pedem uma palavra impressa na tela. Não existe flag que contorne isso. O registro guarda o usuário do sistema operacional, o dispositivo do terminal e a hora, não uma identidade. Um agente que precise de um deles para e pede à pessoa que o execute no próprio terminal.
  - **Evidência de adulteração, não prova.** Toda decisão também é acrescentada ao log de auditoria, uma concessão só é honrada quando existe ali um evento `approval.granted` correspondente, e `wev approval verify` lista as divergências (saída 1). Isso pega acidentes e uma concessão escrita direto em `approvals.json`. Não pega um agente que reescreve os dois arquivos com suas próprias ferramentas.
- `governance.audit.AuditLog(path, clock=None)`: `append(event_type, data)` escreve uma linha JSON redigida; `read(limit=None)`.
- Por que os arquivos não são protegidos do agente: o motor roda na mesma conta de usuário do agente que ele restringe, então não consegue autenticar quem está digitando, e qualquer chave guardada nessa conta poderia ser lida pelo agente. O portão em que uma pessoa pode confiar é o prompt de permissão do próprio Claude Code, alcançado pelo hook (seção 4.14). Sem os hooks, as aprovações são registros. Ver o [ADR 0006](decisions/0006-guardrail-not-boundary.pt-BR.md).

### 4.11 `remote` (opcional)

- `remote.inventory.Inventory`: os aliases SSH permitidos e seu rótulo de ambiente (`staging`, `production`, ...). Hosts fora do inventário são recusados.
- `remote.transport.SshTransport(runner, connect_timeout=10, redactor=None)`: monta `ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=<n> -- <alias> <command>`; nunca passa senhas nem material de chave.
- `remote.tmux.TmuxController(transport, inventory, gate, approval_check, redactor, clock, base_dir="~/.wev/remote", command_timeout=30.0)`: `preflight(alias)`, `start(alias, task_id, argv, mode, risk, timeout_seconds=None) -> RemoteRun`, `status(alias, task_id) -> RemoteStatus`, `capture(alias, task_id, lines=200) -> str`, `stop(alias, task_id)`, `list_owned(alias)`. Os nomes de sessão são `wev-<task>-<hosthash>`; a posse é provada por uma opção marcadora definida na criação; sessões desconhecidas nunca são tocadas; `kill-server` nunca é emitido.
- A lógica de aprovação vive em `governance`, não aqui: o portão, a verificação de aprovação e o solicitante de aprovação são injetados. Um início é governado pelas verificações do próprio controlador, em ordem: inventário, modo (`plan` recusa), o portão sobre o argv remoto, uma verificação de somente leitura para hosts sem `allow_mutating` e uma concessão para a ação exata `<alias> <command>` quando o portão pede aprovação ou o host é de produção. Quando falta a concessão, o controlador registra o pedido de aprovação dessa ação qualificada pelo host (de modo que ele nunca possa ser satisfeito por uma aprovação do mesmo comando executado localmente) e lança `ApprovalRequired` com `approval_id` e um `next_step` para o humano. O `ssh` do controlador é transporte, não um comando executado pelo executor, então a regra de que um `ssh` local exige aprovação não se aplica a ele.
- **Durante uma execução ativa** (`remote.run_scope`): o modo, o risco e o inventário de hosts vêm da execução e a linha de comando só pode repeti-los ou ser mais restritiva; um `--config` diferente é recusado; a `--task` precisa estar no plano da execução e seu agente precisa ter `permissions.may_use_remote`. Sem execução, `--mode` é obrigatório em `start`.
- **Registros de execução remota.** Com uma execução ativa, um início é gravado no estado da execução (`RunState.remote_runs`, escrito com `with_remote_run`), um registro por tarefa e host. Sem execução ativa nada é gravado. `status` só confia em um arquivo de saída com posse comprovada: a sessão ainda existe e traz o marcador desta tarefa ou, depois que ela some, existe um início registrado desta tarefa neste host; do contrário a resposta é `unknown` e nomeia a evidência que falta. Um registro danificado é erro, não uma lista vazia.
- A saída capturada é limpa, redigida e cercada como dado remoto não confiável antes de a CLI devolvê-la.

### 4.12 `evaluation`

`evaluation.harness.run(tasks, configs, agent=ScriptedAgent) -> EvalReport`. As tarefas são fixtures JSON em `evals/tasks/`. O agente padrão é um roteiro determinístico, de modo que o próprio harness é testável sem modelo. Ele executa o gerenciador de contexto, o guarda de execução, o roteador de modelos e a política de decisão local reais; tem o próprio laço de tentativas e escalonador e **não** chama o motor de orquestração, portanto linhas de base, aprovações, a política de permissões e o motor de verificação não são exercitados pelos seus resultados. Métricas: taxa de sucesso, critérios de aceitação atendidos, tentativas, escalonamentos, disparos do guarda, estouros de contexto, verificações não executadas, falhas de seleção de ferramentas, tokens estimados de definição de ferramentas (oferecidas e selecionadas), custo e duração simulados. Ver [evals/README.pt-BR.md](../../evals/README.pt-BR.md).

### 4.13 `core`: montagem e orquestrador

`core.wiring` é a raiz de composição. A partir de uma `Config` e da raiz do repositório, monta os colaboradores reais: `build_approval_store`, `build_audit_log`, `build_policy` (política mais o armazenamento de aprovações e o registro de ferramentas, diretório de estado protegido), `build_executor` (com redação), `build_provider` (por `decisions.factory`, de modo que `decision.provider` tem efeito), `build_model_router`, `build_agents -> AgentCatalog` (registro, fábrica, ids de templates), `build_remote_controller` e `build_services -> Services`, que os reúne para uma invocação da CLI. Um `state_dir` relativo é tomado a partir da raiz do repositório.

**Resolução e fixação da configuração** (`config.resolve_config`). Fora de uma execução, a configuração é `--config CAMINHO` se informado, senão `<raiz do repositório>/wev.config.json` se existir, senão os padrões. `wev run start` grava no estado da execução a configuração efetiva, seu resumo (digest) e sua origem; todo comando posterior dessa execução usa a gravada, e um `--config` de conteúdo diferente é recusado (`config_pinned`). `wev config show` resolve a configuração do mesmo modo (e imprime sua origem, a configuração fixada enquanto há uma execução ativa para o diretório, e avisos); `wev config validate CAMINHO` confere esse arquivo sob as mesmas regras. Uma configuração não pode nomear um programa ou um diretório que o repositório controla: `decision.jev.command` é um nome de programa simples (não um shell nem um interpretador) ou um caminho absoluto fora do repositório, e `agents.directories` fica dentro do repositório ou do diretório de configuração do usuário.

`core.orchestrator.Orchestrator(store: StateStore, services: Services)` é um serviço sobre uma execução. Cada método faz uma transição validada e devolve dados simples para a CLI; nada é mantido entre chamadas. Toda mudança passa por `StateStore.update` e acrescenta um evento de auditoria, e o texto é redigido antes de ser armazenado.

| Método | Comando | Regra que impõe |
|---|---|---|
| `start(objective, mode, signals, run_id=None)` | `wev run start` | Recusado enquanto outra execução estiver ativa (`run_active`); fixa a configuração; instantâneo, descoberta, classificação e estratégia são registrados, cada um, como uma decisão com motivos; a saída de descoberta é devolvida higienizada e cercada como dado não confiável |
| `status()` | `wev run status` | Somente leitura |
| `set_plan(path)`, `show_plan()` | `wev plan set`, `wev plan show` | Esquema do plano e `Plan.validate()`; as verificações podem ser strings ou objetos que amarram um comando a critérios; um agente (`agent_hint`, senão `route_agent`) e um modelo por tarefa, ambos registrados; o risco próprio de uma tarefa só pode elevar seu risco efetivo; um plano não pode descartar uma tarefa que já rodou; para uma tarefa já iniciada alguma vez, mudar seus critérios, verificações, arquivos, risco ou a marca `read_only` exige `--amend --reason <texto>` (registrado como decisão e como evento de auditoria `plan.amended`, zera a verificação da tarefa, listado no relatório em "Plan amendments"; o motor não julga se os critérios novos são mais fracos); imprime `warnings` para uma verificação que vai precisar de aprovação na execução (por exemplo código inline de interpretador como `python3 -c ...`), uma verificação que será recusada e um caminho que o git ignora |
| `next_tasks()` | `wev task next` | Recusa no modo `plan` e diante de veredito do guarda STOP ou ASK_HUMAN; oferece no máximo `max_parallel` tarefas, nenhuma com dependências não verificadas, nunca duas cujos `files` se sobreponham (uma tarefa sem `files` roda sozinha); uma tarefa gated ou de alto risco espera uma concessão humana; calcula a seleção de ferramentas de cada tarefa oferecida quando `harness.tool_selection` está ligado |
| `start_task(task_id)` | `wev task start` | Mesmas regras; gasta a concessão; todo início conta como uma tentativa e é recusado além do limite; registra agente, modelo, um evento de passagem para o guarda e a linha de base (`core.baseline`) |
| `exec_command(argv, task_id, timeout, polling, flaky)` | `wev exec` | O comando roda sob o modo da execução e o risco da tarefa; recusado enquanto houver veredito STOP ou ASK_HUMAN; em uma execução no modo execute o comando age por uma tarefa que está `RUNNING`: `--task` precisa nomear uma (senão é recusado, nomeando as tarefas em andamento), sem `--task` usa-se a única tarefa em andamento e a saída avisa (`task_implied: true`, `task_note`), e com nenhuma ou várias em andamento só comandos de somente leitura são aceitos; um agente com `may_mutate: false` fica limitado como descrito na seção 4.3; a entrada de log e os eventos do guarda são armazenados |
| `check_task(task_id, stop_on_failure)` | `wev task check` | Mesma recusa do guarda; armazena o relatório de verificação, sua evidência, o estado da linha de base e eventos do guarda com a impressão digital da árvore de trabalho |
| `record_task(task_id, status, summary, ...)` | `wev task record` | `verified` exige todo critério atendido por uma verificação recente aprovada ou por evidência manual com ref de arquivo real, e uma árvore inalterada (seção 4.9); `failed` exige uma tarefa em execução; uma falha registra uma tentativa com assinatura de erro e consulta `should_escalate`; quando as tentativas se esgotam a tarefa vira `BLOCKED` |
| `review_task(task_id, reviewer, accepted, summary)` | `wev task review` | O revisor precisa ser um agente conhecido diferente do que executou a tarefa; sua identidade é autodeclarada; uma rejeição reabre a tarefa |
| `reopen_task(task_id, reason, ...)` | `wev task reopen` | Somente operador humano. Devolve uma tarefa bloqueada, com falha ou parcial a `PENDING` com a contagem de tentativas zerada; o histórico fica |
| `restore_tool(task_id, tool, reason)` | `wev task tools --add` | Apenas uma ferramenta que o agente tem permitida e que a seleção descartou, para uma tarefa em execução; contada como falha de seleção |
| `guard_check(task_id=None)` | `wev guard check` | Somente leitura |
| `resume()` | `wev run resume` | A divergência é registrada como decisão; uma tarefa registrada como em execução precisa ser verificada de novo antes de `verified` |
| `report(lang=None)` | `wev run report` | Somente leitura; `complete` apenas quando toda tarefa está verificada (e, se não for `read_only`, mudou algo) e toda revisão exigida foi aceita; disparos e reconhecimentos do guarda são listados. A árvore é comparada com a do último registro `verified` quando o relatório é calculado (também no `run finish`): se ela difere e nenhuma tarefa está em andamento, as tarefas verificadas cujas verificações não passaram na árvore atual são reportadas como "verified, then changed" e o estado é `incomplete` até o `wev task check` passar de novo. É recalculado na hora do relatório, não continuamente |
| `brief(max_chars=None, lang=None)` | `wev run brief` | Somente leitura; texto simples dentro do limite, sem cortar linha, cercado como dado |
| `finish()` | `wev run finish` | Define a fase `done` com uma decisão dizendo se a execução estava completa; toda mudança posterior na execução é recusada (`run_finished`) |

Tentativas: todo início de tarefa conta. O escalonamento para um tier de modelo mais alto dispara na metade do limite (arredondada para cima) ou diante de uma assinatura de erro repetida; no limite a tarefa fica `BLOCKED` e só uma pessoa pode reabri-la.

Módulos de apoio: `core.discovery` (`discover_checks(root)` lê `Makefile`, `package.json`, `pyproject.toml`, `Cargo.toml` e `go.mod` como dados e sugere comandos de um vocabulário fixo; nada é executado), `core.planning` (carga do plano, síntese de uma única tarefa quando a estratégia dispensa plano, atribuição de agente e modelo, seleção de tarefas, `build_contract`), `core.progress` (perguntas puras sobre um estado: risco efetivo, verificação recente, situação da revisão, veredito do guarda, `next_steps`), `core.evidence`, `core.baseline`, `core.task_reopen`, `core.tool_select`, `core.report` e `core.report_markdown`.

Toda saída traz `next_step` (o primeiro) e `next_steps` (uma lista de tudo o que pode ser feito agora): linhas de comando concretas ou, quando só uma pessoa pode agir (uma aprovação, uma tarefa com as tentativas esgotadas), uma instrução de parar e perguntar ao operador humano. Também se imprime uma instrução para: uma aprovação pendente; uma barreira negada ("denied by the operator", reaberta com `wev approval request --reopen-denied`, nunca um comando de concessão); uma tarefa esgotada (todas as tentativas usadas, bloqueada), cujo passo principal é pedir ao humano que rode `wev task reopen` e que não pode ser registrada como `not_executed`; o modo plan depois que o plano é definido ("ready for human review"; executar exige uma execução nova no modo execute depois de `wev run finish`); e uma verificação sobre uma árvore em que nada mudou (faça o trabalho, ou marque a tarefa como `read_only` com `--amend --reason`). Uma aprovação obsoleta (a verificação que a exigia foi substituída e o `task check` informa `all_met`) não bloqueia o `next_step` e aparece em `stale_approvals`. O motor nunca imprime um comando de concessão como passo que um agente poderia executar. `core.brief` monta o lembrete do plano a partir de um estado: objetivo, fase, uma linha por tarefa, os critérios de aceitação da tarefa atual, aprovações pendentes e o próximo passo, ajustados a um limite de caracteres descartando linhas inteiras, das menos importantes para as mais, e cercados como dado. Quando o guarda apenas aconselha mudar de estratégia por um comando repetido e o mesmo comando continua rodando, `core.progress.task_verdict` transforma o veredito em ASK_HUMAN para que `next_tasks` pare de entregar trabalho.

### 4.14 Hooks do Claude Code (`adapters.claude_code.hooks`, `adapters.claude_code.bash_guard`, `commands.hook`, `hooks/hooks.json`)

Três hooks executam `wev hook <nome>`, cada um lendo o JSON do hook em stdin (no máximo 1 MiB).

| Hook | Evento e matcher | O que imprime |
|---|---|---|
| `session-context` | `SessionStart`, `compact\|resume` | Uma linha dizendo que o texto é o estado registrado da execução e que `wev run resume` confere o estado real, depois o resumo (cercado e higienizado) |
| `prompt-reminder` | `UserPromptSubmit` | O resumo limitado a `harness.plan_reminder_max_chars`, quando `harness.plan_reminder` é verdadeiro |
| `pre-tool-use` | `PreToolUse`, `Bash` | Uma decisão `deny` ou `ask` como um único objeto JSON, ou nada |

- **Encontrar a execução.** A partir do `cwd` do hook, dos diretórios que o contêm até a raiz do git e de todo caminho que o comando cita (`cd`, `pushd` e `git -C` são seguidos), usando `core.active.find_active_run` e o registro de execuções por usuário. Olhar é somente leitura e não cria nada. O trabalho tem limite.
- **Pré-checagem de Bash.** O comando é julgado sob a configuração **fixada** da execução ativa, seu modo e o maior risco entre as tarefas em andamento, sem consumir aprovações e **sem ler o armazenamento de aprovações**: um comando destrutivo é `ask` toda vez e a resposta da pessoa no prompt do Claude Code é a aprovação daquela chamada. DENY da política vira `deny`; NEEDS_APPROVAL vira `ask`; ALLOW não imprime nada. O hook nunca responde `allow`, então só pode endurecer as configurações de permissão do usuário.
- **O que ele manda para o humano.** Os comandos sensíveis do próprio motor, quando a linha de comando é uma que o hook consegue ler: `approval grant`, `approval deny`, `approval request` (com ou sem `--reopen-denied`), `guard acknowledge`, `task reopen`, `run adopt`, `run start`, `run finish`, `agent create`, `agent export`, `remote start`, `remote stop` e qualquer comando com `--config`, reconhecidos pelas palavras (o lançador pelo caminho real, a palavra `wev` solta ou `-m wev_skills`) diretamente, atrás de um invólucro que o classificador conhece, em um `sh -c`, `bash -c` ou `zsh -c` inline, ou como argumentos passados a outro programa. A isenção da política comum continua valendo só para um programa que resolve, por caminho real, para o `bin/wev` do plugin ou para o interpretador em uso com `-m wev_skills`. O hook não enxerga o interior de um arquivo de script nem de um programa; por isso um script que digita em um pseudoterminal não gera pergunta. Também pergunta por opções longas abreviadas de `rm`, `git rm -r`/`-f`, `git clean` que não seja simulação, `rsync --delete*` e um leitor recursivo que receba um diretório contendo um caminho protegido: uma heurística sobre uma lista fixa, limitada a 20.000 entradas. Atribuições de variáveis de shell antes de um comando, as palavras de shell que definem variáveis, expansões de shell não resolvidas, `eval`, `source`, invólucros que ele não consegue analisar e um argumento que contém uma linha de comando inteira dão `ask` (`deny` no modo plan). A lista completa está em [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md).
- **Política de falha.** Silencioso somente enquanto nenhuma execução é conhecida. Quando uma execução é conhecida, um estado ilegível ou forjado, um erro interno, entrada malformada ou grande demais e um comando longo demais para análise viram `ask` com um motivo, nunca silêncio. O `bin/wev` sai quieto, com uma nota no stderr, para os subcomandos de hook em um Python anterior ao 3.10, o que significa que nada foi verificado (o `/usr/bin/python3` original do macOS é o 3.9).
- **Limites.** Só a ferramenta Bash passa pelo hook. Edições feitas com as ferramentas de arquivo do próprio Claude Code não são vistas, inclusive edições no diretório de estado, no arquivo de aprovações, no log de auditoria, na configuração e no registro de execuções; um agente pode remover uma entrada do registro para que o hook não encontre execução. Scripts e interpretadores (`python3 script.py`, `make`), `mv`, `sed -i`, redirecionamentos e programas desconhecidos por caminho absoluto não são barrados no modo execute, e os filhos herdam o ambiente de quem chamou. Os hooks só agem quando o plugin está instalado e habilitado. Têm testes unitários e um teste de subprocesso e não foram exercitados em uma sessão real do Claude Code.

### 4.15 Diretrizes do CLAUDE.md (`adapters.claude_code.claude_md`, `commands.claude_md`)

`wev claude-md init|update|check|show` gerencia um bloco do CLAUDE.md de um projeto, delimitado por marcadores, em inglês ou português do Brasil (`guidelines/guidelines.<lang>.md`). `init` cria o arquivo ou insere o bloco em um existente; `update` reescreve apenas o bloco; `check` informa o que falta ou está desatualizado e sai com 2 quando algo está; `show` imprime o bloco; `--dry-run` imprime o diff e não escreve nada. Os comandos de verificação achados por `core.discovery` são lidos como dado. A skill `wev-claude-md` o conduz. Uma checagem de README faz parte do escopo e tem a própria skill (ver a [especificação](../spec.pt-BR.md)).

### 4.16 Seleção de ferramentas (`decisions.tool_selection`, `decisions.local_tools`, `decisions.jev_tools`, `core.tool_select`)

Hipótese H10: entregar menos definições de ferramentas a uma tarefa custa menos contexto. Vem desligada (`harness.tool_selection: off`); `local` reduz com a política offline, `provider` consulta `decision.provider`.

- Os candidatos são a lista allow do agente menos a lista deny. Tudo o que um provider propõe passa por `enforce`: o resultado é um subconjunto dos candidatos, um **piso** é sempre mantido (as ferramentas de leitura que o agente já tinha, a ferramenta de edição quando a tarefa altera arquivos e o agente pode alterá-los, o shell quando a tarefa tem verificações), uma proposta vazia ou malformada volta à política local, um padrão com escopo como `Bash(git:*)` é tratado pelo nome base e a seleção não pode mudar permissões.
- A seleção é calculada uma vez por tarefa, quando seu contrato é montado pela primeira vez, e guardada com a tarefa e como decisão; todo contrato posterior da tarefa concede as mesmas ferramentas. `wev select-tools --task-file F --agent A` imprime uma seleção sem guardar nada.
- Uma ferramenta descartada que se mostra necessária é restaurada com `wev task tools TAREFA --add FERRAMENTA --reason MOTIVO`, apenas entre os candidatos do próprio agente, e contada como falha de seleção.
- Com o JEV como provider, **uma chamada `jev ask` por tarefa** faz uma pergunta `noul` por ferramenta candidata fora do piso, mais uma pergunta `choice` sobre o perfil quando `harness.tool_profile` é `auto`. O estado enviado é o título, o objetivo e os critérios de aceitação da tarefa. Uma ferramenta só é descartada com probabilidade de 0,2 ou menos; uma resposta de perfil abaixo do limiar de confiança (confiança 0,6) é ignorada e usa-se o perfil local. A pergunta de cada ferramenta é montada de modo que uma descrição que já termina em ponto não produza um ".?" sobrando.
- O relatório da execução tem uma seção com as ferramentas oferecidas e selecionadas e estimativas aproximadas de tokens de definição. Os valores somam constantes grosseiras por ferramenta: estimativas para comparação, não medições para qualquer modelo ou cliente. Nenhuma economia de tokens nem ganho em sucesso de tarefa foi medido.

## 5. Estrutura do repositório

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

## 6. Convenções da CLI

`wev <grupo> <comando>` (`bin/wev`, ou `python3 -m wev_skills`). A saída é JSON no stdout; `wev run report --format md` imprime Markdown. Os erros são `{"error": {"code", "message", "details"}}` no stderr. Códigos de saída: `0` ok, `1` erro inesperado, `2` uso ou validação, `3` permissão negada, `4` aprovação necessária, `5` conflito de estado, `6` guarda disparada, `7` não encontrado, `8` falha remota ou de provedor. As mensagens para quem usa estão disponíveis em inglês e em português do Brasil (`--lang`, `WEV_LANG`, um `language` definido num arquivo de configuração ou `LANG`, nessa ordem).

Cada grupo de comandos é um módulo em `wev_skills.commands` com uma função `register(subparsers)`. Um tratador devolve o payload, ou um `cli.CommandResult(payload, exit_code=0, stream="stdout", raw=False)` quando o resultado é uma resposta, e não um erro, mas ainda precisa do seu código de saída: `wev check-command` imprime sua decisão com saída `0` (permitir), `3` (negar) ou `4` (precisa de aprovação); `wev guard evaluate` e `wev guard check` imprimem o veredito com saída `6` a menos que seja CONTINUE; `wev exec` imprime o registro e o veredito com saída `0` (passou), `1` (falhou ou desconhecido) ou `6` (guarda disparada).
