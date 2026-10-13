# Avaliação roteirizada

English version: [README.md](README.md).

> Os resultados deste diretório vêm de um agente roteirizado que reproduz trajetórias fixas. Nenhum modelo é chamado. Eles medem apenas a mecânica do harness, usam unidades simuladas de custo e de duração e não são evidência sobre o desempenho de nenhum modelo.

## O que é isto

`wev eval` executa cada tarefa de `tasks/` sob cada configuração de `baselines/configs.json`. Um agente roteirizado reproduz a lista fixa de passos de cada tarefa contra os componentes reais do motor:

- o gerenciador de contexto (`wev_skills.context`), que recebe cada item e aplica a política de compactação configurada;
- a guarda de execução (`wev_skills.guards`), que recebe eventos reais e devolve vereditos reais;
- o roteador de modelos (`wev_skills.models`) e a política de decisão local (`wev_skills.decisions`), que classificam a tarefa, escolhem o nível de cada tentativa e decidem sobre escalonamento.

O que não é exercitado: o harness tem seu próprio laço de tentativas e seu próprio agendador (`wev_skills.evaluation.agent` e `wev_skills.evaluation.harness`). Ele não chama o motor de orquestração; portanto o fluxo de execuções e tarefas do motor (`wev run`, `wev task`), sua contagem de tentativas e repetições, as linhas de base, as aprovações, a política de permissões e o motor de verificação não são cobertos por estes resultados. Nenhum comando é executado. Repetições, agendamento e paralelismo em um relatório são a reimplementação do próprio harness, mantida simples de propósito; mostram como os componentes respondem em uma trajetória roteirizada, não como o motor orquestra.

O agente não raciocina. Se um passo passa ou falha está escrito no arquivo da tarefa, às vezes como condição sobre a configuração. O harness é, portanto, uma bancada de teste dos componentes: mostra que limiares, guardas, roteamento e decisões de escalonamento se comportam como projetado em trajetórias construídas para exercitá-los. Tudo é determinístico: não há aleatoriedade nem tempo de relógio, então duas execuções produzem relatórios idênticos byte a byte. Rótulo de evidência de todo resultado aqui: **simulado com mocks** (`simulated with mocks` nos relatórios).

## Como executar

Na raiz do repositório, sem instalação e sem rede:

```sh
PYTHONPATH=src python3 -m wev_skills eval list
PYTHONPATH=src python3 -m wev_skills eval run
PYTHONPATH=src python3 -m wev_skills eval run --task context-overload --config baseline --config context-none
PYTHONPATH=src python3 -m wev_skills eval run --format md --lang pt-BR --out /tmp/relatorio.md
PYTHONPATH=src python3 -m wev_skills eval validate evals/tasks/simple-fix.json
```

Opções de `eval run`: `--tasks-dir DIR`, `--configs ARQUIVO`, `--task ID` e `--config ID` (ambas repetíveis), `--out ARQUIVO`, `--format json|md`, `--lang en|pt-BR`. Sem `--out`, o relatório JSON é impresso; com `--format md` e sem `--out`, o texto Markdown é impresso dentro de um objeto JSON, no campo `content`, porque a CLI sempre imprime JSON. Os padrões apontam para este diretório, localizado a partir da árvore de código-fonte. Quando o pacote é instalado sem o repositório, o diretório não existe e o comando falha com `evals_dir_not_found`; informe `--tasks-dir` e `--configs`.

`reports/scripted-baseline.json` e `reports/scripted-baseline.md` são a saída versionada das tarefas e configurações que acompanham o projeto. Um teste unitário falha se a execução do harness deixar de reproduzi-los byte a byte. Depois de alterar uma tarefa, uma configuração ou um componente, gere os dois de novo:

```sh
PYTHONPATH=src python3 -m wev_skills --lang en eval run --out evals/reports/scripted-baseline.json
PYTHONPATH=src python3 -m wev_skills --lang en eval run --format md --out evals/reports/scripted-baseline.md
```

