# Plano de implementação: casos com pontuação e especialistas que evoluem sozinhos

Versão em inglês: [2026-10-22-scored-cases-and-self-evolving-specialists.md](2026-10-22-scored-cases-and-self-evolving-specialists.md).

> **Para agentes de execução:** SUB-HABILIDADE OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam a sintaxe de caixa de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** Guardar falhas reais como casos, dar uma nota a um especialista contra eles com e sem cada lição por meio de um `claude -p` sem supervisão, deixar o modelo escrever lições a partir dos casos que falharam e aceitar ou aposentar lições só pela pontuação.

**Arquitetura:** Os casos, o congelamento, a regra da catraca, o filtro de lições e o laço de pontuação ficam em `evaluation/` e dependem só de duas portas em `core/ports.py` (o `Runner` que já existe e um novo `AgentRunner`). O adaptador do Claude Code implementa `AgentRunner` com `claude -p`. As mudanças no armazenamento de lições ficam em `agents/`. Os comandos ligam o adaptador, como o `CLAUDE.md` exige.

**Pilha técnica:** biblioteca padrão do Python 3.14, `unittest`, o validador de esquema JSON do repositório (`wev_skills.schema.validate`), `git worktree`, flags da CLI do Claude Code 2.1.302 confirmadas com `claude --help`.

**Especificação:** [docs/superpowers/specs/2026-10-22-scored-cases-and-self-evolving-specialists-design.pt-BR.md](../specs/2026-10-22-scored-cases-and-self-evolving-specialists-design.pt-BR.md)

## Restrições globais

- Só biblioteca padrão, Python 3.14 ou mais novo, mypy strict, dataclasses congeladas, funções com menos de 50 linhas e arquivos com menos de 400.
- Toda string visível ao usuário passa por `i18n.t`, com chaves idênticas nos arquivos de locale `en` e `pt-BR`.
- Documentação em inglês e português do Brasil no mesmo commit; `PYTHONPATH=src python3 -m unittest tests.unit.test_docs` passa.
- `make test` nunca chama um modelo, a rede nem um harness real; use os falsos em `tests/fixtures/`.
- Cada teste novo é quebrado de propósito uma vez (reverta a linha que ele protege, veja o teste falhar, restaure).
- Nunca faça push, publique nem lance versão sem a autorização explícita do dono. Os assuntos dos commits seguem `<type>: <description>`. Nenhum assistente de IA é citado como autor em lugar nenhum.
- Nunca rode `make test` ao mesmo tempo que outro `make test` nesta máquina.
- Padrões fixados pela especificação: `score_samples` 3, `score_max_runs` 60, `score_max_new_lessons` 3, `score_on_finish` false.
- Ferramentas sem supervisão: exatamente `Read`, `Edit`, `Write`, `Glob`, `Grep`, `Bash`; nunca `--dangerously-skip-permissions`, `--bare` nem `--permission-mode bypassPermissions`.

## Pontos de atenção na revisão

- Um `check` de caso que trava: ele é encerrado em `score_timeout_seconds` e conta como falha, e a execução da pontuação continua (teste na Tarefa 2).
- Uma execução de pontuação interrompida por uma exceção ou Ctrl-C: nenhum worktree fica sobrando em `.wev/scoring/` (teste na Tarefa 2).
- Um `base_commit` ausente (clone raso, sha digitado errado): um erro claro `case_base_missing` antes de qualquer execução do modelo, não um traceback do git (teste na Tarefa 2).
- Duas execuções de pontuação no mesmo especialista ao mesmo tempo: a segunda gravação vê lições mudadas e é recusada com `lessons_changed` (saída 5), sem decidir nada (teste na Tarefa 6).
- Uma resposta do modelo que tenta fechar a cerca de texto não confiável, traz `specialists accept` ou tem vários MB: descartada, nada é gravado (teste na Tarefa 5).

---

### Tarefa 1: Formato do caso, congelamento e `wev cases list|validate`

