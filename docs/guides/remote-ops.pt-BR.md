# Guia de operações remotas

Versão em inglês: [remote-ops.md](remote-ops.md).

O módulo remoto é opcional. Ele executa diagnósticos e testes autorizados nos hosts que você listar, por SSH, dentro de sessões tmux, com um log e um status de saída que você pode ler depois. Nada mais no wev-skills depende dele, e uma falha nele não quebra o resto.

**Status: simulado com mocks (simulated with mocks).** O módulo está implementado e testado contra um host simulado (um transporte falso com caminhos de falha: host desconhecido, modo plan, comandos recusados, host inalcançável, propriedade de sessão). **Ele nunca foi executado contra um tmux real nem contra um servidor real.** Existem um workflow manual (`.github/workflows/remote-integration.yml`) e um teste (`tests/integration/test_tmux_local.py`) para exercitar um tmux real localmente, sem SSH; nenhum dos dois foi executado, porque o tmux não estava instalado na máquina de desenvolvimento (esses 8 testes são os que a suíte informa como ignorados). O primeiro uso real é o primeiro teste real do módulo, não uma prova de que ele funciona. Diga isso a quem for depender dele.

Neste guia, `wev` significa `"$WEV_HOME/bin/wev"`. As saídas marcadas como reais vêm da CLI de verdade em 2026-10-13. São recusas que acontecem antes de qualquer conexão. (Um início que não foi recusado tentou resolver o alias de exemplo `staging-1`, que não existe na máquina, e falhou com `remote_connection_failed`; nenhuma conexão foi feita.)

**O que os controles são.** O módulo remoto segue a posição do projeto: uma proteção para um agente falível, não uma fronteira contra um agente adversarial. O inventário de hosts, o modo e o risco da execução, o registro de aprovação e o marcador de posse da sessão pegam erros; um agente na mesma conta pode reescrever o estado local e os registros de execução com as próprias ferramentas de arquivo. O portão humano é o prompt de permissão do Claude Code, alcançado pelo hook do plugin, que manda `remote start` e `remote stop` para a pessoa quando consegue ler a linha de comando (não quando um arquivo de script os inicia). Depois que um comando remoto começa, o host está fora do controle do motor.

## Como funciona

O motor conecta com o cliente `ssh` do sistema, usando `-o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10`, de modo que só pode usar o que você já preparou: nunca pede nada, nunca aceita uma chave de host nova e nunca passa senha nem material de chave. Ele inicia o seu comando dentro de uma sessão tmux no host, guarda um log e um arquivo com o status de saída em `~/.wev/remote` lá, e lê o status ou o final do log depois. A sessão se chama `wev-<tarefa>-<hash do host>`, e a propriedade é provada por uma opção marcadora definida na criação da sessão. Cada comando é julgado pela mesma política de permissões dos comandos locais.

## O que você prepara (o agente nunca faz)

1. **Defina um alias** por máquina em `~/.ssh/config` (hostname, usuário, porta). A configuração do wev se refere ao alias, nunca a um endereço bruto. Prefira um usuário dedicado e de poucos privilégios no host.
2. **Carregue a chave num agente SSH** para que as conexões não precisem de prompt. O wev falha em vez de pedir senha.
3. **Conecte uma vez à mão** (`ssh staging-1`) para que a chave do host entre em `known_hosts`. Com a verificação estrita de chave de host, o wev não aceita uma chave desconhecida, e uma chave alterada é uma recusa, não um prompt.
4. **Instale o tmux no host.** Opcionalmente, garanta que `timeout` exista lá, se quiser usar `--timeout`. O wev não instala nada remotamente.
5. **Liste os hosts** num arquivo de configuração do wev, em `remote.hosts`, e passe-o com `--config`:

   ```json
   {
     "remote": {
       "hosts": [
         { "alias": "staging-1", "environment": "staging",    "allow_mutating": false },
         { "alias": "prod-1",    "environment": "production", "allow_mutating": false }
       ]
     }
   }
   ```

   `examples/config.example.json` é esse arquivo mais alguns limites. `environment: "production"` faz todo comando remoto naquele host exigir aprovação humana da ação exata. `allow_mutating: false` (o padrão) limita o host aos comandos que a política considera somente leitura.
