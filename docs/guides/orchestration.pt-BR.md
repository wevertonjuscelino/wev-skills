# Guia de orquestração

Versão em inglês: [orchestration.md](orchestration.md).

Este guia descreve como uma tarefa de vários passos percorre o motor, comando a comando. A skill `wev-orchestrate` instrui o Claude Code a fazer o mesmo quando `wev jev status` informa `orchestration` `wev`, e a usar o fluxo do próprio harness quando informa `harness`; você também pode conduzir cada passo à mão. Toda saída abaixo foi produzida em 2026-10-13 executando a CLI real em um repositório git temporário (um `Makefile` com um alvo `test`). As saídas estão abreviadas onde indicado; os caminhos de logs foram encurtados para `.wev/...`.

Neste guia, `wev` representa `"$WEV_HOME/bin/wev"` ou um symlink para ele (veja o [guia de instalação](installation.pt-BR.md)).

## O que o motor é, em um parágrafo

O motor é uma proteção para um agente falível e um registro de decisões. Não é uma fronteira de segurança contra um agente adversarial na mesma conta de usuário. O portão humano é o prompt de permissão do Claude Code, alcançado pelo hook do plugin; sem os hooks do plugin, as aprovações são registros. Leia o [guia de segurança](security.pt-BR.md) antes de confiar em qualquer controle descrito abaixo.

## O fluxo

`REQUEST → DISCOVER → CLASSIFY → PLAN → DECIDE → EXECUTE → VERIFY → REVIEW → DELIVER`

O motor registra a fase e recusa passos que pulem uma. Você avança com comandos; o modelo raciocina e edita. O que cada fase faz está na [arquitetura](../architecture/architecture.pt-BR.md), seção 2.

Os comandos são cobertos por testes unitários e pelo teste de integração do fluxo da CLI. Quão bem um modelo segue a skill `wev-orchestrate` em uma sessão real do Claude Code não foi observado.

## Execuções, configuração e a execução ativa

- Um repositório tem **uma execução ativa** por vez. `wev run start` é recusado (`run_active`, saída 5) até que `wev run finish` encerre a atual. O modo de uma execução nunca muda.
- Comandos sem `--run` usam a execução ativa. Passe `--run ID` apenas para ler uma execução antiga.
- O diretório de estado (`.wev/` por padrão) é resolvido na raiz do repositório, qualquer que seja o diretório em que você rode. Ele tem o próprio `.gitignore`, que ignora tudo o que há nele, então nada precisa ser acrescentado ao do projeto.
- **A configuração é fixada.** Em `run start` o motor a resolve (`--config CAMINHO`, senão `<raiz do repositório>/wev.config.json`, senão os padrões) e a grava na execução. Todo comando posterior dessa execução usa a gravada, e um `--config` diferente é recusado (`config_pinned`). Para mudar a configuração, encerre a execução e comece outra. Veja o [guia de configuração](configuration-and-providers.pt-BR.md).
- Toda resposta traz `next_step` (a primeira coisa a fazer) e `next_steps` (uma lista de tudo o que pode ser feito agora). Onde só uma pessoa pode agir, o passo é uma instrução de parar e perguntar, nunca um comando que um agente pudesse rodar para se aprovar.

## Modos

| Modo | Efeito |
|---|---|
| `plan` | Só investigar. O motor recusa comandos que não sejam somente leitura (`exec` sai com 3 e `permission_denied`), recusa `task next` (`plan_mode`, saída 3) e não inicia nada remoto. |
| `execute` | Agir dentro das permissões concedidas. Permissão para agir não é autorização geral: comandos arriscados ainda exigem aprovação. Mutação comum (`mv`, `sed -i`, redirecionamentos, rodar um script) é como o trabalho se faz e não é barrada. |
| `auto` (padrão) | O motor escolhe o fluxo a partir da classificação, então uma mudança de uma linha não ganha cerimônia. |
| resume (retomar) | Não é um modo em que se inicia uma execução. `wev run resume` recarrega uma execução existente e a compara com o repositório real; a execução mantém o modo com que começou. |

## Os comandos, em ordem

### 1. Iniciar: pedido, descoberta, classificação

```text
$ wev run start --objective "Add a greeting file" --files 1 --run-id demo-1
```

