# Manutenção do repositório

English version: [maintaining.md](maintaining.md).

Este guia é para o dono e para quem faz merge de mudanças: o formato dos commits, o fluxo de branches e pull requests, como as versões são numeradas e publicadas e a configuração pretendida do GitHub, que não pode ser definida pela árvore de trabalho. O repositório é <https://github.com/wevertonjuscelino/wev-skills>. A seção de configurações é a fonte de verdade de como o repositório deve ser configurado; é apenas documentada, e uma configuração só conta como aplicada depois que alguém a confirma no GitHub.

## Formato dos commits

```
<type>: <description>
<type>(<scope>): <description>
```

Tipos: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `revert`. Os títulos de pull request usam o mesmo formato, exceto que `security` também é aceito e `revert` não; o bot faz commits `chore(release): vX.Y.Z`. O assunto tem no máximo 72 caracteres e não termina com ponto. Commits de merge e de revert gerados pelo git são aceitos. O hook `commit-msg` em `.githooks/` confere isso depois do `make hooks` (veja o [CONTRIBUTING.pt-BR.md](../../CONTRIBUTING.pt-BR.md)). Não nomeie nenhuma ferramenta como autora ou coautora e não adicione trailer de coautoria.

## Branches, pull requests e versões

Existem dois branches de longa vida. `dev` é o branch de quarentena onde o trabalho mesclado espera; `main` guarda o código lançado e é o branch padrão, de modo que as instalações do plugin recebem código lançado. Quem contribui mira `dev`.