**Arquivos:**
- Criar: `src/wev_skills/schemas/case.schema.json`, `src/wev_skills/evaluation/cases.py`, `src/wev_skills/commands/cases.py`
- Modificar: `src/wev_skills/locales/evaluation.en.json`, `src/wev_skills/locales/evaluation.pt-BR.json`
- Teste: `tests/unit/test_cases.py`

**Interfaces:**
- Produz:
  - `CASES_DIR = Path("evals") / "cases"`
  - `@dataclass(frozen=True) class Case(Serializable)`: `id: str`, `title: str`, `source: str`, `ref: str`, `agents: tuple[str, ...]`, `base_commit: str`, `objective: str`, `check: tuple[str, ...]`, `files: tuple[str, ...]`
  - `load_cases(root: Path) -> tuple[Case, ...]`, ordenado por id; levanta `ValidationError("invalid_case", ...)` citando o arquivo.
  - `cases_for(cases: Sequence[Case], agent_id: str) -> tuple[Case, ...]`: `agents` vazio significa todos os especialistas.
  - `case_set_digest(root: Path) -> str`: sha256 em hexadecimal sobre cada arquivo regular em `CASES_DIR`, ordenado pelo caminho relativo POSIX, calculando o hash de `path + "\0" + bytes + "\0"` para cada um.
  - `ensure_committed(runner: Runner, root: Path) -> None`: roda `git status --porcelain --untracked-files=all -- evals/cases`; qualquer saída levanta `StateConflict("cases_uncommitted", ...)`.
  - Os arquivos guardados de um caso ficam em `evals/cases/<id>/<caminho relativo ao repositório>` para cada caminho em `files`.

- [ ] **Passo 1: Escreva os testes que falham** em `tests/unit/test_cases.py`, cada um em um diretório temporário:
  - `test_loads_a_valid_case`: um JSON com todos os campos; `load_cases(root)[0].check == ("python3", "-m", "unittest", "tests.unit.test_x")`.
  - `test_rejects_unknown_source`: `source: "rumor"` levanta `ValidationError` com o código `invalid_case`.
  - `test_rejects_file_listed_but_missing`: `files: ["tests/unit/test_x.py"]` sem `evals/cases/<id>/tests/unit/test_x.py` levanta `invalid_case`.
  - `test_rejects_path_escape`: `files: ["../x"]` levanta `invalid_case`.
  - `test_cases_for_empty_agents_means_all` e `test_cases_for_filters_by_agent`.
  - `test_digest_changes_with_any_byte` e `test_digest_ignores_order_of_creation`.
  - `test_uncommitted_case_is_refused`: um `Runner` falso que devolve `?? evals/cases/a.json` levanta `StateConflict` com o código `cases_uncommitted`; saída vazia passa.
