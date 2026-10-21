# Política de segurança

Versão em inglês: [SECURITY.md](SECURITY.md).

## Versões suportadas

| Versão | Situação |
|---|---|
| A última release (veja a [página de releases](https://github.com/wevertonjuscelino/wev-skills/releases/latest)) | Recebe correções de segurança. |
| Qualquer release mais antiga | Não recebe correções. Atualize para a última release. |

Toda release é completa e final, publicada a partir de `main`; não há branches de manutenção.

## Como relatar uma vulnerabilidade

Não abra uma issue pública para uma vulnerabilidade.

- Use o relato privado de vulnerabilidades do GitHub neste repositório: aba Security e depois "Report a vulnerability", ou <https://github.com/wevertonjuscelino/wev-skills/security/advisories/new>.
- O dono precisa habilitar esse recurso nas configurações do repositório. Se a opção "Report a vulnerability" não aparecer, ele ainda não foi habilitado; nesse caso abra uma issue pública pedindo um meio privado de falar com o mantenedor, sem nenhum detalhe da vulnerabilidade.
- Nenhum endereço de e-mail é publicado para relatos.

Inclua o que você encontrou, os passos ou o comando para reproduzir, a versão ou o commit e o impacto esperado. Não inclua segredos reais nem dados privados. Este é um projeto de uma pessoa só; não há prazo de resposta assumido, mas os relatos são lidos e respondidos.

## Modelo de ameaças

O wev-skills é um guarda-corpo para um agente falível e um registrador de decisões. Ele não é uma fronteira de segurança contra um agente adversário.

O motivo é estrutural. O motor roda na mesma conta de usuário do agente que ele restringe. Dentro de uma conta, a CLI não tem como autenticar quem está digitando, e todo arquivo que o motor mantém (estado da execução, aprovações, log de auditoria, configuração) pode ser reescrito pelo agente com as próprias ferramentas. Nenhuma chave guardada nessa conta mudaria isso, porque o agente também poderia ler a chave.

O que decorre disso:

- O motor pega erros: um comando destrutivo rodado por engano, um comando no modo errado, um segredo colado em um log, um início remoto no host errado.
- A barreira humana que existe é o prompt de permissão do próprio Claude Code. O hook `PreToolUse` do plugin responde `ask` para as linhas de comando Bash sensíveis que ele consegue ler, e a resposta da pessoa nesse prompt é a aprovação daquela chamada. Uma linha de comando que ele não consegue ler (o interior de um arquivo de script ou de um programa) não gera pergunta; veja "Limites conhecidos".
- Sem os hooks do plugin, aprovações são registros, não barreiras. O `wev approval grant` pede um terminal e uma palavra digitada, o que um processo determinado consegue fornecer com um pseudoterminal.
- Um agente que decida derrotar o motor consegue. O isolamento precisa vir de fora: um contêiner, um usuário separado, permissões do sistema operacional, as configurações de permissão da plataforma do agente.

### No escopo dos relatos

- O motor Python em `src/wev_skills/` e sua CLI (`wev`), os hooks em `hooks/hooks.json`, os scripts e os workflows deste repositório.
- Uma falha, do tipo erro, em um controle listado em "O que cada controle faz": um comando que o classificador deveria reconhecer e não reconhece, um hook que fica em silêncio onde este documento diz que ele pergunta, um formato de segredo que a redação diz cobrir e deixa passar.

### Fora do escopo

- Tudo o que está em "Limites conhecidos".
- Vulnerabilidades no Claude Code, tmux, OpenSSH, Python ou outro software que o projeto chama; relate-as aos respectivos mantenedores.
- Achados que exigem um atacante que já controla a máquina ou a conta do usuário, além do que este documento já afirma que um agente nessa conta consegue fazer.

## O que cada controle faz

### O hook do Bash (`wev hook pre-tool-use`)

- Julga cada comando Bash pela configuração fixada, pelo modo e pelo risco da execução ativa. Responde `deny` ou `ask`, nunca `allow`, e nunca lê o registro de aprovações: um comando destrutivo é `ask` todas as vezes.
- Sem execução, julga o comando pela política padrão embutida (os padrões do motor, com o diretório de estado protegido) em modo execute com risco médio, com raiz no topo do git do diretório do hook, ou nesse diretório fora de um repositório. Nesse caso nenhuma configuração do repositório é lida: um arquivo da árvore não pode afrouxar a guarda quando nenhuma execução fixou uma configuração. Aprovações e detecção de laços valem só dentro de uma execução.
- Encontra a execução a partir do diretório do hook e de todo caminho que o comando cita; assim, um comando iniciado em `/tmp` ou em um repositório aninhado que toca a árvore de uma execução é julgado por ela. `cd`, `pushd` e `git -C` são acompanhados. Só confia em uma execução que o registro por usuário lista para aquela raiz e aquele diretório de estado (o `run start` grava a entrada): um `.wev/` que venha dentro de um repositório, ou um diretório de estado indicado pelo `wev.config.json` do repositório, é ignorado, e o comando recebe a política padrão embutida. Os hooks que imprimem o resumo do plano seguem a mesma regra.
- Responde `ask` (e `deny` no modo plan) para qualquer atribuição de ambiente antes de um comando, para `env` e para `export` e palavras de shell parecidas.
- Responde `ask` para tudo o que não consegue ler com certeza: expansão de parâmetro e de comando, aspas `$'...'` e `$"..."`, globs, listas entre chaves, `~usuário`, `eval`, `source`, `exec`, `command`, `builtin`, `script`, `expect`, `xargs`, `find -exec`, `git -c`, `git --exec-path`, `git --config-env`, `git -C` fora da raiz da execução, um shell rodando um arquivo de script e um único argumento que carrega uma linha de comando inteira.
- Responde `ask` para estes comandos do motor quando a linha de comando é uma que ele consegue ler: `approval grant`, `approval deny`, `approval request` (com ou sem `--reopen-denied`, porque há uma execução ativa), `guard acknowledge`, `task reopen`, `specialists accept`, `specialists retire`, `run start`, `run finish`, `agent create`, `agent export`, `remote start`, `remote stop`, `jev ask` e `jev batch` (eles enviam o conteúdo de um arquivo ao serviço JEV, e o `jev batch` sobrescreve o arquivo de `--out`; `jev status` não é perguntado) e qualquer comando com `--config`, com ou sem execução. Ele os reconhece pelas palavras, onde quer que apareçam: o lançador do motor pelo caminho real, a palavra `wev` solta ou `-m wev_skills`, seguidos do subcomando sensível. Isso vale quando o motor é chamado diretamente, atrás de um invólucro que o classificador conhece (`nohup`, `nice`, `timeout`, `time`, `stdbuf`, `setsid`, `env`, `xargs` e o restante da sua lista de invólucros), dentro de um script inline de `sh -c`, `bash -c` ou `zsh -c`, ou como argumentos passados a outro programa. A isenção da política comum continua valendo só para um programa que resolve, pelo caminho real, para o `bin/wev` do plugin ou para o interpretador em uso com `-m wev_skills`.
- Também responde `ask` para `rm` com opções longas abreviadas (`--recursiv`, `--forc`), `git rm -r` ou `-f`, qualquer `git clean` que não seja simulação, `rsync --delete*` e `--remove-source-files`, e para um leitor recursivo (`grep -r`, `rg` com `--hidden` ou `-uu`, `find`, `tar`, `zip`, `cp -r` ou `-a`, `rsync -r` ou `-a`) que receba um diretório contendo um caminho protegido. A leitura direta do arquivo protegido continua negada. É uma heurística sobre uma lista fixa de programas e opções: olha diretórios que existem quando o comando é julgado, percorre no máximo 20.000 entradas (uma árvore maior é tratada como se contivesse um caminho protegido), não lê opções de exclusão, e `rg` sem `--hidden` não gera pergunta sobre nomes protegidos ocultos porque ignora arquivos ocultos.
- Também encontra a execução em `rm -rf <pai do repositório>`: um caminho que é pai da raiz de uma execução registrada conta como tocando essa execução.
- Falha para o lado seguro: estado ilegível, erro interno e comando longo demais para analisar viram `ask`, com ou sem execução. Entrada grande demais ou malformada vira `ask` quando uma execução é conhecida e fica em silêncio sem ela, porque o comando é desconhecido e não há execução pela qual julgá-lo.

### A barreira do próprio motor (`wev exec`)

- Roda um argv sem shell. Recusa sintaxe de shell, um `NOME=valor` inicial e (no modo plan) tudo o que não está na lista de somente leitura.
- Em uma execução no modo execute, um comando age por uma tarefa que está `RUNNING`. `--task` precisa nomear uma tarefa em andamento (um id pendente, concluído ou desconhecido é recusado, e o erro nomeia as tarefas em andamento). Sem `--task`, usa-se a única tarefa em andamento e a saída avisa (`task_implied: true` e um `task_note`). Sem nenhuma tarefa em andamento, ou com várias em andamento e sem `--task`, só comandos de somente leitura são aceitos. Assim, o `may_mutate: false` de um agente e o risco da tarefa não dependem de quem chama nomear a tarefa. Com duas tarefas em andamento, quem chama ainda escolhe para qual delas o comando vale; o motor não sabe dizer qual agente está digitando.
- Um agente com `may_mutate: false` pode rodar comandos de somente leitura, as verificações declaradas da própria tarefa e os comandos de verificação descobertos no repositório em `run start` (por exemplo `make test`, `make lint`), por correspondência exata do argv; todo o resto é recusado com `agent_read_only`. Esses comandos ainda passam pela política, então um que exige aprovação continua exigindo.
- Procura um nome de programa sem caminho apenas em `permissions.exec_path`, nunca em `$PATH`, registra o caminho resolvido e recusa um programa que resolve para dentro da árvore de trabalho da execução. Um programa indicado por caminho relativo precisa de aprovação.
- Classifica comandos como destrutivos, privilegiados, de rede, de efeito externo ou não analisáveis, incluindo abreviações por prefixo único das opções longas do git, configuração do git passada na linha de comando, subcomandos desconhecidos do git e invólucros como `nohup`, `timeout`, `script` e `nice`.
- Nega um argumento, literal ou glob, que nomeie um caminho protegido (`.git`, o arquivo dot-env, o diretório de estado e o que a configuração acrescentar).

### Aprovações

- Uma concessão cobre um argv exato, em um diretório de trabalho resolvido, em uma execução (para uma ação remota, em um alias de host). Vale para um único uso, expira depois de `permissions.approval_ttl_seconds` (padrão 900) e é consumida pela execução que a usa.
- Uma negação é definitiva para aquela ação naquela execução. "A mesma ação", para uma negação, significa as mesmas palavras na mesma ordem na mesma execução: cada token do argv é separado como numa linha de comando e tokens em branco são descartados; assim, o diretório de trabalho (`--cwd`), o risco declarado, o motivo, as aspas, os espaços e o modo de agrupar palavras em tokens não produzem um pedido novo. O `wev approval request` devolve o registro negado e o `wev exec` responde negado. Para uma ação remota, o alias do host é a primeira palavra, então a negação vale por host. Uma execução nova começa limpa. A comparação é por palavras e não resolve caminhos (`build` e `./build` são ações diferentes), e o registro é um arquivo na conta do agente (veja "Limites conhecidos"). Só o `wev approval request --reopen-denied`, um comando do operador humano que exige terminal e a palavra de confirmação digitada, o substitui por um pedido novo pendente. A concessão não muda: presa ao argv exato, ao diretório de trabalho resolvido e à execução (e ao host, no remoto), de uso único e com validade.
- Uma ação cujo texto a redação alteraria é recusada em vez de ser mostrada mascarada; assim o operador vê exatamente o que seria executado. Passe o segredo por um arquivo ou por uma variável de ambiente.
- `approval grant`, `approval deny`, `guard acknowledge`, `task reopen`, `specialists accept` e `specialists retire` exigem terminal em stdin e stdout, mostram a ação completa e pedem uma palavra exibida na tela. O registro guarda o usuário do sistema operacional, o dispositivo de terminal e a hora. Não guarda uma identidade. Um pedido registra `requested_by`, um nome que quem chama informa (autodeclarado). Uma decisão registra o usuário do sistema operacional, o dispositivo de terminal e a hora. Nada compara os dois, porque dentro de uma conta o motor não distingue quem pede de quem opera.
- Evidência de adulteração: toda decisão também vai para o log de auditoria, uma concessão só é honrada quando existe um evento `approval.granted` correspondente, e o `wev approval verify` lista as divergências. Isso pega acidentes e uma concessão escrita direto no `approvals.json`. Não pega um agente que reescreve os dois arquivos.

### Configuração e agentes

- Uma execução fixa sua configuração ao começar. Todo comando usa a fixada e recusa um `--config` diferente. Comandos fora de uma execução informam qual fonte usaram.
- `decision.jev.command` é `builtin` (o padrão, o cliente HTTP embutido descrito abaixo) ou indica um programa externo, que precisa ser um nome de programa sem caminho (que não seja shell nem interpretador) ou um caminho absoluto fora do repositório. `agents.directories` precisa ficar dentro do repositório ou do diretório de configuração do usuário. Uma especificação fora do catálogo embutido não pode reutilizar o id de um agente embutido, a menos que `agents.allow_override` esteja ligado.
- `wev agent create` e `wev agent export` gravam só dentro do repositório, nunca no diretório de estado, em `.git`, em `.claude` ou em caminho protegido, e não sobrescrevem um arquivo que ainda não seja uma especificação de agente ou um arquivo de subagente gerado. A única exceção é `wev agent export --out .claude/agents` (exatamente `<raiz do repositório>/.claude/agents`): só arquivos `<id>.md`, nunca por um `.claude` ou `agents` que seja link simbólico, e sobre um arquivo existente só se ele tiver a marca de arquivo gerado; todo outro caminho sob `.claude` continua recusado. A verificação roda no momento da chamada e é uma proteção, não uma fronteira contra um agente que consegue gravar arquivos por conta própria.

### Cliente JEV embutido

- A chave é buscada nesta ordem: a variável de ambiente `TYPESAFE_API_KEY`, o arquivo `.env` no diretório de configuração do wev-skills do usuário (`$XDG_CONFIG_HOME/wev-skills`, senão `~/.config/wev-skills`) e depois o serviço `typesafe-api-key` do keychain do macOS. A chave nunca é impressa nem entra no motivo de uma falha.
- Esse arquivo é recusado quando o grupo ou outros têm qualquer permissão sobre ele (qualquer coisa mais aberta que o modo 600). A busca então para com um erro em vez de seguir para o keychain.
- O endpoint padrão é `https://api.typesafe.ai/v1/systemone`. `JEV_API_URL` o substitui, e a chave vai num cabeçalho Bearer para o host https que ela indicar, seja qual for. Só um endereço de loopback pode usar http simples, e ele não recebe chave. Redirecionamentos não são seguidos. Definir a variável na frente de um comando (`JEV_API_URL=... wev ...`) é uma atribuição de ambiente, que o hook do Bash responde com `ask` (`deny` no modo plan); um valor que já está no ambiente não é visto pelo hook.
- O texto do estado é mascarado antes de ser enviado. O arquivo de perguntas é enviado como está, sem mascaramento.
- No máximo 1 MiB de uma resposta é lido; uma resposta maior é uma falha (`response_too_large`).
- O hook do Bash responde `ask` para `wev jev ask` e `wev jev batch`, com ou sem execução. `wev jev status` não faz chamada de rede e não é perguntado.

Implementado e testado contra um servidor falso local; o serviço real não foi executado.

### Módulo remoto

- Os hosts vêm do inventário de aliases SSH da execução, com verificação estrita de chave de host. Modo e risco vêm da execução ativa e não podem ser ampliados na linha de comando. A tarefa precisa estar atribuída a um agente com `may_use_remote`.
- O status informa PASSED ou FAILED só com evidência de que a sessão pertence àquela tarefa; caso contrário, UNKNOWN com o motivo. Sessões que o módulo não criou ficam intocadas.

### Texto não confiável e redação

- Saída de comandos, captura remota e outros textos externos têm caracteres de controle e sequências de escape removidos e são cercados como dados antes de a CLI devolvê-los. A busca por texto com cara de instrução apenas informa.
- A redação mascara segredos reconhecíveis em logs, registros de auditoria, eventos do guarda e registros de aprovação, incluindo valores depois de opções com nome de segredo, cabeçalhos `Authorization`, URLs com credenciais ou parâmetros com cara de token e URLs de webhook conhecidas. É melhor esforço. A redação do argv inteiro (o valor depois de `--password`, credenciais em URLs e semelhantes) também vale nos caminhos de recusa. O `tests/integration/test_refused_redaction.py` procura uma isca em todos os arquivos do diretório de estado depois de execuções permitidas, negadas, que exigem aprovação e recusadas pelo guarda, para estes tipos de evento: `exec.ran`, `exec.denied`, `exec.approval_requested`, `guard.tripped`, `task.checked`, `approval.requested` e `task.recorded`. Além disso, qualquer evento de auditoria que guarde uma lista sob a chave `argv` é mascarado como uma única linha de comando.
- Diretórios sob o diretório de estado são criados com modo 0700, e os arquivos, inclusive os de trava, com modo 0600.

## Limites conhecidos

Estes pontos estão abertos. Não conte com o motor para nenhum deles.

- **Outras ferramentas.** Só a ferramenta Bash passa pelo hook. Uma edição de arquivo com as ferramentas do próprio Claude Code não é vista, e isso inclui edições no diretório de estado, no arquivo de aprovações, no log de auditoria, na configuração e no registro de execuções do usuário. Um agente pode forjar uma concessão e o evento de auditoria correspondente, marcar uma execução como encerrada ou remover uma entrada do registro para que o hook não encontre execução.
- **O prompt no terminal.** Um processo pode alocar um pseudoterminal, ler a palavra de confirmação e digitá-la. Sem o hook encaminhando esses comandos ao prompt do Claude Code, nada fica no caminho. O hook não enxerga o interior de um arquivo de script nem de um programa: um script que digita em um pseudoterminal (por exemplo `python3 pty_type.py`, em que o próprio script inicia o motor em um pseudoterminal e digita a palavra de confirmação) não nomeia nada na linha de comando que o hook lê, então não gera pergunta.
- **Scripts e interpretadores.** `python3 script.py`, `node x.js`, `make`, `npm test` e qualquer programa que o classificador não conhece rodam o que seus arquivos mandarem, no modo execute, sem pergunta. Um shell rodando um arquivo de script só gera pergunta quando o arquivo é o primeiro operando. O conteúdo de um script nunca é analisado.
- **Mutação comum no modo execute.** `mv`, `cp`, `sed -i`, redirecionamentos e comandos parecidos são o trabalho em si, então passam sem pergunta, a não ser que toquem um caminho protegido.
- **Programas desconhecidos.** Um programa em caminho absoluto fora da árvore de trabalho é classificado só pelo nome. Um binário renomeado ou embrulhado não é reconhecido.
- **A classificação é uma heurística.** Ela conhece uma lista fixa de programas, subcomandos e opções. O que está fora da lista pode ser tratado como de risco menor do que é.
- **Helpers Git implícitos.** As opções explícitas `--ext-diff` e `--textconv` exigem aprovação, mas a configuração e os atributos do repositório podem habilitar helpers até em um simples `git diff`. Inspecione repositórios desconhecidos antes de confiar nos comandos Git de leitura. A [revisão local de segurança](docs/security-review-2026-10-13.pt-BR.md) registra uma reprodução sintética; isolamento do sistema operacional é necessário para conter helpers arbitrários.
- **O ambiente do processo filho.** O `wev exec` resolve o programa no caminho seguro, mas o programa herda o ambiente de quem chamou, inclusive o `PATH` para o que ele mesmo iniciar.
- **Momento da verificação.** Os caminhos são resolvidos quando o comando é julgado. Um link simbólico trocado depois não é coberto.
- **Hooks podem estar ausentes ou antigos.** Os hooks só agem com o plugin instalado e habilitado. Em um Python anterior ao 3.14, o hook sai sem verificar nada e avisa em stderr (uma linha). O `/usr/bin/python3` original do macOS é o 3.9 e não é suportado; por isso o plugin exige que o `python3` do `PATH` seja 3.14 ou mais novo. Confira com `python3 --version` e, com `command -v python3`, veja qual deles é usado.
- **Alterações de plano são registradas, não impedidas.** O `wev plan set` recusa mudar os critérios de aceitação, as verificações, os arquivos, o risco ou a marca `read_only` de uma tarefa que já foi iniciada alguma vez, a menos que receba `--amend --reason <texto>`. Quem pode rodar `plan set` pode alterar. Uma alteração é registrada como decisão e como evento de auditoria `plan.amended`, zera a verificação daquela tarefa (uma tarefa em andamento precisa ser verificada de novo; uma verificada volta a pendente) e aparece no relatório de entrega em "Plan amendments", com antes e depois. O motor não julga se os critérios novos são mais fracos. Acrescentar tarefas e mudar tarefas nunca iniciadas continua livre.
- **A impressão digital e os arquivos ignorados.** A impressão digital da árvore cobre o commit, o status, os diffs preparados e não preparados e o tamanho e a hora de modificação dos arquivos não rastreados que o git não ignora. Arquivos que o git ignora ficam fora dela de propósito: uma mudança neles não é vista como trabalho e não invalida uma verificação. O `wev plan set` imprime um aviso quando os `files` de uma tarefa ou os argumentos de uma verificação nomeiam um caminho ignorado, e o `task check` e o relatório trazem um aviso.
- **Busca da execução para caminhos montados com variáveis.** O hook encontra a execução pelo seu diretório, pelos diretórios que o contêm, pelos caminhos que o comando cita e por um caminho que seja pai da raiz de uma execução registrada. Um caminho montado com variável não pode ser casado; quando nenhuma execução é encontrada e há alguma registrada para o usuário, um comando com expansão `$` em uma palavra recebe `ask`. Um comando que não casa com nenhuma execução é julgado pela política padrão embutida, então o que a configuração fixada de uma execução acrescenta (caminhos protegidos extras, comandos negados) não vale para ele.
- **O relatório é recalculado na hora do relatório, não continuamente.** No `wev run report` e no `wev run finish`, a árvore é comparada com a vista no último registro `verified`. Se ela difere e nenhuma tarefa está em andamento, toda tarefa verificada cujas verificações não passaram na árvore atual é reportada como "verified, then changed" e o estado geral é `incomplete` até o `wev task check <id>` passar de novo (o `next_step` do relatório diz isso). Uma mudança feita e desfeita entre dois relatórios não é vista; enquanto uma tarefa está em andamento, as mudanças contam como trabalho dela; para uma execução encerrada, o relatório mostra o que o `run finish` registrou.
- **Provedor de decisão.** Um programa externo indicado em `decision.jev.command` (qualquer valor que não seja `builtin`) é executado como está; o motor não verifica que programa é esse. O cliente embutido envia o estado mascarado e a chave ao host https que `JEV_API_URL` indicar, seja qual for (veja "Cliente JEV embutido").
- **Hosts remotos.** Depois que um comando remoto começa, o host está fora do controle do motor. Os registros de execuções remotas ficam no diretório de estado e têm os mesmos limites.
- **O que a redação deixa passar**: segredos sem formato nem nome reconhecível (uma chave secreta de nuvem solta, um valor em tabela separada por espaços, linhas de netrc e pgpass, chaves PuTTY); valores em base64 ou hexadecimal; prosa como "a senha é X"; valores sem aspas depois de espaço, vírgula, ponto e vírgula ou `&`; valores YAML na linha seguinte e TOML de várias linhas; senhas de URL com `@`; tokens curtos de usuário em URL e tokens bearer curtos; nomes como `pw=`, `pass:`, `key=`, `otp`, `pin`, `DSN`; valores de opção que começam com hífen; clientes fora da lista (`mongosh -p`, `psql -W`, `zip -P`, `ldapsearch -w`, corpos de `curl -d`) e senhas posicionais; nomes disfarçados com caracteres de largura zero ou largura total; segredos em nomes de arquivo.
- **Texto não confiável.** Cercar e varrer não torna inofensivo um texto com cara de instrução. Paráfrases, outros idiomas e codificações passam pela varredura.
- **`scripts/scan_secrets.py`** é um alarme para erros óbvios: deixa passar senhas de baixa entropia, segredos sem prefixo nem nome revelador, UTF-16 sem marca de ordem de bytes, valores divididos ou codificados e arquivos em `tests/`.
- **Workflows** fixam suas actions em SHAs de commit (consultados em 2026-10-13) e o Dependabot está configurado para propor atualizações semanais. Consulte o histórico de Actions do repositório para resultados ligados a um commit específico. Um SHA fixado não é uma revisão do código da action.

## Recomendações de operação

- Rode agentes com privilégio mínimo: um usuário dedicado ou um contêiner, um diretório de trabalho limitado e nenhuma credencial de produção no ambiente.
- Mantenha os hooks do plugin habilitados e responda você mesmo aos prompts de permissão do Claude Code. Leia o comando exato antes de permitir.
- Revise o diff antes de aceitar o trabalho. O motor registra o que lhe foi informado; o diff mostra o que aconteceu.
- Nunca aponte um agente, nem o módulo remoto, para produção sem uma pessoa acompanhando cada operação de impacto.
- Trate o arquivo de configuração e o diretório de estado como sensíveis: eles decidem a política e guardam o registro. Mantenha-os fora de locais compartilhados ou graváveis por todos e rode `wev approval verify` quando algo parecer estranho.
- Não coloque segredos na linha de comando. Use arquivos ou variáveis de ambiente.