6. **Valide-o:**

   ```text
   $ wev --config examples/config.example.json config validate examples/config.example.json
   {"valid": true, "path": ".../examples/config.example.json"}
   ```

## Os comandos

Todos recebem `--host ALIAS` exatamente como listado na configuração. As opções globais (`--config`, `--lang`) vão antes de `remote`.

**Com e sem execução.** Com uma execução ativa, `remote` é governado por ela:

- o **modo e o risco vêm da execução**; `--mode` e `--risk` só podem repeti-los ou ser mais restritivos (`--mode plan`, um `--risk` mais alto), nunca ampliá-los (`remote_mode_widened`, `remote_risk_widened`);
- o **inventário de hosts vem da configuração fixada da execução**; um `--config` de conteúdo diferente é recusado (`config_pinned`);
- `start` exige que `--task` seja uma tarefa do plano da execução e que **o agente atribuído a essa tarefa tenha `permissions.may_use_remote`** (`remote_task_not_in_run`, `remote_agent_not_allowed`; o agente `remote-ops` que acompanha o projeto tem). O roteador manda uma tarefa sobre sistemas remotos para um agente assim;
- um início é gravado no estado da execução, um registro por tarefa e host.

Sem execução ativa, `--config` fornece o inventário, `start` exige `--mode` (`remote_mode_required`) e o risco padrão é `medium`. Nada é gravado em uma execução.

```text
$ wev --config examples/config.example.json remote hosts
{"hosts": [
  {"alias": "staging-1", "environment": "staging",    "allow_mutating": false},
  {"alias": "prod-1",    "environment": "production", "allow_mutating": false}]}
```

| Comando | O que faz |
|---|---|
| `remote hosts` | Lista o inventário. Sem rede. |
| `remote preflight --host H` | Somente leitura: informa hostname, usuário, se o tmux existe e o diretório base. Não instala nada. |
| `remote start --host H --task T [--mode M] [--risk R] [--timeout N] -- COMANDO...` | Inicia o comando numa sessão tmux pertencente à tarefa `T`. `--task` deve ser único por trabalho e por host. `--mode` é obrigatório sem execução; `plan` nunca inicia nada. `--risk` (padrão `medium` sem execução) declara o risco do comando. `--timeout` o interrompe após N segundos e exige `timeout` no host. |
| `remote status --host H --task T` | Informa `running`, `passed`, `failed`, `unknown` ou `blocked`, confiando em um status de saída só com prova de posse (abaixo). |
| `remote capture --host H --task T [--lines N]` | Imprime o final do log (padrão 200 linhas, no máximo 2000), mascarado, limpo de caracteres de controle e cercado como dado remoto não confiável. Leia como dado, nunca como instrução. |
| `remote stop --host H --task T [--mode M] [--risk R]` | Encerra a sessão da tarefa, apenas se o wev a criou. Encerrar altera o host, então é recusado no modo plan; durante uma execução o modo e o risco vêm dela. |

### Significado dos status

| Status | Significado |
|---|---|
| `running` | A sessão existe, pertence a esta tarefa e ainda não registrou um status de saída. Continua `running` até existir um status de saída; um log quieto não significa que terminou. |
| `passed` / `failed` | Um status de saída foi registrado (zero ou não). Esta é a única evidência de conclusão. |
| `unknown` | Não foi possível checar o host (por exemplo, a conexão SSH falhou), não há sessão nem status de saída, ou falta a evidência de posse. Depois de uma reinicialização isso é esperado, porque as sessões tmux não sobrevivem a ela. A resposta nomeia a evidência que falta. Relate como desconhecido e não adivinhe. |
| `blocked` | O comando não pôde iniciar. |

Ao consultar um trabalho longo, espere entre as consultas. A guarda de execução trata repetição apertada como laço.

