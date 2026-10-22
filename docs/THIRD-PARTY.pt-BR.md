# Procedência de terceiros

Versão em inglês: [THIRD-PARTY.md](THIRD-PARTY.md).

Este arquivo registra de onde veio o material de terceiros e como ele é usado no wev-skills.

O wev-skills não é afiliado, endossado nem patrocinado pela Anthropic, por Addy Osmani nem pelos autores do artigo citado abaixo. Os nomes são usados apenas para identificar as fontes.

## Código reaproveitado

Nenhum. Nenhum arquivo-fonte de terceiros foi copiado para este repositório.

## Material adaptado

| Fonte | Versão | Licença | O que foi adaptado | Onde está |
|---|---|---|---|---|
| andrej-karpathy-skills, `CLAUDE.md`, https://github.com/multica-ai/andrej-karpathy-skills, uma cópia do projeto de forrestchang, https://github.com/forrestchang/andrej-karpathy-skills | Cópia no commit `2c606141936f1eeef17fa3043a72095b4765b9c2`, verificada em 2026-10-13 | O README diz "License: MIT" e o manifesto do plugin diz `"license": "MIT"` com autor `forrestchang`. Não há arquivo LICENSE nem linha de copyright, e a API do GitHub não detecta licença. Os templates citam a declaração MIT do README e nada mais forte | A estrutura de quatro seções (Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution) e a substância de cada ponto, mais a nota de contrapartida e a linha final "working if", reescritas com as palavras deste projeto e traduzidas para o português do Brasil. A seção 5, "Evidence before claims", é original do wev-skills. O projeto de origem descreve as diretrizes como derivadas das observações públicas de Andrej Karpathy sobre armadilhas de programar com LLMs | `src/wev_skills/adapters/claude_code/guidelines/guidelines.en.md` e `guidelines.pt-BR.md`, inseridos nos `CLAUDE.md` dos usuários pelo `wev claude-md`. Justificativa e atribuição em `skills/wev-claude-md/references/guidelines-source.md` |
| skill `create-readme`, `skills/create-readme/SKILL.md`, https://github.com/github/awesome-copilot | Commit `156736fb63e965b2f547a1460f3b5972c46e6b24`, consultado em 2026-10-13 | MIT. "Copyright GitHub, Inc." (do arquivo LICENSE do repositório) | As ideias das regras da skill: revisar o projeto inteiro antes de escrever, um README conciso e atraente, sem seções que repetem arquivos próprios (licença, contribuição, changelog), GitHub Flavored Markdown com a sintaxe de avisos do GitHub e o logo do projeto no cabeçalho. Reescritas com as palavras deste projeto e ampliadas com regras originais do wev-skills (sem emoji, gêmeos em inglês e português do Brasil, créditos por último, rótulos de evidência, um verificador determinístico). Os READMEs de exemplo para os quais a skill aponta não foram baixados | `skills/wev-readme/SKILL.md`, verificado pelo `wev readme check` (`src/wev_skills/adapters/claude_code/readme_check.py`). Atribuição em `skills/wev-readme/references/readme-standard-source.md` |

O texto de cada entrada é uma adaptação, não uma cópia. Não se sugere afiliação com forrestchang, multica-ai, Andrej Karpathy, GitHub, Inc. nem os autores do awesome-copilot, nem endosso por eles.

## Inspiração arquitetural

Ideias e convenções estudadas, não copiadas. Os detalhes estão em [research/agent-skills-reference.pt-BR.md](research/agent-skills-reference.pt-BR.md), [research/harness-design-paper.pt-BR.md](research/harness-design-paper.pt-BR.md) e [research/sources.md](research/sources.md).

| Fonte | Versão | Licença | Como informa o wev-skills |
|---|---|---|---|
| addyosmani/agent-skills, https://github.com/addyosmani/agent-skills | Commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe` (2026-10-10) | MIT. "Copyright (c) 2025 Addy Osmani" | Convenções compatíveis para `SKILL.md`, agentes no estilo de personas, manifestos de plugin e camadas de avaliação. Apenas inspiração arquitetural |
| "An Empirical Study of Harness Design for Coding Agents", arXiv:2609.20804, https://arxiv.org/abs/2609.20804 | v1, enviado em 17 set 2026 | Não verificada. A página do arXiv não foi examinada quanto a uma licença de reuso, e nenhum texto ou figura do artigo é reproduzido | Fonte de hipóteses testáveis sobre gerenciamento de contexto, planejamento e interface de ferramentas. As conclusões são tratadas como hipóteses, não como garantias |
| Felix Rieseberg, "How to be more ambitious: A tutorial for humans with models", https://felixrieseberg.com/how-to-be-more-ambitious-a-tutorial-for-humans-with-models/ | Publicado em 13 out 2026; lido em 2026-10-21 | Não verificada. Nenhum texto do artigo é reproduzido | Só inspiração: os passos de plano mais profundo e revisão mais ampla de `skills/wev-orchestrate/SKILL.md`, o pedido de acesso para verificar e o campo opcional `outcome` do intake foram escritos com as palavras deste projeto |
| Especificação Agent Skills, https://agentskills.io/specification | Sem versão fixada; consultada por uma rodada de pesquisa em 2026-10-13 | Não verificada | O formato de arquivo de skill que as skills do wev-skills seguem |

