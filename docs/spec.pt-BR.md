# Especificação do produto wev-skills (MVP)

Versão em inglês: [spec.md](spec.md).

## Finalidade

O wev-skills ajuda um agente de programação a conduzir trabalho de vários passos com um plano registrado, contratos de tarefa explícitos, verificações de permissão, detecção de laços, evidências de verificação e estado retomável. É genérico: nada nele pressupõe um repositório, uma linguagem ou um domínio em particular.

## Quem usa

- Quem desenvolve com o Claude Code e quer que tarefas maiores sejam planejadas, delegadas e verificadas, com um registro do que foi de fato checado.
- Equipes que querem definir seus próprios agentes (revisor, auditor de segurança, operador remoto) como arquivos de configuração versionados.
- Quem mantém o projeto e quer comparar configurações do harness sobre um conjunto fixo de tarefas.

## Escopo do MVP

1. Um motor em Python com CLI em JSON que cobre classificação (com um piso lexical de risco lido do objetivo em inglês e português), estratégia, planejamento, contratos de tarefa, estado com gravações condicionais, permissões, aprovações, detecção de laços, execução de comandos, verificação com regras estritas de evidência, roteamento de modelos e relatórios. O orçamento de contexto está disponível como `wev context compact` e no harness de avaliação; o fluxo de orquestração não o usa.
2. Specs de agentes como JSON validado por schema, com registro, fábrica com templates e herança, dez agentes de exemplo e um exportador para arquivos de subagentes do Claude Code.
3. Uma interface de decisão com um provedor local determinístico e um adaptador JEV opcional. Provedores externos só podem elevar risco e complexidade; nunca podem remover uma revisão ou uma aprovação.
4. Um módulo remoto opcional para SSH e tmux, testado com um transporte simulado.
5. Um harness de avaliação determinístico com um agente roteirizado.
6. Skills do Claude Code que acionam o motor, empacotadas como plugin do Claude Code com um manifesto de marketplace.
7. Hooks de plugin para o Claude Code: o resumo (brief) higienizado e cercado da execução ativa é reinjetado depois da compactação de contexto e a cada prompt, e os comandos Bash são checados contra a política de permissões fixada da execução (negar ou perguntar à pessoa; nunca permitir). Os hooks também mandam os comandos sensíveis do próprio motor (comandos de aprovação e de reconhecimento, `run start`, `run finish`, qualquer comando com `--config` e alguns outros) para o prompt de permissão da pessoa quando a linha de comando é uma que o hook consegue ler. Ficam em silêncio somente enquanto nenhuma execução é conhecida; quando uma é conhecida, um problema vira `ask`. Não veem edições de arquivo feitas com as ferramentas do próprio Claude.
8. Seleção de ferramentas por tarefa (`harness.tool_selection`, `wev select-tools`, `wev task tools --add`) com uma política local e um provedor JEV opcional, e uma seção do relatório com estimativas aproximadas de tokens de definição de ferramentas.
9. O recurso de CLAUDE.md (`wev claude-md init|update|check|show`, skill `wev-claude-md`) e o recurso de README (`wev readme check`, skill `wev-readme`), ambos produzindo e verificando texto de diretrizes de um projeto.
10. Seis skills do Claude Code no total: `wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` e `wev-readme`.
11. Documentação em inglês e em português do Brasil, workflows de CI, licença e registro de terceiros.

## Posição de segurança

O motor é uma proteção para um agente falível e um registro de decisões. Não é uma fronteira de segurança contra um agente adversarial na mesma conta de usuário. O portão humano é o prompt de permissão do Claude Code, alcançado pelo hook; sem os hooks do plugin, as aprovações são registros. Limites conhecidos que continuam abertos incluem: as ferramentas de arquivo do próprio agente podem reescrever o estado, as aprovações, o log de auditoria e o registro de execuções; um pseudoterminal pode digitar a palavra de confirmação dos comandos do operador humano, e um script que conduz um não é visto pelo hook; `python3 script.py`, `make`, `mv`, `sed -i`, redirecionamentos e programas desconhecidos por caminho absoluto não são barrados no modo execute; processos filhos herdam o ambiente de quem chamou. Ver [SECURITY.pt-BR.md](../SECURITY.pt-BR.md) e o [ADR 0006](architecture/decisions/0006-guardrail-not-boundary.pt-BR.md).

## Fora do escopo do MVP (trabalho futuro)

- Hooks para ferramentas além do Bash (por exemplo, checar Edit e Write contra o escopo de uma tarefa) e uma execução dos hooks existentes dentro de uma sessão real do Claude Code.
- Adaptadores para ambientes de agente além do Claude Code.
- Entrada em YAML para as specs.
- Execuções de avaliação contra modelos reais e qualquer comparação medida entre configurações.
- Suporte a Windows no armazenamento de estado.
- Uma ferramenta de recuperação (recall) exposta ao modelo durante uma sessão.

## Critérios de aceitação

Cada critério é verificado pela evidência indicada. O status é acompanhado em [docs/mvp-status.pt-BR.md](mvp-status.pt-BR.md).

| # | Critério | Evidência |
|---|---|---|
| 1 | A skill de entrada existe com frontmatter válido | Teste de validação das skills; `claude plugin validate` se disponível |
| 2 | A instalação local está documentada e testada | Guia de instalação; verificação de carga do plugin |
| 3 | O fluxo básico de orquestração roda de ponta a ponta | Teste de integração que aciona a CLI do pedido ao relatório |
| 4 | Pelo menos dois agentes são personalizáveis por configuração | As specs de exemplo carregam, validam e exportam |
| 5 | O roteamento tem interface documentada e implementação funcional | Testes unitários do roteador e dos provedores |
| 6 | A criação e a validação de agentes têm testes | Testes unitários da fábrica e do registro |
| 7 | O plano e o estado persistem e podem ser retomados | Testes do armazenamento de estado e da retomada |
| 8 | A proteção contra laços tem testes determinísticos | Testes unitários da guarda de execução |
| 9 | O contexto gerenciado tem uma estratégia de compactação testável | Testes unitários do gerenciador de contexto |
| 10 | Os controles de permissão são verificados por testes | Suíte de testes de segurança |
| 11 | A integração com SSH e tmux é isolada e testada com mocks | Testes do módulo remoto com um transporte simulado |
| 12 | A documentação existe em português e em inglês | Teste de paridade da documentação |
| 13 | Os workflows de CI estão configurados | Arquivos de workflow |
| 14 | Os comandos de teste executados têm resultados registrados | `docs/mvp-status.pt-BR.md` |
| 15 | Sem segredos, sem referências quebradas conhecidas, sem alegações de compatibilidade sem suporte | Varredura de segredos, verificação de links, revisão |
| 16 | O projeto está publicado como pré-lançamento e seu estado está registrado | Lista "Depois de publicar" em `docs/mvp-status.pt-BR.md` |

## Fora de propósito (non-goals)

O wev-skills não substitui o runtime do agente, não chama APIs de modelo por conta própria no MVP e não controla a janela de contexto do próprio Claude Code.
