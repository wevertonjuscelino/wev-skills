# ADR 0004: Provedores de decisão, com o JEV como adaptador opcional

Versão em inglês: [0004-decision-providers-and-jev.md](0004-decision-providers-and-jev.md).

Status: aceito (2026-10-13)

## Contexto

O briefing pede uma interface de decisão neutra quanto a fornecedor e o JEV como integração opcional de primeira classe, sem inventar capacidades. O cliente do JEV encontrado na máquina de desenvolvimento (`jev.mjs`) foi inspecionado em 2026-10-13. O que ele realmente oferece:

- Dois comandos: `jev ask --questions q.json (--state "texto" | --state-file arquivo)` e `jev batch --questions q.json --items itens.jsonl --out resultados.jsonl`. Não existe `--help`.
- Três tipos de pergunta: `noul` (sim ou não), `choice` (2 a 255 opções), `score` (2 a 10 níveis).
- `ask` imprime um objeto JSON de respostas indexado por pergunta. O código do cliente não define o formato: o serviço remoto o produz, então ele pode mudar sem aviso.
- Toda chamada envia o texto de `state` a uma API remota. O código de saída 0 é sucesso, 1 é erro e 2 é um lote com itens que falharam.

## Decisão

- Definir `DecisionProvider` com sete métodos: `classify_task`, `select_strategy`, `route_agent`, `evaluate_result`, `resolve_conflict`, `should_escalate` e `select_tools` (acrescentado depois, ver Seleção de ferramentas).
- Entregar `LocalPolicyProvider`, um conjunto determinístico de regras, sem acesso à rede. É o padrão e o plano de contingência.
- Entregar `JevProvider` como adaptador opcional que usa `jev ask` para `classify_task` e, quando habilitado, para `select_tools`, porque perguntas tipadas se encaixam diretamente na classificação (`score` para complexidade, `choice` para risco, `noul` para paralelismo). Os outros cinco métodos delegam à política local.
- O adaptador interpreta as respostas de forma estrita, no formato observado (ver Formato de resposta observado). Uma resposta que ele não consegue interpretar, um código de saída diferente de zero, um timeout ou um binário ausente fazem a classificação voltar à política local, e o motivo da contingência fica registrado na classificação.
- A confiança é usada com cautela. Uma resposta `score` ou `choice` com `confidence` abaixo de 0,6 (ou sem ela) não é considerada, e um valor `noul` estritamente entre 0,35 e 0,65 é tratado como incerto; para essa dimensão usa-se o valor local e um motivo registra isso. A `uncertainty` da classificação é o máximo entre a incerteza local e 1 menos a menor confiança entre as respostas consideradas.
- Um provedor externo pode elevar o nível de risco calculado localmente e nunca pode reduzi-lo.

## Consequências

- O sistema funciona sem nenhum serviço de decisão configurado.
- Habilitar o JEV envia o objetivo da tarefa a uma API de terceiros. O adaptador remove segredos antes de enviar, o guia de configuração diz isso de forma explícita, e o recurso vem desligado.
- Os testes usam um executável `jev` falso que serve a resposta real gravada (`tests/fixtures/jev_ask_response_2026-10-13.json`) e deriva dela os outros modos. Chamadas reais não fazem parte da suíte de testes.
- Rótulo de evidência da classificação: implementado; interpretador verificado contra uma resposta real gravada; chamadas reais não fazem parte da suíte de testes.
- O programa do JEV é resolvido como o executor resolve programas: um nome simples é procurado apenas em `permissions.exec_path`, e um caminho absoluto precisa ser um arquivo regular executável existente fora da raiz da execução. A regra do caminho seguro foi mantida de propósito: um repositório ou um agente não deve escolher o que roda editando um arquivo num diretório que controla. O custo é que um JEV instalado num diretório do usuário (`~/.local/bin`) não é encontrado pelo nome simples, porque `exec_path` contém só diretórios do sistema por padrão. Quando o programa não pode ser resolvido, a política local é usada e o motivo é registrado na classificação ou na seleção de ferramentas: o programa não foi encontrado no caminho permitido, com as duas correções (definir `decision.jev.command` com o caminho absoluto do programa ou acrescentar o diretório dele a `permissions.exec_path`). `wev config validate` e `wev config show` imprimem um aviso quando `decision.provider` é `jev` e o comando não é resolvido, então a contingência deixa de ser silenciosa. Um `decision.jev.command` relativo com componente de diretório é rejeitado quando a configuração é carregada. Rótulo de evidência: implementado e testado com um executável falso.

## Formato de resposta observado

Em 2026-10-13 foi feita uma chamada real: `jev ask --questions q.json --state "<texto>"`, onde `q.json` era a saída de `build_questions()` do adaptador (três perguntas: `complexity` como `score` com 4 níveis, `risk` como `choice` com `low`/`medium`/`high`, `parallelizable` como `noul`) e o estado era uma única entrada sintética (renomear uma variável local num pequeno utilitário Python com testes). Código de saída 0, JSON no stdout, um objeto por pergunta:

- `score`: `type`, `score` (índice inteiro de base 0 nos níveis), `confidence` (0 a 1), `legend`, `probabilities`.
- `choice`: `type`, `choice` (a chave da opção), `confidence` (0 a 1), `probabilities`.
- `noul`: `type`, `noul` (um número de 0 a 1, lido como a probabilidade de sim). Sem campo `confidence` nesta amostra.