As páginas da documentação oficial do Claude Code (ver [research/sources.md](research/sources.md)) foram consultadas para conhecer as interfaces. Nenhum texto delas é reproduzido.

## Dependências instaladas

Não incorporadas: nenhum arquivo desses projetos está neste repositório. `wev skills install` os coloca em `$XDG_DATA_HOME/wev-skills/third-party/` a pedido do usuário, e a versão é resolvida na hora da instalação (o release mais novo; veja o [guia de instalação](guides/installation.pt-BR.md#skills-de-terceiros-instalar-verificação-diária-atualizar-reverter-congelar)). O `agent-skills` é baixado como tarball do GitHub; para o `rea` o wev não baixa nada, registra a versão e o `npx` busca o pacote no cache do npm durante a verificação de saúde.

| Fonte | Versão | Licença | Uso |
|---|---|---|---|
| `rea-agents`, https://www.npmjs.com/package/rea-agents (releases em https://github.com/morluto/rea) | Resolvida na instalação (`dist-tags.latest`) | MIT | `wev skills show rea` imprime o argv que inicia seu servidor MCP; o wev só o inicia por conta própria na verificação de saúde |
| addyosmani/agent-skills, https://github.com/addyosmani/agent-skills | Resolvida na instalação (release mais novo) | MIT, "Copyright (c) 2025 Addy Osmani" | Skills ligadas aos diretórios de skills do usuário por `wev skills activate` |

Tanto o `rea` (`morluto/rea`) quanto o `agent-skills` (`addyosmani/agent-skills`) são MIT segundo o `license.spdx_id` da API do GitHub, conferido em 2026-10-20 e 2026-10-22. Essa é a licença do repositório, não os metadados do pacote npm. A linha de copyright do agent-skills é "Copyright (c) 2025 Addy Osmani". Nenhuma afiliação com os autores desses projetos nem endosso por eles é sugerido.

## Regra para adicionar arquivos de terceiros

Antes de adicionar a este repositório qualquer arquivo, trecho, schema, prompt ou conjunto de dados de terceiros, quem contribui deve:

1. Identificar a licença e confirmar que ela é compatível com a licença deste projeto, a PolyForm Noncommercial License 1.0.0 (veja [LICENSE](../LICENSE)). Material sob uma licença permissiva como a MIT é compatível quando seus avisos são mantidos. Se a licença estiver ausente, pouco clara ou incompatível, não adicione o arquivo.
2. Preservar os avisos originais de copyright e de licença no arquivo ou ao lado dele, e acrescentar uma entrada no `NOTICE` quando a licença exigir.
3. Registrá-lo neste arquivo na mesma alteração: URL da fonte, commit ou versão, licença, linha de copyright, arquivos afetados e se o uso é reaproveitamento, adaptação (o que mudou) ou inspiração.
4. Nunca sugerir afiliação com o autor ou a organização da fonte, nem endosso por eles.

Uma alteração que adiciona material de terceiros sem a entrada correspondente aqui não deve ser incorporada.

## Referência externa de manutenção

[skill-repo-skill](https://github.com/netresearch/skill-repo-skill), da Netresearch DTT GmbH,
versão 2.4.0 no commit `42a5e85798a8cdfda2866afb0de9aadb04e187f3`, consultada em 2026-10-13,
é uma dependência externa para orientação estrutural. Copyright (c) 2025-2026
Netresearch DTT GmbH. Conteúdo: CC-BY-SA-4.0; scripts/configuração: MIT. Os arquivos são
instalados separadamente e não são redistribuídos neste repositório. A skill original
`skills/wev-skill-maintenance/`, licenciada com o restante do wev-skills, coordena revisão e exceções locais; registra a procedência em
`references/upstream.json` e aponta para o guia sem copiar suas instruções ou scripts.
Esta referência não migra licença, marca, dependências do motor nem CI do projeto.
Não implica afiliação nem endosso.
