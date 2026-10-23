# Plano de implementação: camadas de revisão

Versão em inglês: [2026-10-22-review-layers.md](2026-10-22-review-layers.md).

> **Para agentes de execução:** SUB-HABILIDADE OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam a sintaxe de caixa de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** Amarrar as revisões e as aprovações de publicação ao código que elas viram, executar rodadas de revisão do motor (caçadores em paralelo, votação de verificadores, etiquetas) sob um `REVIEW.md`, limitar as rodadas com uma nova revisão só do diff, travar o `run finish` enquanto houver achados Importantes abertos, acrescentar Risco e Como reverter ao PR e pontuar o revisor em casos de revisão com a mesma catraca que já existe.

**Arquitetura:** Um novo pacote `review/` guarda a leitura do `REVIEW.md`, os instantâneos e diffs de árvores do git, a leitura de achados e votos, os prompts, a rodada e a trava do fim. Ele depende só de `core/ports.py` (`Runner`, `AgentRunner`) e de registros em um novo `state/review_records.py`, então o estado nunca importa `review/`. Os comandos ligam o adaptador do Claude Code, como o `CLAUDE.md` exige. A pontuação reaproveita `evaluation/` e chama a mesma função de caçar e votar que a rodada usa.

**Pilha técnica:** biblioteca padrão do Python 3.14 (`concurrent.futures`, `fnmatch`, `json`), `unittest`, o validador de esquema do repositório, `git write-tree` com um `GIT_INDEX_FILE` temporário, `git diff`, a CLI do Claude Code por meio do `ClaudeAgentRunner` que já existe.

**Especificação:** [docs/superpowers/specs/2026-10-22-review-layers-design.pt-BR.md](../specs/2026-10-22-review-layers-design.pt-BR.md)

## Restrições globais

- Só biblioteca padrão, Python 3.14 ou mais novo, mypy strict, dataclasses congeladas, funções com menos de 50 linhas e arquivos com menos de 400 (`governance/approvals.py` está em 392, `config.py` em 384, `state/model.py` em 408: o código novo vai para módulos novos).
- Toda string visível ao usuário passa por `i18n.t`, com chaves idênticas em `en` e `pt-BR`; as mensagens novas vão para um novo domínio de locale `review` (`locales/review.en.json`, `locales/review.pt-BR.json`), a menos que estendam as mensagens de um domínio que já existe.
- Documentação em inglês e português do Brasil no mesmo commit; `PYTHONPATH=src python3 -m unittest tests.unit.test_docs` passa; `bin/wev claude-md check` e `bin/wev readme check` passam.
- `make test` nunca chama um modelo, a rede nem um harness real. Use o `FakeAgent` de `tests/unit/test_scoring.py` (mova-o para `tests/fixtures/fake_agent.py` na Tarefa 8, para que outros testes o importem) e `tests/fixtures/fake_claude_agent.py`.
- Cada teste novo é quebrado de propósito uma vez (reverta a linha que ele protege, veja o teste falhar, restaure).
- Arquivos de estado antigos continuam carregando: todo campo novo do estado tem um valor padrão.
- Nunca faça push, publique nem lance versão sem a autorização explícita do dono. Os assuntos dos commits seguem `<type>: <description>`. Nenhum assistente de IA é citado como autor em lugar nenhum. Nunca rode `make test` ao mesmo tempo que outro `make test`.
- Valores fixados pela especificação: `review.depth` padrão `off`; presets `quick` 1/1/quorum 1, `standard` 3/3/2, `deep` 5/5/3; `max_rounds` 3; `full_rounds` 2; `max_runs_per_round` 12; limite de Nits padrão 3; uma execução de risco alto usa pelo menos `standard` quando a revisão está ligada; caçadores e verificadores recebem exatamente `Read`, `Glob`, `Grep`.
- Rótulos de resultado exatamente `wrong`, `intentional`, `does-not-matter` (mais `fixed`, definido pelo motor).

## Pontos de atenção na revisão

- Um `REVIEW.md` cuja lista `Skip` casa com todos os arquivos alterados: a rodada ainda roda, e o resumo diz quantos achados o `REVIEW.md` ignorou (teste na Tarefa 9).
- Uma resposta de caçador que cita a linha 0, uma linha negativa, uma linha depois do fim, um arquivo binário ou um caminho fora do repositório: descartada como não comprovada, nunca derruba a rodada (teste na Tarefa 7).
- Dois `wev review run` iniciados ao mesmo tempo (o agente o coloca em segundo plano duas vezes): a segunda gravação é recusada com um conflito de estado e não registra nada (teste na Tarefa 9).
- Um caçador estoura o tempo enquanto outros respondem: a rodada continua com o que voltou; se todos os caçadores falham sem estouro de tempo, levanta `ProviderError("review_agent_failed")` e não registra rodada (teste na Tarefa 9).
- Uma execução iniciada antes desta mudança (sem `base`) e arquivos de estado antigos: o estado carrega, `review run` recusa com `review_no_base`, e nada mais quebra (teste na Tarefa 3).

---

### Tarefa 1: Revisão de tarefa amarrada à árvore verificada da própria tarefa

