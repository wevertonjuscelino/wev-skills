# Guia de avaliação

Versão em inglês: [evaluation.md](evaluation.md).

O harness de avaliação reproduz trajetórias fixas e roteirizadas contra os componentes reais do motor (o gerenciador de contexto, a guarda de execução, o roteador de modelos e a política de decisão local). **Nenhum modelo é chamado.** Tem o próprio laço de tentativas e escalonador e não chama o motor de orquestração (`wev run`, `wev task`), portanto linhas de base, aprovações, a política de permissões e o motor de verificação não são exercitados pelos seus resultados. É uma bancada de testes para a mecânica do harness: mostra que limites, guardas, roteamento, novas tentativas e agendamento se comportam como projetado em trajetórias construídas para exercitá-los.

Status: o harness está implementado e testado; todo resultado que ele produz é **simulado com mocks (simulated with mocks)**. O roteiro decide cada resultado, uma configuração "passa" numa tarefa porque a tarefa foi escrita para isso, e custo e duração são unidades simuladas, não dinheiro nem tempo. Os resultados não dizem nada sobre a qualidade de nenhum modelo e não são evidência de que alguma configuração melhore algo. **Não existe avaliação com modelo real neste projeto.** A referência completa é [evals/README.pt-BR.md](../../evals/README.pt-BR.md); este guia é o caminho curto por ela.

Neste guia, `wev` significa `"$WEV_HOME/bin/wev"`. Tudo roda sem rede e sem instalação.

## Executar

```text
wev eval list
wev eval run
wev eval run --task context-overload --config baseline --config context-none
wev eval run --format md --lang pt-BR --out relatorio.md
wev eval validate evals/tasks/simple-fix.json
```

`eval list` imprime as tarefas (id, título, categoria, tamanho da janela, subtarefas, passos), os ids das configurações e os diretórios que leu. `eval run` executa cada tarefa selecionada com cada configuração selecionada. `--task` e `--config` são repetíveis; sem eles tudo roda. Opções: `--tasks-dir`, `--configs`, `--out ARQUIVO`, `--format json|md` (JSON é o padrão), `--lang en|pt-BR`. Com `--format md` e sem `--out`, a CLI imprime um objeto JSON cujo campo `content` guarda o Markdown, porque a CLI sempre imprime JSON.

Os padrões são o diretório `evals/` da árvore de código. Uma instalação sem ele falha com `evals_dir_not_found`; passe `--tasks-dir` e `--configs`.

As execuções são determinísticas: sem aleatoriedade e sem relógio de parede, então duas execuções dão relatórios idênticos. `evals/reports/scripted-baseline.json` e `.md` são a saída versionada das tarefas e configurações incluídas, e um teste unitário falha se rodar o harness deixar de reproduzi-los byte a byte. Depois de mudar uma tarefa, uma configuração ou um componente, gere os dois de novo:

```text
PYTHONPATH=src python3 -m wev_skills --lang en eval run --out evals/reports/scripted-baseline.json
PYTHONPATH=src python3 -m wev_skills --lang en eval run --format md --out evals/reports/scripted-baseline.md
```

## Tarefas e configurações incluídas

Oito tarefas, cada uma construída para exercitar um mecanismo: `simple-fix` (um controle em que nada depende da configuração), `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop` (três laços sem saída; nenhuma configuração consegue ter sucesso), `remote-diagnosis` (consultar periodicamente não deve contar como laço), `two-file-change` (um controle para perfis de capacidade) e `tool-selection-miss` (uma subtarefa somente leitura que recebe uma lista de ferramentas menor e uma subtarefa roteirizada para precisar de uma ferramenta que a política local descarta, o que é registrado como falha e restaurado).

