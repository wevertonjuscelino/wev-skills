# wev-skills

Versão em inglês: [README.md](README.md).

Um harness de orquestração de código aberto, orientado a evidências, para agentes de programação com IA: um motor Python sem dependências, com uma interface de linha de comando em JSON (`wev`), mais skills, subagentes e hooks do Claude Code. Ele ajuda um agente a conduzir trabalho de vários passos com um plano registrado, contratos de tarefa, verificações de permissão, detecção de laços, evidências de verificação e estado retomável, e informa cada resultado com um rótulo que diz quanta evidência existe por trás dele.

Serve a quem desenvolve e quer que tarefas maiores sejam planejadas, delegadas e verificadas, com um registro do que foi de fato checado; a equipes que querem definir os próprios agentes como configuração versionada, e não como código; e a quem mantém o projeto e quer comparar configurações do harness sobre um conjunto fixo de tarefas. Nada nele pressupõe um repositório, uma linguagem ou uma empresa em particular. O Claude Code é o único ambiente com adaptador; o motor não depende dele.

> [!IMPORTANT]
> Pré-lançamento 0.1.0, publicado em 2026-10-13 em https://github.com/wevertonjuscelino/wev-skills. Os workflows de CI existem e ainda não concluíram uma execução. Nada foi exercitado em uma sessão real do Claude Code, e não houve execução real com tmux ou SSH. Não há pacote no PyPI nem entrada em um marketplace oficial. Cada afirmação abaixo traz um de cinco rótulos de evidência, e nada é afirmado sem evidência.

## Status

Os rótulos são: implementado e testado (implemented and tested); implementado mas não testado (implemented but untested); simulado com mocks (simulated with mocks); apenas documentado (documented only); bloqueado (blocked). O [status do MVP](docs/mvp-status.pt-BR.md) lista as evidências de cada critério de aceitação.

| Capacidade | Status | Evidência e ressalvas |
|---|---|---|
| Motor: classificação, estratégia, plano, contratos de tarefa, estado, retomada, relatório | implementado e testado | Testes unitários e um teste de integração do fluxo da CLI, todos sem modelo |
| Portão de verificação: `verified` exige uma verificação aprovada feita depois da última vez que a tarefa foi iniciada, sobre a árvore como ela está; uma linha de base das verificações é tirada quando a tarefa começa | implementado e testado | Testes unitários. As verificações são escritas pelo agente ou por quem fez o plano; o motor confirma que elas rodaram e passaram, não que são suficientes |
| Permissões, aprovações, classificação de comandos, mascaramento, proteção do diretório de estado, configuração fixada por execução | implementado e testado | Testes unitários e uma suíte de segurança. A classificação é uma heurística; sem revisão independente |
| Comandos do operador humano (`approval grant`, `approval deny`, `guard acknowledge`, `task reopen`) | implementado e testado | Exigem um terminal e uma palavra digitada e não aceitam opção de contorno. Um processo determinado consegue simular um terminal; veja o aviso abaixo |
| Guarda de execução: laços, falhas repetidas, falta de progresso, ciclos de repasse, tempo | implementado e testado | Testes unitários determinísticos. A regra de orçamento hoje não tem entrada numa execução real |
| Seleção de ferramentas (`wev select-tools`, `harness.tool_selection`, `wev task tools`) com a política local | implementado e testado | Testes unitários |
| Gerenciador de contexto (compactação em estágios) | implementado e testado | Usado por `wev context compact` e pelo harness de avaliação. Não gerencia o contexto do próprio Claude Code |
| Specs de agentes: registro, fábrica, herança, teto de permissões, exportação para subagentes | implementado e testado | Os arquivos de subagentes exportados não foram carregados por uma sessão real do Claude Code |
| Provedor de decisão: política local | implementado e testado | Regras determinísticas, sem rede |
| Provedor de decisão: adaptador JEV (opcional, desligado por padrão) | simulado com mocks | Testado contra um `jev` falso que serve uma resposta real gravada (2026-10-13, entrada sintética). Envia o objetivo da tarefa a um terceiro quando habilitado |
| Módulo remoto (SSH e tmux, opcional) | simulado com mocks | Testado apenas contra um host simulado; nunca executado contra um tmux real nem um servidor real |
| Harness de avaliação | simulado com mocks | Agente roteirizado, unidades simuladas, sem modelo |
| `wev claude-md` e `wev readme check` | implementado e testado | Testes unitários. `claude-md` grava só um arquivo chamado `CLAUDE.md` dentro do repositório; `readme check` apenas lê |
| Hooks do plugin: reinjeção do resumo, pré-checagem de Bash | implementado e testado | Testes unitários e de subprocesso. Quando uma execução é conhecida, um problema vira `ask`, não silêncio |
| Seis skills e os manifestos do plugin | implementado e testado | Testes unitários do formato e das referências a comandos. `claude plugin validate .` passa com um aviso (um `CLAUDE.md` na raiz do plugin não é carregado como contexto do plugin), verificado com o Claude Code 2.1.296 em 2026-10-13 |
| Skills, subagentes e hooks dentro de uma sessão real do Claude Code | implementado mas não testado | Nunca exercitados numa sessão real |
| Mecanismos derivados do artigo de pesquisa (planejamento condicional, perfis de ferramentas, lembrete do plano, perfis de capacidade) | implementado e testado | Mecânica testada; efeito não medido com um modelo real |
| Workflows de CI | implementado mas não testado | Os arquivos são lidos como YAML. Nunca rodaram: nada foi publicado |
| Instalação pelo marketplace ou `pip install` | apenas documentado | Comandos lidos da saída de `--help`; não executados |
| Adaptadores para outros ambientes; avaliação com modelos reais | apenas documentado | Trabalho futuro |
| Windows | bloqueado | O armazenamento de estado usa travas de arquivo POSIX |

