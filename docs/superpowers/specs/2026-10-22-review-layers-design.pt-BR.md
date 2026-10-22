# Design: camadas de revisão

Versão em inglês: [2026-10-22-review-layers-design.md](2026-10-22-review-layers-design.md).

Status: rascunho para aprovação do dono (2026-10-22). Nada aqui está implementado.

## Intenção

Este é o projeto 3 do plano de melhoria contínua. O projeto 1 (casos guardados e uma catraca de nota) e o projeto 2 (especialistas cujas lições entram e saem pela nota) saíram no PR #18; o design deles é [2026-10-22-scored-cases-and-self-evolving-specialists-design.pt-BR.md](2026-10-22-scored-cases-and-self-evolving-specialists-design.pt-BR.md). Este projeto traz para um run do wev as camadas de revisão de "How the Claude Code team does code review" (claude.dev, 2026-10-15).

O dono quer menos interação e melhoria contínua que nunca regride. Aplicado à revisão, isso significa três coisas. Uma revisão é executada e conferida pelo motor, não descrita numa skill. Uma revisão nunca continua valendo para código que ela não viu. E o próprio revisor só muda quando sua nota nos casos guardados sobe.

Hoje uma revisão no wev é um registro: `task review <id> --reviewer <agente> --accept|--reject --summary <texto>`. O motor recusa autorrevisão e recusa revisar uma tarefa não verificada, mas não registra qual código a revisão cobriu. `review_accepted` compara horários, não árvores. Se outra tarefa edita os mesmos arquivos depois da revisão, a revisão continua valendo. Nenhum achado é estruturado, nada é votado, as rodadas não são contadas, e as aprovações de um push são presas ao argv e ao run, mas não ao commit que vai ser enviado.

## Decisões do dono

Em 2026-10-22 o dono pediu que o trabalho seguisse sem mais perguntas ("pode dar andamento e austar como achar melhor de forma a não travar e atingirmos nosso objetivo"). O escopo abaixo veio da sessão que iniciou este design. Todas as outras escolhas estão em "Escolhas que fiz sem o dono" e o dono pode mudá-las.

- Escopo: um `REVIEW.md` por repositório que o motor lê para os revisores; revisores paralelos caçando bugs, com votação de verificadores e as marcas Importante, Nit e Preexistente; aceite de revisão e aprovações presos ao commit ou à árvore; um teto de rodadas de revisão, com revisão só do diff novo; um modelo de PR com as seções Risco e Como reverter; e a nota de um revisor nos casos de `evals/cases/`, com a catraca do PR #18.

## Objetivos, não objetivos e antiobjetivos

Objetivos:

- Uma rodada de revisão executada pelo motor: vários caçadores em paralelo, depois verificadores que votam em cada achado, e só os achados aprovados no voto ficam.
- As regras do `REVIEW.md` que o código consegue conferir (caminhos ignorados, teto de nits, evidência de arquivo e linha, resumo que começa por uma contagem) são aplicadas pelo motor, não deixadas ao modelo.
- Uma revisão, uma verificação e uma aprovação para um comando de publicação só valem para a árvore ou o commit que viram.
- No máximo `review.max_rounds` rodadas por run. As rodadas depois das primeiras `review.full_rounds` revisam só o que mudou desde a rodada anterior. Achados já publicados não se repetem.
- `run finish` recusa enquanto houver um achado Importante aberto.
- Casos de revisão (um diff com um bug conhecido, ou um diff sabidamente limpo) em `evals/cases/`. O revisor recebe nota neles com a mesma catraca, então suas lições entram e saem pela nota, e uma mudança no `REVIEW.md` ou na spec do revisor só fica se a nota subir.
- Um modelo de PR, e um corpo de PR gerado por `run report`, com Testes, Risco, Como reverter e um resumo da revisão.

Não objetivos:

- Comentar no GitHub, ler threads de PR, ou qualquer chamada de rede além da execução do harness. O motor revisa o diff do run localmente. Publicar o corpo do PR continua com o agente, sob as aprovações de push e publicação que já existem.
- Proteção de branch, regras de CODEOWNERS, fila de merge, feature flags ou canais de release. São configurações do repositório, e só o dono pode mudá-las (ver `CLAUDE.md`).
- Uma passada separada de revisão de segurança. Achados de segurança são achados Importantes da mesma rodada. Uma passada separada pode vir depois como fonte de casos de revisão.
- Criar casos de revisão automaticamente a partir de achados descartados. Casos continuam sendo escritos e commitados, como no projeto 1.
- Um `REVIEW.md` por diretório. Um arquivo na raiz do projeto cobre os projetos do wev hoje.

Antiobjetivos (uma falha mesmo que funcione tecnicamente):

- Uma revisão, uma verificação ou uma aprovação de publicação continua valendo depois que a árvore que ela viu mudou.
- O agente cujo trabalho está em revisão descarta sozinho um achado Importante.
- Tokens são gastos em revisões que a configuração não permite, ou além do teto configurado.
- `make test` chama um modelo ou a rede.
- A nota do revisor pode subir editando casos de revisão no mesmo trabalho que está sendo avaliado (vale a fixação do conjunto de casos do projeto 1).
- Saída do modelo (um achado ou um voto) dá uma instrução a um agente, ou carrega um comando de operador, uma concessão de ferramenta ou uma mudança de permissão.
- Rodadas de revisão continuam sem fim. O artigo relata um PR que passou por mais de cinquenta rodadas durante a noite.

## Partes e ordem

As partes estão na ordem de construção. A, B e C podem sair sem nenhuma chamada a modelo. De D a G é preciso o executor de agente do PR #18.

### A. Prender revisões e aprovações ao que viram

- A revisão de tarefa (`task review`) continua por tarefa e mantém o seu papel: quando a estratégia liga `needs_independent_review`, uma tarefa só está completa com uma revisão aceita. Ela roda ao lado das rodadas do run de D, que não a substituem nem a satisfazem. A revisão de tarefa cobre o resultado da própria tarefa, e a rodada cobre a árvore final do run.
- `ReviewRecord` ganha `fingerprint`, a impressão da árvore da última verificação da tarefa no momento em que a revisão é registrada. `review_accepted` exige que essa impressão seja igual à da última verificação que a própria tarefa registrou (`task record`), não a de uma rechecagem posterior. Uma tarefa reaberta e refeita precisa de nova revisão. Uma tarefa posterior que edita outros arquivos, ou as rechecagens antes do `run finish`, não a invalidam, porque a impressão da árvore inteira faria cada tarefa posterior anular todas as revisões anteriores. O desvio entre tarefas é o que a rodada do run, presa à árvore final, pega.
- Uma aprovação para uma ação que o classificador marca como tendo efeito externo (`git push`, as entradas `publish` de `command_tables.py`, `gh pr merge`, `gh release create` e semelhantes) também registra o `HEAD` e a impressão da árvore no momento da aprovação. Ela só pode ser usada enquanto os dois ainda batem. Uma divergência informa `stale_grant` e exige uma nova aprovação. As outras aprovações mantêm o vínculo atual (argv, diretório de trabalho, run, uso único, TTL). Prender toda aprovação à árvore aumentaria os pedidos sem impedir nenhuma regressão.
- Status: são mudanças de código em `state/records.py`, `core/progress.py` e `governance/approvals.py`, com testes unitários. Nada nesta parte chama um modelo.

### B. `REVIEW.md`

Um projeto pode manter um `REVIEW.md` na raiz. O motor o lê a cada rodada de revisão e o passa a caçadores e verificadores como orientação do projeto, cercada. O resto do repositório é tratado como texto não confiável da mesma forma. O arquivo tem títulos de segundo nível fixos, reconhecidos em inglês e em português:

- `## What failure looks like` (`## Como é uma falha`): texto livre, entregue aos revisores.
- `## Skip` (`## Ignorar`): um glob por item de lista. Achados em caminhos que casam são descartados pelo motor.
- `## Nits` (`## Nits`): uma linha `max: <n>` limita os achados Nit mantidos por rodada (padrão 3), mais texto livre opcional.
- `## Important` (`## Importante`): texto livre sobre o que merece a marca Importante aqui.

