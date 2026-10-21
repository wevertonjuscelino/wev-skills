# Configuração e provedores

Versão em inglês: [configuration-and-providers.md](configuration-and-providers.md).

O motor funciona sem arquivo de configuração. Um arquivo só sobrescreve padrões. Este guia lista cada seção com seu padrão (lido de `src/wev_skills/schemas/config.schema.json` e `src/wev_skills/config.py`, e conferido com `wev config show`), explica os níveis de modelo e o roteamento, a seção `harness` e os provedores de decisão, e diz exatamente o que sai da máquina quando o JEV está habilitado.

## Como uma configuração é carregada

- **Resolução.** `wev run start` toma a configuração de `--config CAMINHO` (informado antes do grupo de comandos: `wev --config meu.json run start ...`), senão de `<raiz do repositório>/wev.config.json` se esse arquivo existir, senão dos padrões. A raiz do repositório é o diretório mais próximo, acima do atual, que tem uma entrada `.git`.
- **Fixação.** `run start` grava no estado da execução a configuração efetiva, seu resumo (digest) e sua origem (o campo `config` das respostas de `run start` e `run status` mostra a origem e o digest). Todo comando posterior dessa execução usa a configuração gravada, e um `--config` de conteúdo diferente é recusado com `config_pinned`. Para mudar um ajuste, encerre a execução (`wev run finish`) e comece outra. Um `--config` idêntico ao fixado é aceito.
- **Fora de uma execução**, comandos como `wev classify` resolvem do mesmo jeito, e `wev config show` e `wev config validate CAMINHO` também. `show` imprime a configuração que os demais comandos usariam aqui, com a chave `config_source` dizendo de onde ela veio (`defaults` ou o caminho do arquivo). Quando há uma execução ativa para o diretório atual, `show` imprime a configuração fixada dessa execução, define `config_source` como `run:<id da execução>` e acrescenta `pinned_by_run`; um `--config` diferente é recusado com `config_pinned`, como em todo comando. `validate CAMINHO` confere esse arquivo com as mesmas regras que uma execução aplica (inclusive o que uma configuração não pode nomear, abaixo) e imprime `config_source`. Os dois imprimem uma lista `warnings`, vazia a menos que `decision.provider` seja `jev` e o programa não seja resolvido (veja a seção `jev`).
- O arquivo é JSON. Ele é mesclado em profundidade sobre os padrões: objetos aninhados são mesclados chave a chave; listas e valores simples são substituídos.
- O resultado da mescla é validado contra o schema. Chaves desconhecidas são rejeitadas.
- **O que uma configuração não pode nomear.** `decision.jev.command` precisa ser um nome de programa simples (não um shell nem um interpretador como `sh`, `bash`, `env`, `python`, `node`) ou um caminho absoluto fora do repositório. Cada entrada de `agents.directories` precisa ficar dentro da raiz do repositório ou do diretório de configuração do usuário (`$XDG_CONFIG_HOME/wev-skills`, senão `~/.config/wev-skills`). Um arquivo do repositório não deve escolher o que roda. Uma violação é informada como `invalid_config`.
- Os hooks do Claude Code julgam um comando sob a configuração fixada da execução que encontram, não sob os padrões. Comandos com `--config` são enviados ao prompt de permissão da pessoa quando o hook consegue ler a linha de comando.
- O diretório de estado é acrescentado a `permissions.protected_paths` seja qual for o conteúdo do arquivo.
- Idioma das mensagens: `--lang en|pt-BR`, depois `WEV_LANG`, depois a chave `language` da configuração quando um arquivo de configuração a define explicitamente (o padrão embutido `en` não conta), depois `LANG` (um valor que começa com `pt` seleciona o português) e, por fim, o inglês. Os comandos `run brief` e `run report` com `--lang` próprio ainda prevalecem na sua saída. Uma execução usa o idioma que fixou ao começar, também nos relatórios, nos resumos e na saída dos hooks do Claude Code, então editar o arquivo no meio da execução não o muda.