## Tarefas incluídas

| Tarefa | O que o roteiro exercita |
| --- | --- |
| `simple-fix` | Controle: nada depende da configuração. Só o custo e a duração simulados mudam. |
| `multi-file-feature` | Subtarefas declaradas fora da ordem de dependência, duas subtarefas que compartilham um arquivo, uma verificação que só passa no nível premium. |
| `failing-test` | Uma verificação que só passa a partir da segunda tentativa. |
| `context-overload` | Seis saídas de ferramenta grandes em uma janela pequena, um trace necessário mais adiante e uma nota que a sumarização substitui. |
| `agent-loop` | Três laços sem saída: um comando que falha repetido sem mudança, um comando que passa repetido, dois agentes devolvendo o trabalho um ao outro. Nenhuma configuração pode ter sucesso. |
| `remote-diagnosis` | Consulta periódica a um comando remoto (não pode contar como laço) e notas longas que a elisão não remove. |
| `two-file-change` | Controle para os perfis de capacidade: classificada como simples (dois arquivos, risco baixo), então o planejamento automático planeja para um executor economy e não para um standard ou premium. |
| `tool-selection-miss` | Seleção de ferramentas por tarefa: uma subtarefa somente leitura que recebe uma lista menor, e uma subtarefa roteirizada para precisar de uma ferramenta que a política local remove, o que é registrado como falha da seleção e restaurado. |

## Configurações incluídas

Cada configuração muda um ajuste de `baseline` (planejamento ligado, elisão em 0,6, 3 tentativas, sequencial, roteamento por política, guarda ligada, nível do executor auto, ferramentas structured), exceto os dois perfis de capacidade, que definem um grupo de ajustes de uma vez.

| Comparação | Configurações |
| --- | --- |
| Planejamento | `baseline` (ligado), `planning-off`, `planning-auto` (planeja quando a política local pede) |
| Contexto | `context-none` (sem gerenciamento), `baseline` (elisão), `context-elide-aggressive`, `context-elide-summarize` |
| Roteamento | `baseline` (política), `routing-fixed-standard`, `routing-fixed-premium` |
| Agendamento | `baseline` (sequencial), `parallel-3` |
| Limite de tentativas | `attempts-1`, `attempts-2`, `baseline` (3), `attempts-4` |
| Guarda | `baseline` (ligada), `guard-off` |
| Perfil de capacidade | `profile-economy` (planejamento auto, executor economy, toda tentativa no nível economy, perfil de ferramentas auto), `profile-premium` (o mesmo no nível premium) |
| Perfil de ferramentas | `baseline` (structured), `tools-lean` |
| Seleção de ferramentas | `tools-selection-off` (as mesmas definições de `baseline`), `tools-selection-local` |

O nível do executor decide se `planning: auto` faz um plano. Um perfil de ferramentas só muda quais ferramentas de um agente de referência fixo (`Read`, `Grep`, `Glob`, `Edit`, `Write`, `Bash`) a execução lista: o agente roteirizado não chama ferramenta alguma, então `tools-lean` tem as mesmas contagens de `baseline`, exceto os tokens estimados de definição de ferramentas da lista mais curta. Nenhuma das linhas diz se um perfil ajuda um modelo.

A seleção de ferramentas (`tool_selection`: `off` ou `local`) entrega a cada subtarefa as ferramentas que a política local seleciona para o seu `objective`. Um passo pode nomear a ferramenta que representa com `needs_tool`. Com a seleção ligada, um passo cuja ferramenta foi removida registra uma falha da seleção e a ferramenta é restaurada a partir da lista do próprio agente de referência; uma ferramenta fora dessa lista faz a subtarefa falhar como `tool_unavailable`. Com a seleção desligada nenhum passo confere sua ferramenta. As colunas de tokens de definição de ferramentas do relatório são somas de constantes aproximadas, definidas à mão por ferramenta (`approx_definition_tokens` no registro de ferramentas): estimativas para comparação, não medições para nenhum modelo ou cliente.