A resposta (abreviada) traz o id da execução, a classificação, a estratégia, a configuração fixada e as verificações que o motor descobriu lendo `Makefile`, `package.json`, `pyproject.toml`, `Cargo.toml` e `go.mod` como dados (nada é executado). O texto descoberto veio do repositório, então volta higienizado e cercado como dado não confiável:

```json
{
  "run_id": "demo-1",
  "mode": "auto",
  "classification": { "complexity": "trivial", "risk": "low", "uncertainty": 0.0, "parallelizable": false, "source": "local-policy" },
  "strategy": { "flow": "direct", "needs_plan": false, "needs_independent_review": false, "needs_approval": false, "max_parallel": 1, "max_attempts": 3 },
  "discovery": { "untrusted": true, "source": "repository discovery", "count": 1,
                 "text": "<<<WEV_UNTRUSTED_DATA id=... source=\"repository discovery\">>>\n...\nmake test  [Makefile, test]\n<<<END_WEV_UNTRUSTED_DATA id=...>>>" },
  "config": { "source": "defaults", "digest": "b382..." },
  "next_step": "wev task next --run demo-1",
  "next_steps": ["wev task next --run demo-1"]
}
```

Os sinais são sua estimativa, não uma medição; sinais errados produzem uma estratégia errada. As flags são `--files`, `--unknowns`, `--subtasks`, `--remote`, `--production`, `--destructive`, `--external`, `--no-tests` e `--irreversible`, ou `--signals-file`. Em caso de dúvida, superestime. O motor também lê o texto do objetivo: palavras em inglês e em português que nomeiam produção, operações destrutivas, deploys, sistemas remotos, credenciais ou mudanças de esquema elevam o sinal correspondente (um piso sob as suas flags, com falsos positivos e falhas; nunca reduz nada). Para ver uma decisão sem iniciar uma execução, use `wev classify`, `wev strategy` ou `wev route-model` com as mesmas flags. `--run-id` é opcional; sem ele o motor gera um, como `20261013T144156Z-6db122`.

O fluxo decide o caminho:

| Fluxo | Significado |
|---|---|
| `direct` | Risco baixo e pequeno. O motor sintetiza uma tarefa, `task-1`, com a verificação descoberta como sua verificação. Quando nenhuma verificação foi descoberta, um plano precisa fornecê-las (a resposta avisa). |
| `planned` | Escreva um plano primeiro. A revisão independente costuma ser exigida. |
| `gated` | Risco alto. Um humano aprova antes de o trabalho começar. |

Com 8 arquivos e 1 incógnita, o mesmo repositório dá risco `medium` ("about 8 files are touched (more than 5)"), fluxo `planned`, `needs_plan` verdadeiro, `needs_independent_review` verdadeiro e `next_step: wev plan set --file plan.json --run demo-2`.

### 2. Planejar (fluxos planned e gated)

Escreva um arquivo de plano (formato em `references/plan-format.md` da skill; um exemplo completo é `examples/plan.example.json`) e armazene-o:

```text
$ wev plan set --file plan.json
```

As `checks` de um plano são strings de comando ou objetos que amarram um comando aos critérios que ele prova, por índice começando em zero ou pelo texto exato:

```json
{ "id": "greet", "title": "Add greeting", "objective": "Create greeting.txt containing hello",
  "files": ["greeting.txt"],
  "acceptance_criteria": ["greeting.txt exists", "greeting.txt contains hello"],
  "checks": [ { "command": "test -f greeting.txt", "criteria": [0] },
              { "command": "grep -q hello greeting.txt", "criteria": ["greeting.txt contains hello"] } ] }
```

