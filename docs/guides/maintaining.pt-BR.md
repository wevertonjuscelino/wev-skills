# Manutenção do repositório

English version: [maintaining.md](maintaining.md).

Este guia é para o dono e para quem faz merge de mudanças: o formato dos commits, o fluxo de branches e pull requests, como fazer um lançamento e as configurações do GitHub que não podem ser definidas pela árvore de trabalho. O repositório é <https://github.com/wevertonjuscelino/wev-skills>. Nada na seção de configurações já está habilitado: são recomendações para o dono ligar à mão, e cada uma está apenas documentada até alguém confirmá-la no GitHub.

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
5. Crie a tag no commit de merge: `git tag -a vX.Y.Z -m "wev-skills X.Y.Z"` e `git push origin vX.Y.Z`.
6. Crie a release do GitHub a partir da tag (Releases, "Draft a new release"). Use a entrada do changelog como notas e marque como pré-lançamento enquanto a versão for `0.x`.

Enviar uma tag e criar uma release publicam o projeto. Faça isso de forma deliberada.

## Configurações do repositório para ligar

Elas ficam no GitHub, não na árvore de trabalho, então nenhum arquivo deste repositório consegue defini-las. São recomendações; até este commit, não se sabe se alguma delas está habilitada.

Configurações do repositório (Settings de `wevertonjuscelino/wev-skills`):

- **Proteção de branch ou um ruleset na `main`** (Settings, Rules ou Branches): exigir pull request antes do merge, exigir que os checks do `ci.yml` passem, bloquear force push e bloquear a exclusão do branch.
- **Relato privado de vulnerabilidades** (Settings, Code security): a rota que o [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md) manda quem relata usar. Sem ele, o botão "Report a vulnerability" não aparece.
- **Varredura de segredos e proteção de push** (Settings, Code security): o scanner do GitHub bloqueia um push que contenha um token reconhecido. Ele complementa o `scripts/scan_secrets.py`, que é um alarme estreito.
- **Alertas do Dependabot** (Settings, Code security): o `.github/dependabot.yml` já pede pull requests semanais que atualizam as GitHub Actions fixadas; os alertas são um interruptor separado.

Configurações da conta do dono (a conta, não o repositório):

- **Keep my email address private** (Settings, Emails): os commits passam a usar um endereço no-reply do GitHub.
- **Block command line pushes that expose my email** (Settings, Emails): recusa um push cujos commits tragam um endereço privado.

Confira o autor dos seus commits antes do primeiro push: `git log -1 --format='%an <%ae>'`.