O motor aplica estas regras em código. Um achado precisa citar um arquivo e uma linha que existem na árvore revisada, ou é descartado como sem prova. Nits além do teto são descartados, começando pelos de menos votos. Os globs de Ignorar descartam achados. O resumo da rodada é escrito pelo motor, não pelo modelo. Ele começa pelas contagens ("2 Importantes, 1 Nit, 3 Preexistentes" ou "Nada a corrigir") e depois lista os achados por gravidade.

`wev review md check` valida os títulos e a linha `max:`. `docs/guides/review.md` (nas duas línguas) traz um modelo. O wev-skills escreve o próprio `REVIEW.md` como primeiro usuário. As linhas de "como é uma falha" vêm do `CLAUDE.md`: uma capacidade afirmada sem evidência, um texto de usuário fora do i18n, um documento sem o gêmeo, uma regra que só existe em Markdown, e uma afirmação de segurança mais forte que o `SECURITY.md`. Sem `REVIEW.md`, as rodadas rodam com os padrões embutidos (teto de nits 3, nenhum caminho ignorado).

### C. O modelo de PR e o corpo do PR

- `.github/PULL_REQUEST_TEMPLATE.md` ganha `## Risk` (o nível de risco e o que pode quebrar), `## How to revert` (os passos exatos, incluindo dados ou configuração que um `git revert` não desfaz) e `## Review` (o resumo que começa pela contagem, mais os achados descartados e seus motivos). A seção "What was tested" continua como a seção de Testes.
- `wev run report --format pr` imprime um corpo de PR com essas seções preenchidas a partir do run: o nível de risco e seus motivos vêm da classificação, as verificações que rodaram vêm da evidência, e o resumo vem da última rodada de revisão. O texto de Risco e de Como reverter vem do plano.
- O schema do plano ganha os textos opcionais `risk_notes` e `revert` no nível de cima (não `risk`, que já é o enum de risco por tarefa em `schemas/plan.schema.json`). `plan set` recusa o plano quando falta um dos dois e o maior entre a classificação do run no `run start` e o `risk` de qualquer tarefa é médio ou alto. Essa regra fica em código, então um run de alto risco não chega a `run finish` sem um caminho de reversão. Como no artigo, o agente escreve o texto e a pessoa que pediu a mudança aprova o PR.

### D. Uma rodada de revisão

`wev review run` começa uma rodada no run ativo. Ela revisa o **diff do run**: da base do run até a árvore de trabalho atual. Hoje o estado do run não tem uma base estável. `RepoSnapshot.head` é gravado no `run start` (`core/run_start.py`) e sobrescrito pelo `run resume` (`core/orchestrator.py`). Por isso o `run start` ganha um campo `base`, escrito uma vez e nunca sobrescrito. Ele guarda a árvore como estava no início do run (o `HEAD` mais as mudanças não commitadas e não rastreadas), numa forma que um diff posterior consegue usar (a mesma escolha das árvores das rodadas em "O que fica para quem constrói"). Assim, mudanças que já estavam sem commit no início do run fazem parte da base e não são linhas do autor. Um run iniciado antes desta mudança não tem `base`, e `review run` o recusa com uma mensagem clara.

A rodada:

1. Recusa quando `review.depth` é `off`, quando há uma tarefa rodando, ou quando `review.max_rounds` rodadas já rodaram (ver E).
2. Roda `review.finders` caçadores em paralelo pela porta do executor de agente, usando o especialista revisor indicado por `review.agent` (ver G) com suas lições ativas. Hoje a porta sempre concede `UNATTENDED_TOOLS` (Read, Edit, Write, Glob, Grep, Bash) no `run_agent` e nenhuma ferramenta no `ask` (`adapters/claude_code/agent_runner.py`). Por isso `run_agent` ganha um argumento de conjunto de ferramentas, cujo padrão é o conjunto de hoje, e as rodadas passam o conjunto só de leitura. Cada caçador recebe o diff, o objetivo e o plano do run como intenção declarada, o `REVIEW.md`, o `CLAUDE.md`, e as ferramentas só de leitura Read, Glob e Grep, sem Bash. Ele precisa responder com achados em JSON: arquivo, linha, título, explicação, marca proposta (`important` ou `nit`) e se o bug é de uma classe a corrigir em todo lugar. Qualquer outra coisa é descartada.
3. Junta duplicados (mesmo arquivo e linhas próximas com a mesma afirmação). Descarta achados sem prova, em caminhos ignorados, ou já publicados numa rodada anterior deste run.
4. Roda `review.verifiers` verificadores em paralelo. Cada um vê de uma vez todos os achados que sobraram, cercados como dados não confiáveis, e vota em cada um: real ou não, Importante ou Nit, e se é só estilo, diagnóstico ou limpeza. Um achado fica quando pelo menos `review.quorum` verificadores o consideram real. Achados votados como só estilo, diagnóstico ou limpeza são descartados, como no artigo. A marca é a da maioria.
5. Marca em código um achado mantido como Preexistente quando a linha dele não está entre as linhas que o diff do run (da base até a árvore atual) adicionou ou mudou. É sempre o diff do run, mesmo numa rodada só do diff. Do contrário, o código do próprio autor da rodada 1 pareceria Preexistente na rodada 3 e nunca poderia bloquear. Isso evita que bugs antigos pareçam culpa do autor, e achados Preexistentes nunca bloqueiam.
6. Grava a rodada no estado do run: número, base, a árvore revisada (impressão mais o que E precisa para comparar depois), os achados com seus votos, as execuções de harness usadas, e um evento de auditoria.

Os votos são valores `Verdict`. `LocalPolicyProvider.resolve_conflict` hoje só aceita por unanimidade. Ele ganha um argumento de quórum, e o padrão continua unânime para que o comportamento de quem já o chama não mude. Isso inclui o protocolo `DecisionProvider` (`decisions/__init__.py`) e o adaptador JEV que delega a ele (`decisions/jev.py`). A contagem da rodada o chama com `review.quorum`. `evaluate_result` fica como está. Ele não é um revisor.

Presets de profundidade, seguindo o Quick, Standard e Deep do artigo: `quick` usa 1 caçador e 1 verificador (quórum 1), `standard` 3 e 3 (quórum 2), `deep` 5 e 5 (quórum 3). As chaves explícitas sobrepõem o preset. Um run classificado como de alto risco usa pelo menos `standard` sempre que a revisão está ligada.

Uma rodada pode demorar mais do que a chamada de Bash de um agente pode durar (o Claude Code para uma depois de 2 minutos por padrão). Por isso a skill manda o agente iniciar `wev review run` em segundo plano, e `wev review show` imprime a última rodada. Cada rodada inicia no máximo `review.max_runs_per_round` execuções de harness; o comando recusa antes de começar quando a profundidade pede mais, e imprime o número planejado no stderr como `specialists score` faz.

Quem pode começar uma rodada: o agente pode, sem uma pessoa. A configuração é o consentimento. `review.depth` tem padrão `off` no produto, o run fixa sua configuração, e `--config` já pede confirmação. Isso difere de `specialists score`, que continua só para pessoas. Uma pontuação muda o que todo run seguinte vê, e uma rodada de revisão só relata sobre este run. O wev-skills põe `review.depth: standard` no próprio `wev.config.json`.

### E. Resolução, teto de rodadas e revisão só do diff

- Cada achado está `open`, `fixed` ou `dismissed`. "Não ser encontrado de novo" não prova nada, porque os caçadores são instruídos a não repetir achados. Por isso cada rodada depois da primeira também recheca os achados abertos cujo arquivo e linhas mudaram desde a rodada que os publicou. Os verificadores veem cada um desses achados ao lado do código atual e votam se ele ainda vale. Um achado fica `fixed` quando o quórum vota que ele não vale mais. Um achado aberto cujas linhas não mudaram continua aberto. O agente marca achados Nit e Preexistente com `wev review resolve <achado> --as wrong|intentional|does-not-matter --reason <texto>`. Descartar um achado Importante é um comando de operador humano, `wev review dismiss <achado> --as ... --reason ...`, com o mesmo atrito de terminal e palavra digitada de `approval grant`. Ele entra na lista do `CLAUDE.md`, na lista de perguntas do hook e na lista de negação dos outros harnesses.
- `run finish` recusa enquanto houver um achado Importante aberto, ou enquanto a árvore da última rodada não for a árvore atual e `review.depth` não for `off`. Nesse caso o agente roda outra rodada.
- As rodadas depois das primeiras `review.full_rounds` (padrão 2) revisam só o diff entre a árvore da rodada anterior e a atual. Os achados já publicados vão aos caçadores como "não repita", e o motor descarta repetições exatas de qualquer forma.
- Depois de `review.max_rounds` (padrão 3, como no artigo) o motor recusa outra rodada. Ele registra um disparo de guarda de um tipo novo, `review_rounds`, com a mensagem de que a abordagem deve ser reconsiderada. Como todo disparo de guarda, ele é liberado por `guard acknowledge` de uma pessoa. Cada liberação permite exatamente mais uma rodada, então uma correção feita depois do teto precisa de uma liberação para ser revisada. Esse é o único ponto em que o dono é consultado por desenho, e os números do artigo dizem que deve ser raro (média de 1,32 revisões até passar, 1,5% com cinco ou mais rodadas).

