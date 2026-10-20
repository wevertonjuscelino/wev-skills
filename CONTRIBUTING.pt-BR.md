# Contribuindo com o wev-skills

English version: [CONTRIBUTING.md](CONTRIBUTING.md).

Obrigado por considerar uma contribuição. Este guia cobre a configuração do ambiente, as regras que os revisores aplicam e o checklist de pull requests. Ao participar, você concorda com o [Código de Conduta](CODE_OF_CONDUCT.md). Problemas de segurança seguem o [SECURITY.pt-BR.md](SECURITY.pt-BR.md), não issues públicas.

## Configuração do ambiente

1. Clone <https://github.com/wevertonjuscelino/wev-skills> (`git clone https://github.com/wevertonjuscelino/wev-skills.git`) e entre nele.
2. Use Python 3.14 ou mais recente (`python3 --version`). Interpretadores mais antigos, inclusive o `/usr/bin/python3` original do macOS (3.9), não são suportados.
3. Não há nada para instalar para rodar os testes. O engine usa apenas a biblioteca padrão.
4. Rode a suíte completa de testes:

   ```
   make test
   ```

5. Rode `make lint`. Ele executa `ruff check`, `ruff format --check` (em `src`, `tests` e `scripts`) e `mypy` em `src/wev_skills`. Usa `ruff` e `mypy` do `PATH` quando existirem, senão os roda por `uvx` (nada é instalado no projeto), e senão avisa e pula a ferramenta ausente. `make format` aplica `ruff format`; `make check` roda testes e lint. Não adicione essas ferramentas às dependências de runtime do projeto.

6. Habilite os git hooks do repositório uma vez por clone com `make hooks`. Ele roda `git config core.hooksPath .githooks`, que muda só a configuração local deste clone. Os hooks são scripts `sh` POSIX que precisam só de `git` e `python3`:

   - `commit-msg` confere o assunto do commit (veja "Mensagens de commit").
   - `pre-commit` rejeita arquivos com nomes privados (arquivos de chave privada, arquivos dot-env, armazenes de certificado e de chave, nomes de chave SSH, JSON de credenciais) e arquivos acima de 1 MiB, e então roda `python3 scripts/scan_secrets.py --staged`.
   - `pre-push` roda `make test` e `make lint`, e recusa um push para `main` enquanto houver alterações não commitadas em arquivos rastreados.

   `git commit --no-verify` e `git push --no-verify` os ignoram, e o CI roda as mesmas verificações no servidor. Os hooks são uma conveniência e um alarme, não um controle.

Para rodar um único módulo de teste:

```
PYTHONPATH=src python3 -m unittest tests.unit.test_schema -v
```

## Regras que os revisores aplicam

- **Apenas biblioteca padrão em runtime.** Nenhuma dependência de runtime entra sem justificativa escrita e concordância do mantenedor. Ferramentas de teste e lint são extras opcionais, não dependências de runtime.
- **Todo módulo tem testes, e os testes falham quando o comportamento quebra.** Antes de enviar uma mudança, quebre o comportamento de propósito e confirme que algum teste falha. Testes unitários e o CI devem rodar sem provedor de modelo pago nem host remoto real; use mocks ou os fixtures simulados em `tests/fixtures/`.
- **Regras de segurança vivem no código, e as afirmações sobre elas são modestas.** Uma regra que existe só em um arquivo Markdown ou em um prompt não é um controle. Trate conteúdo de repositório, logs, saída de ferramentas e arquivos remotos como dados não confiáveis. O engine é uma proteção contra erros de um agente falível, não uma fronteira de segurança contra um agente adversário ([ADR 0006](docs/architecture/decisions/0006-guardrail-not-boundary.pt-BR.md)): não escreva "impede", "garante" ou "assegura" sobre um controle que um agente na mesma conta de usuário pode desfazer, e diga o que um controle não cobre.
- **Textos voltados ao usuário passam pelo i18n.** Adicione a chave aos arquivos de locale `en` e `pt-BR` em `src/wev_skills/locales/`, com conjuntos de chaves idênticos. Não escreva texto voltado ao usuário direto nos módulos.
- **A documentação existe nos dois idiomas.** Uma mudança em um documento em inglês vem acompanhada da mudança equivalente no arquivo `.pt-BR.md`. A versão em português tem a mesma estrutura e mantém identificadores de código e comandos em inglês.
- **Sem diretórios vazios e sem módulos placeholder.** Adicione um arquivo quando ele tiver conteúdo real e um teste ou um uso.
- **Nenhuma afirmação sem evidência.** Descreva o estado de cada trabalho com um destes rótulos, mantidos em inglês: implemented and tested; implemented but untested; simulated with mocks; documented only; blocked. Não afirme melhoria medida sem resultados medidos, e não afirme compatibilidade com uma plataforma sem um adaptador e um teste de integração para ela.

## Como adicionar itens

### Uma spec de agente

1. Copie um template de `agent-specs/templates/` (por exemplo `base.json`) ou um exemplo de `agent-specs/examples/`.
2. Preencha os campos e valide contra `src/wev_skills/schemas/agent.schema.json`. Specs são dados; adicionar uma persona não deve exigir mudanças no código-fonte.
3. Adicione ou amplie um teste (veja `tests/unit/test_agent_catalog.py` e `tests/unit/test_agents_spec.py`) para que a nova spec seja carregada e validada.
4. Se ela deve ser exportada como subagente do Claude Code, confira o arquivo exportado com os testes existentes do adaptador.