- [ ] **Passo 2: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_cases -v`. Esperado: FALHA, `ModuleNotFoundError: wev_skills.evaluation.cases`.
- [ ] **Passo 3: Implemente** o esquema (`source` como enum `e2e`, `review`, `revert`, `incident`; `check` como array não vazio de strings; `additionalProperties: false`) e `evaluation/cases.py`. Os caminhos em `files` passam pelo confinamento que já existe em `security/paths.py`.
- [ ] **Passo 4: Implemente** `commands/cases.py` com `register(subparsers)`: `wev cases list` devolve `{"cases": [case.to_dict() ...], "digest": ...}`; `wev cases validate` devolve `{"valid": true, "count": n}`. `--at-base` entra na Tarefa 2.
- [ ] **Passo 5: Rode** os testes do módulo e depois `bin/wev cases list` em um repositório temporário com um caso. Esperado: PASSA, e JSON com `"digest"`.
- [ ] **Passo 6: Faça o commit** `feat: add the case format and wev cases list|validate`.

### Tarefa 2: Área de trabalho do caso, executor do check e `validate --at-base`

**Arquivos:**
- Criar: `src/wev_skills/evaluation/workspace.py`
- Modificar: `src/wev_skills/commands/cases.py`, os dois locales `evaluation.*.json`
- Teste: `tests/unit/test_case_workspace.py`

**Interfaces:**
- Consome: `Case`, `CASES_DIR` (Tarefa 1); `Runner`, `RawCommandResult` (já existem).
- Produz:
  - `@contextmanager case_workspace(runner: Runner, root: Path, case: Case, scratch: Path) -> Iterator[Path]`: primeiro `git cat-file -e <base_commit>^{commit}` (se falhar, levanta `NotFound("case_base_missing", ...)`), depois `git worktree add --detach <scratch>/<case.id>-<n> <base_commit>`; ao sair, sempre `git worktree remove --force <path>`.
  - `run_check(runner: Runner, case: Case, root: Path, workspace: Path, timeout: float) -> RawCommandResult`: copia cada arquivo de `case.files` de `root / CASES_DIR / case.id` para `workspace` e depois roda `case.check` com `cwd=workspace`.
  - `passed(result: RawCommandResult) -> bool`: `exit_code == 0 and not timed_out`.
  - O diretório de rascunho é `state_dir(config, root) / "scoring"`.

- [ ] **Passo 1: Escreva os testes que falham** com um repositório git temporário de verdade (dois commits, `git` do sistema, como os outros testes unitários em `tests/unit/` já fazem):
  - `test_workspace_is_at_base_and_removed`: dentro do contexto, `HEAD` é igual a `base_commit`; depois dele, o caminho some e `git worktree list` tem uma entrada.
  - `test_workspace_removed_on_exception`: levante uma exceção dentro do `with`; o caminho some.
  - `test_missing_base_is_clear`: um sha que não existe levanta `NotFound` com o código `case_base_missing`, e nenhum worktree é criado.
  - `test_check_sees_case_files`: o check `python3 -c "import pathlib,sys; sys.exit(0 if pathlib.Path('t.txt').exists() else 1)"` só passa porque `files: ["t.txt"]` foi copiado.
  - `test_hanging_check_is_a_fail`: `check` é `python3 -c "import time; time.sleep(5)"` com timeout 0.5; `passed(...)` é falso e a chamada retorna.
- [ ] **Passo 2: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_case_workspace -v`. Esperado: FALHA na importação.
- [ ] **Passo 3: Implemente** `evaluation/workspace.py`.
- [ ] **Passo 4: Acrescente** `--at-base` a `wev cases validate`: para cada caso, abra uma área de trabalho e rode o check; o resultado lista `{"id", "fails_at_base": bool}`, e o comando falha (saída 2, `case_passes_at_base`) quando algum check passa no seu base.
- [ ] **Passo 5: Rode** os testes. Esperado: PASSA.
- [ ] **Passo 6: Faça o commit** `feat: run case checks in a worktree at the base commit`.

### Tarefa 3: Os três primeiros casos e o especialista do próprio wev-skills

**Arquivos:**
- Criar: `evals/cases/health-large-tools-list.json`, `evals/cases/tarball-confined-dotdot-link.json`, `evals/cases/exec-path-owned-dirs.json`, cada um com seus arquivos em `evals/cases/<id>/`; a especificação do especialista criada com `bin/wev specialists create wev-engineer --template senior-engineer --specialty implementation`
- Teste: `tests/unit/test_first_cases.py`

**Interfaces:**
- Consome: `load_cases`, `run_check`, `passed` (Tarefas 1 e 2).