**Arquivos:**
- Modificar: `src/wev_skills/state/records.py` (`ReviewRecord`), `src/wev_skills/schemas/state.schema.json` (`$defs.review`), `src/wev_skills/core/task_outcomes.py` (`review_task`), `src/wev_skills/core/progress.py` (`review_accepted`)
- Teste: `tests/unit/test_review_binding.py`

**Interfaces:**
- Produz: `ReviewRecord(task_id, at, reviewer, accepted, summary, fingerprint: str = "")`; `progress.recorded_tree(state: RunState, task_id: str) -> str` (a impressão digital do último evento de tentativa da tarefa com `verified`, vinda de `verified_trees`, `""` se não houver).

- [ ] **Passo 1: Escreva os testes que falham:**
  - `test_review_stores_the_task_recorded_tree`: depois de `task record --status verified` e `task review --accept`, o `fingerprint` da revisão guardada é igual a `recorded_tree(state, id)` e não está vazio.
  - `test_review_survives_another_task_editing_other_files`: a tarefa A é revisada, a tarefa B edita outro arquivo e é registrada; `review_accepted(state, "A")` é `True`.
  - `test_review_voids_when_the_task_is_redone`: a tarefa A é revisada, reaberta, editada e registrada de novo; `review_accepted(state, "A")` é `False` e `task next` indica A para revisão.
  - `test_review_survives_a_recheck_before_finish`: uma nova verificação (`task check`) sobre uma árvore alterada não muda `review_accepted`.
  - `test_old_review_without_fingerprint_does_not_count`: um arquivo de estado cuja revisão não tem `fingerprint` carrega, e `review_accepted` é `False`.
- [ ] **Passo 2: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_review_binding -v`. Esperado: FALHA.
- [ ] **Passo 3: Implemente.** Acrescente o campo com padrão `""` e em `$defs.review` (não obrigatório). `review_task` o define a partir de `recorded_tree`. `review_accepted` exige `review.accepted`, uma impressão digital não vazia e `review.fingerprint == recorded_tree(state, task_id)`. Elimine a comparação `at >= finished_at`; a impressão digital a substitui.
- [ ] **Passo 4: Rode** o módulo e `PYTHONPATH=src python3 -m unittest discover -s tests -p "test_*review*"`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `fix: bind a task review to the tree its task recorded`.

### Tarefa 2: Aprovações de comandos com efeito externo amarradas a `HEAD` e à árvore

**Arquivos:**
- Criar: `src/wev_skills/governance/approval_anchor.py`
- Modificar: `src/wev_skills/governance/approvals.py` (`ApprovalRequest`, `ApprovalStore.__init__`, `grant`, `_usable`), `src/wev_skills/core/wiring.py` (passar a âncora), locales
- Teste: `tests/unit/test_approval_anchor.py`

**Interfaces:**
- Produz:
  - `@dataclass(frozen=True) class Anchor: head: str; tree: str`
  - `needs_anchor(argv: Sequence[str]) -> bool`: verdadeiro quando o classificador de comandos que monta o `CommandRisk` para um argv (o que `security/permissions.py` usa) define `external_effect`.
  - `ApprovalRequest` ganha `head: str = ""`, `tree: str = ""`.
  - `ApprovalStore(..., anchor: Callable[[], Anchor] | None = None)`; `ApprovalStore.is_stale(action: Action, cwd: str = "") -> bool`.
  - `wiring` passa `lambda: Anchor(head=<git rev-parse HEAD ou "">, tree=impressão digital do motor para a raiz)`.
- [ ] **Passo 1: Escreva os testes que falham** com uma âncora falsa cujos valores o teste muda:
  - `test_push_grant_records_head_and_tree`: a aprovação de `("git", "push", "origin", "dev")` guarda os valores da âncora.
  - `test_push_grant_goes_stale_on_new_commit`: muda `head` depois da aprovação; `is_granted` é `False`, `is_stale` é `True`.
  - `test_push_grant_goes_stale_on_tree_change`: o mesmo com `tree`.
  - `test_ordinary_grant_ignores_the_tree`: a aprovação de `("rm", "-r", "build")` continua utilizável depois que os dois mudam.
  - `test_publish_entries_are_anchored`: `needs_anchor` é verdadeiro para `("gh", "pr", "merge", "1")` e `("npm", "publish")`; falso para `("make", "test")`.
- [ ] **Passo 2: Rode** o módulo. Esperado: FALHA.
- [ ] **Passo 3: Implemente.** `grant` define `head` e `tree` a partir de `anchor()` quando `needs_anchor(record.argv)`; `_usable` acrescenta: um registro com `head` ou `tree` definidos só é utilizável enquanto `anchor()` for igual a eles. O caminho de `exec` que informa "aprovação necessária" acrescenta o motivo `stale_grant` quando `is_stale` (uma chave de locale nova por idioma). Mantenha `approvals.py` abaixo de 400 linhas colocando a comparação em `approval_anchor.py`.
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_approvals*`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: tie grants for publishing commands to HEAD and the tree`.

### Tarefa 3: Base da execução, instantâneos de árvore e linhas tocadas

**Arquivos:**
- Criar: `src/wev_skills/review/__init__.py`, `src/wev_skills/review/trees.py`
- Modificar: `src/wev_skills/state/model.py` (`RunState.base`), `src/wev_skills/schemas/state.schema.json`, `src/wev_skills/core/run_start.py` (`_open`)
- Teste: `tests/unit/test_review_trees.py`

**Interfaces:**
- Produz:
  - `write_tree(runner: Runner, root: Path) -> str`: um id de árvore do git da árvore de trabalho, incluindo arquivos não rastreados e não ignorados, escrito com um `GIT_INDEX_FILE` temporário (preenchido por `git read-tree HEAD`, depois `git add -A`, depois `git write-tree`), usando `evaluation/workspace.GIT_HARDENING` e `GIT_ENV`. Não toca em nenhuma referência nem no índice real. Levanta `StateConflict("review_tree_failed")` se o git falhar.
  - `diff_trees(runner: Runner, root: Path, old: str, new: str, context: int = 3) -> str`.
  - `touched_lines(diff: str) -> dict[str, frozenset[int]]`: números de linha do lado novo, adicionadas ou alteradas, por caminho, lidos dos hunks `@@ -a,b +c,d @@` de um diff com `--unified=0`.
  - `RunState.base: str = ""`, definido uma única vez por `run start` como `write_tree(...)`, nunca escrito por `run resume`.
- [ ] **Passo 1: Escreva os testes que falham** em um repositório git temporário:
  - `test_write_tree_includes_untracked_and_leaves_index_alone`: um arquivo não rastreado aparece em `git ls-tree`; `git status --porcelain` fica igual depois.
  - `test_write_tree_skips_ignored_files`.
  - `test_touched_lines_reads_hunks`: um texto de diff fixo dá `{"a.py": frozenset({3, 4}), "b.py": frozenset({10})}`; uma exclusão pura não dá linhas para o seu arquivo.
  - `test_run_start_records_base_and_resume_keeps_it`: `base` não vazio depois do início; inalterado depois de edições mais `run resume`.
  - `test_uncommitted_change_at_start_is_in_base`: um arquivo sujo no `run start` não aparece em `diff_trees(base, write_tree(now))`.
  - `test_state_without_base_loads`.
- [ ] **Passo 2: Rode** o módulo. Esperado: FALHA.
- [ ] **Passo 3: Implemente** como acima. `run_git` define o próprio ambiente; acrescente a `run_git` um argumento nomeado `env` (padrão nenhum, mesclado sobre o ambiente dele) em vez de duplicá-lo.
- [ ] **Passo 4: Rode** o módulo mais `tests.unit.test_run_start*` e `tests.unit.test_case_workspace`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: record a fixed run base as a git tree`.