O sumarizador usado por `context-elide-summarize` é um stub que mantém os 60 primeiros caracteres de cada texto. Não é um modelo e não entende o que encurta.

## Como escrever uma tarefa

Uma tarefa é um arquivo JSON validado contra `src/wev_skills/schemas/eval-task.schema.json` e depois verificado quanto à consistência. Execute `wev eval validate <arquivo>` enquanto a escreve.

| Campo | Significado |
| --- | --- |
| `id`, `title`, `description` | Identificação. `description` é opcional. |
| `category` | Um de `simple-fix`, `multi-file-feature`, `failing-test`, `context-overload`, `agent-loop`, `remote-diagnosis`, `tool-selection`. |
| `signals` | Um objeto `TaskSignals`. A política local o classifica; a classificação define o nível inicial, se `planning: auto` planeja e se as subtarefas podem rodar em paralelo (`independent_subtasks` igual a 2 ou mais). |
| `window_tokens` | Tamanho da janela de contexto de cada subtarefa. |
| `acceptance_criteria` | Lista de `{id, text}`. Cada critério precisa ser sustentado por ao menos um passo `verify`. |
| `subtasks` | Lista de `{id, depends_on, files, objective, read_only}`. Cada subtarefa roda como um agente delegado, com contexto próprio. `objective` e `read_only` são opcionais e são lidos pela seleção de ferramentas. |
| `script` | Passos em ordem. Cada um tem `id`, `subtask`, `kind` e os campos que o seu tipo exige. |

Tipos de passo:

| Tipo | Efeito |
| --- | --- |
| `tool_output`, `note`, `requirement`, `decision` | Acrescenta ao contexto um item de `tokens` tokens. Requisitos e decisões são fixados pelo gerenciador de contexto. |
| `command` | Emite um evento de comando para a guarda, com `signature`; `outcome: fail` faz dele um comando que falha, o que não encerra a tentativa. `repeat` o emite várias vezes. `polling` e `flaky` são repassados à guarda. |
| `edit` | Emite um evento de progresso com uma nova impressão digital. |
| `verify` | Emite um evento de verificação e decide os `criteria` listados. Uma verificação que falha encerra a tentativa. |
| `handoff` | Emite um evento de passagem de `from_agent` para `to_agent`. |

Qualquer passo pode definir `tokens` para também acrescentar um item ao contexto. `needed_later: true` marca um item que um passo posterior da mesma subtarefa exige. `needs_tool` nomeia a ferramenta que o passo representa (veja a seleção de ferramentas acima).

Condições (`conditions`, em qualquer passo) fazem o resultado depender da configuração. Uma condição não atendida encerra a tentativa como falha.

| Condição | O passo falha quando | Modela |
| --- | --- | --- |
| `requires_verbatim: [ids]` | um item listado foi elidido ou substituído por um resumo | informação perdida pela compactação |
| `pass_from_attempt: N` | o número da tentativa é menor que N | trabalho que só dá certo em uma nova tentativa |
| `min_tier: T` | a tentativa roda em um nível abaixo de T | trabalho que só dá certo em determinado nível de modelo |

Regras que o harness aplica, todas mecânicas:

- O contexto estoura quando seus tokens estimados passam de `window_tokens` depois de um passo. Estouro e perda de informação encerram a subtarefa sem nova tentativa, porque uma nova tentativa reproduziria a mesma trajetória sob a mesma política.
- Uma nova tentativa começa com um contexto novo. O roteador recebe o número de tentativas que falharam, então o nível sobe a partir da terceira tentativa no roteamento por política.
- A guarda é consultada depois de cada passo e depois de cada tentativa que falha. `change_strategy` e `reduce_scope` encerram a tentativa; qualquer outro veredito encerra a subtarefa. Um veredito que já foi tratado não é contado duas vezes.
- Com plano, as subtarefas começam na ordem de declaração assim que suas dependências tiveram sucesso, há uma vaga livre e nenhuma subtarefa em execução compartilha um arquivo. Sem plano, elas rodam uma por vez na ordem de declaração, e uma subtarefa alcançada antes de suas dependências fica bloqueada.
- Uma subtarefa cuja dependência falhou não é executada.