- [ ] **Passo 1: Encontre cada `base_commit`.** Para cada correção (`06fc92c` para a sonda de 1 MiB e para o link `..`, `e3d7b2b` para o caminho do exec), encontre o commit que introduziu o código que a correção mudou (`git log --format=%H --diff-filter=A -- <file>` para um arquivo novo, `git log -L` para uma função) e pegue o pai dele. Registre-o como `base_commit` e a correção como `ref`.
- [ ] **Passo 2: Escreva cada caso.** O `objective` pede a funcionalidade como uma pessoa pediria, citando a função e a assinatura que o teste reprodutor chama, nunca o defeito. O `check` roda só o teste reprodutor, como `["env", "PYTHONPATH=src", "python3", "-m", "unittest", "<module>.<Class>.<test>"]`. Os `files` guardam o teste reprodutor e o fixture copiados do commit da correção (`tests/fixtures/fake_npx_mcp.py` para a sonda).
- [ ] **Passo 3: Escreva o teste que falha** `tests/unit/test_first_cases.py::test_each_case_passes_on_current_tree`: para cada caso, rode `case.check` com `cwd` na raiz do repositório e afirme `passed(...)` (os testes reprodutores já existem na árvore atual). Ele não precisa do histórico do git, então um clone raso de CI funciona.
- [ ] **Passo 4: Rode-o** e depois quebre uma correção de propósito (restaure o limite de 1 MiB em `third_party/health.py`), veja o teste falhar, restaure. Esperado: PASSA depois de restaurar.
- [ ] **Passo 5: Rode** `bin/wev cases validate --at-base` localmente. Esperado: todo caso com `"fails_at_base": true`. Se algum passar no seu base, o `base_commit` ou os `files` dele estão errados; corrija isso, não o check.
- [ ] **Passo 6: Faça o commit** `feat: add the first three cases and the wev-engineer specialist`.

### Tarefa 4: A porta do executor de agente e o adaptador `claude -p`

**Arquivos:**
- Modificar: `src/wev_skills/core/contracts.py`, `src/wev_skills/core/ports.py`
- Criar: `src/wev_skills/adapters/claude_code/agent_runner.py`, `tests/fixtures/fake_claude_agent.py`
- Modificar: `src/wev_skills/locales/harness.en.json`, `harness.pt-BR.json`
- Teste: `tests/unit/test_agent_runner.py`

**Interfaces:**
- Produz:
  - Em `core/contracts.py`: `@dataclass(frozen=True) class AgentRunResult(Serializable)`: `ok: bool`, `output: str`, `timed_out: bool = False`.
  - Em `core/ports.py`: `class AgentRunner(Protocol)` com `run_agent(self, workspace: Path, spec: AgentSpec, objective: str, timeout: float) -> AgentRunResult` e `ask(self, prompt: str, timeout: float) -> AgentRunResult`.
  - `ClaudeAgentRunner(runner: Runner, plugin_root: Path, program: str = "claude")` em `adapters/claude_code/agent_runner.py`. `UNATTENDED_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep", "Bash")`.
  - argv de `run_agent`, exatamente: `[program, "-p", objective, "--output-format", "json", "--plugin-dir", str(plugin_root), "--tools", ",".join(UNATTENDED_TOOLS), "--allowedTools", ",".join(UNATTENDED_TOOLS), "--permission-mode", "dontAsk", "--no-session-persistence", "--append-system-prompt", <corpo de render_subagent(spec) sem o frontmatter>]`, com `cwd=workspace`.
  - argv de `ask`, exatamente: `[program, "-p", prompt, "--output-format", "json", "--plugin-dir", str(plugin_root), "--tools", "", "--permission-mode", "dontAsk", "--no-session-persistence"]`, com `cwd` em um diretório temporário novo e vazio.
  - Saída: interprete o stdout como JSON e pegue o campo string `result`; se não for JSON ou faltar `result`, `ok=False`.
  - Antes de qualquer execução, `plugin_root / ".claude-plugin" / "plugin.json"` e `plugin_root / "hooks" / "hooks.json"` precisam existir, senão `ValidationError("plugin_missing", ...)`.