### Tarefa 4: Quorum em `resolve_conflict`

**Arquivos:**
- Modificar: `src/wev_skills/decisions/local.py`, `src/wev_skills/decisions/__init__.py` (protocolo), `src/wev_skills/decisions/jev.py` (delegar)
- Teste: `tests/unit/test_resolve_quorum.py`

**Interfaces:**
- Produz: `resolve_conflict(self, verdicts: Sequence[Verdict], quorum: int | None = None) -> Verdict`. `None` mantém a unanimidade; caso contrário, `accepted = sum(v.accepted) >= quorum`. A nota continua sendo o `min`, os motivos mesclados como hoje. `quorum < 1` ou `> len(verdicts)` levanta `ValidationError("bad_quorum")`.
- [ ] **Passo 1: Testes:** `test_default_stays_unanimous`, `test_two_of_three_accepts`, `test_one_of_three_rejects_at_quorum_two`, `test_bad_quorum_refused`, `test_jev_delegates_quorum`.
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente** nos três lugares.
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_decisions*`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: let resolve_conflict accept by quorum`.

### Tarefa 5: A seção de configuração `review`

**Arquivos:**
- Criar: `src/wev_skills/config_review.py`
- Modificar: `src/wev_skills/config.py` (`Config.review`, `trust_errors`), `src/wev_skills/schemas/config.schema.json`, `docs/guides/configuration-and-providers.md` e o seu gêmeo `.pt-BR.md`
- Teste: `tests/unit/test_config_review.py`

**Interfaces:**
- Produz:
  - `@dataclass(frozen=True) class ReviewConfig(Serializable)`: `agent: str = ""`, `depth: str = "off"`, `finders: int = 0`, `verifiers: int = 0`, `quorum: int = 0` (0 = vem do preset), `max_rounds: int = 3`, `full_rounds: int = 2`, `max_runs_per_round: int = 12`, `timeout_seconds: float = 600.0`.
  - `@dataclass(frozen=True) class ReviewShape: finders: int; verifiers: int; quorum: int`
  - `review_shape(config: ReviewConfig, risk: RiskLevel) -> ReviewShape`: preset a partir de `depth`, elevado para `standard` quando `risk` é HIGH, e depois as chaves explícitas diferentes de zero prevalecem.