Dezoito configurações, cada uma mudando um ajuste do `baseline` (planejamento ligado, omissão em 0,6, 3 tentativas, sequencial, roteamento por política, guarda ligada, nível do executor auto, ferramentas estruturadas), exceto os dois perfis de capacidade, que definem um grupo de ajustes juntos: `baseline`, `planning-off`, `planning-auto`, `context-none`, `context-elide-aggressive`, `context-elide-summarize`, `routing-fixed-standard`, `routing-fixed-premium`, `parallel-3`, `attempts-1`, `attempts-2`, `attempts-4`, `guard-off`, `profile-economy`, `profile-premium`, `tools-lean`, `tools-selection-off`, `tools-selection-local`. O resumidor usado por `context-elide-summarize` é um stub que guarda os 60 primeiros caracteres de cada texto; não é um modelo. Um perfil de ferramentas só muda as ferramentas que um agente de referência fixo lista, e o agente roteirizado não chama ferramenta alguma, então `tools-lean` tem as mesmas contagens do `baseline`. A seleção de ferramentas (`tool_selection`: `off` ou `local`) entrega a cada subtarefa as ferramentas que a política local seleciona para o seu `objective`; um passo pode nomear a ferramenta que representa com `needs_tool`, e com a seleção ligada um passo cuja ferramenta foi descartada registra uma falha e a ferramenta é restaurada da lista do próprio agente de referência (uma ferramenta fora dessa lista faz a subtarefa falhar como `tool_unavailable`). `tools-selection-off` tem os mesmos ajustes do `baseline` e é nomeada para ser lida ao lado de `tools-selection-local`.

## Ler um relatório

Um relatório começa com um aviso de que vem de um agente roteirizado e traz, por execução e somado por configuração, contagens e taxas brutas. Ele não calcula diferenças entre configurações. Saída real, duas tarefas incluídas (`context-overload`, `agent-loop`) com três configurações, agregada:

| Config | Execuções | Sucessos | Taxa de sucesso | Critérios atendidos | Tentativas | Escalonamentos | Disparos da guarda | Estouros de contexto | Itens omitidos | Verificações não executadas | Custo (unidades simuladas) | Duração (unidades simuladas) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline` | 2 | 1 | 0.5000 | 2/5 | 8 | 2 | 10 | 0 | 3 | 3 | 138549 | 33 |
| `context-none` | 2 | 0 | 0.0000 | 0/5 | 7 | 2 | 10 | 1 | 0 | 5 | 64095 | 23 |
| `guard-off` | 2 | 1 | 0.5000 | 2/5 | 11 | 3 | 0 | 0 | 3 | 0 | 497319 | 98 |

(Os cabeçalhos reais do relatório estão em inglês, o idioma padrão; aqui foram traduzidos. As colunas da taxa de critérios, de escalonamentos de nível, de itens resumidos, de falhas por perda de informação, de falhas de seleção de ferramentas e das estimativas de tokens de definição de ferramentas foram omitidas; no `baseline` as quatro primeiras valiam 0.4000, 1, 0, 0.) O que essa tabela permite dizer: com a guarda desligada, as mesmas duas tarefas roteirizadas rodaram mais tentativas (11 contra 8) e mais custo simulado antes de os roteiros as encerrarem; sem gerenciamento de contexto, a janela estourou uma vez. É uma afirmação sobre o que os componentes fizeram nessas trajetórias. Não é uma afirmação de que a guarda ou a omissão de itens "ajudam um modelo".

| Métrica | Significado |
|---|---|
| Sucesso | Todos os critérios de aceitação foram atendidos. A taxa de sucesso é sucessos divididos por execuções |
| Critérios atendidos | Critérios cujos passos `verify` rodaram todos e passaram na tentativa final da sua subtarefa |
| Tentativas | Tentativas iniciadas, somando todas as subtarefas |
| Escalonamentos | Vezes em que a política local respondeu "escalar" depois de uma tentativa que falhou |
| Escalonamentos de nível | Tentativas que rodaram num nível mais alto que a primeira tentativa da subtarefa |
| Disparos da guarda | Vereditos da guarda diferentes de "continue", no total e por regra |
| Estouros de contexto | Passos depois dos quais o contexto passou da janela |
| Itens omitidos, itens resumidos | Itens que o gerenciador de contexto trocou por um marcador ou condensou num resumo |
| Falhas por perda de informação | Tentativas encerradas porque um item necessário havia sido omitido ou resumido |
| Verificações não executadas | Passos `verify` que não rodaram na tentativa final da subtarefa |
| Falhas de seleção de ferramentas | Passos cuja ferramenta tinha sido descartada pela seleção e foi restaurada |
| Tokens de definição de ferramentas estimados, oferecidos e selecionados (aproximados) | Somas de constantes grosseiras, definidas à mão, por ferramenta (`approx_definition_tokens` no registro de ferramentas), para a lista inteira do agente e para a lista selecionada. Estimativas para comparação, não medições para qualquer modelo ou cliente |
| Custo (unidades simuladas) | Soma, sobre os passos, dos tokens no contexto vezes uma constante por nível (economy 1, standard 3, premium 15) |
| Duração (unidades simuladas) | Uma unidade por passo, uma para o plano; subtarefas concorrentes se sobrepõem |

Se quiser comparar duas configurações, ponha duas linhas lado a lado e diga qual mecanismo difere. Não escreva que uma é mais rápida, mais barata ou melhor.

## Escrever uma tarefa

Uma tarefa é um arquivo JSON, validado contra `src/wev_skills/schemas/eval-task.schema.json` e depois checado quanto à consistência. Parta de uma das incluídas em `evals/tasks/` e rode `eval validate` a cada edição. Esta tarefa foi escrita e executada para este guia:

```json
{
  "id": "retry-once",
  "title": "A verification that passes only on the second attempt",
  "description": "Exercises the attempt limit: with one attempt the task fails, with two or more it passes.",
  "category": "failing-test",
  "signals": { "objective": "Make one scripted check pass", "files_touched_estimate": 2, "unknowns": 1, "independent_subtasks": 1 },
  "window_tokens": 8000,
  "acceptance_criteria": [ { "id": "check-passes", "text": "The scripted check passes." } ],
  "subtasks": [ { "id": "work", "files": ["a.py"] } ],
  "script": [
    { "id": "edit-a", "subtask": "work", "kind": "edit", "tokens": 60 },
    { "id": "check", "subtask": "work", "kind": "verify", "signature": "make test", "tokens": 40,
      "criteria": ["check-passes"], "conditions": { "pass_from_attempt": 2 } }
  ]
}
```

```text
$ wev eval validate mytasks/retry-once.json
{"valid": true, "path": "mytasks/retry-once.json", "id": "retry-once", "subtasks": 1, "steps": 2}

$ wev eval run --tasks-dir mytasks --config attempts-1 --config baseline --format md
  baseline    1 execução  1 sucesso   tentativas 2  disparos da guarda 0
  attempts-1  1 execução  0 sucessos  tentativas 1  disparos da guarda 1