- [ ] **Passo 1: Escreva `tests/fixtures/fake_claude_agent.py`**, um substituto em Python do `claude` que acrescenta seu argv como uma linha JSON em `$FAKE_LOG` e imprime `$FAKE_CLAUDE_STDOUT` (padrão `{"result": "done"}`), sai com `$FAKE_CLAUDE_EXIT` (padrão 0) e dorme `$FAKE_CLAUDE_SLEEP` segundos.
- [ ] **Passo 2: Escreva os testes que falham:** `test_argv_is_pinned` (o argv registrado é igual à lista acima e não contém nenhum de `--dangerously-skip-permissions`, `--bare`, `bypassPermissions`); `test_ask_has_no_tools`; `test_result_field_is_output`; `test_non_json_is_not_ok`; `test_timeout_is_not_ok`; `test_missing_plugin_is_refused` (nenhum falso é executado).
- [ ] **Passo 3: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_agent_runner -v`. Esperado: FALHA na importação.
- [ ] **Passo 4: Implemente** a dataclass, o protocolo e o adaptador. Use o `SubprocessRunner` existente; reutilize `render_subagent` e tire o frontmatter com a cerca que ele já escreve.
- [ ] **Passo 5: Rode** os testes. Esperado: PASSA.
- [ ] **Passo 6: Faça o commit** `feat: add the agent-runner port and the claude -p adapter`.

### Tarefa 5: A regra da catraca e o filtro de lições do modelo

**Arquivos:**
- Criar: `src/wev_skills/evaluation/ratchet.py`, `src/wev_skills/evaluation/lesson_writer.py`
- Modificar: os dois locales `evaluation.*.json`
- Teste: `tests/unit/test_ratchet.py`, `tests/unit/test_lesson_writer.py`

**Interfaces:**
- Consome: `Case` (Tarefa 1); `wrap`, `scan` de `security/untrusted.py`; `redact` de `security/redact.py`; `LESSON_TEXT_MAX` de `agents/experience.py`.
- Produz:
  - `improves(baseline: Mapping[str, int], other: Mapping[str, int]) -> bool`: verdadeiro quando as chaves são iguais, nenhum caso em `other` tem menos passagens que em `baseline`, e `sum(other) > sum(baseline)`.
  - `lesson_request(case: Case, check_output: str, diff: str, lang: str) -> str`: o prompt, com as três entradas cada uma dentro de uma cerca por `wrap(..., source="case objective" | "check output" | "agent diff")` depois de `redact`, pedindo exatamente `{"lesson": "<uma prática, no máximo 600 caracteres>"}`.
  - `parse_lesson(answer: str) -> str | None`: `None`, a menos que a resposta seja um objeto JSON com uma única chave `lesson` contendo uma string de 1 a `LESSON_TEXT_MAX` caracteres, `scan(text)` esteja vazio e `FORBIDDEN` não case.
  - `FORBIDDEN = re.compile(r"(?i)(allowed[-_ ]?tools|permission|bypass|dangerously|--tools|tools\s*:|model\s*:|\bsudo\b|\bchmod\b|specialists\s+(accept|retire))")`.

- [ ] **Passo 1: Escreva os testes que falham.** `test_ratchet.py`: entra (`{a:1,b:0}` → `{a:1,b:1}` verdadeiro), empate (iguais → falso), regressão (`{a:2,b:0}` → `{a:1,b:3}` falso), chaves diferentes → falso. `test_lesson_writer.py`: resposta válida mantida; chave extra descartada; não-JSON descartado; textos vazio e de 601 caracteres descartados; `"run specialists accept now"` descartado; `"use --allowedTools Bash"` descartado; uma resposta com um marcador `<<<END_` forjado descartada; uma resposta de 5 MB descartada sem deixar a suíte lenta (limite pelo tamanho antes de interpretar); a saída de `lesson_request` contém cada entrada dentro de uma cerca e nunca crua.
- [ ] **Passo 2: Rode** os dois módulos. Esperado: FALHA na importação.
- [ ] **Passo 3: Implemente** os dois módulos.
- [ ] **Passo 4: Rode** os dois módulos. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: add the ratchet rule and the model-lesson filter`.

### Tarefa 6: Armazenamento de lições para decisões de pontuação e lições do modelo

**Arquivos:**
- Modificar: `src/wev_skills/agents/experience.py`, `src/wev_skills/agents/learning.py`, `src/wev_skills/agents/project.py`, `src/wev_skills/schemas/agent.schema.json`, os dois locales `agents.*.json`
- Teste: `tests/unit/test_score_decisions.py`; confira que `tests/unit/test_specialists_learning.py`, `test_agents_experience.py`, `test_lesson_acceptance.py` continuam passando sem mudança