- Limites do esquema: `depth` enum `off|quick|standard|deep`; `finders`, `verifiers`, `quorum` 0–10; `max_rounds` 1–10; `full_rounds` 0–10; `max_runs_per_round` 1–50; `timeout_seconds` 0,1–3600.
- [ ] **Passo 1: Testes:** `test_defaults_are_off`, `test_presets` (as três tuplas exatas), `test_high_risk_raises_quick_to_standard`, `test_explicit_keys_override`, `test_depth_on_needs_agent` (`trust_errors` informa), `test_quorum_above_verifiers_refused`, `test_unknown_key_refused`.
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente** e documente cada chave nas duas versões de idioma do guia de configuração.
- [ ] **Passo 4: Rode** o módulo, `tests.unit.test_config*` e `tests.unit.test_docs`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: add the review configuration section`.

### Tarefa 6: Leitura do `REVIEW.md` e `wev review md check`

**Arquivos:**
- Criar: `src/wev_skills/review/guide.py`, `src/wev_skills/commands/review.py` (grupo `review`, aqui só a ação `md check`), `src/wev_skills/locales/review.en.json`, `src/wev_skills/locales/review.pt-BR.json`
- Teste: `tests/unit/test_review_guide.py`

**Interfaces:**
- Produz:
  - `@dataclass(frozen=True) class ReviewGuide: failure: str = ""; skip: tuple[str, ...] = (); nit_cap: int = 3; nits: str = ""; important: str = ""`
  - `HEADINGS: Mapping[str, str]` que liga cada título em inglês e em português (`What failure looks like` / `Como é uma falha`, `Skip` / `Ignorar`, `Nits`, `Important` / `Importante`, sem diferenciar maiúsculas) a um campo.
  - `parse_guide(text: str) -> ReviewGuide`; um título de segundo nível desconhecido, um `max:` que não seja um inteiro de 0 a 50 ou um arquivo com mais de 20.000 caracteres levanta `ValidationError("invalid_review_md")` citando a linha.
  - `load_guide(root: Path) -> ReviewGuide`: valores padrão quando o `REVIEW.md` não existe.
  - `skipped(path: str, guide: ReviewGuide) -> bool` (`fnmatch` sobre o caminho POSIX).
- [ ] **Passo 1: Testes:** `test_parses_english_headings`, `test_parses_portuguese_headings`, `test_missing_file_gives_defaults`, `test_bad_max_refused`, `test_unknown_heading_refused`, `test_skip_glob_matches`, `test_md_check_command_reports_ok_and_error` (saída 2 em caso de erro).
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente.** O grupo de comandos segue `commands/cases.py` (`resolve_scope`, um subparser `actions`, payload em dicionário).
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_skills` (ele confere os comandos citados nas habilidades contra o `--help`). Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: read REVIEW.md for reviewers`.

### Tarefa 7: Achados, votos e prompts

**Arquivos:**
- Criar: `src/wev_skills/state/review_records.py`, `src/wev_skills/review/findings.py`, `src/wev_skills/review/prompts.py`
- Modificar: `src/wev_skills/adapters/claude_code/agent_runner.py`, `src/wev_skills/core/ports.py` (argumento do conjunto de ferramentas), locales
- Teste: `tests/unit/test_review_findings.py`, `tests/unit/test_agent_runner.py` (estender)

**Interfaces:**
- Produz:
  - Em `state/review_records.py`: `FindingRecord(Serializable)`: `id: str`, `round: int`, `file: str`, `line: int`, `title: str`, `body: str`, `tag: str` (`important|nit|pre_existing`), `class_wide: bool`, `votes_real: int`, `votes_total: int`, `status: str = "open"` (`open|fixed|dismissed`), `outcome: str = ""`, `reason: str = ""`, `resolved_by: str = ""`. `ReviewRoundRecord(Serializable)`: `number: int`, `at: str`, `scope: str` (`full|diff`), `tree: str`, `fingerprint: str`, `depth: str`, `findings: tuple[FindingRecord, ...]`, `skipped: int`, `runs_used: int`, `summary: str`.
  - Em `review/findings.py`: `RawFinding(file, line, title, body, tag, class_wide)`; `Vote(index: int, real: bool, tag: str, kind: str)`; `finding_id(file: str, line: int, title: str) -> str` (os 12 primeiros hexadecimais do sha256 sobre `file\0line\0título em minúsculas, com espaços colapsados`); `parse_findings(answer: str) -> tuple[RawFinding, ...]` (JSON `{"findings": [...]}`, no máximo `MAX_FINDINGS = 20`, `TITLE_MAX = 120`, `BODY_MAX = 1200`, um item cujo texto `untrusted.scan` sinaliza é descartado, qualquer resposta malformada dá `()`); `parse_votes(answer: str, count: int) -> tuple[Vote, ...]` (JSON `{"votes": [{"index", "real", "tag", "kind"}]}`, `kind` em `bug|security|style|diagnostic|cleanup`; um índice fora do intervalo ou um `kind` inválido descarta aquele voto); `proven(raw: RawFinding, root: Path) -> bool` (um arquivo regular, não binário, sob `root`, com `1 <= line <=` o número de linhas dele).
  - Em `review/prompts.py`: `finder_prompt(diff: str, intent: str, guide: ReviewGuide, claude_md: str, posted: Sequence[FindingRecord], lang: str) -> str`; `verifier_prompt(diff: str, candidates: Sequence[RawFinding], rechecks: Sequence[FindingRecord], guide: ReviewGuide, lang: str) -> str`. Toda parte vinda do repositório passa por `wrap(redact(text), source=...)`; as instruções vêm das chaves de locale `review.prompt.finder` e `review.prompt.verifier` e pedem o JSON exato acima.
  - `AgentRunner.run_agent(workspace, spec, objective, timeout, tools: Sequence[str] = UNATTENDED_TOOLS)`; `READ_ONLY_TOOLS = ("Read", "Glob", "Grep")` em `agent_runner.py`.
- [ ] **Passo 1: Testes:** `test_parses_valid_findings`; `test_malformed_answer_gives_nothing`; `test_operator_command_in_body_dropped` (`wev approval grant` em `body`); `test_over_long_title_dropped`; `test_more_than_twenty_capped`; `test_unproven_lines_dropped` (linha 0, −1, depois do fim, arquivo binário, `../x`); `test_finding_id_stable_across_whitespace`; `test_votes_parse_and_drop_bad_index`; `test_prompt_fences_repository_text` (um `</untrusted>` plantado não consegue fechar a cerca); `test_runner_passes_read_only_tools` (`--tools Read,Glob,Grep` e o mesmo `--allowedTools` no argv registrado pelo falso); `test_runner_default_tools_unchanged`.
- [ ] **Passo 2: Rode** os dois módulos. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** os dois módulos mais `tests.unit.test_scoring`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: parse review findings and votes; let the runner take a tool set`.

