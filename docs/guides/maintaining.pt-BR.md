# Manutenção do repositório

English version: [maintaining.md](maintaining.md).

Este guia é para o dono e para quem faz merge de mudanças: o formato dos commits, o fluxo de branches e pull requests, como fazer um lançamento e a configuração pretendida do GitHub, que não pode ser definida pela árvore de trabalho. O repositório é <https://github.com/wevertonjuscelino/wev-skills>. A seção de configurações é a fonte de verdade de como o repositório deve ser configurado; é apenas documentada, e uma configuração só conta como aplicada depois que alguém a confirma no GitHub.

## Formato dos commits

```
<type>: <description>
<type>(<scope>): <description>
```

Tipos: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`. O assunto tem no máximo 72 caracteres e não termina com ponto. Commits de merge e de revert gerados pelo git são aceitos. O hook `commit-msg` em `.githooks/` confere isso depois do `make hooks` (veja o [CONTRIBUTING.pt-BR.md](../../CONTRIBUTING.pt-BR.md)). Não nomeie nenhuma ferramenta como autora ou coautora e não adicione trailer de coautoria.

## Branches e pull requests

1. Trabalhe em um branch, nunca na `main`: `git switch -c <type>/<short-name>`.
2. Envie o branch e abra um pull request contra a `main`. Preencha o modelo de pull request, inclusive o rótulo de evidência de cada afirmação.
3. Espere os checks do CI passarem (`test` no Ubuntu e no macOS, `lint`, `skills`, `git hooks and documents`, `secrets-scan`). O CODEOWNERS pede a revisão do dono.
4. Faça o merge com squash ou rebase, para que a `main` mantenha um histórico linear de assuntos de commit bem formados. No squash, o título do pull request vira o assunto e precisa seguir o formato dos commits.
5. Com a proteção de branch ligada, ninguém envia direto para a `main`. O hook `pre-push` já recusa um push para a `main` com alterações não commitadas em arquivos rastreados, mas um hook é uma conveniência, não um controle.

## Passos de um lançamento

1. Atualize o [CHANGELOG.md](../../CHANGELOG.md): mova as entradas de `[Unreleased]` para um novo título `## [X.Y.Z] - AAAA-MM-DD`, deixe `[Unreleased]` vazio acima dele e atualize os links de comparação e de tag no fim do arquivo.
2. Suba a versão em todo lugar onde ela está escrita, em um só commit: `pyproject.toml` (`version`), `.claude-plugin/plugin.json` (`version`) e `src/wev_skills/__init__.py` (`__version__`). O `.claude-plugin/marketplace.json` não tem campo de versão. O `tests/unit/test_repo_hygiene.py` falha quando os três divergem.
3. Rode `make test`, `make lint` e `bin/wev readme check`. Registre as linhas de resultado no [mvp-status.pt-BR.md](../mvp-status.pt-BR.md) e no gêmeo em inglês, e nos READMEs, no mesmo commit.
4. Faça o merge desse commit por um pull request.
5. Crie uma tag anotada no commit de merge: `git tag -a vX.Y.Z -m "wev-skills X.Y.Z"` e `git push origin vX.Y.Z`.
6. O push de uma tag `v*.*.*` inicia o [`.github/workflows/release.yml`](../../.github/workflows/release.yml). O job `verify` confere que a tag é igual a `v` mais a versão do `pyproject.toml` e roda `make test`. O job `release` (o único com acesso de escrita a contents) pega a seção `[X.Y.Z]` do changelog com o `scripts/changelog_section.py` e roda `gh release create` com `--verify-tag`, acrescentando `--prerelease` quando a versão maior é `0` ou a versão tem sufixo com `-`. A release usa essa seção do changelog como notas; as categorias do `.github/release.yml` só valem se você pedir ao GitHub que gere as notas. Se o changelog não tiver seção para a versão, o job falha e nenhuma release é criada.
7. Confira a página da release e a execução do workflow. Se o workflow falhou antes do `release`, corrija a causa, apague a tag localmente e no remoto (`git tag -d vX.Y.Z` e `git push origin :refs/tags/vX.Y.Z`; o ruleset de tags abaixo bloqueia a exclusão remota até o dono suspender a regra para a ocasião) e crie a tag de novo.

