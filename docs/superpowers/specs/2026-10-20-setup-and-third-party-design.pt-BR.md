# Design: instalador, harnesses e skills de terceiros

Versão em inglês: [2026-10-20-setup-and-third-party-design.md](2026-10-20-setup-and-third-party-design.md).

Status: rascunho para aprovação do dono (2026-10-20). Nada aqui foi implementado.

## Intenção

Hoje o wev-skills só se instala clonando o repositório e rodando `claude --plugin-dir`, e ninguém nunca instalou do zero. O dono quer que qualquer pessoa, com ou sem instrução técnica, consiga instalar e deixar tudo pronto com uma linha só, como se instala o Claude Code: copiar um comando, rodar um `.sh`, responder algumas perguntas.

Junto com isso, o wev passa a carregar skills de terceiros que o dono quer manter sempre atualizadas com o upstream. As duas primeiras são o [rea](https://github.com/morluto/rea) (engenharia reversa, MCP `rea-agents` no npm, MIT) e o [agent-skills](https://github.com/addyosmani/agent-skills) (skills de engenharia, MIT). O rea não é só uma ferramenta a mais: ele vira a forma de o wev entender sistemas, o do próprio usuário e os de outros, para trazer soluções melhores.

## Decisões do dono

Decididas nesta conversa, não cabem ao construtor:

1. **Entrada:** uma linha `curl -fsSL <url>/install.sh | bash` que faz perguntas, pede as chaves necessárias, instala e deixa tudo pronto. O público vai de quem nunca abriu um terminal até quem usa agentes todo dia.
2. **Harnesses da primeira entrega:** Claude Code, Codex, Gemini CLI e OpenCode. O setup instala em cada um que a pessoa escolher.
3. **JEV liga ou desliga a orquestração do wev:** com JEV, vale a orquestração do wev. Sem JEV, cada harness usa a orquestração nativa dele.
4. **Chaves num `.env` em todos os sistemas:** `~/.config/wev-skills/.env`, permissão `600`. O keychain do macOS continua aceito para quem já usa.
5. **Cliente JEV embutido:** o `jev.mjs` é código do dono e será portado para dentro do wev-skills. Hoje não existe outro lugar de onde baixar o cliente.
6. **Licença:** PolyForm Noncommercial 1.0.0. Já aplicada e publicada (v3.0.0 em diante). O rea e o agent-skills continuam MIT.
7. **Terceiros na instalação:** o setup sempre baixa a versão mais nova.
8. **Terceiros depois de instalados:** uma vez por dia, na primeira abertura do harness, o wev consulta o upstream. Se houver versão nova, ele avisa e **pergunta** se a pessoa quer atualizar. Se ela aceitar, instala, testa e, se falhar, volta sozinho para a versão anterior.
9. **Integração completa do rea:** MCP configurado em cada harness, uso na fase DISCOVER e uma skill dedicada.
10. **Dois usos do rea**, os dois terminando numa solução entregue ao usuário:
    - **Entender o sistema do usuário e trazer a solução** (ex.: "melhorar minha autenticação"): mapear como funciona de verdade, estudar como outros programas resolvem o mesmo problema e propor mudanças com evidência.
    - **Estudar um recurso de outro produto para construir o seu** (ex.: "como o Spotify monta as Jams"): produzir uma especificação de comportamento e arquitetura e construir uma versão própria a partir dela.
11. **Liberdade do rea no estudo:** ele pode baixar programas, fazer engenharia reversa, analisar sites e capturar tráfego sem pedir permissão a cada passo.
12. **Onde roda o que foi baixado:** a pessoa escolhe no setup entre **isolado** (container ou VM) e **direto** na máquina, com aviso de risco.
13. **Teste de ponta a ponta obrigatório:** quando tudo estiver pronto, testar com instalações reais e funcionamento prático, não só com testes unitários.
14. **Sem JEV, só o fluxo sai:** o harness orquestra do jeito dele (sem `run`, contratos de tarefa, verificação e relatório do wev). As proteções continuam ligadas para todos: bloqueio de comandos, aprovações e detecção de loop.
15. **No modo isolado, o rea inteiro roda no container:** o servidor MCP e tudo o que ele baixa e executa ficam lá dentro, então o isolamento é feito por código, não só por instrução. Frida, adb e captura de navegador precisam funcionar no container.
16. **O próprio wev-skills:** o setup instala a tag do release mais recente, e o wev entra na mesma checagem diária, com pergunta e rollback, que os terceiros.
17. **Recursos para os testes de ponta a ponta:** o dono fornece os logins dos harnesses, Docker local e uma chave JEV de teste. Não há VM nem usuário macOS limpo.

## Objetivos, não objetivos e antiobjetivos

**Objetivos**
- Uma pessoa sem instrução chega do zero a um wev funcionando no harness dela sem entender o que aconteceu por baixo.
- Uma pessoa experiente roda o mesmo setup sem perguntas, com flags, e consegue desinstalar.
- Rodar o setup de novo é seguro e serve para reconfigurar (ligar o JEV depois, trocar harness, trocar o modo de execução do rea).
- Skills de terceiros nunca ficam esquecidas numa versão velha sem que a pessoa saiba.
- Com o rea, o wev entrega soluções baseadas em como os sistemas funcionam de verdade, não só no que o código aparenta.

**Não objetivos**
- Windows (o engine não suporta).
- Pedir ou gerenciar o login dos harnesses. Cada um cuida do seu.
- Publicar o wev-skills em marketplace ou registro de pacotes. Isso exige autorização separada do dono.
- Vender ou distribuir comercialmente (a licença proíbe).

**Antiobjetivos** (seria fracasso mesmo funcionando)
- Atualizar uma skill de terceiros sem a pessoa dizer sim.
- Dizer "compatível com Codex/Gemini/OpenCode" sem adaptador e teste de integração.
- Gravar chave dentro de um repositório ou mostrá-la na tela.
- Um programa baixado pelo rea rodar na máquina da pessoa sem ela ter escolhido o modo direto.
- Tratar texto vindo de um site ou binário analisado como instrução para o agente.
- Copiar código ou assets de produtos de terceiros no uso 2 do rea.

## Partes e ordem

São cinco partes que podem ser entregues uma de cada vez, cada uma testada. Ordem: **2 → 3 → 4 → 5 → 1**, mais os testes de ponta a ponta no fim. O instalador vem por último porque só costura o que as outras partes já fazem.

### Parte 2: cliente JEV embutido e troca de orquestração

- Portar `~/.claude/tools/jev/jev.mjs` para Python stdlib dentro de `src/wev_skills/decisions/`, falando direto com `https://api.typesafe.ai/v1/systemone`. O comportamento a preservar está no próprio `jev.mjs`: tipos de pergunta `noul`, `choice` (até 255 opções) e `score` (2 a 10 níveis), novas tentativas em 429/529 com backoff, timeout por requisição, modo batch.
- Ordem de leitura da chave: variável `TYPESAFE_API_KEY` exportada, depois o `.env` do wev, depois o keychain do macOS (serviço `typesafe-api-key`).
- O adaptador atual (`decisions/jev.py`, que chama um programa `jev` externo) continua aceito para quem configurar `decision.jev.command`.
- **Troca de orquestração** (decisão 14):
  - **Com chave JEV válida:** `decision.provider` = `jev`, e as skills dizem ao modelo para seguir o fluxo do wev.
  - **Sem chave:** as skills dizem ao modelo para usar a orquestração nativa do harness. As proteções (hooks de guard, aprovações, detecção de loop) continuam ativas nos dois modos.
  - A forma exata de "usar a nativa" em cada harness fica para a parte 3.
- Os testes unitários usam um servidor HTTP falso. A chamada real vai para os testes de ponta a ponta.

### Parte 3: adaptadores de harness

- O Claude Code já tem plugin (skills, subagentes, hooks). Ganham adaptador novo: **Codex, Gemini CLI e OpenCode**.
- Para cada harness, o adaptador instala as skills do wev, registra o hook de início de sessão (para a checagem diária da parte 4) e registra o MCP do rea (parte 5), no formato daquele harness.
- **Primeiro passo obrigatório:** ler a interface real de cada harness (formato de skills, de hooks, de MCP e de config) antes de escrever código. As regras do projeto proíbem inventar capacidades. Se algum harness não tiver hook de início de sessão, o design dessa parte volta ao dono com as alternativas.
- O agent-skills já publica manifestos para os quatro (`.claude-plugin`, `.codex-plugin`, `.gemini`, `.opencode`). Vale estudar como ele faz.

### Parte 4: gerenciador de skills de terceiros

- Um registro de fontes, com o tipo de cada uma: rea = pacote npm `rea-agents`; agent-skills = releases do GitHub. Ele precisa aceitar fontes novas sem mudar código.
- O próprio wev-skills entra no mesmo mecanismo como uma fonte, pelos releases do GitHub (decisão 16).
- Um arquivo de estado por usuário registra a versão em uso e a anterior de cada fonte, e a data da última checagem.
- **Instalação:** sempre a versão mais nova.
- **Checagem diária:** na primeira abertura do dia (hook de início de sessão), consultar o upstream. Se houver versão nova, avisar e perguntar, com o link do changelog. O hook do Claude Code só injeta texto no contexto e não abre diálogo, então quem pergunta é o agente, no chat. Nos outros harnesses, depende do que a parte 3 encontrar.
- **Atualização aceita:** instalar a nova ao lado da atual, rodar o teste de saúde e, se passar, trocar a versão em uso. Se falhar, manter a anterior e avisar.
- **Recusa:** perguntar de novo só quando sair outra versão.
- **Comandos:** atualizar agora, voltar à versão anterior, congelar uma fonte numa versão.
- **Teste de saúde:** rea = subir o servidor MCP e conferir que ele responde e lista ferramentas. agent-skills = conferir que os arquivos de skill são válidos para cada harness instalado.
- Atualizar sem revisar o conteúdo é uma troca aceita pelo dono, mas só depois de um "sim" explícito. A documentação diz claramente que o teste de saúde pega atualização quebrada, não atualização maliciosa.
- O `docs/THIRD-PARTY.md` passa a registrar o rea e o agent-skills como dependências instaladas (não copiadas), com licença e fonte.

### Parte 5: integração completa do rea

- **MCP:** configurado em cada harness escolhido, pela parte 3. O rea tem um `install.sh` e um setup próprios que já registram o servidor em agentes. Vale avaliar usar o setup dele em vez de reescrever.
- **Fase DISCOVER:** a skill `wev-orchestrate` passa a mandar o modelo usar o rea quando a tarefa envolve um sistema que roda (app, site, binário, bundle): primeiro entender como funciona de verdade, depois planejar.
- **Skill dedicada** (nome a definir pelo construtor, sugestão `wev-reverse`) com os dois usos da decisão 10, cada um terminando num entregável: plano de mudança com evidência (uso 1) ou especificação de comportamento e arquitetura (uso 2), que alimenta o fluxo normal do wev.
- **Sala limpa no uso 2:** estudar o comportamento e produzir especificação. Não copiar código ou assets do alvo, não quebrar proteção ou DRM, não fazer o produto do usuário depender de APIs privadas do alvo. O uso continua sendo decisão do usuário. Isso reduz o risco jurídico, mas não elimina.
- **Modo de execução** (decisão 12): gravado na config do wev.
  - **Isolado:** o servidor MCP do rea inteiro roda num container (decisão 15), e o harness fala com ele lá dentro. Antes de prometer, é preciso verificar como Frida, adb e captura de navegador funcionam nesse arranjo.
  - **Direto:** roda na máquina, depois do aviso dado no setup.
  - Container Docker não executa app de macOS ou iOS. Nesse caso, mesmo no modo isolado, o wev avisa e pergunta antes de rodar direto.
- **Conteúdo do alvo é dado, nunca instrução.** O rea já marca isso como `untrusted_content`, e a skill reforça.

### Parte 1: instalador

Uma linha `curl ... | bash`. O script:
1. Confere sistema (macOS ou Linux), `git`, Python 3.14+ e Node.js/npm (o rea precisa). Se faltar Python ou Node, oferece instalar em vez de mandar a pessoa se virar.
2. Detecta os harnesses instalados e pergunta em quais instalar, já marcando os encontrados.
3. Pergunta se a pessoa tem chave da TypeSafe/JEV.
   - **Sim:** pede a chave sem ecoar, grava no `.env`, faz uma chamada de teste e liga o JEV.
   - **Não:** deixa desligado e vale a orquestração nativa.
4. Pergunta o modo de execução do rea, sugerindo isolado se o Docker existir.
5. Instala as skills do wev e as de terceiros (versão mais nova) em cada harness e configura o MCP do rea.
6. Testa se ficou tudo funcionando e mostra um resumo: o que instalou, onde, e o que ficou de fora e por quê.
7. Mostra a licença (uso não comercial) antes de instalar.

Também precisa ter:
- **Modo sem perguntas** (flags) para quem é experiente.
- **Reexecução segura**, que serve para reconfigurar.
- **Desinstalação** que não deixa nada para trás. Ela remove o `.env` só se a pessoa confirmar.

## Testes de ponta a ponta

São separados do `make test`, porque as regras do projeto proíbem rede e modelo pago nos testes unitários. Proposta: um alvo `make e2e`.

- **Linux:** container zerado. Roda a linha do `curl`, responde às perguntas e confere o resultado.
- **macOS:** não há VM nem usuário limpo (decisão 17). O teste roda na máquina do dono com um `HOME` temporário e vazio. Isso cobre instalação e configuração, mas não pega dependências já instaladas no sistema. A documentação rotula o macOS como "testado com HOME isolado", não como "máquina limpa".
- **Por harness:** confirmar que carrega as skills do wev, que o rea responde como MCP e que o agent-skills aparece.
- **JEV:** um cenário com chave real e um sem chave (orquestração nativa).
- **Atualização:** instalar uma versão antiga do rea de propósito, ver a pergunta, aceitar e conferir a troca. Depois forçar uma versão quebrada e conferir o rollback.
- **Desinstalação:** conferir que nada sobrou.

Rodar harnesses de verdade gasta conta e créditos do dono, então cada rodada pede autorização antes. A documentação só pode dizer "compatível com X" depois que esse teste passar para X.

## Restrições

- Runtime do engine: Python 3.14+ só com a biblioteca padrão. O `install.sh` é shell POSIX/bash. Node.js entra como requisito do rea, não do engine.
- mypy strict, dataclasses frozen, funções com menos de 50 linhas e arquivos com menos de 400.
- Toda mensagem ao usuário passa por i18n (EN e pt-BR com as mesmas chaves). Docs mudam nas duas línguas no mesmo commit.
- Rótulos de evidência em toda afirmação de capacidade. Afirmações de segurança de acordo com o `SECURITY.md`: o engine é um guardrail, não uma barreira contra um agente adversário na mesma conta.
- Comandos de operador humano continuam fora do alcance do agente.
- Nada é publicado (push, release, hospedagem do `install.sh`) sem autorização explícita do dono.

## O que fica para o construtor

- Formato e lugar do registro de fontes e do arquivo de estado dos terceiros.
- Nomes de comandos e flags (seguindo o padrão `wev <grupo> <ação>` e a saída JSON do CLI).
- Como o `install.sh` instala Python 3.14 e Node quando faltam (`uv`, gerenciador do sistema etc.), desde que a pessoa seja avisada antes.
- Forma exata do teste de saúde de cada fonte.
- Nome da skill do rea.
- Se usa o setup do próprio rea ou registra o MCP diretamente.
- Onde hospedar o `install.sh` (fica para o dono autorizar quando chegar a hora).

## Chamadas que fiz sem o dono

Valem como padrão até o dono dizer o contrário:
- O `.env` fica em `~/.config/wev-skills/`, e a variável exportada no shell tem prioridade sobre ele.
- O cliente JEV antigo, externo, continua aceito.
- O modo de execução padrão sugerido é isolado quando há Docker.
- Recusar uma atualização vale até sair a próxima versão.
- A ordem de entrega é 2 → 3 → 4 → 5 → 1.
- **Troca de modo em tempo de uso:** as skills consultam o wev a cada sessão (um comando que diz se o JEV está ativo). Assim, ligar ou desligar o JEV não exige reinstalar. A chave é validada no setup. Se uma chamada falhar depois, o wev cai na política local e avisa, como já faz hoje.
- **Escopo do cliente JEV:** fica dentro do processo, substituindo o programa externo quando `decision.jev.command` não estiver definido, e ganha também `wev jev ask|batch`. O setup não mexe na configuração global do usuário (`~/.claude/CLAUDE.md`, `agent-model-hook.mjs`).
- **Terceiros compartilhados:** uma cópia de cada fonte, ligada a todos os harnesses. A checagem diária é global, então rollback e congelamento valem para todos de uma vez.
- **Versão nova do agent-skills:** é o release mais recente (o repositório publica tags; `0.6.13` em 2026-10-20). Para fontes sem release, é o HEAD da branch padrão.
- **Desinstalar remove só o que o wev gravou.** Cada entrada que o wev escreve em configs de harness é registrada num manifesto, e a desinstalação apaga só essas. Entradas que o usuário já tinha antes ficam.
- **Profundidade dos adaptadores:** cada adaptador leva tudo o que o harness suporta (skills, hook de início de sessão, guard de comandos, subagentes, lembrete por prompt). O que não der para levar fica escrito na documentação, com rótulo de evidência.