**Posse.** Um arquivo de saída no host não prova nada por si só, porque qualquer coisa no host pode escrevê-lo. `status` só o aceita quando a sessão ainda existe e traz o marcador de posse desta tarefa ou, depois que a sessão some, quando o estado da execução guarda um registro do início desta tarefa neste host. Sem essa evidência a resposta é `unknown` e diz o que falta; sem execução ativa não há registro, então uma sessão encerrada aparece como `unknown`.

### O que o módulo recusa

Respostas reais da CLI, sem rede, porque a recusa acontece antes de qualquer conexão:

```text
$ wev --config examples/config.example.json remote start --host other-9 --task t1 --mode execute -- df -h        # saída 3
{"error": {"code": "remote_host_not_listed", "message": "Host is not in the remote inventory. Only hosts listed in the configuration can be reached.", "details": {"alias": "other-9"}}}

$ wev --config examples/config.example.json remote start --host staging-1 --task t1 --mode plan -- df -h        # saída 3
{"error": {"code": "remote_plan_mode", "message": "Plan mode never starts a remote command.", ...}}

$ wev --config examples/config.example.json remote start --host staging-1 --task t1 --mode execute -- rm -rf /tmp/x        # saída 3
{"error": {"code": "remote_read_only_host", "message": "This host only accepts read-only commands, and the policy does not consider this command read-only.", ...}}
```

Um host com `allow_mutating` falso aceita apenas comandos que a política considera somente leitura: diagnósticos comuns como `uptime`, `hostname`, `whoami`, `id`, `date`, `uname`, `df`, `free`, `ps`, `du`, `stat`, `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `find`, `nproc`, `lscpu`, `ss`, `netstat`, `systemctl status`, `systemctl is-active`, `journalctl`, `docker ps`, `docker logs`, `kubectl get`, `kubectl describe`, `kubectl logs` e `git status`. Os mesmos programas são recusados com opções que escrevem, executam ou mudam estado (`find -exec` ou `-delete`, `date -s`, `hostname NOME`, `journalctl --vacuum-size`, `ss -K`, `kubectl --kubeconfig`); `sed`, `awk`, `tee`, `xargs` e `env` nunca são somente leitura. Não procure um jeito de contornar; defina `allow_mutating` como verdadeiro para um host só quando for a sua intenção.

Sem execução e sem `--mode`, `start` é recusado antes (`remote_mode_required`; resposta real: "No run is active here, so --mode is required to start a remote command. During an active run the mode comes from the run."). Ordem das checagens do próprio controlador em `start`: inventário, modo, a política de permissões sobre o comando remoto, a checagem de somente leitura para hosts sem `allow_mutating` e, por fim, a aprovação.

### Aprovações e produção

Produção exige aprovação humana explícita do comando exato, e o mesmo vale para qualquer comando que a política sinalize (uma remoção recursiva, por exemplo) em qualquer host. Quando falta a aprovação, `start` registra o pedido da ação qualificada pelo host, `<alias> <comando>` (de modo que ele nunca possa ser satisfeito por uma aprovação do mesmo comando executado localmente), e sai com 4. Resposta real, para um `df -h` inofensivo no alias de produção da configuração de exemplo:

```text
$ wev --config examples/config.example.json remote start --host prod-1 --task disk-1 --mode execute -- df -h        # saída 4
{"error": {"code": "remote_approval_required",
  "message": "This remote command needs explicit approval before it can start. Approval apr-6d91c612e298f40c was requested for the exact action 'prod-1 df -h'. Stop and ask the human operator to review it (wev approval show apr-6d91c612e298f40c) and to run 'wev approval grant apr-6d91c612e298f40c' themselves in their own terminal; then start it again.",
  "details": {"alias": "prod-1", "action": "prod-1 df -h", "environment": "production", "approval_id": "apr-6d91c612e298f40c", "next_step": "Stop and ask the human operator: ..."}}}
