# Design: casos pontuados e especialistas que evoluem sozinhos

Versão em inglês: [2026-10-22-scored-cases-and-self-evolving-specialists-design.md](2026-10-22-scored-cases-and-self-evolving-specialists-design.md).

Status: rascunho para aprovação do dono (2026-10-22). Nada aqui está implementado.

## Intenção

O dono quer um desenvolvimento contínuo de ponta a ponta em que toda mudança eleve a qualidade do sistema e nenhuma a rebaixe. O modelo é o fluxo de revisão que o time do Claude Code descreveu em "How the Claude Code team does code review" (claude.dev, 2026-10-15). O ciclo central é: todo incidente ou revert vira um caso de eval, toda mudança no revisor é pontuada contra todos os casos, e a mudança só fica quando a nota sobe.

O wev-skills já tem as peças que vêm antes desse ciclo: `task record --status verified` é recusado sem evidência executada pela engine, existem níveis de risco, loops são detectados e os especialistas de projeto aprendem lições com checagens e bloqueios do guard. O que falta é o ciclo em si. Hoje uma falha real não ensina nada. Em 2026-10-22 o teste de ponta a ponta mostrou que o health check de terceiros lia no máximo 1 MiB, enquanto o `rea` 6.7.0 responde `tools/list` com 3,1 MB. Todos os testes unitários passavam porque as fakes respondiam com payloads pequenos. Nenhum caso foi guardado, nenhum especialista aprendeu com isso, e nada avisaria uma mudança futura de que ela trouxe o bug de volta.

Este design fecha esse ciclo para os especialistas de projeto. Falhas reais viram **casos** guardados. Uma lição proposta é **pontuada** rodando o especialista com e sem ela contra todos os casos, e ela entra ou sai sozinha conforme a nota. Nas palavras do dono: "quero que ele atualize mediante nota sozinho para não ter tanta interação".

## Decisões do dono

Decididas nesta conversa, não cabem ao construtor:

- O trabalho são três projetos, nesta ordem: (1) a catraca de casos e nota, (2) especialistas que evoluem pela nota, (3) as camadas de revisão do artigo (`REVIEW.md`, revisores em paralelo com votação, aprovações presas a um commit, template de PR com seções de risco e de reversão). Este documento cobre 1 e 2. O projeto 3 terá um design próprio depois.
- Lições entram e saem pela nota, sem uma pessoa aprovar cada uma.
- Os bugs de ponta a ponta de 2026-10-22 são os primeiros casos.
- A engine escreve sozinha o texto da lição a partir de uma falha, chamando o modelo, sem PR. É a nota, e não uma pessoa, que decide se o texto entra.
- O `claude -p` sem supervisão roda com o plugin wev carregado e um conjunto limitado de ferramentas.

## Objetivos, não objetivos e antiobjetivos

Objetivos:

- Um formato de caso commitado e validado, com os três bugs de ponta a ponta de 2026-10-22 como primeiros casos.
- Um comando que pontua um especialista contra todos os casos, com e sem cada lição proposta, usando uma execução real do harness.
- Lições escritas pelo modelo a partir dos casos em que o especialista falha, para que uma falha como a do probe de 1 MiB possa ensinar "aguente respostas de `tools/list` de vários MB", algo que lições derivadas de checagens nunca dizem.
- Aceite e aposentadoria automáticos de lições pela nota, segundo a regra da catraca abaixo.
- Um registro de cada pontuação, para o dono ver a tendência ao longo do tempo.

Não objetivos:

- Pontuar um revisor ou o `REVIEW.md` (projeto 3).
- Feature flags, lançamentos em etapas ou reverter mudanças aplicadas.
- Gerar casos automaticamente a partir de falhas. Nesta versão um caso é escrito (por uma pessoa ou um agente) e commitado; transformar um relatório de ponta a ponta ou um achado de revisão em caso automaticamente fica para depois.
- Lições que mudem ferramentas, permissões ou modelo de um agente. Lições continuam sendo texto de orientação.

Antiobjetivos (uma falha mesmo que funcione tecnicamente):

