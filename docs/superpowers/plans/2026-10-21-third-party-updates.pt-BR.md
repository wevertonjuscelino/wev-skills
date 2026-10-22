# Plano de Implementação das Atualizações de Skills de Terceiros

Versão em inglês: [2026-10-21-third-party-updates.md](2026-10-21-third-party-updates.md).

> **Para agentes de execução:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam a sintaxe de caixa de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** o wev instala a versão mais nova de cada skill de terceiros (rea, agent-skills) e do próprio wev, consulta o upstream uma vez por dia na primeira sessão do dia, pergunta à pessoa antes de atualizar, instala a nova versão ao lado da atual, roda uma verificação de saúde e só troca quando ela passa; a pessoa pode reverter ou congelar uma fonte.

**Arquitetura:** um pacote `third_party` em `src/wev_skills/` guarda um registro fixo de fontes (tipo `npm` ou `github`), um arquivo de estado por usuário (versão ativa, versão anterior, flag de congelada, última consulta) validado como dado, consultas de versão por HTTPS com timeouts curtos, instalações lado a lado sob o diretório de dados do usuário, uma verificação de saúde por tipo de fonte e as operações de troca, reversão e congelamento. Um novo grupo de CLI `wev skills` as expõe. O hook `SessionStart` do Claude Code ganha uma entrada `startup` que roda `wev skills check --daily`: ela sai em silêncio a menos que um dia tenha passado e, então, injeta um parágrafo curto (`additionalContext`) que nomeia as atualizações e diz ao modelo para perguntar à pessoa uma vez. A skill `wev-skill-maintenance` carrega a instrução "perguntar uma vez, atualizar no sim". A ativação do agent-skills nos harnesses usa symlinks nas raízes de skills de usuário compartilhadas dos harnesses, controlados por um manifesto como o da Parte 3.