### Tarefa 8: Caçar e votar

**Arquivos:**
- Criar: `src/wev_skills/review/vote.py`, `tests/fixtures/fake_agent.py` (movido de `tests/unit/test_scoring.py`, estendido com respostas roteirizadas por tipo de prompt)
- Teste: `tests/unit/test_review_vote.py`

**Interfaces:**
- Consome: Tarefas 3, 4, 6 e 7.
- Produz:
  - `@dataclass(frozen=True) class VoteInputs: root: Path; agent: AgentRunner; spec: AgentSpec; diff: str; run_touched: Mapping[str, frozenset[int]]; intent: str; guide: ReviewGuide; claude_md: str; posted: tuple[FindingRecord, ...]; rechecks: tuple[FindingRecord, ...]; shape: ReviewShape; timeout: float; round: int; decide: Callable[[Sequence[Verdict], int], Verdict]; lang: str`
  - `@dataclass(frozen=True) class VoteResult: kept: tuple[FindingRecord, ...]; fixed: tuple[str, ...]; skipped: int; runs_used: int`
  - `find_and_vote(inputs: VoteInputs) -> VoteResult`.
- Algoritmo: executar `shape.finders` caçadores em um `ThreadPoolExecutor` com `READ_ONLY_TOOLS`. Um caçador que estoura o tempo não contribui com nada; se todos os caçadores falham sem estouro de tempo, levantar `ProviderError("review_agent_failed")`. Descartar os não comprovados, os ignorados (contados em `skipped`) e os ids já publicados. Mesclar candidatos no mesmo arquivo dentro de `DUPLICATE_LINE_WINDOW = 3` linhas, mantendo o primeiro. Executar `shape.verifiers` verificadores em paralelo sobre os candidatos mais as rechecagens. Para cada candidato, transformar cada voto em `Verdict(accepted=real and kind in {"bug", "security"}, score=1.0)`; mantê-lo quando `decide(verdicts, shape.quorum).accepted`. Etiquetar como `important` quando a maioria dos votos que aceitam diz isso, senão `nit`. Etiquetar como `pre_existing` quando `line` não está em `run_touched[file]`. Aplicar o limite de Nits, mantendo os mais votados. Uma rechecagem é `fixed` quando o quorum vota que ela já não é real. `runs_used` conta cada execução do harness iniciada.
- [ ] **Passo 1: Testes**, com o agente falso: `test_quorum_keeps_and_drops`; `test_style_votes_drop_a_finding`; `test_pre_existing_from_run_diff_not_round_diff`; `test_nit_cap_keeps_most_voted`; `test_duplicates_merged`; `test_posted_ids_not_repeated`; `test_skipped_counted`; `test_recheck_marks_fixed`; `test_one_finder_timeout_continues`; `test_all_finders_fail_raises`; `test_runs_used_counts_every_run`.
- [ ] **Passo 2: Rode** o módulo. Esperado: FALHA.
- [ ] **Passo 3: Implemente** e atualize `tests/unit/test_scoring.py` para importar o falso movido.
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_scoring`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: find and vote on review findings`.

### Tarefa 9: A rodada de revisão, `review run|show|resolve|dismiss` e o limite de rodadas

**Arquivos:**
- Criar: `src/wev_skills/review/round.py`, `src/wev_skills/review/summary.py`, `src/wev_skills/commands/_agent_runner.py` (a construção do `ClaudeAgentRunner` que hoje está em `commands/_scoring.py`, compartilhada pelos dois)
- Modificar: `src/wev_skills/state/model.py` (`review_rounds`, `review_allowance`), `src/wev_skills/schemas/state.schema.json`, `src/wev_skills/commands/review.py`, `src/wev_skills/core/guard_ack.py`, `src/wev_skills/adapters/claude_code/engine_cli.py` (`OPERATOR_COMMANDS`), `src/wev_skills/security/untrusted.py` (regra de comando de operador), `src/wev_skills/adapters/harness_hooks.py` (negação só para pessoas nos outros harnesses, se ele mantiver a própria lista)
- Teste: `tests/unit/test_review_round.py`, `tests/unit/test_review_commands.py`