- A nota pode subir editando os casos no mesmo trabalho que está sendo pontuado.
- O `make test` chama um modelo ou a rede.
- Tokens são gastos sem o dono ter pedido uma pontuação, ou além de um teto configurado.
- Uma lição que o dono aposentou volta sozinha.
- Uma lição entra fazendo falhar algum caso que passava sem ela.
- Texto escrito pelo modelo chega a um agente sem ter sido pontuado, ou carrega um comando de operador, uma concessão de ferramenta ou uma mudança de permissão.

## Partes e ordem

### A. Casos

É um recurso do produto: todo projeto que usa o wev tem seus próprios casos em `evals/cases/` na raiz do projeto, ao lado dos especialistas em `agents.project_dir`. O wev-skills é o primeiro projeto a usar isso em si mesmo, então a implementação inclui criar o especialista do próprio wev-skills e seus primeiros casos.

Um caso é um arquivo JSON em `evals/cases/<id>.json`, validado por um schema em `src/wev_skills/schemas/`. Ele contém:

- `id`, `title`, `source` (`e2e`, `review`, `revert` ou `incident`) e `ref` (o commit, PR ou relatório onde a falha foi encontrada).
- `agents`: lista opcional de ids de especialistas a que o caso se aplica; vazia significa todos os especialistas do projeto.
- `base_commit`: um commit do projeto de antes de o código que falhou ser escrito, para que o especialista construa esse código e repita a falha ou não.
- `objective`: a tarefa dada ao especialista, escrita como uma pessoa pediria, sem citar o bug.
- `check`: o argv que a engine roda depois que o especialista termina, no workspace do caso. Passar significa que o especialista não reproduziu a falha. No caso de 1 MiB, a checagem é um teste que entrega ao probe uma resposta gravada de 3,1 MB de `tools/list`.
- `files`: os caminhos de que a checagem precisa e que não existiam no `base_commit` (o teste que reproduz e sua fixture), copiados para o workspace antes da checagem e nunca mostrados ao especialista.

Os primeiros casos do wev-skills são os bugs em Python encontrados em 2026-10-22: o health probe que lia no máximo 1 MiB (`06fc92c`), a checagem de tarball que rejeitava um symlink `..` confinado (`06fc92c`) e o exec path que confiava em diretórios que não são do usuário (`e3d7b2b`). O bug do uninstall vive no `install.sh` e fica para um caso posterior.

`wev cases list` e `wev cases validate` leem e conferem o conjunto; `wev cases validate --at-base` também confirma, localmente, que cada `check` falha no seu `base_commit`. Adicionar um caso é escrever o arquivo e commitá-lo; o dono o vê no PR como qualquer outra mudança.

### B. O congelamento do conjunto de casos

Uma pontuação usa só arquivos de caso commitados e sem mudanças na árvore de trabalho; um arquivo modificado ou não rastreado em `evals/cases/` recusa a pontuação. Ela registra um sha256 sobre a lista ordenada de (caminho, bytes) dos arquivos de caso, com a mesma receita canônica do `config_digest`. Se o conjunto mudar antes de a pontuação terminar, ela é recusada e nada é decidido.

### C. O executor de agente

O `core/ports.py` ganha uma porta de executor de agente: dado um workspace, um prompt, um conjunto de ferramentas, um tempo limite e um limite de tokens ou turnos, ela devolve se a execução terminou normalmente e a saída. O core nunca importa o adaptador. O primeiro adaptador fica em `adapters/claude_code/` e roda `claude -p` pelo `SubprocessRunner` existente, com o prompt exportado do especialista e o conjunto de lições em teste. Cada caso roda numa `git worktree` temporária no `base_commit`, removida depois. Os testes unitários usam o `fake_bin/claude` existente.

Toda execução sem supervisão carrega o plugin wev, para que seus hooks e o guard de Bash valham, e permite só Read, Edit, Write, Glob, Grep e Bash. Ela nunca passa `--dangerously-skip-permissions` nem um modo que ignore permissões. Uma execução que não consegue carregar o plugin é recusada em vez de rodar sem ele.

### C2. Lições escritas pelo modelo