É uma única observação, feita com uma entrada sintética. Campos além dos listados e o comportamento para outras entradas são desconhecidos. Como o cliente não define o formato, ele pode mudar sem aviso; o adaptador valida tipos e intervalos de forma estrita e volta à política local quando algo foge do esperado.

## Seleção de ferramentas

Acrescentado em 2026-10-13. `select_tools(task, agent, available, tier)` escolhe, por tarefa, o menor conjunto de ferramentas do agente de que a tarefa precisa (hipótese H10 em [hypotheses.pt-BR.md](../../research/hypotheses.pt-BR.md)). Só roda quando `harness.tool_selection` é `local` ou `provider`; o padrão é `off`. O JEV só é usado no modo `provider` com `decision.provider: jev`.

- **O que é perguntado.** Uma chamada `jev ask` por tarefa. Uma pergunta `noul` por ferramenta candidata que não está no piso ("Does this task need the <tool> tool: <descrição de uma linha do registro de ferramentas>?"), e uma pergunta `choice` para o perfil de ferramentas (`structured` ou `lean`, com os dois significados por extenso) só quando `harness.tool_profile` é `auto`.
- **O que é enviado.** O texto de estado é o título, o objetivo e os critérios de aceitação da tarefa, passados pelo mesmo redator usado na classificação. Não são enviados conteúdos de arquivos, nomes de arquivos, dados do repositório nem saída de comandos. Os nomes das ferramentas e suas descrições de uma linha fazem parte das perguntas.
- **Limiares conservadores, e por quê.** Remover uma ferramenta de que a tarefa precisava faz a tarefa falhar ou custa uma recuperação, enquanto manter uma desnecessária só custa contexto. Por isso uma ferramenta só é removida quando o valor `noul` é igual ou menor que 0,2 (`DROP_THRESHOLD`); qualquer valor acima a mantém. Uma resposta `choice` com confiança abaixo do limiar de confiança já existente, 0,6, mantém o perfil resolvido localmente. O piso (as ferramentas de leitura que o agente tinha, a de edição quando a tarefa altera arquivos, o shell quando a tarefa tem verificações) nunca é perguntado nem removido.
- **O que o JEV não pode fazer.** A resposta dele passa pela mesma função que a da política local. Ela só pode restringir a lista de permitidas do agente menos a de negadas, não pode acrescentar uma ferramenta negada ou fora da lista, e não pode mudar permissões.
- **Falhas.** Binário ausente, timeout, código de saída diferente de zero, JSON inválido, formato errado ou resposta ausente recaem na seleção local com o motivo registrado, exatamente como na classificação. Mais de 12 perguntas de ferramentas (`MAX_TOOL_QUESTIONS`) também usam a política local, sem chamada. Nada é guardado em cache entre chamadas.
- **Recuperação.** Uma ferramenta removida por engano é restaurada para uma tarefa em execução com `wev task tools TASK --add TOOL --reason TEXT`, só a partir do conjunto de candidatas do agente, e o relatório conta isso como uma falha da seleção.
- **Rótulo de evidência: implementado; formato de resposta verificado contra duas respostas reais em 2026-10-13; não faz parte da suíte de testes.** Os formatos de resposta são os registrados para a classificação (`noul` como um número em [0, 1] sem campo `confidence`, `choice` com `choice` e `confidence`). As duas observações reais estão descritas em Respostas observadas na seleção de ferramentas. Não se sabe se o serviço responde de forma útil a perguntas por ferramenta, nem se a seleção economiza tokens ou mantém as tarefas bem-sucedidas. Os números de tokens mostrados junto a uma seleção são constantes aproximadas por ferramenta, rotuladas como "tokens de definição estimados (aproximados)"; não são uma economia medida.

## Respostas observadas na seleção de ferramentas

Em 2026-10-13 foram feitas duas chamadas reais a `jev ask` para a seleção de ferramentas, cada uma com uma tarefa sintética. As respostas não foram salvas como fixtures, então a suíte de testes não as exercita.

- Uma tarefa de revisão somente leitura: Write 0,06, Bash 0,26, WebFetch 0,36, WebSearch 0,14 e perfil de ferramentas `structured` com confiança 0,56. Essa confiança está abaixo do limiar de confiança 0,6, então o perfil resolvido localmente foi usado. Só Write (0,06) e WebSearch (0,14) ficam no limiar de descarte de 0,2 ou abaixo.
- Uma tarefa de funcionalidade: Write 0,76, Bash 0,58, WebFetch 0,06, WebSearch 0,12 e perfil `structured` com confiança 0,86.

As respostas `noul` não traziam campo `confidence`. Essas duas chamadas verificam o formato da resposta para este uso e nada sobre economia de tokens ou sucesso das tarefas.

## Julgamento independente

`evaluate_result` e `resolve_conflict` existem para que um resultado possa ser julgado por algo diferente de quem o produziu. No MVP, quem julga é a política local determinística sobre as evidências registradas, mais um agente revisor independente que a estratégia exige para trabalho de risco médio e alto. Várias personas rodando no mesmo modelo não são estatisticamente independentes, e a documentação não afirma o contrário.