### F. Casos de revisão

O schema de caso ganha `kind`: `build` (o padrão, os casos de hoje) ou `review`. Um caso de revisão tem:

- `base_commit` e `head_commit`: o diff em revisão, por exemplo o commit que introduziu um bug depois revertido ou corrigido.
- `objective`: a intenção declarada daquela mudança, como o PR a descreveu.
- `expect`: uma lista de `{file, lines: [primeira, última]}` onde está um bug real. Uma lista vazia marca uma mudança sabidamente limpa.
- `id`, `title`, `source`, `ref` e `agents`, como nos casos de build. `check` e `files` não se aplicam.

Uma amostra passa quando, num caso com bug, pelo menos um achado Importante mantido cai num arquivo e num intervalo de linhas esperados, e quando, num caso limpo, nenhum achado Importante é mantido. A precisão (alarmes falsos) é medida pelos casos limpos, como o artigo mede o ruído em PRs sabidamente limpos. A fixação do conjunto de casos, as amostras e as contagens de acertos são as do projeto 1.

Os primeiros casos de revisão: os commits que introduziram os três bugs do teste ponta a ponta de 2026-10-22 (a sonda de saúde de 1 MiB, o symlink `..` confinado na checagem do tarball, o exec path do `install.sh`), como casos com bug cujo `expect` aponta para as linhas que os commits de correção `06fc92c` e `e3d7b2b` mudaram. Dois ou três commits do wev-skills já mergeados, que nenhuma correção posterior tocou, servem como casos limpos. Quem constrói escolhe os commits e registra por que cada um é limpo. `wev cases validate --at-base` ganha a checagem de revisão: o diff `base_commit..head_commit` precisa aplicar, e todo intervalo de `expect` precisa estar em linhas que o diff toca.

### G. A nota do revisor

O revisor é um especialista comum do projeto, `wev-reviewer` no wev-skills, indicado pela chave de configuração `review.agent`. O schema de agente não tem campo de papel, e nenhum é criado. `wev specialists score <agente>` roda os casos que se aplicam àquele agente (pela lista `agents` de cada caso), e cada caso é avaliado pelo seu `kind`. Um caso de build roda o agente e o `check` dele. Um caso de revisão roda uma rodada de revisão no `review.depth` da configuração fixada, com o agente como revisor. O registro da nota guarda essa profundidade, e notas em profundidades diferentes nunca são comparadas. Cada execução de harness de uma rodada (cada caçador e cada verificador) conta para `specialists.score_max_runs`. O número planejado impresso antes da execução as inclui, e o dono sobe o teto quando uma configuração `deep` precisar. Todo o resto é a maquinaria do projeto 2: linha de base, com e sem cada lição proposta, lições escritas pelo modelo a partir dos casos que falharam, a catraca `improves()`, `.wev/scores.jsonl` e a auditoria antes da escrita. Assim as lições do revisor entram e saem pela nota, sem regra nova.

Uma mudança no `REVIEW.md` ou na spec do revisor é uma mudança no revisor, então não pode baixar a nota:

- `wev specialists score wev-reviewer --compare <rev>` avalia o revisor como ele está em `<rev>` (a spec e o `REVIEW.md` lidos do git) e como está na árvore de trabalho, no mesmo conjunto fixado de casos. Ele grava as duas contagens com a impressão da árvore em `.wev/scores.jsonl`.
- `run finish` recusa um run cujo diff toca o `REVIEW.md` ou a spec do revisor, a menos que `.wev/scores.jsonl` tenha uma comparação para a árvore atual em que `improves(baseline, current)` é verdadeiro. A pontuação continua só para pessoas, então esse é o único outro caso em que uma pessoa age. Ele só acontece quando o próprio revisor muda.

### H. Medir o ruído

Cada resolução grava o seu desfecho (`fixed`, `wrong`, `intentional`, `does-not-matter`) no estado do run e em `.wev/reviews.jsonl` (local, como `.wev/scores.jsonl`). `wev review stats` imprime a tendência por profundidade: achados por rodada, a parte de cada desfecho, rodadas por run, e runs que passaram depois de uma rodada. São as medidas do artigo. Elas mostram ao dono se o revisor está ficando mais quieto sem deixar passar bugs. Um achado que uma pessoa descartou como `wrong` é impresso como candidato a caso limpo. Transformá-lo em caso continua sendo uma mudança commitada.

### I. Configuração e textos que precisam mudar

- Uma seção nova `review` no schema de configuração, com testes e docs nas duas línguas: `agent` (o especialista revisor), `depth` (`off`, `quick`, `standard`, `deep`; padrão `off`), `finders`, `verifiers`, `quorum`, `max_rounds` (3), `full_rounds` (2), `max_runs_per_round` (padrão 12, o suficiente para `deep` com uma folga de 2), `timeout_seconds` por execução de harness.
- Textos a atualizar nas duas línguas na mesma mudança: `SECURITY.md` (rodadas de revisão são execuções `claude -p` sem supervisão e com ferramentas só de leitura; achados e votos são texto não confiável; `review dismiss` é só para humanos; aprovações de comandos com efeito externo ficam presas ao `HEAD` e à árvore), `CLAUDE.md` (a lista de operador humano ganha `review dismiss`), `docs/guides/orchestration.md`, o novo `docs/guides/review.md`, `docs/guides/evaluation.md` (casos de revisão), `docs/guides/specialists.md` (o revisor e o `--compare`), `docs/guides/configuration-and-providers.md`, `docs/glossary.md`, `skills/wev-orchestrate/SKILL.md` (quando iniciar uma rodada, em segundo plano, e como resolver achados), e as chaves de locale.

## Testes

- Unitários, sem rede e sem modelo: a impressão nas revisões (uma revisão deixa de valer depois de uma edição); aprovações de comandos com efeito externo ficam vencidas com um commit novo ou uma mudança na árvore, enquanto aprovações comuns mantêm o vínculo; leitura do `REVIEW.md` nas duas línguas, teto de nits, globs de Ignorar, arquivo ou linha sem prova; o resumo que começa pela contagem, incluindo "Nada a corrigir"; uma rodada com respostas falsas de caçadores e verificadores (JSON malformado, um comando de operador num achado, quórum atingido e não atingido, um voto de só estilo, a marca Preexistente vinda do diff, repetições descartadas); `resolve_conflict` com quórum, e a unanimidade inalterada por padrão; o teto e o disparo de guarda `review_rounds`; rodadas só do diff; `run finish` recusando um achado Importante aberto, uma rodada vencida, ou um revisor mudado sem uma comparação que melhora; `plan set` recusando um plano de risco médio ou alto sem `risk_notes` e `revert`; o schema de caso de revisão e a regra de acerto para casos com bug e limpos; o teto de execuções. Cada teste é quebrado de propósito uma vez para vê-lo falhar.
- Os primeiros casos de revisão: um teste unitário confirma, só com os arquivos commitados, que cada intervalo de `expect` está dentro das linhas que o diff toca. Aplicar `base_commit..head_commit` exige histórico, então é uma checagem local, `wev cases validate --at-base`.
- Uma rodada real e uma nota real do revisor com `claude -p` são rodadas pelo dono, gastam tokens, e são relatadas como não testadas até rodarem.

## Restrições