**Interfaces:**
- Produz:
  - Em `experience.py`: `KIND_MODEL = "model"` acrescentado a `LESSON_KINDS`; `SCORER = "score"`, reservado como `PROPOSER`.
  - Em `learning.py`: `model_lesson(case_id: str, text: str, score_id: str, now: str) -> Lesson` com `id=_id(("model", case_id, text))`, `kind=KIND_MODEL`, `status=PROPOSED`, `accepted_by=PROPOSER`, `evidence=LessonEvidence(score_id, case_id, ())`, `derivation="model"`.
  - `_carry` ganha: uma lição com `status == RETIRED and accepted_by == SCORER` volta como `PROPOSED` com `accepted_by=PROPOSER`; `accepted_by == SCORER` e ativa é mantida.
  - `reconcile` mantém toda lição `KIND_MODEL` de `old` que `derived` não contém, passada por `_carry` com ela mesma como `before`.
  - Em `project.py`: `record_scores(root: Path, config: Config, agent_id: str, seen: tuple[Lesson, ...], decisions: ScoreDecisions, record: Record) -> AgentSpec`, em que `@dataclass(frozen=True) class ScoreDecisions`: `new: tuple[Lesson, ...]`, `accepted: tuple[str, ...]`, `retired: tuple[str, ...]`. Sob o lock dos especialistas: se `spec.experience != seen`, levanta `StateConflict("lessons_changed", ...)`; acrescenta `new`; marca `accepted` como `ACTIVE`/`SCORER` e `retired` como `RETIRED`/`SCORER`; nunca toca uma lição com `status == RETIRED` e `accepted_by` de uma pessoa (qualquer valor que não seja `PROPOSER` nem `SCORER`); chama `record()` antes de `_write`.
  - `_decide` continua recusando `PROPOSER` e agora também recusa `SCORER` como nome de operador.