## Como funciona

O motor (`src/wev_skills/`, Python 3.14+, só biblioteca padrão) é dono de toda regra que código consegue verificar: se um plano é válido, quais transições de tarefa são legais, se um comando é permitido, se uma aprovação o cobre, se o agente está preso num laço e se uma tarefa pode ser registrada como verificada. As seis skills em `skills/` (`wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` e `wev-readme`) são instruções em Markdown que dizem ao Claude Code quando chamar o motor e como agir sobre as respostas dele. O modelo raciocina e edita; o motor registra, decide e recusa passos inválidos com código de saída diferente de zero. O raciocínio está no [ADR 0002](docs/architecture/decisions/0002-engine-enforces-skills-instruct.pt-BR.md) e na [arquitetura](docs/architecture/architecture.pt-BR.md).

O fluxo é `REQUEST → DISCOVER → CLASSIFY → PLAN → DECIDE → EXECUTE → VERIFY → REVIEW → DELIVER`, com os modos `plan` (olhar, não mudar nada), `execute`, `auto` e uma operação de retomada que antes compara a execução registrada com o repositório real.

> [!WARNING]
> O motor é uma proteção para um agente falível e um registro de decisões. Não é uma fronteira de segurança contra um agente adversário na mesma conta: ele roda como o mesmo usuário do agente que restringe, e todo arquivo que ele guarda pode ser reescrito por esse agente. O isolamento precisa vir de fora (um contêiner, outro usuário, permissões do sistema operacional). A imposição também cobre apenas o que passa pelo motor ou pelo hook de Bash; edições feitas com as ferramentas de arquivo do próprio Claude Code não são vistas. Veja [SECURITY.pt-BR.md](SECURITY.pt-BR.md).

## Requisitos

- Python 3.14 ou mais novo, em macOS ou Linux. Nada a instalar: o motor usa só a biblioteca padrão. Interpretadores mais antigos não são suportados, inclusive o `/usr/bin/python3` original do macOS (3.9). Com um `python3` mais antigo primeiro no `PATH`, os hooks do plugin saem quietos e não verificam nada (confira com `python3 --version`). A suíte rodou pela última vez no Python 3.14.7, como registrado no [status do MVP](docs/mvp-status.pt-BR.md).
- `git`, para os instantâneos das execuções e a detecção de divergência (drift).
- Claude Code, apenas para o plugin (skills, subagentes, hooks). A CLI funciona sem ele.
- Opcionais: `tmux` e `ssh` (módulo remoto), `ruff`, `mypy` ou `uvx` (`make lint`).

## Início rápido

Clone o repositório (apenas documentado; o clone não foi executado para este README) e chame o clone de `$WEV_HOME`. Atualização, desinstalação, verificação e reversão estão no [guia de instalação](docs/guides/installation.pt-BR.md).

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
export WEV_HOME="$PWD/wev-skills"
"$WEV_HOME/bin/wev" --help
```

Abaixo, `wev` significa `"$WEV_HOME/bin/wev"`. É uma execução real, feita hoje num repositório git temporário com um `Makefile` que tem o alvo `test` e `.wev/` no `.gitignore`. As saídas foram abreviadas aos campos que importam (os campos e valores são os da CLI, em inglês); o motor imprime mais. O estado é gravado em `.wev/` no diretório atual.

```text
$ wev run start --objective "Add a greeting file" --files 1 --run-id demo-1
  classification: complexity trivial, risk low        (source: local-policy)
  strategy:       flow direct, no plan, no independent review
  discovery:      make test (from Makefile)
  config:         source defaults, digest pinned for the run
  next_step:      wev task next --run demo-1