### Um skill

O repositório traz seis skills: `wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md` e `wev-readme`. Quando um comando, flag, código de saída ou regra que uma skill descreve mudar, atualize a skill correspondente na mesma mudança.

1. Crie `skills/<nome-do-skill>/SKILL.md` no formato Agent Skills: um arquivo de entrada enxuto com frontmatter, com o material longo em arquivos referenciados e carregados só quando necessário.
2. Mantenha as instruções coerentes com o que o engine realmente faz. Não descreva comandos que não existem; confira `wev --help` e a ajuda de cada subcomando.
3. Garanta que os testes de validação de skills o aceitem: `PYTHONPATH=src python3 -m unittest tests.unit.test_skills -v` confere cada comando e flag que uma skill mostra contra a CLI.
4. Comandos do operador humano (`approval grant`, `approval deny`, `guard acknowledge`, `task reopen`) nunca são algo que um agente executa. Descreva-os como o passo do operador, digitado no terminal da própria pessoa.

### Uma tarefa de eval

1. Adicione a tarefa em `evals/` seguindo o layout já usado ali.
2. Evals devem ser determinísticos e rodar com o agente roteirizado, sem provedor pago.
3. Adicione ou atualize um teste que execute a tarefa pelo harness.

### Uma chave de locale

1. Escolha uma chave com o prefixo do módulo, por exemplo `security.error.<nome>`.
2. Adicione-a ao arquivo `en` e ao arquivo `pt-BR` do módulo em `src/wev_skills/locales/`, com os mesmos placeholders.
3. Use-a por meio de `i18n.t("<chave>", **params)`.
4. Rode `make test`; os testes comparam os conjuntos de chaves dos dois locales.

## Padrões de README e CLAUDE.md

- `README.md` e `README.pt-BR.md` mantêm a mesma estrutura e dizem apenas o que o código e os testes sustentam. As linhas de status usam os rótulos de evidência; não declare resultado medido que nenhuma execução produziu. `tests/unit/test_docs.py` confere a paridade das versões, os links relativos e que os créditos vêm por último.
- O `CLAUDE.md` de um projeto que usa o wev-skills tem um bloco de diretrizes gerenciado entre os marcadores `<!-- wev-skills:guidelines:start v1 -->` e `<!-- wev-skills:guidelines:end -->`. Altere-o com `wev claude-md init|update` (use `--dry-run` para ver o diff), confira com `wev claude-md check` (saída 2 quando algo falta ou está desatualizado) e edite só fora dos marcadores. A skill `wev-claude-md` cobre as seções ao redor do bloco.

## Material de terceiros

Antes de adicionar qualquer arquivo, trecho, schema, prompt ou dataset de terceiros:

1. Verifique a licença e confirme que ela é compatível com a distribuição sob a licença deste projeto, a [PolyForm Noncommercial License 1.0.0](LICENSE).
2. Preserve os avisos de copyright e de licença.
3. Registre em [docs/THIRD-PARTY.md](docs/THIRD-PARTY.md) (e em `NOTICE` quando a licença exigir), indicando se é inspiração, adaptação ou reuso.

Não copie material por inteiro e não sugira afiliação com outro projeto ou empresa.

## Mensagens de commit

```
<type>: <description>

<optional body>
```

Tipos: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`. Um escopo é permitido: `fix(hooks): ask before a recursive delete`. O assunto tem no máximo 72 caracteres e não termina com ponto; o hook `commit-msg` confere isso (commits de merge e de revert gerados pelo git são aceitos). Não liste ferramentas como autoras ou coautoras.

Trabalhe em um branch criado a partir de `dev` e abra um pull request **para `dev`** em <https://github.com/wevertonjuscelino/wev-skills/pulls>; pull requests para `main` só são aceitos vindos de `dev` (o check `source-branch` falha caso contrário). O título do pull request deve seguir `<type>(<scope>): <description>` com tipo `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build` ou `security` e escopo opcional (o check `pr-title`); ele vira a linha do changelog. Os pull requests são mesclados com um commit de merge.

As versões são calculadas a partir do histórico do git: `X` conta as releases em `main`, `Y` conta os pull requests mesclados em `dev` desde a última release e `Z` conta os commits do pull request em andamento. Você nunca edita um número de versão nem as seções de release do changelog; o workflow de release faz isso quando `dev` é mesclado em `main`. O [guia de manutenção](docs/guides/maintaining.pt-BR.md) tem o fluxo completo e um exemplo. Relate bugs e peça funcionalidades em <https://github.com/wevertonjuscelino/wev-skills/issues>.

## Checklist de pull request

- [ ] A mudança é focada e está descrita no resumo do pull request
- [ ] Testes foram adicionados, e eles falham quando o comportamento quebra
- [ ] `make test` passa localmente; `make lint` foi executado se `ruff` e `mypy` estiverem disponíveis
- [ ] Textos voltados ao usuário usam i18n, e os conjuntos de chaves `en` e `pt-BR` são idênticos
- [ ] A documentação está atualizada nos dois idiomas
- [ ] Nenhuma nova dependência de runtime
- [ ] Registro de terceiros atualizado se material de terceiros foi adicionado
- [ ] Nenhum segredo, token ou dado privado no diff
- [ ] Nenhum diretório vazio ou módulo placeholder
- [ ] Cada afirmação tem um rótulo de evidência (implemented and tested, implemented but untested, simulated with mocks, documented only, blocked)