- [ ] **Passo 1: Escreva os testes que falham** em `tests/unit/test_score_decisions.py`: `test_score_accepts_proposed`; `test_score_retired_returns_proposed_after_learn`; `test_person_retired_never_changes` (uma lição aposentada por `"alice"` continua aposentada depois de `record_scores(accepted=(its id,))`); `test_model_lesson_survives_relearning`; `test_changed_lessons_refuse` (passe um `seen` desatualizado, espere `StateConflict` com o código `lessons_changed` e o arquivo inalterado); `test_audit_runs_before_write` (um `record` que levanta exceção deixa o arquivo inalterado); `test_operator_name_score_is_reserved`.
- [ ] **Passo 2: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_score_decisions -v`. Esperado: FALHA.
- [ ] **Passo 3: Implemente** as mudanças e o enum do esquema para `kind`.
- [ ] **Passo 4: Rode** o módulo novo e `tests.unit.test_specialists_learning tests.unit.test_agents_experience tests.unit.test_lesson_acceptance tests.unit.test_lesson_balance tests.unit.test_lesson_usage`. Esperado: PASSA, os antigos sem mudança.
- [ ] **Passo 5: Faça o commit** `feat: store score decisions and model-written lessons`.

### Tarefa 7: Chaves de configuração

**Arquivos:**
- Modificar: `src/wev_skills/config.py` (`SpecialistsConfig`), `src/wev_skills/schemas/config.schema.json`, `docs/guides/configuration-and-providers.md` e `.pt-BR.md` (uma nova seção `specialists` listando as oito chaves)
- Teste: `tests/unit/test_config_specialists.py`

**Interfaces:**
- Produz: `SpecialistsConfig.score_samples: int = 3` (1..10), `score_max_runs: int = 60` (1..1000), `score_max_new_lessons: int = 3` (0..10), `score_timeout_seconds: float = 900.0` (> 0, no máximo 3600), `score_on_finish: bool = False`.

- [ ] **Passo 1: Escreva os testes que falham:** padrões; cada limite recusado com `invalid_config`; um estado fixado com a configuração antiga (sem as chaves de pontuação) ainda carrega.
- [ ] **Passo 2: Rode** o módulo. Esperado: FALHA.
- [ ] **Passo 3: Implemente** os campos e as propriedades do esquema; escreva a seção da documentação nos dois idiomas.
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_docs`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: add the specialist scoring configuration`.

### Tarefa 8: Pontuação, histórico e `wev specialists score|scores`

**Arquivos:**
- Criar: `src/wev_skills/evaluation/scoring.py`
- Modificar: `src/wev_skills/commands/specialists.py`, `src/wev_skills/adapters/claude_code/engine_cli.py`, `src/wev_skills/locales/core.en.json`, `core.pt-BR.json`, os dois `agents.*.json`
- Teste: `tests/unit/test_scoring.py`, `tests/unit/test_hook_bypasses.py` (um caso novo)

**Interfaces:**
- Consome: tudo das Tarefas 1, 2, 4, 5, 6 e 7.
- Produz:
  - `planned_runs(cases: int, proposals: int, active: int, samples: int, new_lessons: int) -> int`, exatamente `(1 + proposals + new_lessons + active) * cases * samples + new_lessons`.
  - `@dataclass(frozen=True) class ScoreReport(Serializable)`: `score_id: str`, `agent: str`, `digest: str`, `baseline: dict[str, int]`, `accepted: tuple[str, ...]`, `retired: tuple[str, ...]`, `new: tuple[str, ...]`, `runs_used: int`.
  - `score_specialist(root: Path, config: Config, runner: Runner, agent: AgentRunner, agent_id: str, audit: AuditLog) -> ScoreReport`. Ordem: `ensure_committed`, digest, carregar a especificação e `cases_for`; recusar com `BudgetExhausted("score_over_cap", ...)` quando `planned_runs(...)` com `new_lessons=score_max_new_lessons` passar de `score_max_runs`; linha de base com as lições ativas; para até `score_max_new_lessons` casos que falharam, `agent.ask(lesson_request(...))` e depois `parse_lesson`; pontuar cada proposta e cada lição do modelo como linha de base mais ela, e cada lição ativa como linha de base menos ela; decidir com `improves`; recalcular o digest e recusar com `StateConflict("cases_changed", ...)` se ele mudou; `record_scores` com eventos de auditoria `specialists.auto_accept` / `specialists.auto_retire` (carga: especialista, lição, digest, antes, depois) gravados em `record`; acrescentar o relatório como uma linha JSON a `state_dir(config, root) / "scores.jsonl"` com `append_line`.
  - O diff entregue a `lesson_request` é o `git diff` na área de trabalho depois que o agente rodou, pelo `Runner`.
  - CLI: `wev specialists score <id>` devolve o relatório; `wev specialists scores [<id>]` devolve as linhas de `scores.jsonl`, a mais nova por último. O comando liga `ClaudeAgentRunner(SubprocessRunner(), plugin_root)` com `plugin_root` = a raiz do repositório acima de `src/` (`ENGINE_LAUNCHER.parent.parent` em `engine_cli.py`).
  - Hook: `SCORE_COMMANDS = frozenset({("specialists", "score")})` com `REASON_SCORE = "engine_score"`, respondido com `ask` (gasta tokens) e fora de `PERSON_ONLY_REASONS`; chave de locale `hooks.reason.engine_score`.

- [ ] **Passo 1: Escreva os testes que falham** em `tests/unit/test_scoring.py` com um `AgentRunner` falso cujo `run_agent` escreve ou omite uma correção na área de trabalho conforme um dado texto de lição aparece em `spec.experience`, e cujo `ask` devolve uma lição roteirizada: `test_planned_runs_formula`; `test_over_cap_refuses_before_any_run` (o falso registra zero chamadas); `test_lesson_that_fixes_a_case_enters`; `test_tie_stays_proposed`; `test_regression_never_enters`; `test_active_lesson_that_hurts_is_retired`; `test_model_lesson_written_and_scored`; `test_cases_changed_during_run_decides_nothing`; `test_history_line_written`; `test_audit_events_carry_digest_and_counts`.
- [ ] **Passo 2: Acrescente** a `test_hook_bypasses.py`: `wev specialists score x` dá `ask` com o motivo `engine_score`.
- [ ] **Passo 3: Rode** os dois. Esperado: FALHA.
- [ ] **Passo 4: Implemente** `evaluation/scoring.py` (separe auxiliares para manter cada função com menos de 50 linhas e o arquivo com menos de 400), os dois subcomandos e a entrada do hook.
- [ ] **Passo 5: Rode** os dois módulos. Esperado: PASSA.
- [ ] **Passo 6: Faça o commit** `feat: score specialists against cases and decide lessons by score`.

### Tarefa 9: `score_on_finish`

**Arquivos:**
- Modificar: `src/wev_skills/commands/run.py` (`_finish`)
- Teste: `tests/unit/test_score_on_finish.py`

**Interfaces:**
- Consome: `score_specialist` (Tarefa 8).
- Produz: quando `config.specialists.score_on_finish` é verdadeiro, depois de um encerramento bem-sucedido, `score_specialist` roda uma vez para cada especialista do projeto que terminou uma tarefa na execução; seus relatórios vão na carga do encerramento sob `"scores"`; uma falha de pontuação é informada sob `"score_errors"` e nunca desfaz o encerramento.

- [ ] **Passo 1: Escreva os testes que falham:** desligado por padrão (nenhuma chamada de pontuação); ligado com dois especialistas usados (duas chamadas); uma pontuação que falha deixa a execução em `done` e lista o erro.
- [ ] **Passo 2: Rode, implemente, rode.** Esperado: FALHA, depois PASSA.
- [ ] **Passo 3: Faça o commit** `feat: score the run's specialists at finish when configured`.