$ wev task next
  offered: task-1  agent senior-engineer  model claude-sonnet-5-5  checks ["make test", "git diff --stat"]

$ wev task start task-1
  status running, attempt 1, contract handed out
  baseline: taken, passed ["make test", "git diff --stat"]

$ wev exec --task task-1 -- touch greeting.txt
  record: status passed, exit_code 0, changed_files ["greeting.txt"]    guard: continue

$ wev task check task-1
  all_met true: "1 of 1 acceptance criteria met, 0 unmet, 0 unverified; 0 checks not run."

$ wev task record task-1 --status verified --summary "greeting file added" --changed-file greeting.txt
  status verified   next_step: wev run finish --run demo-1

$ wev run report --format md
  # Delivery report: run demo-1
  - Overall status: complete
  ### task-1: Add a greeting file     Status: verified   Evidence: tested
  | Check that ran | Exit code | Log | Evidence |    make test | 0 | ... | tested |

$ wev run finish
  {"run_id": "demo-1", "phase": "done", "complete": true, ...}
```

(O relatório sai em inglês por padrão; `--lang pt-BR` o gera em português.) Tentar pular a evidência é recusado, e um comando destrutivo pede uma pessoa:

```text
$ wev task record task-1 --status verified --summary "too early"
  exit 2  verification_required: Task task-1 cannot be recorded as verified: 1 acceptance criterion(s) have no passing check made after the task last started and no tested evidence.

$ wev exec --task task-1 -- rm -rf build
  exit 4  approval_required: Command needs approval: Approval needed: the command removes files recursively or without confirmation.