**Interfaces:**
- Consome: Tarefas 3, 5, 7 e 8.
- Produz:
  - `RunState.review_rounds: tuple[ReviewRoundRecord, ...] = ()`, `RunState.review_allowance: int = 0`.
  - `run_round(engine: Engine, agent: AgentRunner, lang: str) -> ReviewRoundRecord`: recusa com `review_off` (saída 2) quando a profundidade é `off`, `task_running` (saída 5), `review_no_base` (saída 5); quando `len(review_rounds) >= max_rounds + review_allowance`, registra um `GuardTrip` com a regra `review_rounds` e levanta `GuardTripped` (saída 6). Recusa com `review_over_cap` (saída 6) antes de qualquer execução quando `finders + verifiers > max_runs_per_round`, e imprime a contagem planejada em stderr como `evaluation.scoring.plan`. O escopo é `full` enquanto `number <= full_rounds`, senão `diff` (da árvore da rodada anterior até agora). `run_touched` sempre vem de `diff_trees(base, now, context=0)`. As rechecagens são os achados abertos cujo arquivo e ±3 linhas cruzam as linhas tocadas desde a rodada deles. Grava com `base=state`, então uma rodada concorrente entra em conflito (saída 5).
  - `summarize(findings: Sequence[FindingRecord], skipped: int, lang: str) -> str`: a primeira linha conta os Importantes, Nits e Preexistentes abertos, ou o "Nada a corrigir" do locale; depois os achados por gravidade com `file:line`; depois "N ignorados pelo REVIEW.md" quando `skipped > 0`.
  - `review show` imprime a última rodada. `review resolve <id> --as wrong|intentional|does-not-matter --reason <text>` resolve um achado Nit ou Preexistente e recusa um Importante com `PermissionDenied("review_dismiss_person_only")`. `review dismiss <id> --as ... --reason ...` é só para pessoas, por meio de `commands/_human.OperatorPrompt`, e funciona com qualquer etiqueta.
  - `guard acknowledge` sobre um disparo `review_rounds` no nível da execução soma 1 a `review_allowance`.
- [ ] **Passo 1: Testes:** `test_round_records_findings_and_summary`; `test_summary_nothing_to_fix`; `test_summary_counts_skips_when_skip_matches_everything`; `test_off_refused`; `test_no_base_refused`; `test_running_task_refused`; `test_over_cap_refused_before_any_run`; `test_third_round_is_diff_only`; `test_fourth_round_trips_guard`; `test_acknowledge_allows_exactly_one_more`; `test_concurrent_round_conflicts`; `test_resolve_refuses_important`; `test_dismiss_needs_a_terminal`; `test_dismiss_is_an_operator_command` (`engine_cli` pergunta; `untrusted.scan` sinaliza `wev review dismiss`; os outros harnesses negam).
- [ ] **Passo 2: Rode** os dois módulos. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** os dois módulos, `tests.unit.test_guard*`, `tests.unit.test_bash_guard*`, `tests.security`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: run review rounds with a round cap`.

### Tarefa 10: A trava do fim

**Arquivos:**
- Criar: `src/wev_skills/review/gate.py`
- Modificar: `src/wev_skills/core/orchestrator.py` (`finish`)
- Teste: `tests/unit/test_review_gate.py`

**Interfaces:**
- Consome: Tarefas 3, 5 e 9; os registros de comparação de `.wev/scores.jsonl` da Tarefa 13.
- Produz: `finish_refusal(state: RunState, config: Config, fingerprint: str, touched: Mapping[str, frozenset[int]], comparisons: Sequence[Mapping[str, object]]) -> WevError | None`, nesta ordem:
  1. um achado Importante aberto: `StateConflict("review_open_important")`, listando os ids;
  2. profundidade diferente de `off` e (nenhuma rodada, ou o `fingerprint` da última rodada diferente de `fingerprint`): `StateConflict("review_stale")`;
  3. `touched` inclui `REVIEW.md` ou `<agents.project_dir>/<review.agent>.json`, e nenhuma comparação tem `fingerprint` igual ao atual com `improves` verdadeiro: `StateConflict("reviewer_unscored")`.
  `Orchestrator.finish()` levanta a recusa antes de gravar qualquer coisa; com profundidade `off` e nada aberto, ele se comporta como hoje.
- [ ] **Passo 1: Testes:** um por recusa, `test_off_finishes_as_before`, `test_dismissed_important_does_not_block`, `test_pre_existing_never_blocks`, `test_improving_comparison_lets_reviewer_change_finish`.
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_run*`, `tests.unit.test_score_on_finish`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: refuse run finish on open Important findings or a stale review`.

### Tarefa 11: Risco e reversão do plano, modelo de PR e `run report --format pr`

**Arquivos:**
- Criar: `src/wev_skills/core/report_pr.py`
- Modificar: `src/wev_skills/schemas/plan.schema.json`, `src/wev_skills/core/contracts.py` (`Plan`), `src/wev_skills/core/plan_flow.py` (`adopt_plan`), `src/wev_skills/core/report.py` (chaves de `build_report`), `src/wev_skills/commands/run.py` (`FORMATS`), `.github/PULL_REQUEST_TEMPLATE.md`
- Teste: `tests/unit/test_plan_revert.py`, `tests/unit/test_report_pr.py`

**Interfaces:**
- Produz: `Plan.risk_notes: str = ""`, `Plan.revert: str = ""`; `adopt_plan` levanta `ValidationError("plan_needs_revert")` quando qualquer um dos dois está em branco e `higher_risk` de `state.classification.risk` e do `risk` de cada tarefa é MEDIUM ou HIGH. O dicionário do relatório ganha `risk_notes`, `revert` e `review` (`{"summary": str, "dismissed": [{"id", "tag", "outcome", "reason"}]}`). `render_pr(report: Mapping[str, Any], lang: str) -> str` imprime `## Summary`, `## What was tested`, `## Risk`, `## How to revert`, `## Review` nessa ordem. O modelo ganha os mesmos três títulos novos.
- [ ] **Passo 1: Testes:** `test_low_risk_plan_without_revert_ok`; `test_medium_task_risk_needs_revert`; `test_high_run_risk_needs_revert`; `test_pr_body_sections_in_order`; `test_pr_body_lists_dismissed_findings`; `test_template_has_risk_revert_review` (lê `.github/PULL_REQUEST_TEMPLATE.md`).
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** os dois módulos e `tests.unit.test_plan*`, `tests.unit.test_report*`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: require risk and revert notes and print a PR body`.

### Tarefa 12: Casos de revisão

**Arquivos:**
- Modificar: `src/wev_skills/schemas/case.schema.json`, `src/wev_skills/evaluation/cases.py`, `src/wev_skills/commands/cases.py` (`--at-base`), `src/wev_skills/evaluation/workspace.py` (argumento de commit em `case_workspace`)
- Teste: `tests/unit/test_review_cases.py`

**Interfaces:**
- Produz: `Case` ganha `kind: str = "build"`, `head_commit: str = ""`, `expect: tuple[Expect, ...] = ()` com `Expect(file: str, first: int, last: int)`. O esquema acrescenta `kind` (`build|review`), `head_commit`, `expect`; `check` e `files` passam a ser opcionais no esquema, e `load_cases` aplica por tipo: `build` exige `check`; `review` exige `head_commit` e um `evals/cases/<id>/change.diff` guardado, e proíbe `check` e `files`. `case_workspace(runner, root, case, scratch, commit: str | None = None)`. `review_case_passed(case: Case, kept: Sequence[FindingRecord]) -> bool`: um caso de bug passa quando um achado `important` tem `file == e.file` e `e.first <= line <= e.last` para algum `e`; um caso limpo (`expect` vazio) passa quando nenhum é `important`. `--at-base` para um caso de revisão confere que `git diff base_commit head_commit` é igual ao `change.diff` guardado, byte a byte.
- [ ] **Passo 1: Testes:** `test_review_case_loads`; `test_review_case_with_check_refused`; `test_build_case_without_check_refused`; `test_expect_must_lie_in_stored_diff` (`touched_lines` de `change.diff`, offline); `test_pass_rule_bug_case`; `test_pass_rule_clean_case`; `test_nit_does_not_pass_a_bug_case`; `test_old_cases_still_load`.
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** o módulo, `tests.unit.test_cases`, `tests.unit.test_first_cases`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: add review cases`.