```

Uma tarefa cujo critério de aceitação não tem passo `verify` falha na validação (saída 2):

```text
{"error": {"code": "invalid_eval_task", "message": "Invalid eval task mytasks/bad.json: Criterion check-passes is not supported by any verify step.", ...}}
```

Campos:

| Campo | Significado |
|---|---|
| `id`, `title`, `description` | Identificação; `description` é opcional |
| `category` | `simple-fix`, `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop`, `remote-diagnosis` ou `tool-selection` |
| `signals` | Sinais da tarefa; a política local os classifica, e a classificação define o nível inicial, se `planning: auto` faz plano e se as subtarefas podem rodar em paralelo |
| `window_tokens` | Janela de contexto de cada subtarefa |
| `acceptance_criteria` | `{id, text}`; cada um precisa de pelo menos um passo `verify` |
| `subtasks` | `{id, depends_on, files, objective, read_only}`; cada uma roda como um agente delegado com contexto próprio |
| `script` | Passos em ordem, com `id`, `subtask`, `kind` e os campos que o tipo exige |

Tipos de passo: `tool_output`, `note`, `requirement`, `decision` (acrescentam ao contexto um item de `tokens` tokens; requisitos e decisões são fixados), `command` (um evento da guarda com uma `signature`; `outcome: fail` o faz falhar; `repeat`, `polling`, `flaky`), `edit` (um evento de progresso), `verify` (decide os `criteria` listados; uma verificação que falha encerra a tentativa), `handoff` (um evento de repasse). Qualquer passo pode definir `tokens`; `needed_later: true` marca um item de que um passo posterior precisa; `needs_tool` nomeia a ferramenta que o passo representa. As condições fazem o resultado depender da configuração: `requires_verbatim: [ids]` (falha se um item listado foi omitido ou resumido), `pass_from_attempt: N`, `min_tier: T`. As regras completas estão em [evals/README.pt-BR.md](../../evals/README.pt-BR.md) e na referência da skill, `skills/wev-harness-evaluation/references/task-fixtures.md`.

Escreva fixtures que exercitem um mecanismo, diga em `description` o que elas exercitam e mantenha os textos dos passos como enchimento. Uma tarefa acrescentada a `evals/tasks/` altera o relatório-base versionado, então gere-o de novo como mostrado acima, ou o teste que o compara vai falhar.

## Os limites da avaliação roteirizada

- O roteiro decide cada resultado. As tabelas mostram que um mecanismo disparou, não que ele é útil.
- As contagens de tokens são estimativas (caracteres divididos por 4) e os textos dos itens são enchimento.
- Custos e durações são constantes escolhidas para este harness. Não correspondem a preços nem latências de nenhum provedor.
- A recuperação de originais arquivados não é modelada: um item omitido conta como perdido para um passo que o exija.
- Um agente roteirizado não consegue mudar de estratégia. Um veredito da guarda que pede nova estratégia apenas encerra a tentativa.
- As tarefas incluídas são exemplos, não um benchmark. Suas taxas de aprovação não devem ser citadas como tal.
- Os mecanismos motivados pelo artigo de pesquisa (compactação em estágios, planejamento condicional, perfis de ferramentas, lembretes de plano e outros) estão implementados como padrões configuráveis cujo efeito num modelo real não foi medido. Veja `docs/research/hypotheses.pt-BR.md` e `docs/research/experiments.pt-BR.md`.

## Comparando execuções reais antes e depois de mudar uma instrução

Mudanças de instrução nas skills (por exemplo o passo de plano mais profundo da `wev-orchestrate`) não podem ser medidas pelo harness roteirizado, porque ele não chama modelo. Até existir um harness com modelo real, compare execuções reais à mão: rode os mesmos objetivos nos mesmos repositórios antes e depois da mudança, com o mesmo modelo, e leia cada `wev run report --format json`. Conte por execução: critérios de aceitação por tarefa, critérios amarrados a uma verificação, tarefas `verified` com evidência `tested`, vereditos de revisão `reject` e tentativas até a tarefa ser verificada. Registre o modelo, as datas e os relatórios. Nenhuma comparação dessas foi feita, então nenhuma melhora é afirmada: rotule qualquer afirmação sobre essas práticas como apenas documentada até que seja.

## Avaliando com um modelo real

Trabalho futuro; não implementado. Exige um provedor de modelo, que este repositório não chama (os testes unitários e o CI rodam sem provedor pago), um agente que implemente a interface de agente do harness chamando um modelo, tarefas apoiadas em repositórios e verificações reais, execuções repetidas por tarefa e configuração, e um registro dos identificadores de modelo, datas e saídas brutas. Enquanto uma execução assim não for feita e registrada, as hipóteses seguem não testadas.