Uma string de comando simples sustenta todos os critérios e é rotulada sem amarração: conta, mas como evidência mais fraca, e o relatório e os avisos dizem isso. Amarre as verificações aos critérios sempre que puder. O motor valida o plano, atribui um agente e um modelo a cada tarefa e registra ambos. O `risk` próprio de uma tarefa só pode elevar o risco da execução, nunca reduzi-lo, e o roteamento de agentes é uma heurística: leia o `agent_id` de cada contrato e decida se serve (o campo `agent_hint` do plano indica um). Marque uma tarefa com `read_only: true` quando ela não deve mudar nada. O `wev plan set` imprime `warnings`: uma verificação que vai precisar de aprovação na execução (por exemplo código inline de interpretador como `python3 -c ...`; use um arquivo de script ou um teste nomeado), uma verificação que será recusada e um caminho em `files` de uma tarefa ou nos argumentos de uma verificação que o git ignora (a impressão digital da árvore não cobre arquivos ignorados, então uma mudança neles não é vista como trabalho). Depois que uma tarefa foi iniciada alguma vez, o `plan set` recusa mudar seus critérios de aceitação, verificações, arquivos, risco ou a marca `read_only`, a menos que receba `--amend --reason <texto>`. Uma alteração é registrada como decisão e como evento de auditoria `plan.amended`, zera a verificação daquela tarefa e aparece no relatório em "Plan amendments", com antes e depois. O motor não julga se os critérios novos são mais fracos, e quem pode rodar `plan set` pode alterar. Acrescentar tarefas e mudar tarefas nunca iniciadas continua livre. `wev plan show` imprime o plano armazenado. No modo `plan`, é aqui que você para e mostra o plano à pessoa.

### 3. Decidir e executar: um contrato, um agente

```text
$ wev task next
```

`task next` devolve os contratos das tarefas que podem começar agora: objetivo, contexto, escopo, exclusões, restrições, critérios de aceitação, verificações (com `check_links` e `required_checks`), formato de resposta, permissões, `agent_id`, `model`, `risk` e, da spec do agente, `max_attempts`, `timeout_seconds`, `budget_units`, `may_mutate`, `may_use_remote`, `success_criteria`, `stop_conditions` e `escalation`. O motor aplica `required_checks`, o orçamento, as tentativas, o tempo limite, `may_mutate` e os modos e o risco máximo do agente; `success_criteria`, `stop_conditions`, `escalation` e `output_format` são instruções que o agente recebe e que nada verifica. Oferece no máximo `max_parallel` tarefas, nenhuma com dependências não verificadas, e nunca duas cujos `files` se sobreponham (uma tarefa sem `files` roda sozinha). `deferred` lista as demais com o motivo. Iniciar uma tarefa que não foi oferecida é recusado (`task_not_startable`, saída 2).

Inicie a tarefa, entregue o contrato a exatamente um agente e faça os comandos passarem pelo motor, para que sejam verificados quanto a permissões, registrados e vigiados contra laços:

```text
$ wev task start task-1
$ wev exec -- touch greeting.txt
```

`task start` conta como uma **tentativa** (todo início conta) e **roda as verificações da tarefa uma vez como linha de base** (`harness.baseline_checks`, ligado por padrão). A resposta mostra quais verificações já passavam antes de qualquer trabalho:

```json
"baseline": { "taken": true, "passed": ["git diff --stat"], "failed": ["make test"], "skipped": [] }
```

Em uma execução no modo execute, um comando age por uma tarefa que está `RUNNING`. `--task` precisa nomear uma tarefa em andamento (um id pendente, concluído ou desconhecido é recusado e o erro nomeia as tarefas em andamento); sem `--task` usa-se a única tarefa em andamento e a saída avisa (`task_implied: true` e um `task_note`); sem nenhuma tarefa em andamento, ou com várias em andamento e sem `--task`, só comandos de somente leitura são aceitos. Assim, `may_mutate: false` e o risco da tarefa não dependem de quem chama nomear a tarefa. Com duas tarefas em andamento, quem chama ainda escolhe para qual delas o comando vale; o motor não sabe dizer qual agente está digitando. O modo plan não muda (só comandos de somente leitura). Um agente com `may_mutate: false` pode rodar por `wev exec` comandos de somente leitura, as verificações declaradas da própria tarefa e os comandos de verificação descobertos no repositório em `run start` (por exemplo `make test`, `make lint`), por correspondência exata do argv; todo o resto é recusado com `agent_read_only`. Esses comandos ainda passam pela política, então um que exige aprovação continua exigindo. Comandos `wev exec` de somente leitura não contam para a janela de ausência de progresso (um comando idêntico repetido continua sendo um laço), e a leitura no modo plan não dispara `no_progress`.