### Tarefa 13: Pontuação do revisor e `--compare`

**Arquivos:**
- Modificar: `src/wev_skills/evaluation/score_runs.py` (`_attempt` por tipo), `src/wev_skills/evaluation/scoring.py` (`planned_runs`, verificação do limite, `ScoreReport.depth`), `src/wev_skills/commands/specialists.py` (`--compare`)
- Criar: `src/wev_skills/evaluation/compare.py`
- Teste: `tests/unit/test_score_review_cases.py`

**Interfaces:**
- Consome: Tarefas 8 e 12.
- Produz: uma amostra de caso de revisão executa `find_and_vote` em uma área de trabalho em `head_commit`, com `diff` e `run_touched` vindos do `change.diff` guardado, `intent = case.objective`, o guia e a especificação como configurados, e o formato `review_shape(config.review, LOW)`. Ela passa por `review_case_passed`. Em caso de falha, `Failure.output` é o resumo e `Failure.diff` é o diff do caso, então o redator de lições do projeto 2 funciona sem mudanças. `planned_runs` recebe `runs_per_sample` (1 para build, `finders + verifiers` para revisão) e a verificação do limite da linha de base o usa. `ScoreReport.depth: str = ""`. `compare_reviewer(root, config, runner, agent, agent_id, rev: str, audit) -> CompareReport` pontua a especificação e o `REVIEW.md` lidos com `git show <rev>:<path>` contra a árvore de trabalho, nos mesmos casos fixados, sem decisões de lições. Ele acrescenta `{"compare": rev, "fingerprint", "depth", "baseline", "current", "improves"}` a `scores.jsonl`. `--compare` faz parte de `specialists score`, então continua só para pessoas.
- [ ] **Passo 1: Testes:** `test_review_case_scored_with_fake_votes`; `test_runs_per_sample_in_plan_and_cap`; `test_depth_recorded`; `test_compare_records_improves_true_and_false`; `test_compare_refuses_dirty_cases` (o congelamento); `test_build_cases_unchanged`.
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** o módulo e `tests.unit.test_scoring`, `tests.unit.test_score_decisions`. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: score the reviewer on review cases`.

### Tarefa 14: Registros de ruído e `wev review stats`

**Arquivos:**
- Criar: `src/wev_skills/review/stats.py`
- Modificar: `src/wev_skills/review/round.py`, `src/wev_skills/commands/review.py`
- Teste: `tests/unit/test_review_stats.py`

**Interfaces:**
- Produz: acrescenta a `<state_dir>/reviews.jsonl` um `{"kind": "round", "at", "run_id", "round", "depth", "important", "nit", "pre_existing", "skipped", "runs_used"}` por rodada e um `{"kind": "outcome", "at", "run_id", "finding", "tag", "outcome", "depth", "round"}` por resolução, dispensa ou `fixed` do motor. `review_stats(path: Path) -> dict[str, object]`, por profundidade: achados por rodada, parcela por resultado, rodadas por execução, execuções aprovadas após uma rodada, mais `clean_case_candidates` (achados `wrong` dispensados por pessoas).
- [ ] **Passo 1: Testes:** `test_round_and_outcome_lines_written`; `test_stats_aggregate_by_depth`; `test_wrong_dismissal_listed_as_candidate`; `test_missing_file_gives_empty_stats`.
- [ ] **Passo 2: Rode** os testes. Esperado: FALHA.
- [ ] **Passo 3: Implemente.**
- [ ] **Passo 4: Rode** o módulo. Esperado: PASSA.
- [ ] **Passo 5: Faça o commit** `feat: record review outcomes and print review stats`.

### Tarefa 15: O revisor do próprio wev-skills, `REVIEW.md` e os primeiros casos de revisão

**Arquivos:**
- Criar: `REVIEW.md`, `wev-specialists/wev-reviewer.json` (mesmo formato de `wev-specialists/wev-engineer.json`), `wev.config.json` (`{"review": {"agent": "wev-reviewer", "depth": "standard"}}`), três casos de revisão com bug e dois casos de revisão limpos em `evals/cases/`, cada um com o seu `change.diff`
- Teste: `tests/unit/test_first_review_cases.py`

- [ ] **Passo 1:** Ache os commits que introduziram os três bugs corrigidos por `06fc92c` (sonda de saúde de 1 MiB, link simbólico `..` no tarball) e `e3d7b2b` (caminho de exec do `install.sh`) com `git log -L` nas linhas que as correções alteraram. Escreva cada um como um caso de bug cujo `expect` cobre essas linhas do lado de `head_commit`.
- [ ] **Passo 2:** Escolha dois commits já mesclados que nenhuma correção posterior tocou (confirme com `git log --follow` nas linhas alteradas por eles) e escreva-os como casos limpos. O `title` de cada caso diz por que ele é limpo.
- [ ] **Passo 3: Teste** `test_first_review_cases_are_consistent`: eles carregam, cada `expect` cruza `touched_lines(change.diff)`, e há 3 casos de bug e 2 limpos. Rode `bin/wev cases validate --at-base` localmente e cole a saída no corpo do commit.
- [ ] **Passo 4:** A seção "What failure looks like" do `REVIEW.md` lista as cinco falhas citadas na especificação (parte B). `bin/wev review md check` passa.
- [ ] **Passo 5: Faça o commit** `chore: add wev-skills' reviewer, REVIEW.md and first review cases`.