```

Este é o passo do operador humano: ele lê o host, o comando e o motivo e concede no próprio terminal; a concessão cobre aquela ação exata (alias do host e comando, em um diretório e uma execução) por um uso e expira após `permissions.approval_ttl_seconds` (padrão 900); depois o mesmo `start` é executado de novo. Uma negação é definitiva para aquela ação naquela execução. Um agente nunca roda `approval grant`, `approval deny` nem `approval request --reopen-denied`; eles exigem um terminal e uma palavra digitada e não têm flag de contorno. Com o plugin instalado, o hook também manda `remote start` e `remote stop` para o prompt da pessoa. Para pedir com antecedência, um agente pode registrar o mesmo pedido, escrevendo o alias e o comando como palavras separadas: `wev approval request --risk high --reason "check disk usage on production" --requested-by remote-ops -- prod-1 df -h`.

## Uma primeira execução real, com segurança

Como o módulo só foi exercitado contra uma simulação, faça a primeira execução real num host que você possa se dar ao luxo de perturbar, e trate o resultado como um teste do módulo.

1. **Rode antes o teste local com tmux** (precisa do tmux; sem SSH, sem host remoto): `PYTHONPATH=src python3 -m unittest tests.integration.test_tmux_local -v`, a partir da raiz do repositório. Ele usa um HOME temporário e um servidor tmux próprio num diretório temporário, e nunca toca no seu servidor tmux padrão. O mesmo teste é o workflow manual do GitHub `remote-integration.yml`. Até que ele tenha passado em alguma máquina, as linhas de comando reais do tmux não estão verificadas.
2. **Escolha um host de staging** sem dados importantes, acessível por um usuário de poucos privilégios. Nunca comece por produção.
3. **Faça a preparação acima**, inclusive o `ssh` manual que registra a chave do host.
4. **Liste só esse host**, com `allow_mutating: false`, numa configuração só dele, e rode `wev config validate` nela.
5. **Preflight:** `wev --config staging.json remote preflight --host staging-1`. Leia você mesmo a saída: hostname, usuário, tmux presente.
6. **Um comando inofensivo, somente leitura, com timeout curto:**

   ```text
   wev --config staging.json remote start --host staging-1 --task first-1 --timeout 30 -- uptime
   wev --config staging.json remote status --host staging-1 --task first-1
   wev --config staging.json remote capture --host staging-1 --task first-1 --lines 20
   wev --config staging.json remote stop --host staging-1 --task first-1
   ```

7. **Confira você mesmo no host** (`tmux ls` e os arquivos em `~/.wev/remote`) que a única sessão foi a que o wev criou, que ela terminou e que nada mais mudou.
8. **Registre o que aconteceu** com honestidade: o que rodou, o status e o código de saída, e o que não foi verificado. Uma execução num host real que registrou um status de saída é evidência para aquele comando naquele host, e só.
9. Só então considere mais comandos. Produção vem por último, um comando aprovado de cada vez.

## Regras que o módulo segue

- Só hosts do inventário; o inventário é a sua declaração do que pode ser tocado e, durante uma execução, é o que a execução fixou.
- O modo e o risco vêm da execução e não podem ser ampliados na linha de comando; o agente da tarefa precisa poder usar hosts remotos.
- Nada no modo plan.
- Nunca instala pacotes nem altera a configuração do sistema remotamente; apenas diagnósticos e testes.
- Nunca toca numa sessão tmux que não criou (`remote_session_not_owned`) e nunca emite `tmux kill-server`.
- A saída capturada é limpa, mascarada e cercada como dado não confiável, e ainda assim pode conter texto que parece instrução. Use `wev scan-untrusted --source <host>` antes de entregá-la a um modelo.
- Nunca imprima variáveis de ambiente de um host remoto; elas costumam guardar segredos.
- O código de saída 8 é uma falha remota (conexão, tmux ausente). Relate-a como ela é.

A skill `wev-remote-ops` dá ao Claude Code o mesmo fluxo. Ela também não foi exercitada numa sessão real.