Enviar uma tag publica o projeto. Faça isso de forma deliberada.

A primeira tag, `v0.1.0`, é criada retroativamente no commit publicado como 0.1.0 (`4ab225b`): `git tag -a v0.1.0 4ab225b -m "wev-skills 0.1.0"`. Esse commit não tem `release.yml`, então o push da tag não inicia nenhum workflow de release; crie a release à mão a partir da seção `[0.1.0]` do changelog e marque como pré-lançamento.

## Configurações do repositório

Esta é a configuração pretendida de `wevertonjuscelino/wev-skills`, guardada aqui para poder ser revisada e reaplicada. Evidência hoje: apenas documentado. Nada aqui é sabidamente aplicado até o dono confirmar no GitHub, e o [estado do MVP](../mvp-status.pt-BR.md) lista isso como "a aplicar".

**Geral** (Settings, General):

- Descrição e tópicos: uma descrição de uma linha do motor e do plugin, e tópicos como `claude-code`, `claude-code-plugin`, `ai-agents`, `agent-orchestration`, `cli` e `python`.
- Recursos: Issues ligado, Discussions ligado (com uma categoria Q&A, para a qual o [SUPPORT.pt-BR.md](../../SUPPORT.pt-BR.md) aponta), Wiki desligada, Projects desligado. A documentação vive no repositório.
- Merge: permitir squash e rebase; não permitir commits de merge; apagar o branch de origem após o merge.

**Segurança** (Settings, Code security):

- Relato privado de vulnerabilidades ligado: a rota que o [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md) manda quem relata usar. Sem ele, o botão "Report a vulnerability" não aparece.
- Varredura de segredos e proteção de push ligadas. Elas complementam o `scripts/scan_secrets.py`, que é um alarme estreito.
- Alertas do Dependabot e atualizações de segurança do Dependabot ligados. O `.github/dependabot.yml` pede, à parte, pull requests semanais que atualizam as GitHub Actions fixadas.

**Ruleset de branch na `main`** (Settings, Rules):

- Bloquear exclusão e bloquear force push.
- Exigir histórico linear.
- Exigir pull request antes do merge, com 0 aprovações exigidas (um único mantenedor não consegue aprovar o próprio pull request).
- Exigir estes status checks, com os nomes que o `ci.yml` informa: `test (ubuntu-latest, Python 3.14)`, `test (macos-latest, Python 3.14)`, `lint`, `skills`, `git hooks and documents` e `secrets-scan`. O último não tem `name:` no workflow, então o nome do check é o id do job.
- Lista de bypass: administrador do repositório, para que o dono ainda possa enviar direto. O bypass é uma conveniência do dono, não um controle contra o dono.

**Ruleset de tags** (Settings, Rules): alvo `v*`; bloquear exclusão e bloquear atualização das tags que casam. A criação continua permitida, porque criar a tag é o que inicia o workflow de release.

**Labels**: crie as labels de [`.github/labels.json`](../../.github/labels.json) (nome, cor, descrição) à mão ou com um script executado pelo dono. Os formulários de issue usam `bug`, `enhancement`, `documentation` e `status: needs-triage`, e o [`.github/release.yml`](../../.github/release.yml) agrupa as notas geradas por label; crie as labels antes de chegar a primeira issue. Crie um milestone por versão planejada, como o [roteiro](../../ROADMAP.pt-BR.md) descreve.

**Configurações da conta do dono** (a conta, não o repositório):

- Keep my email address private (Settings, Emails): os commits passam a usar um endereço no-reply do GitHub.
- Block command line pushes that expose my email (Settings, Emails): recusa um push cujos commits tragam um endereço privado.

Confira o autor dos seus commits antes do primeiro push: `git log -1 --format='%an <%ae>'`.
