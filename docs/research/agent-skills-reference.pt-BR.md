# Referência: addyosmani/agent-skills

Versão em inglês: [agent-skills-reference.md](agent-skills-reference.md).
Fonte: https://github.com/addyosmani/agent-skills no commit `1be8e34187e34647bb83adc3a1323b26ae6f6abe` (data do commit 2026-10-10), licença MIT, "Copyright (c) 2025 Addy Osmani" (`LICENSE`). Consultado em 2026-10-13. Os caminhos abaixo são relativos a esse repositório.

**Até a data desta escrita, nenhum arquivo daquele repositório foi copiado para o wev-skills.** A relação é de inspiração arquitetural e de convenções compatíveis. O wev-skills não é afiliado nem endossado pelo autor. A procedência é registrada em [../THIRD-PARTY.md](../THIRD-PARTY.md).

O que foi lido: `docs/skill-anatomy.md`, `CONTRIBUTING.md`, `evals/README.md`, `docs/agents.md`, `agents/code-reviewer.md` (e o frontmatter das outras três personas), `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, o `plugin.json` da raiz, o cabeçalho e a configuração de `scripts/lib/skill-lint.js`, os cabeçalhos de `scripts/validate-commands.js` e `scripts/validate-artifact-paths.js`, o início de `scripts/validate-versions.js` e uma skill (`skills/test-driven-development/SKILL.md`). Não lidos: `scripts/validate-skills.js`, `scripts/validate-reference-links.js`, `scripts/run-evals.js`, os hooks e as outras 24 skills. O que se diz abaixo sobre esses arquivos vem de referências a eles nos arquivos que foram lidos.

## O que foi aprendido

**Convenções do SKILL.md** (`docs/skill-anatomy.md`, `scripts/lib/skill-lint.js`).
- Cada skill é um diretório `skills/<name>/` com um `SKILL.md` obrigatório; `scripts/` e `references/` são opcionais e não devem ser criados vazios.
- Frontmatter: `name` e `description` são obrigatórios. As chaves de nível superior permitidas são exatamente `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` (`SPEC_FRONTMATTER_KEYS` em `skill-lint.js`); chaves de fornecedor como `model` ou `max_turns` ficam em `metadata` ou em um arquivo adaptador por agente. O linter trata outras chaves como erro.
- `name` deve ser igual ao nome do diretório e escrito em minúsculas com hífens (`KEBAB_CASE` em `skill-lint.js`).
- `description` tem no máximo 1024 caracteres (`MAX_DESCRIPTION_LENGTH`). Diz o que a skill faz na terceira pessoa e depois traz um gatilho "Use when ...". O linter aceita "use when" e "use before/after/during" e rejeita formas negadas. O documento de anatomia diz para não resumir o fluxo na descrição, porque o agente pode seguir o resumo em vez de ler a skill.
- Seções do corpo: Overview, When to Use, um processo central, Common Rationalizations, Red Flags, Verification. O documento de anatomia chama o layout de recomendado; o linter lista cinco delas (`REQUIRED_SECTIONS`: Overview, When to Use, Common Rationalizations, Red Flags, Verification) como obrigatórias, com uma tabela documentada de isenções.
- Economia de contexto: `SKILL.md` com menos de 500 linhas (aviso do linter, `MAX_SKILL_LINES`), divulgação progressiva, referências a um nível de profundidade, arquivos de apoio só quando o conteúdo passa de cerca de 100 linhas.
- Checklists compartilhados ficam em um diretório `references/` na raiz do repositório. O próprio documento observa que uma instalação por skill os perde (issue #361 daquele repositório).
- "Write the Procedure, Not the Workaround": um passo que só se justifica citando um modelo ou o nome privado de uma ferramenta não pertence a uma skill.

**Personas** (`agents/*.md`, `docs/agents.md`). Quatro arquivos Markdown (`code-reviewer`, `security-auditor`, `test-engineer`, `web-performance-auditor`) com frontmatter `name` e `description` e um corpo que funciona como prompt de sistema. O `docs/agents.md` afirma que o usuário ou um comando de barra é o orquestrador e que personas não chamam outras personas.

**Manifestos de plugin e marketplace do Claude Code.** O `.claude-plugin/plugin.json` traz `name`, `version`, `description`, `author`, `homepage`, `repository`, `license`, `commands`, `skills` e `experimental.evals`. O `.claude-plugin/marketplace.json` traz `$schema`, `name`, `description`, `owner` e um array `plugins` cuja entrada tem uma `source` do GitHub. O `scripts/validate-versions.js` confere que a versão coincide em cinco manifestos. A lista autoritativa de campos é a referência oficial de manifesto (ver [sources.md](sources.md)), que não foi relida para este arquivo.

**Scripts de validação e níveis de avaliação** (`evals/README.md`). O Nível 1 é estrutural (frontmatter, nomes, seções obrigatórias, paridade de comandos). O Nível 2 é uma checagem lexical determinística de roteamento (TF-IDF com stemming sobre as descrições) que testa se prompts positivos classificam a skill certa e se duas descrições colidem. O Nível 3 é comportamental: roda um `claude` headless em um repositório git descartável e avalia o rastro, o que gasta tokens e roda sob demanda. Um caminho separado, `claude plugin eval`, pontua casos com e sem o plugin. Cada skill precisa de `evals/cases/<skill>.json` com pelo menos 3 gatilhos positivos, 2 negativos e 1 avaliação comportamental (`CONTRIBUTING.md`). Aquele repositório publica seus próprios números de roteamento nos próprios documentos; nenhum é reaproveitado aqui.

**Política de contribuição** (`CONTRIBUTING.md`, "Translations"). Traduções da documentação e das skills não são aceitas; tudo fica em inglês para evitar divergência.

## Como o wev-skills se relaciona com ele

| O wev-skills adota como convenção | O wev-skills faz diferente, e por quê | O wev-skills não adota |
|---|---|---|
| `skills/<name>/SKILL.md` como ponto de entrada, `name` igual ao nome do diretório, minúsculas com hífens | Documentação bilíngue para usuários (inglês e português do Brasil) com uma implementação compartilhada, como o projeto exige (`CLAUDE.md`); o upstream rejeita traduções para evitar divergência, então o wev-skills precisa manter os pares sincronizados por conta própria | As 25 skills e seu conteúdo; o wev-skills tem domínio próprio (orquestração) e nada é copiado |
| Frontmatter limitado às chaves da especificação Agent Skills; configurações de fornecedor em `metadata` ou em um adaptador | Um motor em Python aplica regras em código (permissões, aprovações, guardas, estado). As skills do upstream são principalmente instruções em Markdown, que um modelo pode ignorar | Comandos de barra e hooks para muitos hosts (`.gemini`, `.opencode` e outras integrações de host); o wev-skills mira primeiro o Claude Code e mantém o núcleo independente de host |
| `description` com até 1024 caracteres, terceira pessoa, com gatilho "Use when", sem resumo do fluxo | Agentes são definidos por YAML ou JSON versionado e validado por esquema, na configuração, não por arquivos Markdown de persona, então personas não exigem mudança de código | O registro de rejeição de mudanças em skills (`evals/skill-impact.md`) e a exigência de casos de avaliação por skill na forma atual |
| `SKILL.md` enxuto (menos de 500 linhas), divulgação progressiva, referências a um nível de profundidade | A delegação passa pelo orquestrador com um contrato de tarefa (objetivo, escopo, critérios de aceitação, permissões); o upstream deixa a orquestração ao usuário ou a um comando | `references/` compartilhado na raiz, fora do diretório da skill, por causa da lacuna de portabilidade que o próprio upstream documenta; o wev-skills pretende manter cada skill autocontida (a confirmar) |
| "Personas não chamam outras personas"; sem invocação recursiva de agentes | As avaliações incluem um harness determinístico com agente roteirizado para a mecânica do motor, além de checagens de gatilho e comportamentais | A política de contribuição só em inglês |
| Validação como código: biblioteca de linter com testes unitários, rodando no CI (padrão de `scripts/lib/skill-lint.js`) | Os validadores devem ser código Python da biblioteca padrão, como o motor em `docs/architecture/architecture.md` (ainda não implementado); o upstream usa scripts Node | Qualquer número medido de roteamento ou de impacto do upstream |
| Seção Verification orientada a evidências em cada skill; três níveis de avaliação (estrutural, roteamento, comportamental) | Testes unitários e CI rodam sem modelo pago; avaliações com provedor real são opcionais | |
| Manifestos de plugin e de marketplace para distribuição no Claude Code | Os manifestos são escritos conforme a referência oficial de manifesto; nenhuma compatibilidade com plataforma é declarada antes de existirem adaptador e teste de integração (restrição do projeto) | |

As linhas listam itens independentes; não formam pares entre as colunas.

## Questões em aberto

- Se o wev-skills exige as mesmas cinco seções de corpo ou um subconjunto. Não decidido.
- Se será usado o layout de referências compartilhadas ou `references/` por skill. Por skill é a intenção, ainda não implementada.
- O upstream cita o "WikiSkill" (arXiv:2608.27454) para a afirmação de que skills escritas contra as falhas de um modelo podem prejudicar modelos mais fortes. Esse artigo não foi lido para este registro, então a afirmação não é usada aqui como base.