**Stack Técnica:** biblioteca padrão do Python 3.14 (`urllib.request`, `tarfile` com `filter="data"`, `json`, `subprocess` sem shell), `unittest`; um fixture de servidor HTTP falso local para os registros e um script `npx` falso que fala JSON-RPC do MCP por stdio.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.pt-BR.md), Parte 4, decisões 7, 8, 16, e as escolhas "shared third-party installs", "newest = latest GitHub release, else HEAD", "refusing an update waits for the next version". Fatos dos hooks do Claude Code: matchers do SessionStart `startup|resume|clear|compact|fork`, `hookSpecificOutput.additionalContext` limitado a 10.000 caracteres, sem controle de decisão, timeout padrão de 600 s, sem "uma vez por dia" nativo (fonte: https://code.claude.com/docs/en/hooks.md, lida em 2026-10-21).

## Restrições Globais

- Somente biblioteca padrão, Python >= 3.14, mypy strict, dataclasses congeladas, funções com menos de 50 linhas, arquivos com menos de 400 linhas.
- Toda string voltada ao usuário passa pelo i18n, com chaves idênticas em `en` e `pt-BR`. A documentação muda em EN e pt-BR no mesmo commit.
- Testes unitários não fazem chamadas de rede além do loopback e nunca rodam o `npx`, `npm`, `gh` ou GitHub reais. Downloads reais pertencem à parte e2e.
- Fontes, valores exatos: `rea` = pacote npm `rea-agents`, mais nova = `dist-tags.latest` de `https://registry.npmjs.org/rea-agents`; `agent-skills` = GitHub `addyosmani/agent-skills`, mais nova = `tag_name` de `/releases/latest`, tarball = o `tarball_url` dessa release; `wev-skills` = GitHub `wevertonjuscelino/wev-skills`, mesma regra. Uma fonte sem release usa o HEAD do branch padrão (sha de `/commits/HEAD`) e o tarball do branch. Link do changelog = o `html_url` da release (npm: `https://github.com/morluto/rea/releases/tag/rea-agents-<version>`).
- Tudo o que é baixado é dado não confiável: a extração do tar usa `tarfile.extractall(filter="data")` em um diretório novo, recusa membros fora dele, limita o arquivo a 50 MiB, e o diretório nunca é executado a partir dali. O tarball do GitHub não tem checksum; a documentação diz isso.
- Layout de dados: `$XDG_DATA_HOME/wev-skills/third-party/` (senão `~/.local/share/wev-skills/third-party/`): `state.json`, `<source>/<version>/` por versão instalada, symlink `<source>/current` para a versão ativa, `manifest.json` para os symlinks de ativação. O arquivo de estado é dado: chaves desconhecidas, tipos errados ou uma string de versão que não seja `[A-Za-z0-9._-]+` são rejeitados com `ValidationError`.
- Timeouts de rede: 5 s por requisição na consulta, 120 s para um download, 60 s para uma verificação de saúde. A consulta diária nunca bloqueia o início de uma sessão por mais de 10 s no total e nunca falha de forma ruidosa: em qualquer erro não imprime nada e não deixa marcador.
- O hook pergunta (Claude Code `RUN_COMMANDS`) para `skills update`, `skills rollback`, `skills freeze` e `skills install`; `skills check`, `skills list` e `skills show` não perguntam. Em harnesses sem decisão de perguntar, esses quatro são `person_only` → negar (marcador da Parte 3).
- Assuntos de commit `<type>: <description>`, no máximo 72 caracteres, sem atribuição a IA. Sem push sem o ok do dono.

## Foco da Revisão

1. Uma resposta do registro ou do GitHub com formato inesperado (`tag_name` ausente, versão que não é string, HTML no lugar de JSON, um 5xx) deve deixar o estado intacto e reportar `check_failed` para aquela fonte, nunca quebrar nem gravar um marcador. Testado na Tarefa 2.
2. Um tarball com um membro fora do destino (`../x`, um caminho absoluto, um symlink para `/etc`) deve ser recusado antes de qualquer gravação, e o diretório parcial removido. Testado na Tarefa 3.
3. Uma verificação de saúde que passa em uma instalação quebrada (lista de ferramentas vazia, zero arquivos `SKILL.md`, `wev version` imprimindo outra versão) deve falhar; a versão anterior continua ativa. Testado na Tarefa 4.
4. Rodar `skills update` duas vezes, ou `rollback` sem versão anterior, não pode corromper o estado nem o symlink `current`. Testado na Tarefa 5.
5. Uma fonte congelada nunca é atualizada nem incomoda a pessoa; a consulta diária a ignora e o diz uma vez em `skills list`. Testado nas Tarefas 2 e 5.

---

### Tarefa 1: Registro e estado

**Arquivos:**
- Criar: `src/wev_skills/third_party/__init__.py`, `src/wev_skills/third_party/sources.py`, `src/wev_skills/third_party/state.py`
- Criar: `src/wev_skills/commands/skills.py`, `src/wev_skills/locales/skills.en.json`, `skills.pt-BR.json`
- Teste: `tests/unit/test_third_party_state.py`, `tests/unit/test_cli_skills.py`

**Interfaces:**
- Produz:
  - `@dataclass(frozen=True) class Source: name: str; kind: Literal["npm", "github"]; package: str; health: Literal["mcp", "skills", "wev"]; changelog: str` (changelog é uma string de formato com `{version}`).
  - `SOURCES: tuple[Source, ...]` com exatamente `rea` (npm, `rea-agents`, `mcp`), `agent-skills` (github, `addyosmani/agent-skills`, `skills`), `wev-skills` (github, `wevertonjuscelino/wev-skills`, `wev`).
  - `def source(name: str) -> Source` levantando `ValidationError("unknown_source")`.
  - `@dataclass(frozen=True) class SourceState: active: str | None; previous: str | None; frozen: bool; last_check: str | None; latest_seen: str | None; declined: str | None` (`declined` = a versão à qual a pessoa disse não; a consulta só incomoda de novo quando `latest != declined`).
  - `@dataclass(frozen=True) class State: sources: Mapping[str, SourceState]; checked_at: str | None` com `load(path) -> State` (arquivo ausente = estado vazio; inválido = `ValidationError("state_invalid")`) e `save(path, state)` por meio de `atomic_write_text` com modo 0600.
  - `def data_home() -> Path` (`$XDG_DATA_HOME/wev-skills/third-party`, senão `~/.local/share/...`).
- CLI: `wev skills list` imprime `{"sources": [{"name", "kind", "active", "previous", "frozen", "latest_seen", "changelog"}]}`.

- [ ] **Passo 1: Testes que falham:** `test_sources_are_exactly_the_three`; `test_state_roundtrip`; `test_missing_state_is_empty`; `test_invalid_state_rejected` (string de versão inválida `../x`, `frozen` que não é bool, chave desconhecida); `test_list_cli` (no mesmo processo por `cli.main`, XDG/HOME isolados).
- [ ] **Passo 2: Rodar e vê-los falhar. Passo 3: Implementar. Passo 4: Rodar e passar; quebrar a regex de versão de propósito, confirmar e restaurar.**
- [ ] **Passo 5: Commit** `feat: add the third-party source registry and state`

### Tarefa 2: Consulta de versão e o hook diário

**Arquivos:**
- Criar: `src/wev_skills/third_party/check.py`
- Modificar: `src/wev_skills/commands/skills.py`, `hooks/hooks.json`, `src/wev_skills/adapters/claude_code/hooks.py` (um tratador de hook `skills_check`) ou `commands/hook.py`
- Criar: `tests/fixtures/fake_registry_server.py` (servidor HTTP em loopback com roteiro por caminho), teste `tests/unit/test_third_party_check.py`

**Interfaces:**
- Consome: Tarefa 1.
- Produz:
  - `def latest(source: Source, opener: Callable[[str, float], bytes], base_urls: Mapping[str, str]) -> Release` onde `@dataclass(frozen=True) class Release: version: str; url: str; tarball: str | None`. `base_urls` tem as raízes `npm` e `github` para que os testes apontem para o servidor falso; padrões `https://registry.npmjs.org` e `https://api.github.com`. Qualquer falha levanta `CheckFailed(code)`.
  - `def check(state: State, now: datetime, opener, base_urls, *, force: bool) -> tuple[State, list[Update]]` com `@dataclass(frozen=True) class Update: source: str; active: str | None; latest: str; url: str`. Ignora fontes congeladas; ignora uma fonte cujo `latest == declined`; registra `latest_seen`, `last_check`; `checked_at` só é definido com `force` ou quando passou um dia (24 h desde `checked_at`).
  - `def daily_context(updates: Sequence[Update]) -> str`: o parágrafo de `additionalContext`, chave i18n `skills.hook.updates`, com menos de 1.000 caracteres, nomeando cada fonte, as versões e a URL do changelog, e a instrução "perguntar uma vez à pessoa se deve atualizar; no sim rodar `wev skills update <source>`; no não rodar `wev skills decline <source>`".
- CLI: `wev skills check [--daily] [--json]`. `--daily`: sai com 0 em silêncio quando não está na hora; quando está, faz a consulta com um orçamento total de 10 s e imprime o JSON de `SessionStart` do Claude (`hookSpecificOutput.additionalContext`) ou nada. Sem `--daily`: sempre consulta e imprime `{"updates": [...], "checked": [...], "failed": [...]}`.
- `wev skills decline <source>` registra `declined = latest_seen`.
- `hooks/hooks.json`: adicionar uma entrada `SessionStart` com matcher `startup` rodando `"${CLAUDE_PLUGIN_ROOT}/bin/wev" skills check --daily`, timeout 15. A entrada existente `compact|resume` permanece.

- [ ] **Passo 1: Escrever o fixture do servidor falso** (respostas roteirizadas por caminho: documento npm, GitHub releases/latest, commits/HEAD, um 500, HTML).
- [ ] **Passo 2: Testes que falham:** `test_latest_npm`, `test_latest_github_release`, `test_github_without_release_uses_head`, `test_bad_shape_is_check_failed` (Foco da Revisão 1: 4 formatos), `test_frozen_skipped`, `test_declined_skipped_until_new_version`, `test_daily_not_due_prints_nothing_and_writes_nothing`, `test_daily_due_prints_session_json_under_10k`, `test_daily_network_error_prints_nothing_leaves_no_marker`, `test_hooks_json_has_startup_entry`, `test_hook_does_not_ask_for_check`.
- [ ] **Passos 3–5:** rodar/falhar, implementar, rodar/passar, quebrar a regra das 24 h de propósito, restaurar. **Commit** `feat: check third-party versions daily and ask through the session hook`

### Tarefa 3: Baixar e instalar lado a lado

**Arquivos:**
- Criar: `src/wev_skills/third_party/fetch.py`
- Modificar: `src/wev_skills/commands/skills.py`
- Teste: `tests/unit/test_third_party_fetch.py` (tarballs montados no teste com `tarfile`)

**Interfaces:**
- Produz:
  - `def install_version(source: Source, release: Release, home: Path, opener, runner: Runner) -> Path`: para `github`, baixa `release.tarball` (limite de 50 MiB, `CheckFailed("too_large")`), extrai com `filter="data"` em `home/<source>/<version>.tmp-<pid>`, remove o único diretório de nível superior que o GitHub adiciona, verifica que nenhum membro escapou, e então renomeia para `home/<source>/<version>`; para `npm`, grava `home/rea/<version>/npm-ref.json` com `{"package": "rea-agents", "version": ...}` e não executa nada (o npx resolve a versão fixada no uso; a verificação de saúde da Tarefa 4 o aquece).
  - `def mcp_argv(version: str) -> tuple[str, ...]` = `("npx", "-y", f"rea-agents@{version}", "mcp")`, o argv que a Parte 5 grava nas configurações de MCP.
  - Versão já instalada: devolve o caminho existente sem baixar.
- CLI: `wev skills install <source> [--version V]` (padrão: a mais nova de uma consulta nova) instala sem trocar, imprime `{"source", "version", "path", "active": false}`.

- [ ] **Passo 1: Testes que falham:** `test_github_tarball_extracted_under_version_dir`, `test_member_outside_target_refused_nothing_left` (Foco da Revisão 2: `../x`, absoluto, symlink para `/etc`, hardlink), `test_too_large_refused`, `test_existing_version_not_redownloaded`, `test_npm_install_writes_ref_only`, `test_hook_asks_for_skills_install`.
- [ ] **Passos 2–5** como antes; quebrar a verificação de escape de propósito. **Commit** `feat: install third-party versions side by side`

### Tarefa 4: Verificações de saúde

**Arquivos:**
- Criar: `src/wev_skills/third_party/health.py`, `tests/fixtures/fake_npx_mcp.py` (fala JSON-RPC `initialize` e `tools/list` por stdio; falhas roteirizadas por variável de ambiente)
- Teste: `tests/unit/test_third_party_health.py`

**Interfaces:**
- Produz `def health(source: Source, version: str, home: Path, runner: Runner, *, npx: str = "npx", python: str = sys.executable) -> HealthReport` com `@dataclass(frozen=True) class HealthReport: ok: bool; code: str; detail: str`:
  - `mcp`: roda `mcp_argv(version)` (com `npx` substituível para testes), envia `initialize` e depois `tools/list` como JSON-RPC por stdio com orçamento de 60 s; ok quando a lista de ferramentas tem ao menos uma ferramenta. Códigos: `spawn_failed`, `timeout`, `bad_jsonrpc`, `no_tools`.
  - `skills`: sob `home/agent-skills/<version>/skills/`, ao menos um `*/SKILL.md`, e todos têm frontmatter com `name` igual ao seu diretório e uma `description` não vazia. Códigos: `no_skills`, `bad_skill:<dir>`.
  - `wev`: roda `[python, home/wev-skills/<version>/bin/wev, version]` e exige que a versão impressa seja igual a `<version>` sem o `v` inicial. Códigos: `spawn_failed`, `version_mismatch`.
- Nada do diretório instalado é importado neste processo; tudo roda como subprocesso sem shell.

- [ ] **Passo 1: Testes que falham** com o npx falso e diretórios temporários: caminhos ok para os três tipos; `test_empty_tools_list_fails`, `test_zero_skill_files_fails`, `test_skill_name_mismatch_fails`, `test_wrong_wev_version_fails` (Foco da Revisão 3), `test_mcp_timeout_fails`.
- [ ] **Passos 2–5**; quebrar `no_tools` de propósito. **Commit** `feat: add health checks for mcp, skill and wev versions`

### Tarefa 5: Atualizar, reverter, congelar e ativar

**Arquivos:**
- Criar: `src/wev_skills/third_party/switch.py`, `src/wev_skills/third_party/activate.py`
- Modificar: `src/wev_skills/commands/skills.py`, `src/wev_skills/adapters/claude_code/engine_cli.py` (`skills update|rollback|freeze|install` em `RUN_COMMANDS`, person_only nos outros harnesses), `skills/wev-skill-maintenance/SKILL.md`
- Teste: `tests/unit/test_third_party_switch.py`, `tests/unit/test_third_party_activate.py`, testes do hook

**Interfaces:**
- `def update(source, home, state, opener, runner, base_urls) -> tuple[State, UpdateResult]`: consultar → `install_version` → `health` → se ok: `previous = active`, `active = new`, reapontar `home/<source>/current` (symlink substituído de forma atômica: criar `current.tmp` e depois `os.replace`), `declined = None`; em caso de falha: estado inalterado, o novo diretório mantido para inspeção, `UpdateResult(ok=False, code=...)`. Congelada → `ValidationError("frozen")`. Já na mais nova → resultado sem operação.
- `def rollback(source, home, state) -> State`: troca `active` e `previous` e reaponta `current`; sem anterior → `StateConflict("no_previous")`.
- `def freeze(source, state, on: bool) -> State`.
- Ativação (somente agent-skills): `def activate(home, manifest_path, roots: Sequence[Path]) -> Manifest` cria, para cada `skills/<name>/` em `current`, um symlink `<root>/<name>` → esse diretório, em cada uma das raízes que existem: `~/.claude/skills` e `~/.agents/skills` (a raiz compartilhada por Codex, OpenCode e Gemini segundo as notas de pesquisa). Recusa uma entrada existente que não lhe pertence (StateConflict nomeando-a), registra cada link no manifesto, e `deactivate` remove apenas os links do manifesto. Rodar de novo depois de uma atualização renova os links (eles apontam para `current`, então em geral nada muda).
- CLI: `wev skills update [SOURCE] [--yes]` (sem SOURCE = toda fonte não congelada; `--yes` só pula a proteção "já recusada", o consentimento da pessoa é dado no chat ou ao digitar o comando), `wev skills rollback SOURCE`, `wev skills freeze SOURCE [--off]`, `wev skills activate`, `wev skills deactivate`, `wev skills show SOURCE` (imprime o estado e, para rea, `mcp_argv`).
- Texto da skill (`wev-skill-maintenance/SKILL.md`): quando o contexto da sessão nomear atualizações disponíveis, perguntar à pessoa uma vez ("atualizar X de A para B? changelog: URL"); no sim rodar `wev skills update X`; no não rodar `wev skills decline X`; nunca atualizar sem o sim da pessoa; uma fonte congelada é deixada em paz; reportar o resultado da saúde à pessoa; em caso de falha dizer que a versão anterior continua ativa.

- [ ] **Passo 1: Testes que falham:** atualização ok troca e mantém a anterior; atualização com saúde falhando mantém a ativa e reporta; `test_update_twice_is_noop_and_state_stable`, `test_rollback_without_previous_is_conflict` (Foco da Revisão 4); congelada recusada (Foco da Revisão 5); a ativação cria só links próprios, recusa uma entrada alheia, deactivate remove só os seus links; o hook pergunta para update/rollback/freeze/install e os nega em codex/gemini/opencode; `test_skills.py` continua passando (a skill nomeia apenas comandos e flags reais).
- [ ] **Passos 2–5**; quebrar a regra "trocar só com saúde ok" de propósito. **Commit** `feat: update, roll back, freeze and activate third-party skills`

### Tarefa 6: Documentação

**Arquivos:** `README.md` + pt-BR (uma linha em cada: atualizações de terceiros); `docs/guides/installation.md` + pt-BR (seção "Third-party skills: install, daily check, update, rollback, freeze"); `SECURITY.md` + pt-BR (seção: downloads são dado não confiável; o tarball do GitHub não tem checksum; a verificação de saúde pega uma atualização quebrada, não uma maliciosa; uma atualização só roda depois do sim da pessoa, por um comando sobre o qual o hook pergunta; os links em `~/.claude/skills` e `~/.agents/skills` são controlados por um manifesto; a consulta diária usa a rede no início da sessão com orçamento de 10 s e falha em silêncio); `docs/THIRD-PARTY.md` + pt-BR (rea e agent-skills como dependências instaladas, MIT, com versões resolvidas na instalação, não embutidas); `CHANGELOG.md`; `docs/mvp-status.md` + pt-BR.

Rótulos, exatamente: "implemented and tested with a local fake registry, a fake npx and local tarballs"; "the real registries, downloads and the real rea server are not run in this change (e2e part)". Nada de "compatible with", "prevents", "guarantees".

- [ ] **Passo 1: Editar.** **Passo 2:** `PYTHONPATH=src python3 -m unittest tests.unit.test_skills tests.unit.test_docs tests.unit.test_repo_hygiene`, `bin/wev readme check`, `bin/wev claude-md check`, `make check`. **Passo 3: Commit** `docs: document third-party skill updates`