### Tarefa 10: Documentação e texto de segurança

**Arquivos:**
- Modificar, cada um com seu gêmeo `.pt-BR.md`: `SECURITY.md` (linhas 57, 78, 115 e um parágrafo novo sobre pontuação sem supervisão), `CLAUDE.md` (a lista de comandos de operador humano é mantida, mais uma linha dizendo que as decisões de pontuação não precisam dela, e a pontuação em `evaluation/` em Architecture), `docs/guides/specialists.md`, `docs/guides/evaluation.md` (uma seção de casos), `docs/guides/installation.md`, `docs/glossary.md`, `CHANGELOG.md`; docstrings de `commands/specialists.py`, `agents/experience.py`, `agents/learning.py`, `commands/_human.py`
- Teste: `tests/unit/test_docs.py`, `tests/unit/test_skills.py`, `bin/wev claude-md check`, `bin/wev readme check`

- [ ] **Passo 1: Escreva** o texto. O parágrafo de segurança diz o que a execução sem supervisão pode fazer (as seis ferramentas, `dontAsk`, o plugin carregado, nenhum bypass), que lições escritas pelo modelo são texto não confiável até serem pontuadas, e que o congelamento, o limite de execuções, o filtro de texto e a pontuação protegem contra um agente falível, não contra um agente adversário na mesma conta. Rotule cada capacidade: testada na unidade com falsos; o caminho real do `claude -p` não testado até o dono rodar.
- [ ] **Passo 2: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_docs tests.unit.test_skills -v`, `bin/wev claude-md check` e `bin/wev readme check`. Esperado: PASSA e nenhum achado.
- [ ] **Passo 3: Faça o commit** `docs: describe scored cases and lessons decided by score`.

### Tarefa 11: Verificação do branch inteiro

- [ ] **Passo 1: Rode** `make check` (sozinho na máquina). Esperado: saída 0.
- [ ] **Passo 2: Rode** `claude plugin validate .`. Esperado: passa só com o aviso conhecido do `CLAUDE.md`.
- [ ] **Passo 3: Relate** o que rodou e o que não rodou: o `bin/wev specialists score wev-engineer` real gasta tokens e espera pelo dono.