### Tarefa 16: Documentação e texto de segurança

**Arquivos:**
- Modificar, cada um com o seu gêmeo `.pt-BR.md`: `SECURITY.md`, `CLAUDE.md` (a lista de comandos do operador humano ganha `review dismiss`; a lista de pacotes ganha `review/`), `docs/guides/orchestration.md`, `docs/guides/evaluation.md`, `docs/guides/specialists.md`, `docs/glossary.md`, `skills/wev-orchestrate/SKILL.md`
- Criar: `docs/guides/review.md` e `docs/guides/review.pt-BR.md` (com um modelo de `REVIEW.md`)

- [ ] **Passo 1:** Escreva o texto que a especificação lista na parte I, rotulando cada capacidade (`implemented and tested` para o que os testes unitários cobrem; `implemented but untested` para uma rodada real com `claude -p` e uma pontuação real do revisor). Redação de segurança: uma proteção para um agente falível; as ferramentas de arquivo do agente ainda podem editar o estado da execução e os achados.
- [ ] **Passo 2:** A habilidade diz para iniciar `wev review run` em segundo plano antes de `run finish`, ler `review show`, corrigir ou dar `review resolve` nos Nits e achados Preexistentes, e parar e perguntar a uma pessoa diante de um achado Importante que ela considere errado ou de um disparo `review_rounds`.
- [ ] **Passo 3: Rode** `PYTHONPATH=src python3 -m unittest tests.unit.test_docs tests.unit.test_skills`, `bin/wev claude-md check`, `bin/wev readme check`. Esperado: PASSA.
- [ ] **Passo 4: Faça o commit** `docs: document review layers in both languages`.

### Tarefa 17: Verificação da branch inteira

- [ ] **Passo 1: Rode** `make check` (sozinho na máquina). Esperado: todos os testes passam; ruff e mypy limpos.
- [ ] **Passo 2: Rode** `claude plugin validate .`. Esperado: só o aviso conhecido sobre o `CLAUDE.md`.
- [ ] **Passo 3:** Peça ao dono que rode, em um terminal, um `wev review run` real em uma execução pequena e um `wev specialists score wev-reviewer`. Até lá, informe os dois como implemented but untested.