Opções de `wev exec`: `--task`, `--timeout SEGUNDOS`, `--polling` (o comando apenas consulta um processo longo; só vale para uma tarefa em execução que já rodou um comando, e vale um teto de `limits.max_polling_commands` consultas consecutivas) e `--flaky` (um teste sabidamente instável). O motor executa o vetor de argumentos diretamente, nunca por um shell, procura o programa somente em `permissions.exec_path` (nunca no `$PATH`), registra o caminho resolvido e devolve a cauda da saída redigida e cercada como dado não confiável (`"untrusted_output": true`). O processo filho herda o seu ambiente.

O motor só governa por completo o que passa por `exec`. Com o plugin instalado, um hook também verifica comandos Bash comuns e manda para o seu prompt de permissão os sensíveis que consegue ler (veja o [guia de segurança](security.pt-BR.md)); ele não enxerga o interior de um arquivo de script nem de um programa. Edições feitas com as ferramentas de arquivo do próprio Claude Code não são verificadas pelo motor; o `scope` e as `exclusions` do contrato e o passo de verificação é que as pegam.

Para ver se um comando seria permitido sem executá-lo:

```text
$ wev check-command -- git push origin main     # saída 4
  "decision": {"outcome": "needs_approval", "reason": "Approval needed: the command pushes to a remote repository."}
```

`check-command` sai com 0 (permitir), 3 (negar) ou 4 (precisa de aprovação). Não registra pedido.

### 4. Verificar

```text
$ wev task check task-1
```

Isso roda as verificações da tarefa e armazena a evidência. Se você rodou logo depois de `task start`, com o repositório como estava, a verificação do Makefile falha (como deve: o arquivo ainda não existe) e o critério fica `unmet`. Depois do trabalho:

```json
{ "task_id": "task-1", "all_met": true,
  "report": { "criteria": [ { "criterion": "The objective is achieved and checked: Add a greeting file", "status": "met", "support": "untied" } ],
              "summary": "1 of 1 acceptance criteria met, 0 unmet, 0 unverified; 0 checks not run." },
  "baseline": "taken", "tree_changed": true, "warnings": [],
  "next_step": "wev task record task-1 --status verified --summary <text> --run demo-1" }
```

**O que conta como evidência.** `verified` é estrito, e o rigor é o ponto:

- Uma verificação que **já passava na linha de base, em uma árvore que não mudou desde que a tarefa começou**, não mostra nada sobre o trabalho. A resposta real quando uma tarefa é iniciada em um repositório onde `make test` já passa e nada é alterado:

  ```text
  all_met: false
  warnings: ["Every passing check had already passed before any work and no file changed since the task started."]
  criterion reason: "The checks already passed before any work on this task and no file changed since it started, so they do not show the work was done."
  ```

  Registrar `verified` então falha com `verification_required` (saída 2). Faça o trabalho, ou escreva uma verificação que falhe até o trabalho existir. Uma tarefa `read_only` é isenta dessa regra.
- Uma **verificação sem efeito** (`true`, `echo`, `printf`, `test` sobre constantes, `sh -c 'exit 0'` e similares) não conta como evidência. A lista é um piso: uma verificação vazia mais esperta não é pega, e o motor não julga se as verificações bastam. Isso é trabalho de quem escreve o plano.
- Uma verificação **sem amarração** (uma string simples em um plano, ou a verificação padrão descoberta) sustenta todos os critérios, mas é rotulada no relatório como evidência mais fraca. Uma verificação **amarrada** sustenta apenas os seus critérios.
- A **evidência manual** (`wev task record ... --evidence-file F`, um arquivo JSON com uma lista `evidence` em que cada item nomeia seu critério em `kind` e traz um `ref`) só conta quando o `ref` é um arquivo existente sob o diretório de logs da execução, sob o diretório de evidências da execução (`<diretório de estado>/runs/<id>/evidence/`) ou um dos arquivos que a tarefa lista no plano; qualquer outro arquivo existente é recusado e o erro diz isso. Para mostrar um arquivo ou uma saída, rode-o por `wev exec` e referencie o log. É uma afirmação do agente e o relatório a rotula assim.
- A impressão digital da árvore de trabalho é **recalculada em `task record`**. Se arquivos mudaram depois do `task check` aprovado, `verified` é recusado (`tree_changed`); verifique de novo.
- Uma tarefa verificada que não é `read_only` e não mudou nenhum arquivo desde que começou não torna a execução `complete`.

Depois registre o resultado que o agente relatou:

```text
$ wev task record task-1 --status verified --summary "greeting file added" --changed-file greeting.txt
```

Os outros status são `partial`, `blocked`, `failed` e `not_executed`; use-os quando forem a verdade e acrescente `--blocker` para trabalho bloqueado. `failed` exige uma tarefa em execução. `verified` sem evidência é recusado:

```text
$ wev task record parser --status verified --summary "too early"          # saída 2
{"error": {"code": "verification_required", "message": "Task parser cannot be recorded as verified: 1 acceptance criterion(s) have no passing check made after the task last started and no tested evidence.", "details": {"next_step": "wev task check parser --run demo-2"}}}
```

**Tentativas e escalonamento.** Todo `task start` conta. Uma falha registra uma tentativa com uma assinatura de erro. O escalonamento para um tier de modelo mais alto dispara na metade das tentativas (arredondada para cima) ou quando a mesma assinatura de erro se repete, o que vier primeiro; `next_model` na resposta nomeia o modelo da próxima tentativa. Quando as tentativas se esgotam, a tarefa vira `BLOCKED` e o próximo passo manda pedir a uma pessoa. **Só uma pessoa a reabre**, no próprio terminal (veja "Passos que só uma pessoa dá").

### 5. Revisar

Quando a estratégia define `needs_independent_review`, `task record` responde com um comando `task review` como `next_step`. O revisor precisa ser um agente conhecido diferente do que executou a tarefa:

```text
$ wev task review parser --reviewer senior-engineer --verdict accept --summary "self review"      # saída 3
{"error": {"code": "self_review", "message": "Agent senior-engineer executed task parser and cannot review it."}}

$ wev task review parser --reviewer code-reviewer --verdict accept --summary "read the diff and the check output"
{"task_id": "parser", "reviewer": "code-reviewer", "reviewer_identity": "self-declared", "verdict": "accept", "task_status": "verified"}
```

Um `reject` reabre a tarefa com o seu resumo como contexto. O motor registra o nome de revisor que quem chamou informou (`self-declared`); não consegue saber se aquele agente leu mesmo o diff, e vários agentes rodando no mesmo modelo não são estatisticamente independentes.

### 6. Entregar e encerrar

```text
$ wev run report --format md
```

Relatório real da primeira execução (abreviado). O corpo é cercado como dado, porque repete texto que um agente escreveu:

```markdown
# Delivery report: run demo-1

<<<WEV_UNTRUSTED_DATA id=... source="wev run record">>>
- **Objective:** Add a greeting file
- **Overall status:** complete
- **Classification:** risk low, complexity trivial
- **Strategy:** direct flow, up to 1 in parallel, up to 3 attempts

### task-1: Add a greeting file

- **Status:** verified
- **Evidence:** tested
- **Attempts:** 1

| Acceptance criterion | Result | Evidence | What stands behind it |
|---|---|---|---|
| The objective is achieved and checked: Add a greeting file | met | tested | Met by a check not tied to this criterion: a generic check passed, which is weaker evidence. |
...
## Guard trips
None.
<<<END_WEV_UNTRUSTED_DATA id=...>>>
```

O status geral é `complete` somente quando toda tarefa está verificada (e, a menos que seja `read_only`, mudou algo) e toda revisão exigida foi aceita; caso contrário é `incomplete` ou `blocked`, com uma seção "Why the run is not complete". Os disparos da guarda e seus reconhecimentos ficam no relatório. O relatório é recalculado quando você o pede (e no `run finish`), não continuamente: a árvore é comparada com a vista no último registro `verified`, e se ela difere e nenhuma tarefa está em andamento, toda tarefa verificada cujas verificações não passaram na árvore atual é reportada como "verified, then changed" e o estado é `incomplete` até o `wev task check <id>` passar de novo (o `next_step` diz isso). Uma mudança feita e desfeita entre dois relatórios não é vista; enquanto uma tarefa está em andamento, as mudanças contam como trabalho dela. Apresente o relatório como está: não melhore um rótulo. Quando a seleção de ferramentas está ligada, o relatório tem uma seção com as ferramentas oferecidas e selecionadas e estimativas aproximadas de tokens de definição.