- Só biblioteca padrão, Python 3.14 ou mais novo, mypy strict, dataclasses congeladas, funções com menos de 50 linhas, arquivos com menos de 400.
- Todo texto para o usuário passa pelo i18n com as mesmas chaves em `en` e `pt-BR`. Os docs mudam nas duas línguas no mesmo commit.
- O núcleo nunca importa um adaptador. As rodadas usam a porta do executor de agente do PR #18.
- `make test` nunca chama um modelo, a rede ou um harness real.
- O texto de segurança segue o `SECURITY.md`: são proteções para um agente falível, não uma fronteira contra um agente adversário na mesma conta. As ferramentas de arquivo do próprio agente ainda podem editar o estado do run, inclusive os achados.
- Nunca fazer push, publicar ou lançar versão sem a autorização explícita do dono.

## O que fica para quem constrói

- Nomes e organização dos módulos, dentro das responsabilidades de pacote do `CLAUDE.md` (provavelmente um pacote `review/` ou módulos sob `governance/` e `evaluation/`).
- Os modelos de prompt de caçadores e verificadores, a regra de juntar duplicados ("linhas próximas" e "mesma afirmação"), e como uma rodada guarda a sua árvore para o diff seguinte (um objeto tree do git escrito com um índice temporário, ou uma cópia sob o diretório do run usando `evaluation/snapshot.py`).
- Qual marca do classificador conta como "efeito externo" para prender aprovações, desde que `git push`, `gh pr merge` e as entradas `publish` estejam cobertos e comandos locais comuns não.
- O formato da saída de `wev review show` e `wev review stats`.
- Quais commits mergeados servem como os primeiros casos limpos, com o motivo registrado em cada caso.

## Escolhas que fiz sem o dono

- As revisões rodam localmente sobre o diff do run. Nada é publicado no GitHub.
- A revisão de tarefa continua por tarefa e roda ao lado das rodadas. Ela fica presa à última verificação da própria tarefa, não à árvore inteira.
- O run ganha uma `base` fixa: a árvore no início do run, incluindo as mudanças sem commit, que não contam como do autor.
- Preexistente é sempre medido contra o diff do run, inclusive nas rodadas só do diff.
- Uma correção é provada por uma rechecagem dos verificadores nas linhas mudadas, não pela ausência do achado. Cada `guard acknowledge` depois do teto permite mais uma rodada.
- Um revisor é avaliado no `review.depth` fixado, e cada execução de caçador e de verificador conta para o teto da nota.
- O revisor é indicado por `review.agent`. Nenhum campo de papel é criado no schema de agente.
- O motor roda a revisão pelo executor de agente, então o registro é evidência do motor, não um subagente autodeclarado.
- `review.depth` tem padrão `off` no produto e é `standard` na configuração do próprio wev-skills. O agente pode começar uma rodada sem uma pessoa, porque a configuração é o consentimento.
- Um run de alto risco revisa pelo menos em `standard` quando a revisão está ligada.
- Caçadores e verificadores recebem só Read, Glob e Grep, sem Bash.
- O quórum é maioria nos presets, e `resolve_conflict` mantém a unanimidade como padrão.
- Preexistente é decidido em código pelas linhas que o diff toca, não pelo modelo, e nunca bloqueia.
- Só um achado Importante bloqueia `run finish`, e só uma pessoa pode descartá-lo. O agente pode resolver sozinho Nits e achados Preexistentes.
- No máximo 3 rodadas, as 2 primeiras completas, depois só do diff. O teto dispara uma guarda que uma pessoa libera.
- Aprovações ficam presas ao `HEAD` e à árvore só para comandos com efeito externo.
- Planos de risco alto e médio precisam declarar `risk_notes` e `revert`.
- O revisor é um especialista do projeto avaliado com a maquinaria do projeto 2 em casos `kind: review`. Uma mudança no `REVIEW.md` ou na spec do revisor precisa de uma comparação que melhora antes do `run finish`.
- Os primeiros casos de revisão são os commits que introduziram os três bugs de 2026-10-22, mais dois ou três commits limpos.
- Um `REVIEW.md` na raiz, com títulos em inglês ou português, e teto padrão de 3 nits.
- Os desfechos de ruído usam os quatro rótulos do artigo e ficam locais em `.wev/reviews.jsonl`.
