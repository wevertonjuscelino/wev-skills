# ADR 0006: O motor é uma proteção contra erros, não uma fronteira de segurança

Versão em inglês: [0006-guardrail-not-boundary.md](0006-guardrail-not-boundary.md).

Status: aceito (2026-10-13)

## Contexto

O ADR 0002 divide o sistema em um motor que impõe e skills que instruem. Os primeiros controles de aprovação e de hook foram escritos como se o motor pudesse impedir o agente que ele restringe. Três rodadas de revisão independente em 2026-10-13, antes da publicação, testaram isso e acharam os controles de aprovação e de hook contornáveis pelo agente restringido. A razão estrutural é a mesma em todos os achados: o motor roda na mesma conta de usuário que o agente. Dentro de uma conta, a CLI não sabe quem está digitando, e todo arquivo que o motor mantém pode ser reescrito com as ferramentas de arquivo do próprio agente.

## Decisão

Enunciar a posição de segurança do mesmo modo em todo lugar, com o texto do [SECURITY.pt-BR.md](../../../SECURITY.pt-BR.md):

- O motor é uma proteção para um agente falível e um registrador de decisões. Não é uma fronteira de segurança contra um agente adversário na mesma conta de usuário.
- O portão humano é o prompt de permissão do Claude Code, alcançado pelo hook `PreToolUse` do plugin, que responde `deny` ou `ask` e nunca `allow`. A resposta da pessoa nesse prompt é a aprovação daquela chamada.
- Sem os hooks do plugin, as aprovações são registros, não portões.
- O isolamento contra um agente que decide derrotar o motor tem de vir de fora: um contêiner, outro usuário, permissões do sistema operacional, as configurações de permissão da plataforma do agente.

Documentos e skills não devem dizer que um controle "impede", "garante" ou "assegura" algo que um agente na mesma conta pode desfazer.

## O que mudou depois das revisões

Tudo isto está implementado e coberto por testes unitários ou de subprocesso; as correções feitas depois da última rodada de revisão não foram verificadas de novo de forma independente (veja [mvp-status.pt-BR.md](../../mvp-status.pt-BR.md)).

- As aprovações são de uso único, expiram (`permissions.approval_ttl_seconds`, padrão 900) e são atadas ao argv exato, ao diretório de trabalho, à execução e, em ação remota, ao host. As concessões reutilizáveis foram removidas. Uma negativa é final para as mesmas palavras na mesma ordem dentro da execução (o diretório de trabalho, o risco, o motivo e as aspas não geram pedido novo), a menos que o operador a reabra. Um comando cujo texto o mascaramento alteraria é recusado em vez de ir para aprovação. `wev approval verify` confronta as concessões com o log de auditoria.
- Os comandos do operador humano (`approval grant`, `approval deny`, `approval request --reopen-denied`, `guard acknowledge`, `task reopen`) exigem um terminal em stdin e stdout e uma palavra de confirmação digitada. Não têm flag de contorno.
- O hook de Bash nunca responde `allow` e nunca lê o repositório de aprovações. Ele encaminha ao humano os comandos sensíveis do próprio motor quando a linha de comando é uma que ele consegue ler, diretamente, atrás de um invólucro conhecido ou em um `sh -c` inline (comandos do operador, `approval request`, `run start`, `run finish`, `agent create`, `agent export`, `remote start`, `remote stop`, qualquer comando com `--config`), responde `ask` (ou `deny` no modo plan) para prefixos de atribuição de ambiente, expansões de shell não resolvidas e wrappers que não consegue analisar, encontra a execução pelo diretório de trabalho, pelos diretórios que o contêm ou por um registro por usuário confrontado com os caminhos do comando e, uma vez que a execução é conhecida, falha para `ask` em vez de ficar em silêncio.
- A configuração é fixada no estado da execução em `run start`; um `--config` diferente em comando posterior é recusado.
- O executor resolve programas num caminho seguro fixo (`permissions.exec_path`), registra o caminho resolvido e mascara o argv inteiro nos logs.
- A saída capturada (caudas do exec, captura remota e saída de descoberta da execução) tem caracteres de controle removidos e é delimitada como dado antes de a CLI devolvê-la.
- O programa do JEV é resolvido no mesmo caminho seguro ou precisa ser um caminho absoluto fora da raiz da execução.

## O que continua em aberto

São os limites conhecidos listados no SECURITY.pt-BR.md. O motor não se defende deles:

- As ferramentas de arquivo do próprio agente (Edit, Write) podem reescrever o estado da execução, o arquivo de aprovações, o log de auditoria, a configuração e o registro de execuções por usuário.
- Um pseudoterminal pode digitar a palavra de confirmação, e um script que conduz um (por exemplo `python3 pty_type.py`) não nomeia nada na linha de comando que o hook lê, então não gera pergunta.
- No modo execute, `python3 script.py`, `make`, `mv`, `sed -i`, redirecionamentos e programas desconhecidos em caminho absoluto não passam por portão.
- Processos filhos herdam o ambiente de quem os chama.
- A classificação é heurística; os caminhos são checados quando o comando é julgado, não quando executa; o mascaramento e a varredura de padrões de instrução deixam passar formatos e paráfrases.
- Os hooks só atuam com o plugin instalado e habilitado e, com Python anterior ao 3.14 (o `/usr/bin/python3` original do macOS é o 3.9), não verificam nada.
- Alterações de plano são registradas, não impedidas: `wev plan set --amend --reason` muda os critérios, as verificações, os arquivos, o risco ou a marca `read_only` de uma tarefa iniciada, e o motor não julga se os critérios novos são mais fracos.
- A impressão digital da árvore deixa de fora os arquivos que o git ignora, então uma mudança neles não é vista como trabalho.
- A execução não é encontrada para um caminho montado com variável; uma expansão `$` gera pergunta quando há alguma execução registrada, e substituição de comando, here-documents e globs onde nenhuma execução é encontrada não são cobertos.
- O relatório é recalculado na hora do relatório, não continuamente; uma mudança feita e desfeita entre dois relatórios não é vista.

## Consequências

- As afirmações de segurança ficam limitadas ao que o código faz contra um erro. O guia do usuário e as skills dizem ao operador o que ler antes de responder a um prompt de permissão.
- Documentos que descrevem um controle devem dizer o que ele não cobre. O texto é conferido por leitura, não por teste.
- Uma mudança futura que passe um limite de "aberto" para "fechado" precisa de um teste que falhe quando o controle quebrar e de um novo registro.

## Alternativas consideradas

- Continuar descrevendo os controles como preventivos: rejeitado, porque as revisões mostraram que isso é falso para um agente adversário.
- Guardar uma chave de assinatura para autenticar os comandos do operador: rejeitado, porque uma chave legível pela conta do usuário é legível pelo agente.

## Rótulo de evidência

Apenas documentado, quanto à posição em si. As mudanças em "O que mudou depois das revisões" estão implementadas e testadas nas suítes unitária e de segurança; o efeito dos hooks dentro de uma sessão real do Claude Code não foi observado.