| Rótulo no relatório | Significado |
|---|---|
| `tested` | Um comando rodou, registrou código de saída e log, e a verificação passou |
| `untested` | Sem evidência de verificação aprovada |
| `mocked` | Evidência de um substituto falso ou simulado |
| `documented_only` | Descrito, não executado |
| `blocked` | Não foi possível executar ou verificar |

Eles correspondem aos cinco rótulos do projeto (implementado e testado, implementado mas não testado, simulado com mocks, apenas documentado, bloqueado). `--lang pt-BR` renderiza o relatório em Markdown em português.

Por fim, encerre a execução, seja qual for o resultado, para que ela deixe de ser a execução ativa e os hooks silenciem:

```text
$ wev run finish
{"run_id": "demo-1", "phase": "done", "complete": true, "next_step": "wev run report --run demo-1"}
```

Uma execução encerrada mantém seu registro (`run status` e `run report` continuam funcionando) e não aceita mais mudanças (`run_finished`). `wev run finish` é um dos comandos que o hook manda para o seu prompt de permissão. Não encerre uma execução que você ainda quer continuar.

`wev run brief` imprime o resumo curto em texto simples da execução ativa que os hooks injetam, cercado como dado.

## Seleção de ferramentas

`harness.tool_selection` (padrão `off`) pode reduzir as ferramentas que o agente de uma tarefa recebe: `local` usa uma política offline, `provider` consulta o provedor de decisão. A seleção é calculada uma vez por tarefa, sempre mantém um piso (as ferramentas de leitura, a de edição quando a tarefa altera arquivos, o shell quando a tarefa tem verificações) e só pode escolher entre as ferramentas que o agente já tem. `wev select-tools --task-file task.json --agent senior-engineer` mostra uma seleção sem armazená-la. Se uma ferramenta descartada se mostrar necessária, restaure-a enquanto a tarefa roda:

```text
$ wev task tools task-1 --add Write --reason "the task needs a new file"
```

Só uma ferramenta que o agente tem permitida pode ser restaurada, e cada restauração é contada como uma falha de seleção. Veja o [guia de configuração](configuration-and-providers.pt-BR.md) para saber o que é enviado quando o provedor é o JEV. Nenhuma economia de tokens nem melhora no sucesso das tarefas foi medida.

## Códigos de saída

| Código | Significado | O que fazer |
|---|---|---|
| 0 | Sucesso | Siga `next_step` |
| 1 | Erro inesperado, ou um comando de `exec` que falhou | Leia a saída; corrija a causa |
| 2 | Erro de uso ou de validação (por exemplo `verified` sem evidência, configuração fixada, plano inválido) | Corrija a entrada ou execute o passo que falta |
| 3 | Permissão negada (modo plan, caminho protegido, autorrevisão, host fora do inventário, um agente que não pode fazer isto) | Não contorne; mude o plano |
| 4 | Aprovação necessária | Pare e peça ao operador humano |
| 5 | Conflito de estado (a execução mudou sob você, ou outra execução está ativa) | `wev run status` e continue a partir do estado real |
| 6 | Guarda disparada | Mude de abordagem ou pare |
| 7 | Não encontrado (execução, tarefa, agente, aprovação) | Confira o id com `wev state list` ou `wev plan show` |
| 8 | Falha remota ou de provedor | Relate como está |

Os erros são JSON no stderr: `{"error": {"code", "message", "details"}}`.

## Passos que só uma pessoa dá

Cinco comandos são do operador humano: `wev approval grant`, `wev approval deny`, `wev approval request --reopen-denied`, `wev guard acknowledge` e `wev task reopen`. Cada um exige um terminal interativo na entrada e na saída padrão, mostra a ação completa e pede que a pessoa digite uma palavra impressa na tela. Não existe flag que pule isso. Um agente não pode executá-los e não deve tentar; ele para, mostra à pessoa o que é preciso e espera. Um processo determinado consegue simular um terminal. Com o plugin instalado, o prompt de permissão do Claude Code é alcançado para linhas de comando que o hook consegue ler (o comando de concessão digitado diretamente, atrás de um invólucro conhecido ou em um `sh -c` inline); um script em cujo interior o hook não enxerga, ou um pseudoterminal conduzido por um, não é barrado (veja o [guia de segurança](security.pt-BR.md)).

### Aprovações

Quando um comando precisa de aprovação (uma remoção recursiva, um push, um host de produção), o motor registra um pedido e sai com 4. Exemplo real:

```text
$ wev exec -- rm -rf build        # saída 4
{"error": {"code": "approval_required",
  "message": "Command needs approval: Approval needed: the command removes files recursively or without confirmation.",
  "details": {"approval_id": "apr-fbe3eac8c14c6768",
              "next_step": "Stop and ask the human operator: they review approval apr-fbe3eac8c14c6768 (wev approval show apr-fbe3eac8c14c6768) and, if they agree, run 'wev approval grant apr-fbe3eac8c14c6768' themselves in their own terminal. Do not grant it yourself; afterwards, retry the command that was refused."}}}
```

O que a pessoa faz, no próprio terminal:

```text
wev approval list --status pending
wev approval show apr-fbe3eac8c14c6768
wev approval grant apr-fbe3eac8c14c6768      # só depois de ler o comando exato
```

e `wev approval deny <id>` para recusar ou revogar. Este guia não executa `grant` nos exemplos. As regras de uma concessão:

- Fica presa ao **argv exato**, ao **diretório de trabalho resolvido** e à **execução** (em uma ação remota, também ao alias do host).
- É de **uso único** e **expira** após `permissions.approval_ttl_seconds` (padrão 900). A execução que a usa a consome. Não existem concessões reutilizáveis.
- Uma **negação é definitiva** para aquela ação naquela execução. "A mesma ação" significa as mesmas palavras na mesma ordem dentro da execução: o diretório de trabalho (`--cwd`), o risco declarado, o motivo, as aspas, os espaços e o modo de agrupar palavras em tokens não produzem um pedido novo, e para uma ação remota o alias do host é a primeira palavra, então a negação vale por host. O `wev approval request` devolve o registro negado e o `wev exec` responde negado. A comparação é por palavras e não resolve caminhos (`build` e `./build` diferem), e o registro é um arquivo na conta do agente. Uma execução nova começa limpa. Só a pessoa pode substituí-lo por um pedido novo pendente, com `wev approval request --reopen-denied`; a concessão em si não muda (argv exato, diretório resolvido, execução, uso único, com validade). Quando a barreira é negada, o `next_step` diz isso ("denied by the operator") e como o operador a reabre, nunca um comando de concessão.
- Um comando cujo texto a redação alteraria (contém algo que parece um segredo) é **recusado**, não enviado para aprovação, para que a pessoa nunca aprove uma versão mascarada do que seria executado. Passe o segredo por um arquivo ou por uma variável de ambiente.
- Um pedido registra `requested_by`, um nome que quem chama informa (autodeclarado); uma decisão registra o usuário do sistema operacional, o dispositivo do terminal e a hora. Nada compara os dois, porque dentro de uma conta o motor não distingue quem pede de quem opera.
- Toda decisão também fica no log de auditoria, e `wev approval verify` compara o arquivo de aprovações com o log e lista as divergências (saída 1). É evidência de adulteração para acidentes; um agente que consegue escrever os dois arquivos consegue forjar os dois.

Um agente pode registrar um pedido antecipadamente com `wev approval request --risk high --reason "..." --requested-by <agente> -- <comando e argumentos>`.

### Disparos da guarda e reconhecimento

A guarda de execução observa os eventos que o motor registra (comandos, passagens de bastão, tentativas, verificações, progresso, orçamento) e devolve um veredito: `continue`, `change_strategy`, `reduce_scope`, `escalate`, `ask_human` ou `stop`. Detecta comandos idênticos repetidos, ciclos de comandos alternados, falhas consecutivas, tentativas esgotadas, ciclos de passagem de bastão, ausência de progresso observável, estouro de orçamento e de tempo, verificação repetida sem mudança entre elas e consultas (polling) além de um teto. Exemplo real, com `limits.max_identical_commands` igual a 3: rodar `wev exec -- false` quatro vezes deu saída 1, 1, 6, 6 e depois:

```text
$ wev guard check        # saída 6
{"action": "change_strategy", "rule": "identical_commands",
 "reasons": ["Command 972a67578a6d7c28 ran 4 times without progress (allowed 3).",
             "4 consecutive failures (limit 3); change strategy."], "run_id": "demo-4"}
```