```

O agente deve parar aí e pedir ao operador humano, que revisa a aprovação e a concede no próprio terminal. Esse passo exige um terminal e uma palavra digitada, então não foi executado para este README; é mostrado como o passo do operador:

```sh
wev approval grant <approval-id>
```

O [guia de orquestração](docs/guides/orchestration.pt-BR.md) mostra o fluxo completo, com planos, revisão independente e retomada.

Para carregar o plugin (seis skills, dez subagentes e três hooks) apenas em uma sessão:

```sh
claude --plugin-dir "$WEV_HOME"
```

Para instalar em todas as sessões, adicione o repositório como marketplace e instale o plugin (apenas documentado; esses comandos mudam a configuração do Claude Code da máquina e não foram executados):

```sh
claude plugin marketplace add wevertonjuscelino/wev-skills
claude plugin install wev-skills@wev-skills-marketplace
```

Dentro de uma sessão do Claude Code, os equivalentes são `/plugin marketplace add wevertonjuscelino/wev-skills` e `/plugin install wev-skills@wev-skills-marketplace` (apenas documentado). A partir de um clone, `claude plugin marketplace add "$WEV_HOME"` adiciona o marketplace local.

## Recursos

- **Orquestração** com contratos de tarefa: objetivo, contexto, escopo, exclusões, restrições, critérios de aceitação, verificações, formato da resposta, permissões, agente e modelo, entregues a exatamente um agente. Tarefas em paralelo só quando independentes, nunca duas nos mesmos arquivos. [Guia de orquestração](docs/guides/orchestration.pt-BR.md).
- **Rótulos de evidência**: o relatório rotula cada afirmação como `tested`, `untested`, `mocked`, `documented_only` ou `blocked`.
- **Agentes como dados**: specs JSON validadas por schema, templates, herança, teto de permissões, texto bilíngue e exportação para subagentes do Claude Code. [Criando agentes](docs/guides/creating-agents.pt-BR.md).
- **Permissões e aprovações**: sem shell, classificação de comandos, negação no modo plan, caminhos protegidos, aprovações atadas ao comando exato, de uso único e com validade, mascaramento. [Guia de segurança](docs/guides/security.pt-BR.md).
- **Guarda de execução**: comandos idênticos repetidos, falhas consecutivas, falta de progresso, ciclos de repasse e tempo.
- **Provedores de decisão e roteamento de modelos**: uma política local determinística e um adaptador JEV opcional; níveis `economy`, `standard`, `premium`; seleção de ferramentas por tarefa, opcional. Uma execução fixa sua configuração (`wev.config.json` na raiz do repositório, ou `--config` no início). [Configuração e provedores](docs/guides/configuration-and-providers.pt-BR.md).
- **Hooks do plugin para o Claude Code**: reinjetam o resumo da execução depois da compactação e a cada prompt, e checam comandos Bash contra a política fixada da execução respondendo `ask` ou `deny`, nunca `allow`. Optou-se por hooks simples em vez de mods do Claude Code: [ADR 0005](docs/architecture/decisions/0005-hooks-not-mods.pt-BR.md).
- **Módulo remoto** (opcional): aliases SSH só do inventário, verificação estrita de chave de host, sessões tmux pertencentes à tarefa, produção protegida por aprovação. [Guia de operações remotas](docs/guides/remote-ops.pt-BR.md).
- **Harness de avaliação roteirizado**: determinístico, sem modelo. [Guia de avaliação](docs/guides/evaluation.pt-BR.md).
- **Auxiliares de documentação**: `wev claude-md init|update|check|show` mantém um bloco de diretrizes gerenciado no `CLAUDE.md` de um projeto ([skill `wev-claude-md`](skills/wev-claude-md/SKILL.md)), e `wev readme check` verifica arquivos README contra o padrão de README deste projeto ([skill `wev-readme`](skills/wev-readme/SKILL.md)).
- Referência: [arquitetura](docs/architecture/architecture.pt-BR.md), [especificação](docs/spec.pt-BR.md), [registros de decisão](docs/architecture/decisions/), [glossário](docs/glossary.md), [notas de pesquisa](docs/research/hypotheses.pt-BR.md), [registro de terceiros](docs/THIRD-PARTY.pt-BR.md).

> [!NOTE]
> Os resultados de avaliação vêm de um agente roteirizado que reproduz trajetórias fixas contra os componentes do motor. Nenhum modelo é chamado, então eles não dizem nada sobre a qualidade de nenhum modelo.

> [!NOTE]
> O módulo remoto só foi testado contra um host simulado. Nunca rodou contra um tmux real nem um servidor real.

## Testes e lint

```sh
make test
make lint
```

O `make test` roda `unittest discover`, sem rede, sem modelo e sem nada a instalar. O `make lint` roda `ruff check`, `ruff format --check` e `mypy` em modo estrito no pacote, usando as ferramentas do `PATH`, depois o `uvx`, e do contrário informa que pulou. Os testes unitários e o CI rodam sem provedor de modelo pago e sem host remoto real.

Última execução registrada (2026-10-13, Python 3.14.7, na máquina do dono, não no CI): o `make test` terminou com `Ran 2076 tests in 167.282s` e `OK (skipped=8)`; o `make lint` terminou com `Success: no issues found in 146 source files`. O registro completo está no [status do MVP](docs/mvp-status.pt-BR.md). Os testes de integração com tmux são pulados onde o tmux não está instalado.

Arquivos do projeto: [LICENSE](LICENSE) (MIT; veja também [NOTICE](NOTICE)), [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md), o [guia de manutenção](docs/guides/maintaining.pt-BR.md), [SECURITY.pt-BR.md](SECURITY.pt-BR.md), [CHANGELOG.md](CHANGELOG.md) e [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## Limitações

- Não é uma sandbox. Um comando permitido roda com todas as permissões do seu usuário, e o motor não lê o que um script faz.
- A classificação de comandos é uma heurística; um comando que ela não reconhece pode ser tratado como menos arriscado do que é. Interpretadores e scripts (`python3 script.py`, `make`, `npm test`) rodam o que seus arquivos mandarem.
- As aprovações são atrito mais registro de auditoria, não autenticação. Sem os hooks do plugin, nada impede um processo de usar um pseudo-terminal para digitar a palavra de confirmação, e mesmo com eles um script que conduz um pseudo-terminal não nomeia nada na linha de comando que o hook lê, então não gera pergunta.
- O mascaramento é de melhor esforço e pega apenas segredos de formato reconhecível.
- Os hooks veem só a ferramenta Bash e só atuam quando o plugin está instalado e habilitado. O motor não checa edições feitas com as ferramentas de arquivo do próprio Claude Code.
- As skills, os subagentes e os hooks não foram exercitados numa sessão real do Claude Code. A compatibilidade com o Claude Code só é afirmada até onde o validador dele aceita os manifestos.
- O adaptador JEV foi verificado contra uma resposta gravada; chamadas reais não foram testadas. Um JEV instalado fora dos diretórios do sistema não é encontrado pelo nome: defina `decision.jev.command` com o caminho absoluto dele (veja o guia de configuração).
- Os mecanismos tirados do artigo de pesquisa são padrões configuráveis cujo efeito não foi medido com um modelo real.
- O roteamento de agentes é uma heurística de correspondência de palavras e pode escolher um agente inadequado; leia o `agent_id` de cada contrato. A classificação depende de sinais que quem chama estima.
- Algumas chaves de configuração não fazem o que o nome sugere: `limits.budget_units` não tem entrada numa execução real, e `context.*` vale só para `wev context compact` e para o harness de avaliação.
- Windows não é suportado (travas de arquivo POSIX).
- Os workflows de CI existem e não concluíram uma execução. Só o Python 3.14 é suportado e testado; interpretadores mais antigos são recusados pelo `bin/wev`. Nada foi executado em Linux.

## Roteiro

Trabalho futuro, nada disso está implementado:

- Hooks para ferramentas além do Bash e uma execução dos hooks existentes dentro de uma sessão real do Claude Code.
- Adaptadores para ambientes de agente além do Claude Code.
- Entrada em YAML para as specs de agentes.
- Avaliação contra modelos reais e qualquer comparação medida entre configurações.
- Suporte a Windows no armazenamento de estado.
- Uma ferramenta de recuperação (recall) exposta ao modelo durante uma sessão.
- Primeiras execuções reais do módulo remoto, começando pelo teste local com tmux e por um host de staging.

O que resta fazer depois da publicação está em "Depois de publicar" em [docs/mvp-status.pt-BR.md](docs/mvp-status.pt-BR.md).

## Créditos

O wev-skills foi escrito por Weverton Juscelino. Baseia-se nos trabalhos a seguir. Nenhum arquivo de terceiros foi copiado para este repositório; o registro de procedência é [docs/THIRD-PARTY.pt-BR.md](docs/THIRD-PARTY.pt-BR.md) e as notas de pesquisa estão em [docs/research/](docs/research/sources.md).

- **addyosmani/agent-skills**, de Addy Osmani, https://github.com/addyosmani/agent-skills. Licença: MIT, "Copyright (c) 2025 Addy Osmani". Estudado no commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe` (2026-10-10). Inspiração arquitetural e convenções compatíveis (`SKILL.md`, agentes no estilo de personas, manifestos de plugin, camadas de avaliação). Nenhum arquivo foi copiado.
- **"An Empirical Study of Harness Design for Coding Agents"**, arXiv:2609.20804 (v1, 17 set 2026), de Run-Ze Fan, Zihao Zhang, Simin Ma, Yebowen Hu, Shouju Wang, Kaiqiang Song, Fei Liu, Hamed Zamani e Xiaoyang Wang, https://arxiv.org/abs/2609.20804. Fonte das hipóteses testáveis por trás dos padrões do harness, tratadas como hipóteses e não como garantias. A licença de reuso não foi verificada, e nenhum texto ou figura é reproduzido.
- **andrej-karpathy-skills**, de forrestchang, https://github.com/forrestchang/andrej-karpathy-skills (a cópia de referência foi https://github.com/multica-ai/andrej-karpathy-skills no commit `2c606141936f1eeef17fa3043a72095b4765b9c2`, verificada em 2026-10-13). Licença: MIT, conforme declarado no README; o repositório não tem arquivo LICENSE. O projeto descreve suas diretrizes como derivadas das observações públicas de Andrej Karpathy sobre armadilhas de programar com LLMs. Fonte do bloco de diretrizes que o `wev claude-md` grava, adaptado com as palavras deste projeto.
- **skill `create-readme` do github/awesome-copilot**, de GitHub, Inc., https://github.com/github/awesome-copilot, caminho `skills/create-readme/SKILL.md`, commit `156736fb63e965b2f547a1460f3b5972c46e6b24` (consultado em 2026-10-13). Licença: MIT, "Copyright GitHub, Inc.". Fonte das ideias por trás do padrão de README da skill `wev-readme`, reescritas com as palavras deste projeto e ampliadas com regras próprias.
- **Especificação Agent Skills**, https://agentskills.io/specification. O formato de arquivo de skill que as skills seguem. A licença não foi verificada, e nenhum texto é reproduzido.
- **Documentação do Claude Code**, publicada pela Anthropic, https://code.claude.com/docs (skills, plugins e marketplaces, subagentes, hooks, modo headless). Consultada para conhecer as interfaces que o plugin, o exportador e os hooks usam. A licença não foi verificada, e nenhum texto é reproduzido.
- **tmux**, https://github.com/tmux/tmux, pelos contribuidores do tmux. Citado para o módulo remoto opcional; nenhum código do tmux é usado, e a licença dele não está registrada neste repositório.

O wev-skills é um projeto independente e não é afiliado nem endossado por nenhum dos projetos, artigos, autores ou organizações listados acima.
