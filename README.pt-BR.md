# wev-skills

Um motor de orquestração, com código-fonte disponível, para quem quer que agentes de programação com IA planejem, executem e relatem trabalho com evidências de verificação registradas.

[English](README.md) · [Instalação](docs/guides/installation.pt-BR.md) · [Arquitetura](docs/architecture/architecture.pt-BR.md) · [Exemplos](examples/README.md)

[![CI](https://github.com/wevertonjuscelino/wev-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/wevertonjuscelino/wev-skills/actions/workflows/ci.yml)
[![Python 3.14+](https://img.shields.io/badge/python-3.14%2B-blue)](pyproject.toml)
[![License: PolyForm Noncommercial 1.0.0](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-green)](LICENSE)
[![Status: alpha](https://img.shields.io/badge/status-alpha-orange)](CHANGELOG.md)

O motor Python, feito só com a biblioteca padrão, oferece a CLI JSON `wev`. Um plugin para Claude Code conecta o motor a skills, subagentes e hooks. Contratos de tarefa, estado retomável e rótulos de evidência permitem inspecionar o trabalho; o motor impõe as regras que código consegue verificar.

## Status

> [!IMPORTANT]
> A versão <!-- wev:version -->5.0.0<!-- /wev:version --> é um lançamento alfa. A CLI e o formato do plugin têm testes automatizados; uma sessão real do Claude Code, execução remota real e avaliação da qualidade dos modelos seguem sem validação. Não há pacote no PyPI nem entrada em marketplace oficial. O badge de CI leva aos resultados atuais do workflow.

| Capacidade | Evidência | Limite prático |
|---|---|---|
| Planos, contratos de tarefa, estado, retomada e relatórios de entrega | Implementado e testado | Testes locais não usam modelo |
| Permissões, aprovações de uso único e portões de verificação | Implementado e testado | Heurísticas e registros de auditoria; sem sandbox |
| Registro de agentes, herança e exportação de subagentes | Implementado e testado | Agentes exportados não foram carregados em sessão real |
| Entrevista de objetivo: até três perguntas por rodada | Implementado e testado | CLI local e briefs armazenados; entrevista conduzida por modelo não validada |
| Especialistas de projeto, experiência limitada e orçamento de execução | Implementado e testado | Só registros do motor; lições consultivas; unidades de comando, não tokens ou dinheiro |
| Skills, hooks e manifestos do plugin | Implementado e testado | Testes de formato e subprocesso; integração real não testada |
| Adaptadores opcionais JEV, SSH/tmux e avaliação | Simulado com mocks | Uma resposta JEV gravada e hosts remotos simulados |
| Codex, Gemini CLI e OpenCode: exportação do pacote, instalação, desinstalação, codecs dos hooks | Implementado e testado com CLIs de harness falsas; ainda não executado contra os harnesses reais (parte e2e) | Um ask de política vira allow mais aviso nesses harnesses; veja [SECURITY.pt-BR.md](SECURITY.pt-BR.md) |
| rea (servidor MCP de engenharia reversa de terceiros): `wev rea` (serve, status, mode, build-image), imagem de contêiner, registro por harness | Implementado e testado com executáveis `npx` e `docker` falsos (testes unitários); o servidor rea real, o build real do contêiner e os carregadores reais dos harnesses não são executados nesta alteração (parte e2e). A skill `wev-reverse` está apenas documentada | O rea diz que "not a sandbox" (não é um sandbox); veja [SECURITY.pt-BR.md](SECURITY.pt-BR.md#rea-servidor-de-engenharia-reversa) |
| Outros ambientes de agentes e suporte a Windows | Apenas documentado / bloqueado | Adaptadores futuros; travas de arquivo POSIX hoje |

Execução de ponta a ponta de 2026-10-22: a rota de fonte local do instalador passou em 13 de 13 verificações no macOS com HOME isolado (não uma máquina limpa); os cenários de Linux e Docker foram pulados e nenhum cenário de harness rodou. Veja [Testes de ponta a ponta](docs/guides/installation.pt-BR.md#testes-de-ponta-a-ponta) e [o relatório](evals/reports/e2e-2026-10-22.md). As evidências detalhadas de aceitação estão no [status do MVP](docs/mvp-status.pt-BR.md). A [revisão local de segurança de 2026-10-13](docs/security-review-2026-10-13.pt-BR.md) registra achados e escopo; é uma revisão interna, não uma certificação.

## Requisitos

- **Python 3.14+** em macOS ou Linux, e **Git**. O motor não tem dependências de execução.
- **Claude Code** para usar o plugin. A CLI funciona de forma independente.
- Opcionais: `ssh` e `tmux` para operações remotas; `ruff` e `mypy`, ou `uvx`, para lint.

Confira `python3 --version` antes de usar o plugin. Interpretadores antigos não são suportados, e os hooks podem sair sem verificar comandos quando o Python é antigo demais. Windows não é suportado.

## Início rápido

Instalação guiada (faz algumas perguntas e depois registra o wev-skills, as skills de terceiros e os harnesses que você escolher; implementada e testada com CLIs de harness falsas e uma fonte local, ainda não executada na rota de download nem nos harnesses reais). A partir de um clone:

```sh
bash install.sh
```

Depois que o dono publicá-la (apenas documentado): `curl -fsSL https://raw.githubusercontent.com/wevertonjuscelino/wev-skills/main/install.sh | bash`. Só no Claude Code, pelo repositório publicado como marketplace (apenas documentado, não executado): `/plugin install wev-skills --marketplace wevertonjuscelino/wev-skills`. Flags, o que grava e a desinstalação estão no [guia de instalação](docs/guides/installation.pt-BR.md#instalação-rápida).

Ou à mão: clone o repositório público e localize a CLI. Estes comandos de clone são o passo de instalação de quem lê e não foram executados durante esta revisão da documentação:

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
cd wev-skills
export WEV_HOME="$PWD"
"$WEV_HOME/bin/wev" --help
```

O exemplo somente de leitura a seguir foi executado localmente em 2026-10-13. Usa a política local padrão, não chama modelos nem altera arquivos do projeto:

```text
$ bin/wev classify --objective 'Add a greeting file' --files 1
{
  "complexity": "trivial",
  "risk": "low",
  "uncertainty": 0.0,
  "parallelizable": false,
  "reasons": [
    "Low risk: no risk rule fired.",
    "Trivial: at most one file, no unknowns, a single piece of work."
  ],
  "source": "local-policy"
}
```

Para uma sessão com o plugin, execute o seguinte passo de quem lê (sessão real não validada):

```sh
claude --plugin-dir "$WEV_HOME"
```

O [guia de instalação](docs/guides/installation.pt-BR.md) cobre instalação persistente do plugin, atualizações e remoção. O [guia de orquestração](docs/guides/orchestration.pt-BR.md) mostra como iniciar uma execução, executar tarefas, registrar verificações e gerar um relatório.

A entrada de objetivos está documentada no [guia de entrevista](docs/guides/intake.pt-BR.md). Papéis de projeto, experiência baseada em evidência e os limites de 80%/100% do orçamento de comandos estão no [guia de especialistas](docs/guides/specialists.pt-BR.md).

## Recursos e documentação

| Área | Guia | Skill |
|---|---|---|
| Plano → tarefa → executar → verificar → relatar; retomada e guardas de execução | [Orquestração](docs/guides/orchestration.pt-BR.md) | `wev-orchestrate` |
| Specs JSON de agentes, templates, herança e tetos de permissão | [Criando agentes](docs/guides/creating-agents.pt-BR.md) | `wev-agent-builder` |
| Avaliação determinística da mecânica do harness | [Avaliação](docs/guides/evaluation.pt-BR.md) | `wev-harness-evaluation` |
| SSH com inventário e sessões tmux pertencentes à tarefa | [Operações remotas](docs/guides/remote-ops.pt-BR.md) | `wev-remote-ops` |
| Engenharia reversa com evidências usando as ferramentas rea (plano de mudança ou especificação clean-room) | [Skill](skills/wev-reverse/SKILL.md) | `wev-reverse` |
| Diretrizes gerenciadas de projeto no `CLAUDE.md` | [Skill de diretrizes](skills/wev-claude-md/SKILL.md) | `wev-claude-md` |
| Verificações de READMEs bilíngues | [Padrão de README](skills/wev-readme/SKILL.md) | `wev-readme` |
| Skills, hooks de guarda e agentes para Codex, Gemini CLI e OpenCode | [Instalação: Codex, Gemini CLI e OpenCode](docs/guides/installation.pt-BR.md#codex-gemini-cli-e-opencode) | CLI `wev harness` |
| Atualizações revisadas de fontes e conciliação de conflitos | [Política de manutenção](skills/wev-skill-maintenance/references/policy.pt-BR.md) | `wev-skill-maintenance` |
| Instalar, verificar diariamente, atualizar, reverter e congelar skills de terceiros | [Instalação: skills de terceiros](docs/guides/installation.pt-BR.md#skills-de-terceiros-instalar-verificação-diária-atualizar-reverter-congelar) | CLI `wev skills` |

Harnesses: o Claude Code usa o plugin; Codex, Gemini CLI e OpenCode recebem as skills e o guarda por `wev harness install --target <nome>`.

Configuração, decisões locais e o provedor JEV opcional de terceiros estão documentados em [configuração e provedores](docs/guides/configuration-and-providers.pt-BR.md). As skills instruem o agente; o código do motor impõe transições de tarefa e regras de verificação ([ADR 0002](docs/architecture/decisions/0002-engine-enforces-skills-instruct.pt-BR.md)).

```text
src/wev_skills/   Python engine, CLI and adapters
skills/          Agent instructions
agent-specs/     Source JSON specifications for agents
agents/          Generated Claude Code subagents
hooks/           Plugin integration
tests/          Unit, integration and security tests
docs/           Guides, architecture, evidence and provenance
examples/       Sample configuration and task contracts
```

Arquivos do projeto: [contribuição](CONTRIBUTING.pt-BR.md), [política de segurança](SECURITY.pt-BR.md), [changelog](CHANGELOG.md), [código de conduta](CODE_OF_CONDUCT.md), [licença](LICENSE) e [NOTICE](NOTICE). Materiais externos e condições próprias de licença estão registrados na [procedência de terceiros](docs/THIRD-PARTY.pt-BR.md).

O wev-skills é de código-fonte disponível, e não open source no sentido da Open Source Initiative (OSI). A partir do próximo release (3.0.0), ele é licenciado sob a [PolyForm Noncommercial License 1.0.0](LICENSE): qualquer pessoa pode usá-lo, alterá-lo e redistribuí-lo para qualquer finalidade não comercial, e o uso comercial é proibido. Tudo o que foi publicado antes da mudança continua sob a licença MIT: os releases 1.0.0 a 2.0.0 e os commits até `577a6f6`. Material de terceiros mantém a própria licença.

## Verificação

```sh
make test
make lint
bin/wev readme check
```

Os testes usam `unittest` da biblioteca padrão, fixtures falsas e nenhum modelo pago ou host remoto real. O lint verifica regras e formatação com Ruff, além de mypy estrito. Ferramentas ausentes podem ser puladas: inspecione a saída antes de afirmar que o lint passou. Os testes de integração com tmux são pulados quando ele não está disponível.

A referência local anterior registrada (2026-10-13, Python 3.14.7) foi de **2076 testes, 8 pulados**, com mypy estrito relatando **146 arquivos-fonte sem problemas**. Isso é evidência histórica, não uma afirmação de que o checkout atual passou; veja o [status do MVP](docs/mvp-status.pt-BR.md) e as [execuções de CI](https://github.com/wevertonjuscelino/wev-skills/actions/workflows/ci.yml) para os registros de validação.

## Limitações

> [!WARNING]
> Este motor não é uma fronteira de segurança contra um agente adversário executado como o mesmo usuário. Comandos permitidos herdam as permissões desse usuário, e o estado pode ser reescrito. Use isolamento do sistema operacional quando precisar de uma fronteira real de confiança.

- A classificação de comandos e o mascaramento de segredos são heurísticas. Scripts e interpretadores podem fazer mais do que a linha de comando revela.
- A configuração do repositório pode habilitar helpers Git até em comandos de leitura; consulte a [revisão de segurança](docs/security-review-2026-10-13.pt-BR.md) antes de trabalhar com repositórios desconhecidos.
- Aprovações oferecem atrito e trilha de auditoria, não autenticação humana; um processo pode emular um terminal.
- A imposição do plugin vê chamadas Bash que passam por seus hooks. Edições pelas ferramentas nativas de arquivo ficam fora dessas verificações.
- Verificações aprovadas provam que os checks registrados executaram com sucesso, não que os critérios de aceitação ou os testes sejam suficientes.
- JEV é opcional e vem desligado. Quando habilitado, envia dados da tarefa a terceiros; revise a política do provedor antes de habilitar.
- A avaliação usa um agente roteirizado, então não mede qualidade de modelos. Operações remotas têm apenas evidência de hosts simulados.
- `limits.budget_units` não tem entrada em execução real. As configurações de contexto valem para o gerenciador de contexto da CLI e o harness de avaliação, não para o contexto do próprio Claude Code.

## Roteiro

Trabalho futuro, não implementado ou validado:

- Exercitar skills, agentes exportados e hooks em uma sessão real do Claude Code.
- Validar tmux local e um host SSH de staging; avaliar com modelos reais.
- Adicionar adaptadores para outros ambientes de agentes e suporte a travas de estado no Windows.
- Ampliar a cobertura dos hooks além de Bash e expor recuperação de contexto durante uma sessão de agente.

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