Depois da linha de base de uma pontuação, para cada caso em que o especialista falhou, a engine pede ao modelo uma lição candidata. O pedido passa pela mesma porta sem nenhuma ferramenta, e leva o objetivo do caso, a saída do `check` e o diff que o especialista produziu, cada um cercado e redigido como dado não confiável com o `security/untrusted.py` e o redator existentes. A resposta precisa ser um objeto JSON curto com o texto da lição; qualquer outra coisa é descartada.

A engine então filtra o texto antes de ele virar lição: um teto de tamanho, a mesma varredura de texto não confiável usada em outros lugares (que já marca comandos de operador como `specialists accept`) e a recusa de texto que cite ferramentas, permissões ou modelos. Um texto que sobrevive vira uma lição `proposed` de um tipo novo (`model`), com seu caso como evidência, e é pontuado na mesma execução como qualquer outra proposta. Nada que o modelo escreve chega a um agente sem a nota deixar.

São escritas no máximo `score_max_new_lessons` candidatas por pontuação (padrão 3), e cada chamada de geração conta para o `score_max_runs`.

### D. Pontuação e a regra da catraca

`wev specialists score <agent>` roda o especialista em todos os casos com as lições ativas (a linha de base) e, para cada lição proposta, com as lições ativas mais ela. Cada configuração roda cada caso `score_samples` vezes; a nota de um caso é o número de acertos.

Uma lição proposta **entra** quando, contra a linha de base, nenhum caso perde acerto e o total de acertos sobe. Um empate a deixa proposta, porque uma lição que não muda nada só gasta contexto.

Uma lição ativa **sai** quando a execução sem ela, contra a linha de base, não perde acerto em nenhum caso e o total sobe. Testar a remoção das lições ativas faz parte da mesma pontuação, dentro do teto abaixo.

Antes de rodar, o comando mostra quantas execuções do harness vai fazer (configurações × casos × amostras) e recusa quando isso passa de `specialists.score_max_runs`. Rodar o comando é o consentimento para gastar; não há confirmação extra.

### E. Decisões e auditoria

Uma decisão automática grava `accepted_by` com o nome reservado `score`, como o `engine` de hoje, e escreve um evento de auditoria (`specialists.auto_accept` ou `specialists.auto_retire`) antes do arquivo do especialista, com a lição, o hash do conjunto de casos e os acertos antes e depois. O aprendizado preserva as decisões `score` entre reaprendizados do mesmo jeito que preserva as humanas.

Uma lição que a nota aposentou volta a `proposed` no próximo aprendizado e pode ser pontuada de novo, porque uma execução pode perder só pela variação das amostras. Os comandos humanos continuam valendo por cima: `specialists retire` sempre funciona, e uma lição aposentada por uma pessoa nunca é aceita de novo pela nota; o `accepted_by` distingue os dois casos. `specialists accept` continua existindo para uma lição que o dono quer sem pontuar.

### F. Configuração

Chaves novas na seção `specialists`, com validação no schema, testes e documentação nas duas línguas: `score_samples` (padrão 3), `score_max_runs` (padrão 60), `score_max_new_lessons` (padrão 3), `score_timeout_seconds` (por execução do harness) e `score_on_finish` (padrão `false`; quando `true`, o `run finish` inicia uma pontuação dos especialistas que a run usou). O `docs/guides/configuration-and-providers.md` ganha uma seção `specialists` nas duas línguas, já que hoje não tem.

### G. Histórico das notas

Cada pontuação acrescenta uma linha a `.wev/scores.jsonl` (agente, hash do conjunto de casos, configuração, acertos, decisões, execuções do harness usadas) e `wev specialists scores` mostra a tendência. O arquivo é local, como o resto de `.wev/`.

### H. Textos que precisam mudar