## O que cada métrica significa

Os relatórios trazem estas métricas por execução e somadas por configuração. São contagens e taxas brutas. Os relatórios não calculam diferenças entre configurações.

| Métrica | Significado |
| --- | --- |
| Sucesso | Todos os critérios de aceitação foram atendidos. A taxa de sucesso é sucessos dividido por execuções. |
| Critérios atendidos | Critérios cujos passos `verify` rodaram e passaram, todos, na última tentativa da subtarefa. Um critério fica não atendido quando um deles falhou e não verificado quando um deles não rodou. |
| Tentativas | Tentativas iniciadas, somando todas as subtarefas. |
| Escalonamentos | Vezes em que a política local respondeu "escalar" depois de uma tentativa que falhou. |
| Escalonamentos de nível | Tentativas que rodaram em um nível acima do da primeira tentativa da subtarefa. |
| Disparos da guarda | Vereditos da guarda diferentes de "continue", no total e por regra. |
| Estouros de contexto | Passos depois dos quais o contexto passou da janela. |
| Itens elididos, itens resumidos | Itens que o gerenciador de contexto substituiu por um stub ou incorporou a um resumo. |
| Falhas por perda de informação | Tentativas encerradas por `requires_verbatim`. |
| Verificações não executadas | Passos `verify` que não rodaram na última tentativa da subtarefa. |
| Custo (unidades simuladas) | Soma, por passo, dos tokens no contexto multiplicados por uma constante por nível (economy 1, standard 3, premium 15). Não é dinheiro. |
| Duração (unidades simuladas) | Uma unidade por passo e uma pelo plano; subtarefas concorrentes se sobrepõem. Não é tempo. |

## Limites da avaliação roteirizada

- O roteiro decide todo resultado. Uma configuração "passa" em uma tarefa porque a tarefa foi escrita para isso. As tabelas mostram que o mecanismo atuou, não que ele é útil.
- As contagens de tokens são estimativas (caracteres divididos por 4), e os textos dos itens são preenchimento.
- Custos e durações são constantes escolhidas para este harness. Não correspondem a preços nem a latências de nenhum provedor.
- A recuperação de originais arquivados não é modelada: um item elidido conta como perdido para o passo que o exige.
- Um agente roteirizado não muda de estratégia. Um veredito da guarda que pede nova estratégia apenas encerra a tentativa.
- As tarefas incluídas são exemplos que exercitam mecanismos. Não são um benchmark, e suas taxas de sucesso não devem ser citadas como tal.

Nenhum relatório deste harness pode ser usado para afirmar que uma configuração melhora o sucesso, o custo ou a velocidade de um modelo. Veja [`docs/research/experiments.pt-BR.md`](../docs/research/experiments.pt-BR.md) para saber quais perguntas o agente roteirizado responde e quais exigem um modelo.

## Avaliação com um modelo real

Isto é trabalho futuro. Não está implementado, e **não existe nenhum resultado com modelo real** neste projeto.

Ela exige um provedor de modelos, que este repositório não chama: os testes unitários e a CI rodam sem provedor pago. Uma execução com modelo real precisaria de um agente que implemente a interface de agente do harness chamando um modelo, de tarefas apoiadas em repositórios reais e verificações reais em vez de roteiros, de execuções repetidas por tarefa e configuração e do registro dos identificadores de modelo, das datas e das saídas brutas. Até que uma execução assim seja feita e registrada, as hipóteses em [`docs/research/hypotheses.pt-BR.md`](../docs/research/hypotheses.pt-BR.md) continuam sem teste.