`examples/config.example.json` é um arquivo válido com um inventário remoto; `tests/unit/test_skills.py` o valida.

## Seções e padrões

Os padrões mostrados são a saída real de `wev config show`.

### `language`

Padrão `"en"`; valores `en`, `pt-BR`. O idioma das mensagens, relatórios, resumos e da saída dos hooks quando nem `--lang` nem `WEV_LANG` são dados. Só conta quando um arquivo de configuração a define: com `{"language": "pt-BR"}` em `wev.config.json`, as mensagens saem em português mesmo que `LANG` seja inglês, e `{"language": "en"}` mantém o inglês mesmo que `LANG` comece com `pt`. Uma configuração que não a define deixa a escolha para `LANG` e, depois, o inglês. A execução fixa o valor ao começar (implementado e testado; veja `tests/unit/test_language_config.py`). A ordem está em [Como uma configuração é carregada](#como-uma-configuração-é-carregada).

### `state_dir`

Padrão `".wev"`. Onde ficam as execuções, as aprovações e o log de auditoria. Um caminho relativo é tomado a partir da raiz do repositório, não do diretório em que você roda. Ele guarda `approvals.json`, `audit.jsonl` e `runs/<id da execução>/` com `state.json`, `events.jsonl` e `logs/`. Cria o próprio `.gitignore`, que ignora tudo o que há nele, diretórios com modo 0700 e arquivos com modo 0600. Estado escrito por um layout anterior não carrega. É sempre um caminho protegido, o que barra um comando que o cita, mas não as ferramentas de arquivo do próprio agente.

### `decision`

| Chave | Padrão | Significado |
|---|---|---|
| `provider` | `"local"` | `local` ou `jev` |
| `jev.command` | `"builtin"` | O cliente JEV. `builtin` usa o cliente HTTP embutido no wev-skills. Qualquer outro valor executa um programa externo: um nome de programa simples, resolvido somente em `permissions.exec_path`, ou o caminho absoluto de um arquivo regular executável existente fora do repositório. Um caminho relativo com componente de diretório é rejeitado quando a configuração é carregada |
| `jev.timeout_seconds` | `10.0` (mínimo 0,1) | Quanto esperar por uma chamada antes de voltar à política local. No cliente embutido, também limita as novas tentativas |

Veja [Provedores de decisão](#provedores-de-decisão).

### `models`

```json
"models": { "tiers": {
  "economy":  ["claude-haiku-5-5"],
  "standard": ["claude-sonnet-5-5"],
  "premium":  ["claude-opus-5-5", "claude-sonnet-5-5"] } }
```

Cada nível é uma lista não vazia de ids de modelo, em ordem de contingência. Veja [Níveis de modelo e roteamento](#níveis-de-modelo-e-roteamento). Os ids são padrões do projeto, não uma afirmação sobre quais modelos você pode usar; troque-os pelos seus.

### `limits`

| Chave | Padrão | Significado |
|---|---|---|
| `max_attempts` | `3` | Tentativas permitidas por tarefa |
| `max_parallel` | `3` | Tarefas oferecidas juntas, quando a classificação diz que o trabalho é paralelizável (senão, 1) |
| `max_consecutive_failures` | `3` | Guarda: comandos consecutivos que falham antes de aconselhar mudança de estratégia |
| `max_identical_commands` | `3` | Guarda: execuções do mesmo comando sem progresso entre elas |
| `task_timeout_seconds` | `3600.0` | Guarda: tempo desde o primeiro evento de uma tarefa antes de chamar uma pessoa |
| `budget_units` | `100.0` | Guarda: soma dos eventos de orçamento de um histórico; o `budget.max_units` de um agente o substitui para a tarefa desse agente |
| `max_polling_commands` | `60` | Guarda: comandos `--polling` consecutivos de uma tarefa antes de chamar uma pessoa |
| `lock_timeout_seconds` | `30.0` | Quanto um comando espera outro processo liberar o arquivo de estado |

Observado: `max_identical_commands` igual a 3 disparou na quarta execução de `wev exec -- false` (veja o [guia de orquestração](orchestration.pt-BR.md)). Uma execução real alimenta a guarda com eventos reais: comandos e verificações gastam unidades de orçamento, o progresso é detectado por uma impressão digital da árvore de trabalho e as tentativas são contadas. `wev guard evaluate --events-file` pode julgar qualquer histórico registrado.

`max_attempts` limita quantas vezes uma tarefa pode começar (todo `task start` conta), e o `max_attempts` do próprio agente pode reduzi-lo. O escalonamento para um nível de modelo mais alto dispara na metade das tentativas (arredondada para cima) ou diante de uma assinatura de erro repetida; no limite a tarefa fica `BLOCKED` até uma pessoa rodar `wev task reopen`.

### `context`

| Chave | Padrão | Significado |
|---|---|---|
| `budget_tokens` | `100000` | Orçamento de tokens do gerenciador de contexto |
| `elide_at` | `0.6` | Razão de uso em que saídas antigas e grandes de ferramentas são trocadas por um marcador que aponta para o original arquivado |
| `summarize_at` | `0.85` | Razão de uso em que um resumidor injetado condensa os itens restantes não fixados |

Essas configurações alimentam `wev context compact` e o harness de avaliação. E mais nada: o fluxo de orquestração (`wev run`, `wev task`) não usa o gerenciador de contexto. Elas não controlam a janela de contexto do próprio Claude Code. Sem resumidor, o segundo estágio é pulado e isso é informado. Itens de requisito, decisão e evidência são fixados e nunca omitidos.

### `permissions`

| Chave | Padrão | Significado |
|---|---|---|
| `allowed_commands` | `[]` | Se não estiver vazia, um comando que não casa com nenhum padrão exige aprovação (não é negado) |
| `denied_commands` | `[]` | Um comando que casa é negado, também quando está atrás de `sudo`, `env` ou `sh -c` |
| `allow_shell` | `false` | Se o executor aceita uma string de comando de shell. Deixe desligado |
| `protected_paths` | `[".git", ".env", ".wev", "<estado, caminho absoluto>"]` | Um argumento que cita um desses (ou um glob que possa casar com um) é negado |
| `approval_ttl_seconds` | `900.0` (mínimo 1) | Por quanto tempo uma concessão fica utilizável depois que a pessoa a dá; a concessão é de uso único e presa a um argv, um diretório e uma execução |
| `exec_path` | `["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin"]` | Os únicos diretórios onde `wev exec` (e o cliente JEV) procuram um programa nomeado sem caminho. O `$PATH` nunca é usado. Um programa que se resolve dentro da árvore de trabalho é recusado |

Os padrões são prefixos do comando, token a token: `"git status"` casa com `git status -s`. Uma lista no arquivo substitui a lista padrão daquela chave, então ao definir `protected_paths` repita `.git` e `.env`; o diretório de estado é reacrescentado por você. Se definir `exec_path`, liste todo diretório que contenha um programa de que você precisa. Veja o [guia de segurança](security.pt-BR.md) para o que a política pega e o que não pega.

### `remote`

`hosts`, padrão `[]`: uma lista de `{ "alias": "staging-1", "environment": "staging", "allow_mutating": false }`. `alias` é obrigatório e deve ser um nome `Host` da sua configuração SSH; `environment` é um rótulo (`production` faz todo comando naquele host exigir aprovação humana da ação exata); `allow_mutating` vale falso por padrão e limita o host aos comandos que a política considera somente leitura. Veja o [guia de operações remotas](remote-ops.pt-BR.md).

### `agents`

| Chave | Padrão | Significado |
|---|---|---|
| `directories` | `[]` | Diretórios extras de specs de agentes; os posteriores sobrescrevem os anteriores |
| `default_agent` | `"senior-engineer"` | O agente para o qual uma tarefa vai quando nenhum agente combina com suas palavras (precisa poder alterar arquivos) |
| `allow_override` | `false` | Deixa uma spec de um diretório configurado substituir um agente embutido com o mesmo id. Desligado, essa spec é recusada |

### `harness`

| Chave | Padrão | Valores | Significado |
|---|---|---|---|
| `planning` | `"auto"` | `auto`, `always`, `never` | Se uma execução faz um plano |
| `executor_tier` | `"auto"` | `auto`, `economy`, `standard`, `premium` | O nível que a estratégia presume para quem faz o trabalho; `auto` usa o nível que o roteador escolheu |
| `plan_reminder` | `true` | booleano | Se o hook de prompt injeta o resumo (brief) |
| `plan_reminder_max_chars` | `600` | 80 a 20000 | Limite de tamanho do resumo |
| `tool_profile` | `"structured"` | `auto`, `structured`, `lean` | Quantas ferramentas um agente exportado ou contratado lista |
| `tool_selection` | `"off"` | `off`, `local`, `provider` | Seleção de ferramentas por tarefa: `off` entrega a lista de ferramentas do agente como está, `local` a reduz com a política offline, `provider` consulta `decision.provider` |
| `baseline_checks` | `true` | booleano | Roda as verificações de uma tarefa uma vez quando ela começa, para que verificações que já passavam antes de qualquer trabalho não sejam tomadas como evidência do trabalho. Desligado: só a árvore inicial é registrada |

Esses mecanismos são padrões configuráveis, motivados por um artigo de pesquisa (veja `docs/research/hypotheses.pt-BR.md`, H4, H5, H8, H9, H10). **O efeito deles não foi medido com um modelo real.** Em particular, com o padrão `executor_tier: auto` a regra de planejamento sensível à capacidade não muda nada na prática: o roteador atribui o nível econômico (economy) apenas a tarefas triviais (risco baixo, no máximo um arquivo, sem incógnitas), e uma tarefa trivial não é planejada em nenhum nível; e a regra do nível premium hoje é igual à do padrão (standard) (as duas planejam a partir de complexidade moderada). A regra só altera a decisão de planejar quando você mesmo define `executor_tier`. Exemplos reais com `wev strategy --files 2 --executor-tier ...`: `economy` dá fluxo `planned`; `standard` e `premium` dão `direct`.

A seleção de ferramentas (`tool_selection`, hipótese H10) sempre mantém um piso (as ferramentas de leitura, a de edição quando a tarefa altera arquivos, o shell quando a tarefa tem verificações), só escolhe entre ferramentas que o agente já tem e não pode mudar permissões. Uma ferramenta descartada pode ser restaurada durante a tarefa com `wev task tools --add`, e cada restauração é contada como uma falha. O relatório mostra estimativas aproximadas de tokens de definição (somas de constantes grosseiras por ferramenta). Não foi medido se ela economiza tokens ou afeta o sucesso das tarefas.

Como `planning: auto` decide: economy planeja tudo acima de trivial; standard e premium planejam a partir de complexidade moderada; qualquer nível planeja acima do risco baixo; `always` e `never` prevalecem; o modo plan e os fluxos com portão (gated) sempre planejam. Risco, aprovação, revisão e limites são iguais para todos os níveis. `tool_profile: lean` está descrito no [guia de agentes](creating-agents.pt-BR.md); é uma opção de custo e nunca acrescenta uma ferramenta nem muda permissões.

## Níveis de modelo e roteamento

O roteador (`wev route-model`) escolhe um nível a partir da classificação e depois um modelo desse nível:

1. Nível inicial: `premium` para risco alto ou trabalho complexo; `economy` para trabalho trivial de risco baixo; `standard` nos demais casos.
2. Falhas sobem o nível. Saída real para uma tarefa moderada: as tentativas 0 e 1 escolhem `standard` (`claude-sonnet-5-5`); as tentativas 2 e 3 escolhem `premium` (`claude-opus-5-5`).
3. O `model_policy` de um agente (`min_tier`, `max_tier`) limita o resultado, e um agente que fixa um `model` concreto prevalece enquanto esse modelo estiver disponível.
4. Um modelo indisponível (`--unavailable`) cai para a próxima entrada do seu nível e depois para um nível vizinho.

Cada resultado lista seus motivos. O roteamento é uma regra, não uma medição de qual modelo serve a uma tarefa. O id de modelo que aparece num contrato de tarefa é também o modelo do agente quando ele fixa um, então uma execução pode mostrar um modelo `standard` para uma tarefa que o roteador teria mandado para `economy`.

## Provedores de decisão

A interface tem sete métodos: `classify_task`, `select_strategy`, `route_agent`, `evaluate_result`, `resolve_conflict`, `should_escalate`, `select_tools` (veja a [arquitetura](../architecture/architecture.pt-BR.md), 4.2, e o [ADR 0004](../architecture/decisions/0004-decision-providers-and-jev.pt-BR.md)).

### `local` (padrão)

Regras determinísticas, sem rede, sempre disponíveis, cada decisão explicada. Status: implementado e testado (implemented and tested). É também o plano de contingência de todos os outros provedores. Regra rígida para todo provedor: um serviço externo pode elevar o nível de risco calculado pelas regras locais e nunca reduzi-lo.

### `jev` (opcional, desligado por padrão)

O JEV é um serviço de decisão de terceiros. Por padrão o wev-skills o acessa com um cliente HTTP próprio (`decision.jev.command` é `builtin`); definir `command` como um nome de programa ou um caminho absoluto mantém o caminho antigo, por um cliente externo de linha de comando. O adaptador o usa para `classify_task`, mapeando perguntas tipadas para a classificação (`score` para complexidade, `choice` para risco, `noul` para paralelismo) e, quando `harness.tool_selection` é `provider`, para `select_tools`; os outros métodos são os da política local. Um provedor só pode elevar risco e complexidade acima do que as regras locais (inclusive o piso lexical lido do objetivo) calcularam; nunca pode reduzir nenhum dos dois, então nunca consegue remover uma revisão ou uma aprovação.

#### O cliente embutido

Selecionado quando `decision.jev.command` é `builtin` (o padrão). Tudo abaixo vale só para ele; o caminho do programa externo, que vem em seguida, não mudou.

- **Busca da chave, nesta ordem:** a variável de ambiente `TYPESAFE_API_KEY`; o arquivo `~/.config/wev-skills/.env` (ou `$XDG_CONFIG_HOME/wev-skills/.env`), que é recusado quando o grupo ou outros podem lê-lo (`chmod 600` resolve) ou quando não pode ser lido (isso interrompe a busca com um erro; não passa para o keychain); depois, se o arquivo não existe ou não tem chave, o serviço `typesafe-api-key` do keychain do macOS. A busca no keychain tem seu próprio limite de 10 segundos, que `decision.jev.timeout_seconds` não cobre. Uma chave com caracteres de controle ou fora de latin-1 é rejeitada. Nenhuma chave é impressa nem entra no motivo de uma falha.
- **Endpoint:** `https://api.typesafe.ai/v1/systemone`, substituído por `JEV_API_URL`. Toda URL que não seja de loopback precisa ser `https` e não pode ter usuário nem senha; uma URL malformada dá `endpoint_invalid`. Uma chave do arquivo env ou do keychain só é enviada quando o esquema, o host e a porta do endpoint são os do padrão; para outro host, exporte `TYPESAFE_API_KEY` com uma chave para ele, ou a chamada falha com `key_not_for_endpoint` antes de qualquer requisição (e `wev jev status` informa `harness`). Uma URL de loopback dispensa a chave e não recebe nenhuma. Redirecionamentos nunca são seguidos.
- **Novas tentativas e prazo:** só HTTP 429 e 529 são repetidos, após 0,5, 1 e 2 segundos, com no máximo 4 tentativas. A chamada inteira fica dentro de `decision.jev.timeout_seconds` (padrão 10,0), que limita as novas tentativas e cada timeout de socket. Um servidor que envia bytes muito devagar, ou uma resolução de DNS lenta, ainda pode passar desse prazo.
- **Falha:** qualquer falha volta à política local e registra o motivo, que nunca contém a chave. No máximo 1 MiB de uma resposta é lido; uma resposta maior é a falha `response_too_large`. `wev config show` e `wev config validate` avisam quando o provedor é `jev` e nenhuma chave foi encontrada (sem aviso de chave para um endpoint de loopback).
- **Comandos:** `wev jev status` imprime `provider`, `client` (`builtin` ou `program`), `key_source`, `key_error`, `endpoint` e `orchestration`. Não faz chamada de rede, nunca imprime a chave e, quando o provedor não é `jev`, não procura a chave. `orchestration` é `wev` só quando `decision.provider` é `jev` e o JEV é utilizável (cliente embutido com chave ou endpoint de loopback, ou um programa que é resolvido), e `harness` nos demais casos, então uma instalação padrão (provedor `local`) informa `harness`; a skill `wev-orchestrate` lê isso primeiro. `wev jev ask --questions ARQUIVO (--state TEXTO | --state-file ARQUIVO)` faz um conjunto de perguntas tipadas, e `wev jev batch --questions ARQUIVO --items ARQUIVO --out ARQUIVO` as faz para cada linha `{"id","state"}` de um arquivo JSONL e grava uma linha de resultado por item, saindo com 8 quando algum item falhou. Os dois mascaram o estado antes. Ao contrário de uma classificação, `ask` e `batch` não voltam à política local: `ask` sai com 2 para perguntas inválidas e com 8 numa falha do JEV, e `batch` registra a falha por item e sai com 8 quando algum item falhou. `ask` e `batch` sempre usam o cliente embutido e ignoram `decision.provider` e `decision.jev.command`. O hook do Bash responde `ask` para os dois, porque eles enviam dados para fora da máquina.
- **Sem o JEV** só o fluxo de orquestração fica desligado. O hook de guarda do Bash continua ativo: sem execução, julga os comandos pela política padrão embutida (modo execute, risco médio) e não lê nenhuma configuração do repositório. Aprovações e detecção de laços precisam de uma execução, então não estão em uso no modo harness.

Status: o cliente embutido está implementado e testado contra um servidor falso local. O serviço real da TypeSafe não foi executado nesta mudança.

O programa externo é resolvido como qualquer programa que o motor executa: um nome simples é procurado somente em `permissions.exec_path` (nunca no `$PATH`), ou `decision.jev.command` é o caminho absoluto de um arquivo regular executável existente fora do repositório. `exec_path` contém só diretórios do sistema por padrão, então um JEV instalado num diretório do usuário, como `~/.local/bin`, **não é encontrado** pelo nome `jev`. Quando o programa não pode ser resolvido, a chamada volta à política local e registra o motivo na classificação (ou na seleção de ferramentas): ele diz que o programa não foi encontrado no caminho permitido e nomeia as duas correções. Defina `decision.jev.command` com o caminho absoluto do programa ou acrescente o diretório dele a `permissions.exec_path`. `wev config validate` e `wev config show` imprimem um aviso em `warnings` quando `decision.provider` é `jev` e o comando não é resolvido, de modo que a contingência silenciosa fique visível antes de uma execução.

Status: implementado e testado contra um executável `jev` falso. O formato das respostas foi verificado contra três chamadas reais feitas em 2026-10-13 com entradas sintéticas (uma classificação, duas seleções de ferramentas); as respostas não foram salvas como fixtures e as chamadas reais não fazem parte da suíte de testes, então o comportamento para outras entradas e ao longo do tempo não foi testado. Quem define o formato da resposta é o serviço, não este projeto, e ele pode mudar sem aviso; o adaptador valida tipos e intervalos de forma estrita e volta à política local diante de qualquer coisa inesperada.

Para habilitar:

```json
{ "decision": { "provider": "jev", "jev": { "command": "/absolute/path/to/jev", "timeout_seconds": 10 } } }
```

A outra correção mantém o nome simples e amplia o caminho de busca: `"permissions": { "exec_path": ["/usr/bin", "/bin", "/usr/sbin", "/sbin", "/usr/local/bin", "/opt/homebrew/bin", "/absolute/path/to/directory-of-jev"] }`. A lista substitui o padrão, então repita os diretórios do sistema de que ainda precisa. Troque `/absolute/path/to/...` pelo local real na sua máquina.

```text
wev --config jev.json run start --objective "..." --files 3
```

**O que sai da máquina.** Quando o provedor é `jev`, cada classificação executa `jev ask` (o cliente embutido faz a mesma chamada por conta própria), e o cliente envia um texto a um serviço remoto. Esse texto é montado a partir dos sinais da tarefa e de mais nada:

```text
Task: <o objetivo que você informou>
files_touched_estimate=<n> unknowns=<n> independent_subtasks=<n>
touches_remote=<bool> touches_production=<bool> destructive=<bool> external_side_effects=<bool> has_tests=<bool> reversible=<bool>
```

O objetivo é texto livre escrito por você ou pelo agente, então é a parte que merece cuidado: não coloque segredos, dados pessoais de clientes nem detalhes privados num objetivo quando o JEV estiver ligado. O adaptador passa o texto antes pelo mascarador do motor, que só esconde segredos de formato reconhecível (veja o [guia de segurança](security.pt-BR.md)). Ele não envia conteúdo de arquivos, saída de comandos, planos nem o estado da execução. Consulte a documentação do próprio cliente JEV para saber o que ele faz com o texto; este projeto não controla isso. As perguntas tipadas enviadas junto são as três listadas acima.

**Seleção de ferramentas com o JEV.** Com `harness.tool_selection: provider` há uma chamada `jev ask` por tarefa. Ela faz uma pergunta `noul` por ferramenta candidata fora do piso ("esta ferramenta é necessária para esta tarefa?"), mais uma pergunta `choice` sobre o perfil de ferramentas quando `harness.tool_profile` é `auto`. O texto enviado é o título, o objetivo e os critérios de aceitação da tarefa e mais nada: nem conteúdo de arquivos, nem nomes de arquivos. Uma ferramenta só é descartada quando a resposta é uma probabilidade de 0,2 ou menos; o piso nunca é perguntado; uma resposta vazia ou inutilizável volta à seleção local. Duas chamadas reais em 2026-10-13 com tarefas sintéticas: uma tarefa de revisão somente leitura devolveu Write 0,06, Bash 0,26, WebFetch 0,36, WebSearch 0,14 e perfil `structured` com confiança 0,56, abaixo do limiar de confiança de 0,6, então usou-se o perfil local; uma tarefa de funcionalidade devolveu Write 0,76, Bash 0,58, WebFetch 0,06, WebSearch 0,12 e perfil `structured` com 0,86. As respostas `noul` não traziam campo de confiança. Isso verifica o formato das respostas para esse uso e não diz nada sobre economia de tokens ou sucesso das tarefas.

Como as respostas são usadas: uma resposta `score` ou `choice` com confiança abaixo de 0,6 (ou sem confiança) não é considerada, e um valor `noul` estritamente entre 0,35 e 0,65 conta como incerto; nessa dimensão usa-se o valor local e um motivo registra isso. A `uncertainty` da classificação passa a ser o maior valor entre a incerteza local e 1 menos a menor confiança considerada. Um binário ausente, uma saída diferente de zero, um timeout ou uma resposta não interpretável voltam à política local e registram o porquê nos motivos da classificação. Confira `classification.source` na resposta de `run start`: ele diz `jev` ou `local-policy`.

### Adicionar outro provedor

A interface `DecisionProvider` é neutra quanto a fornecedor e `build_provider` escolhe por `decision.provider`. Um novo provedor é código em `src/wev_skills/decisions/`, um valor no `enum` do schema e um teste; não há mecanismo de plugin para provedores.