Saída 6 significa: mude de abordagem ou pare e avise a pessoa. Quando o mesmo comando continua rodando depois desse aviso, o veredito vira `ask_human` (`ignored_loop`). Enquanto um veredito `stop` ou `ask_human` valer para a execução ou para a tarefa, **`wev exec` e `wev task check` são recusados** (`guard_tripped`, saída 6) e `task next` não entrega mais trabalho. Todo disparo fica na execução e no relatório mesmo depois de liberado. Só uma pessoa o libera, no próprio terminal:

```text
wev guard acknowledge --run <id da execução> [--task <id da tarefa>] --reason "por que é seguro continuar"
```

A guarda passa então a contar de novo a partir desse momento. Um comando que apenas consulta um processo longo deve ser rodado com `--polling`.

### Reabrir uma tarefa bloqueada

Quando uma tarefa usou suas tentativas, ela fica `BLOCKED` e só uma pessoa pode dar mais:

```text
wev task reopen <id da tarefa> --reason "por que ela ganha mais tentativas"
```

A contagem de tentativas recomeça do zero; o histórico permanece no registro. O agente relata a tarefa bloqueada, mostra o motivo e espera. Uma tarefa esgotada não pode ser registrada como `not_executed`; seu `next_step` principal é a instrução de pedir ao humano que rode `wev task reopen`, não `wev task next`.

`next_step` pode ser uma instrução em vez de um comando: uma aprovação pendente; uma barreira negada; no modo plan, depois que o plano é definido ("ready for human review"; executar exige uma execução nova no modo execute depois de `wev run finish`); uma verificação sobre uma árvore em que nada mudou (faça o trabalho, ou marque a tarefa como `read_only` no plano com `--amend --reason`). Uma aprovação obsoleta (a verificação que a exigia foi substituída e o `task check` agora informa `all_met`) deixa de bloquear o `next_step`; ela aparece em `stale_approvals`.

## Retomar

```text
wev state list
wev run resume --run <id da execução>
```

`run resume` compara a execução registrada com o repositório real. Resposta real depois de aparecer um arquivo solto e de uma tarefa ter ficado em execução:

```json
{ "run_id": "demo-2",
  "drift": { "drifted": true, "head_changed": false, "branch_changed": false,
             "new_dirty_files": ["parser.py", "stray.txt"], "missing_files": [],
             "stale_running_tasks": ["notes"],
             "notes": ["Tasks recorded as running must be verified again, not assumed finished: notes.",
                       "2 file(s) are modified now that were clean when the run was recorded."] },
  "needs_reverification": ["notes"],
  "next_step": "..." }
```

Registros antigos são afirmações, não fatos. Rode `wev task check` de novo para cada tarefa em `needs_reverification` antes de registrar qualquer coisa. O estado é escrito com verificação de revisão e uma trava (`limits.lock_timeout_seconds`), e um arquivo de estado de um layout anterior não carrega. `wev state drift` mostra a mesma comparação sem registrar uma decisão, e `wev state show` imprime todo o estado armazenado.

## Hooks, em resumo

Com o plugin instalado, três hooks rodam enquanto uma execução é conhecida para o diretório atual, um diretório pai até a raiz do git ou um caminho que um comando cita. Eles reinjetam o resumo depois da compactação e a cada prompt e verificam os comandos Bash contra a política fixada da execução. Respondem `deny` ou `ask`, nunca `allow`, e nunca leem o armazenamento de aprovações; os comandos sensíveis do próprio motor (os comandos do operador, `approval request`, `run start`, `run finish`, qualquer comando com `--config`, `agent create`, `agent export`, `remote start`, `remote stop`, `jev ask`, `jev batch`) vão para o prompt da pessoa quando o hook consegue ler a linha de comando, diretamente, atrás de um invólucro conhecido ou em um `sh -c` inline; um arquivo de script ou um programa é opaco para ele. Sem execução, os hooks do resumo ficam em silêncio e a verificação do Bash julga os comandos pela política padrão embutida (modo execute, risco médio; nenhuma configuração do repositório é lida); um problema na verificação do Bash vira `ask`. Não foram exercitados em uma sessão real do Claude Code. Detalhes e limites estão no [guia de segurança](security.pt-BR.md); depois de `wev run finish` os hooks do resumo voltam a ficar em silêncio e a verificação do Bash volta à política padrão.