O aceite automático contradiz afirmações de que lições precisam de uma pessoa. Cada uma deve ser atualizada nas duas línguas na mesma mudança: `SECURITY.md` (linhas 57, 78 e 115), `CLAUDE.md` (a lista de comandos de operador humano continua, com uma nota de que decisões pela nota não precisam dela), `docs/guides/specialists.md`, `docs/guides/installation.md`, `docs/glossary.md`, as docstrings de `commands/specialists.py`, `agents/experience.py` e `agents/learning.py`, e as chaves de locale em `agents.specialists`. O texto de segurança deve dizer que o congelamento, o teto, o filtro de texto e a nota protegem contra um agente que erra, não contra um agente mal-intencionado na mesma conta, e deve descrever o que o `claude -p` sem supervisão pode fazer e que lições escritas pelo modelo são texto não confiável até serem pontuadas.

## Testes

- Unitários, sem rede e sem modelo: geração de lição com uma resposta falsa do modelo (JSON válido, resposta malformada, um comando de operador, uma concessão de ferramenta, um texto longo demais, cada um descartado ou mantido como desenhado); a recusa quando o plugin não carrega; o schema de caso; o congelamento (um caso modificado, não rastreado ou alterado durante a pontuação recusa a execução); a regra da catraca (entrada, empate, regressão, remoção, aposentada por pessoa nunca volta); o teto de execuções; auditoria antes da escrita; o adaptador falso do `claude`, incluindo tempo esgotado e saída anormal. Cada um é quebrado de propósito uma vez para ver o teste falhar.
- Os três casos de 2026-10-22: um teste unitário roda cada `check` contra a árvore atual e espera que passe, sem modelo e sem histórico, para funcionar num clone raso do CI. Que cada `check` falha no seu `base_commit` é confirmado localmente com `wev cases validate --at-base`.
- Uma pontuação real com `claude -p` é rodada pelo dono, gasta tokens e é relatada como não testada até ter rodado.

## Restrições

- Só biblioteca padrão, Python 3.14 ou mais novo, mypy strict, dataclasses congeladas, funções com menos de 50 linhas, arquivos com menos de 400.
- Toda mensagem ao usuário via i18n com as mesmas chaves em `en` e `pt-BR`; documentação nas duas línguas no mesmo commit.
- O `make test` nunca chama um modelo, a rede ou um harness real.
- Nunca fazer push, publicar ou lançar release sem autorização explícita do dono.

## O que fica com o construtor

- Nomes e organização dos módulos, dentro das responsabilidades de pacote do `CLAUDE.md`.
- Nomes exatos dos campos JSON além dos acima, e o template de prompt dado ao `claude -p`.
- Como o executor limita uma execução do harness (turnos, tokens ou tempo), desde que o `score_timeout_seconds` a limite.
- O formato da saída de `wev cases` e `wev specialists scores`.

## Escolhas que fiz sem o dono

- A pontuação roda sob demanda por padrão; `score_on_finish` vem desligado.
- A regra da catraca: nenhum caso pode perder acerto, e o total precisa subir estritamente; um empate mantém a lição proposta.
- Acertos contados em três amostras por caso, para absorver a variação do modelo.
- Arquivos de caso precisam estar commitados e limpos para serem pontuados.
- Lições que uma pessoa aposentou nunca voltam pela nota; `specialists accept` continua como caminho manual.
- O teto de 60 execuções do harness por comando de pontuação.
- O histórico das notas fica local em `.wev/`.
- Um recurso do produto para todo projeto, com o wev-skills como primeiro usuário; casos na raiz do projeto, opcionalmente marcados por especialista.
- No caso, o especialista constrói o código a partir de antes de ele existir, para poder repetir a falha ou evitá-la.
- Os primeiros casos são os três bugs em Python de 2026-10-22; o bug do uninstall no `install.sh` fica para depois.
- Uma lição que a nota aposentou pode ser pontuada de novo; só a aposentadoria feita por uma pessoa é definitiva.
- O teste unitário só confere que cada caso passa na árvore atual; falhar na base é uma checagem local.
- Lições são geradas só a partir de casos que falharam durante uma pontuação, não de toda checagem que falhou em runs comuns, porque um caso tem um estado conhecido que passa para pontuar contra.
- No máximo três lições novas por pontuação, e a chamada de geração não tem ferramentas.
- Os casos continuam sendo escritos e commitados; só as lições são geradas sem PR.