1. Trabalhe em um branch criado a partir de `dev`, nunca em `dev` nem em `main`: `git switch -c <type>/<short-name> origin/dev`.
2. Envie o branch e abra um pull request contra `dev`. O título deve ser `<type>(<scope>): <description>` (tipos `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `ci`, `build`, `security`; o escopo é opcional), porque a linha do changelog vem dele. Preencha o modelo de pull request, inclusive o rótulo de evidência de cada afirmação.
3. Espere os checks (`test` no Ubuntu e no macOS, `lint`, `skills`, `git hooks and documents`, `secrets-scan`, `pr-title`, `source-branch`). O CodeOwners pede a revisão do dono.
4. Faça o merge com um commit de merge (o único método habilitado). O commit de merge é o que conta o pull request na versão.
5. Para lançar, abra um pull request de `dev` para `main` e faça o merge com um commit de merge. Mais nada é preciso: o workflow de release assume (veja "O que é automático").
6. Ninguém envia direto para `main` nem para `dev`. O hook `pre-push` já recusa um push para a `main` com mudanças não commitadas em arquivos rastreados, mas um hook é uma conveniência, não um controle.

### Fórmula da versão

A versão é `vX.Y.Z` e é calculada a partir do histórico do git por `python3 scripts/versioning.py`; ela nunca é escrita em arquivo a cada commit.

- `X` conta as releases em `main`. Cada pull request de `dev` para `main` que é mesclado publica `v(X+1).0.0`, em que `X` é o maior da última tag de release. O número maior não sinaliza mudanças incompatíveis como no Versionamento Semântico; para isso, leia o changelog.
- `Y` conta os pull requests mesclados em `dev` desde a última tag de release (commits de merge na cadeia de primeiro pai da referência até a tag).
- `Z` conta os commits do pull request em andamento e recomeça quando esse pull request é mesclado em `dev`.

Exemplo, com `v2.0.0` como última release e `dev` avançado até ela: dev é `2.0.0`. Um pull request de 3 commits é mesclado: dev é `2.1.3`. Um segundo, de 2 commits: `2.2.2`. Um branch criado a partir de dev com 4 commits até agora é `2.3.4`, exatamente o que dev vira quando ele for mesclado (um commit enviado direto para dev depois de um merge conta como mais um `Z` do próximo pull request). O pull request de release dev para main publica `v3.0.0`; dev avança até ele e passa a ser `3.0.0`; o próximo pull request mesclado o torna `3.1.n`. `python3 scripts/versioning.py [--ref REF] [--next-release]` imprime esses valores, e o CI os mostra no resumo do job `lint`.

### O que é automático

O [`.github/workflows/release.yml`](../../.github/workflows/release.yml) roda a cada push em `main`. O job `verify` roda `make test`. O job `release` (o único com `contents: write` e `issues: write`) só prossegue quando o commit enviado é um commit de merge cujo assunto é `Merge pull request #N from <dono>/dev`; para qualquer outro push (um push direto de administrador, o commit de release do próprio bot) ele registra "Not a dev->main merge, no release" e para. Um push direto de administrador em `main` portanto nunca lança uma release. Quando prossegue, ele:

1. calcula a próxima versão com `scripts/versioning.py --next-release` e recusa se essa tag já existir;
2. reúne os pull requests mesclados em `dev` desde a tag anterior com `scripts/collect_release_prs.py` (assuntos dos merges e depois `gh pr view` para título, URL e labels; commits enviados a dev sem pull request não entram na lista);
3. cria o milestone da release seguinte se ele não existir;
4. roda `scripts/release_prep.py`, que reescreve `pyproject.toml`, `.claude-plugin/plugin.json`, `src/wev_skills/__init__.py`, o marcador de versão nos dois READMEs e no `CLAUDE.md`, o exemplo de plugin.json dos guias de instalação, o `CHANGELOG.md` (uma nova seção `## [X.Y.Z]` a partir dos títulos dos pull requests: feat vira Added, fix vira Fixed, label ou tipo `security` vira Security, docs vira Documentation, todo o resto vira Changed, mais os links de comparação) e os blocos gerados `wev:release-status` dos roadmaps e dos documentos de estado do MVP; qualquer padrão que não case exatamente uma vez aborta a execução antes de qualquer arquivo ser escrito; em seguida roda `bin/wev readme check` e `bin/wev claude-md check`;
5. faz o commit como `github-actions[bot]` com o assunto `chore(release): vX.Y.Z`, cria a tag anotada e envia `main` e a tag juntas;
6. cria a release do GitHub com a seção do changelog como notas, como a release mais recente e nunca como pré-lançamento;
7. fecha o milestone `vX.Y.Z` se ele existir;
8. avança `dev` até `main` com um push simples (sem force), para que a cadeia de primeiro pai de `dev` depois da tag comece limpa.

O commit do bot é o único que edita os arquivos de versão e as seções do changelog; não os edite à mão. As entradas escritas à mão em `## [Unreleased]` são mantidas e incorporadas à nova seção. Pushes feitos com o token do job não iniciam outros workflows, então tudo acontece nessa única execução. Evidência: implementado mas não testado; só roda no GitHub. As partes puras (cálculo da versão, reescrita de arquivos, coleta de pull requests a partir dos assuntos de merge) são cobertas por testes unitários com repositórios temporários.

### Se uma release falhar no meio

Leia primeiro o log da execução; cada passo é separado e a execução para na primeira falha.

- Falhou antes de "Push main and the tag": nada foi publicado. Corrija a causa e rode de novo a execução que falhou, ou não envie nada e faça o merge de um novo pull request de release.
- Falhou no push ou depois dele, mas antes da release: o commit e a tag existem. Crie a release à mão a partir da seção do changelog: `python3 scripts/changelog_section.py X.Y.Z > notes.md` e `gh release create vX.Y.Z --title "wev-skills X.Y.Z" --notes-file notes.md --latest --verify-tag`. Não rode o workflow de novo: ele recusa porque a tag existe.
- Falhou no passo do milestone: feche o milestone à mão. É cosmético.
- Falhou no avanço de dev (dev tem commits que main não tem, porque um pull request foi mesclado em dev enquanto a release rodava, ou um ruleset recusou o push): a release está publicada, mas dev está atrasado em termos de versão. Enquanto dev não contiver o commit de release, sua versão calculada está errada. Como administrador, coloque o commit de release sob o trabalho novo: refaça o rebase dos commits que dev ganhou sobre `main` e envie dev (o ruleset de dev bloqueia force push, então isso exige o bypass de administrador) ou, se não houver nada a manter, `git push origin main:dev`. Evite mesclar pull requests em dev enquanto uma release roda.
- Uma tag enviada por engano: o ruleset de tags bloqueia a exclusão até o dono liberá-lo para a ocasião; apague a release e a tag e recomece.

## Configurações do repositório

Esta é a configuração pretendida de `wevertonjuscelino/wev-skills`, guardada aqui para poder ser revisada e reaplicada. Evidência hoje: apenas documentado. Nada aqui é sabidamente aplicado até o dono confirmar no GitHub, e o [estado do MVP](../mvp-status.pt-BR.md) lista isso como "a aplicar".

**Geral** (Settings, General):

- Descrição e tópicos: uma descrição de uma linha do motor e do plugin, e tópicos como `claude-code`, `claude-code-plugin`, `ai-agents`, `agent-orchestration`, `cli` e `python`.
- Recursos: Issues ligado, Discussions ligado (com uma categoria Q&A, para a qual o [SUPPORT.pt-BR.md](../../SUPPORT.pt-BR.md) aponta), Wiki desligada, Projects desligado. A documentação vive no repositório.
- Merge: permitir commits de merge (a versão os conta); squash e rebase desligados. "Automatically delete head branches" pode continuar ligado para branches de feature, mas nunca pode apagar `dev`: o ruleset de `dev` bloqueia a exclusão, e o job de release recria `dev` por avanço de qualquer forma. O branch padrão continua `main`.

**Segurança** (Settings, Code security):

- Relato privado de vulnerabilidades ligado: a rota que o [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md) manda quem relata usar. Sem ele, o botão "Report a vulnerability" não aparece.
- Varredura de segredos e proteção de push ligadas. Elas complementam o `scripts/scan_secrets.py`, que é um alarme estreito.
- Alertas do Dependabot e atualizações de segurança do Dependabot ligados. O `.github/dependabot.yml` pede, à parte, pull requests semanais que atualizam as GitHub Actions fixadas.

**Ruleset de branch na `main`** (Settings, Rules):

- Bloquear exclusão e bloquear force push.
- Não exigir histórico linear: o merge de dev em main é um commit de merge.
- Exigir pull request antes do merge, com 0 aprovações exigidas (um único mantenedor não consegue aprovar o próprio pull request); método de merge permitido: apenas merge.
- Exigir estes status checks, com os nomes que os workflows informam: `test (ubuntu-latest, Python 3.14)`, `test (macos-latest, Python 3.14)`, `lint`, `skills`, `git hooks and documents`, `secrets-scan` (do `ci.yml`, cujo último job não tem `name:`, então o nome do check é o id do job), `pr-title` e `source-branch` (do `pr-policy.yml`).
- Lista de bypass: administrador do repositório e o app GitHub Actions. O job de release envia o commit de release e a tag para `main` e avança `dev` com o token do job, o que precisa do bypass; o bypass de administrador é uma conveniência do dono, não um controle contra o dono, e um push direto de administrador em `main` não lança release.

**Ruleset de branch em `dev`**:

- Exigir pull request antes do merge (0 aprovações), método de merge: apenas merge.
- Exigir os mesmos status checks de CI da `main` e o `pr-title`. O `source-branch` só importa para a `main`.
- Bloquear exclusão e bloquear force push.
- Lista de bypass: administrador do repositório e o app GitHub Actions (para o avanço depois de uma release).

**Ruleset de tags** (Settings, Rules): alvo `v*`; bloquear exclusão e bloquear atualização das tags que casam. A criação continua permitida, porque o job de release cria a tag.

**Renumeração das primeiras releases.** As duas releases publicadas antes deste esquema (anunciadas como 0.1.0 no commit `4ab225b` e 0.2.0 no commit `e6035b7`) passam a ser `v1.0.0` e `v2.0.0` e são releases finais. O dono refaz as tags (o ruleset de tags bloqueia a exclusão de tags antigas até ser liberado para a ocasião) e recria suas releases do GitHub; as seções do changelog dizem que foram renumeradas em 2026-10-15. O `dev` é criado uma vez a partir de `main`, antes do primeiro pull request.

**Labels**: crie as labels de [`.github/labels.json`](../../.github/labels.json) (nome, cor, descrição) à mão ou com um script executado pelo dono. Os formulários de issue usam `bug`, `enhancement`, `documentation` e `status: needs-triage`, e o [`.github/release.yml`](../../.github/release.yml) agrupa as notas geradas por label; crie as labels antes de chegar a primeira issue. Os milestones levam o nome da release que alimentam (`v3.0.0` é a próxima; o job de release cria o seguinte e fecha o que publicou). Os milestones antigos `0.2.x` e `0.3.0` são renomeados à mão. Veja o [roteiro](../../ROADMAP.pt-BR.md).

**Configurações da conta do dono** (a conta, não o repositório):

- Keep my email address private (Settings, Emails): os commits passam a usar um endereço no-reply do GitHub.
- Block command line pushes that expose my email (Settings, Emails): recusa um push cujos commits tragam um endereço privado.

Confira o autor dos seus commits antes do primeiro push: `git log -1 --format='%an <%ae>'`.
