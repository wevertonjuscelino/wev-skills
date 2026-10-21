# Plano de Implementação do Cliente JEV Embutido

Versão em inglês: [2026-10-20-jev-builtin-client.md](2026-10-20-jev-builtin-client.md).

> **Para agentes de execução:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam a sintaxe de caixa de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** o wev conversa com o serviço JEV por conta própria (sem Node, sem programa externo `jev`, sem editar `exec_path`), lê a chave do ambiente, do `.env` do usuário ou do keychain do macOS, e informa às skills se quem orquestra é o wev ou o harness.

**Arquitetura:** Um novo cliente HTTP em `decisions/` devolve a mesma string JSON de respostas que o `jev ask` externo imprime, de modo que `JevProvider` e `jev_tools` mantêm o parsing inalterado. `decision.jev.command` ganha um novo padrão, `builtin`, que seleciona o cliente HTTP. Qualquer outro valor mantém o caminho existente do programa externo. Um novo grupo da CLI, `wev jev status|ask|batch`, expõe o cliente, e `wev-orchestrate` lê `wev jev status` para escolher entre o fluxo do wev e o do próprio harness.

**Stack técnica:** biblioteca padrão do Python 3.14 (`urllib.request`, `http.server` para o servidor falso dos testes, `concurrent.futures`), `unittest`.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.pt-BR.md), Parte 2, decisões 4, 5 e 14, e a seção "Calls I made without the owner".

## Restrições Globais

- Apenas biblioteca padrão, Python >= 3.14. mypy strict, dataclasses congeladas, funções com menos de 50 linhas, arquivos com menos de 400 linhas.
- Toda string voltada ao usuário passa por i18n, com chaves idênticas em `en` e `pt-BR`. A documentação muda em EN e pt-BR no mesmo commit.
- Os testes unitários não usam rede além de loopback (`127.0.0.1`) nem serviço pago. A chamada real ao JEV está fora do escopo aqui (Parte 6, e2e).
- A chave nunca é impressa, registrada em log, gravada no estado, nem colocada em mensagem de erro ou URL.
- O texto do estado passa pelo redator existente (`core/wiring.py` `redact`) antes de sair da máquina, como o caminho do programa faz hoje.
- Endpoint padrão `https://api.typesafe.ai/v1/systemone`, modelo `jev-latest`, serviço do keychain `typesafe-api-key`, variável de ambiente `TYPESAFE_API_KEY`, substituição `JEV_API_URL`. Esses valores são copiados de `~/.claude/tools/jev/jev.mjs`.
- Repetir a tentativa apenas em HTTP 429 e 529. Espera `0.5 * 2**(attempt-1)` segundos, no máximo 4 tentativas, tudo dentro de um único prazo de `decision.jev.timeout_seconds` (padrão 10.0).
- Assuntos de commit `<type>: <description>`, no máximo 72 caracteres, sem atribuição a IA. Nada de push sem o ok do dono.
- O nome do projeto sempre mantém o `s` final: `wev-skills`.

## Foco da Revisão

1. Um `.env` escrito à mão: `export TYPESAFE_API_KEY=...`, valores entre aspas, finais de linha CRLF, comentários e linhas em branco devem resultar todos na chave pura. Teste na Tarefa 1.
2. Um `.env` legível pelo grupo ou por outros (modo diferente de `600`): a chave é recusada com um motivo que nomeia o arquivo e a correção (`chmod 600`), nunca usada em silêncio. Teste na Tarefa 1.
3. Uma chave inválida ou revogada (HTTP 401): sem nova tentativa, recorre à política local com um motivo que diz que a chave foi rejeitada, e a chave não aparece no motivo. Teste na Tarefa 2.
4. Uma enxurrada de 429 ou um servidor lento não pode bloquear uma classificação além de `timeout_seconds`. Teste na Tarefa 2.
5. `JEV_API_URL` apontando para um host `http://` simples que não seja loopback, ou uma URL com credenciais: recusada antes de qualquer requisição. Teste na Tarefa 2.

---

### Tarefa 1: Resolução da chave

**Arquivos:**
- Criar: `src/wev_skills/decisions/jev_key.py`
- Modificar: `src/wev_skills/locales/decisions.en.json`, `src/wev_skills/locales/decisions.pt-BR.json`
- Teste: `tests/unit/test_jev_key.py`

**Interfaces:**
- Produz:
  - `ENV_VAR = "TYPESAFE_API_KEY"`, `KEYCHAIN_SERVICE = "typesafe-api-key"`, `ENV_FILE_NAME = ".env"`
  - `@dataclass(frozen=True) class ApiKey: value: str; source: str` onde `source` é `"env" | "env_file" | "keychain"`. O `__repr__` não pode incluir `value`.
  - `def env_file_path() -> Path`, que devolve `user_config_home() / ".env"` (reutilize `config.user_config_home`).
  - `def read_env_file(path: Path) -> dict[str, str]`, que levanta `JevUnavailable("env_file_insecure", ...)` quando `path.stat().st_mode & 0o077`.
  - `def resolve_api_key(env: Mapping[str, str], env_file: Path, keychain: Callable[[], str | None]) -> ApiKey | None`
  - `def macos_keychain() -> str | None`, que executa `/usr/bin/security find-generic-password -s typesafe-api-key -w`. Devolve `None` fora do darwin, em saída diferente de zero ou em `OSError`, e remove a quebra de linha final.

- [ ] **Passo 1: Escreva os testes que falham** em `tests/unit/test_jev_key.py`, usando um diretório temporário para o `.env` (`os.chmod(path, 0o600)`) e um lambda para o keychain:
  - `test_env_var_wins_over_file_and_keychain`: env `{"TYPESAFE_API_KEY": "k-env"}` mais um arquivo `TYPESAFE_API_KEY=k-file` mais keychain `"k-chain"` resulta em `ApiKey("k-env", "env")`.
  - `test_file_used_when_env_missing`: resulta em `source == "env_file"`.
  - `test_keychain_used_last`: resulta em `source == "keychain"`.
  - `test_none_when_nothing_found`: devolve `None`.
  - `test_env_file_formats`: as linhas `# c`, uma linha em branco, `export TYPESAFE_API_KEY="k1"\r` resultam em `"k1"`; `TYPESAFE_API_KEY='k2'` resulta em `"k2"`; `TYPESAFE_API_KEY = k3 ` resulta em `"k3"`.
  - `test_insecure_env_file_refused`: com modo `0o644`, `resolve_api_key` levanta `JevUnavailable` cujo `code == "env_file_insecure"` e cuja mensagem contém o caminho e `chmod 600`.
  - `test_missing_env_file_is_not_an_error`: um caminho inexistente segue para o keychain.
  - `test_repr_hides_key`: `"k-env" not in repr(ApiKey("k-env", "env"))`.
  - `test_keychain_off_darwin_is_none`: substitua `sys.platform` por `"linux"`, e `macos_keychain()` devolve `None` sem executar nada (substitua `subprocess.run` para falhar se for chamado).

- [ ] **Passo 2: Execute-os e veja-os falhar**
  Execute: `PYTHONPATH=src python3 -m unittest tests.unit.test_jev_key -v`
  Esperado: ERROR, `ModuleNotFoundError: wev_skills.decisions.jev_key`.

- [ ] **Passo 3: Implemente `jev_key.py`** com as interfaces acima. Adicione a chave i18n `decisions.jev.why.env_file_insecure` (parâmetros `path`) aos dois locales. pt-BR: "o arquivo {path} pode ser lido por outros usuários; rode chmod 600 {path}".

- [ ] **Passo 4: Execute-os e veja-os passar**, com o mesmo comando. Esperado: OK. Depois quebre a verificação de permissão de propósito (comente o teste de modo), confirme que `test_insecure_env_file_refused` falha e restaure.

- [ ] **Passo 5: Commit**
  ```bash
  git add src/wev_skills/decisions/jev_key.py src/wev_skills/locales/decisions.*.json tests/unit/test_jev_key.py
  git commit -m "feat: resolve the JEV key from env, .env or keychain"
  ```

### Tarefa 2: Cliente HTTP

**Arquivos:**
- Criar: `src/wev_skills/decisions/jev_http.py`
- Criar: `tests/fixtures/fake_jev_server.py`
- Modificar: `src/wev_skills/locales/decisions.en.json`, `src/wev_skills/locales/decisions.pt-BR.json`
- Teste: `tests/unit/test_jev_http.py`

**Interfaces:**
- Consome: `ApiKey`, `resolve_api_key`, `env_file_path`, `macos_keychain` (Tarefa 1); `JevUnavailable` de `decisions/jev_wire.py`.
- Produz:
  - `DEFAULT_ENDPOINT = "https://api.typesafe.ai/v1/systemone"`, `MODEL = "jev-latest"`, `RETRYABLE = (429, 529)`, `MAX_ATTEMPTS = 4`, `BASE_BACKOFF_SECONDS = 0.5`
  - `@dataclass(frozen=True) class Endpoint: url: str; local: bool`
  - `def resolve_endpoint(env: Mapping[str, str]) -> Endpoint`, que lê `JEV_API_URL`. Levanta `JevUnavailable("endpoint_insecure")` para uma URL não https e não loopback e `JevUnavailable("endpoint_credentials")` para uma URL com usuário ou senha. Loopback é `127.0.0.1`, `localhost` ou `::1`.
  - `def validate_questions(questions: Mapping[str, Any]) -> None`, que levanta `ValidationError("invalid_questions", ...)` (saída 2). Aplica as regras de `validateQuestions` do `jev.mjs`: um objeto não vazio; `type` em `noul|choice|score`; `instructions` não vazio; `choice` aceita de 2 a 255 chaves em `criteria`; `score` aceita de 2 a 10 itens em `criteria`.
  - `class HttpAsker:` com `__init__(self, endpoint: Endpoint, key: ApiKey | None, timeout_seconds: float, *, opener: Callable[[urllib.request.Request, float], tuple[int, bytes]] = _urlopen, sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic)` e `__call__(self, questions: Mapping[str, Any], state: str) -> str`. A chamada devolve `json.dumps(body["answers"])`, de modo que quem chama recebe o mesmo texto que o programa externo imprime.
  - `def build_http_asker(timeout_seconds: float, env: Mapping[str, str] | None = None) -> HttpAsker`, que usa `os.environ`, `env_file_path()` e `macos_keychain`. Levanta `JevUnavailable("key_missing")` quando o endpoint não é loopback e não há chave.
- Requisição: `POST` com corpo JSON `{"model", "state", "questions"}` e cabeçalhos `Content-Type: application/json`, mais `Authorization: Bearer <key>` apenas quando o endpoint não é loopback.
- Os erros são `JevUnavailable` com estes códigos: `key_missing`, `key_rejected` (401, sem nova tentativa), `http_status` (outros não 2xx, a mensagem leva só o número), `retries_exhausted`, `timed_out` (o prazo passou ou houve timeout de socket), `network` (`URLError` ou `OSError`), `invalid_json`, `unparseable` (nenhum objeto `answers`). O prazo é `clock() + timeout_seconds`. O timeout de cada requisição é o tempo restante. Uma espera que cruzaria o prazo levanta `timed_out` em vez de dormir.

- [ ] **Passo 1: Escreva o servidor falso** `tests/fixtures/fake_jev_server.py`: um `ThreadingHTTPServer` em `127.0.0.1:0`, executado em uma thread daemon, usado como gerenciador de contexto que devolve sua URL. Recebe uma lista de respostas roteirizadas `(status, body_bytes, delay_seconds)` servidas em ordem (a última se repete) e registra os cabeçalhos e o corpo JSON de cada requisição em uma lista.

- [ ] **Passo 2: Escreva os testes que falham** em `tests/unit/test_jev_http.py`, com `JEV_API_URL` apontando para o servidor falso e o keychain definido como `lambda: None`:
  - `test_returns_answers_as_json_text`: o falso devolve `{"answers": {"risk": {"type": "choice", "choice": "low", "confidence": 0.9}}}`, e `json.loads(asker(q, "s"))["risk"]["choice"] == "low"`.
  - `test_body_has_model_state_questions`: o corpo registrado é igual a `{"model": "jev-latest", "state": "s", "questions": q}`.
  - `test_loopback_sends_no_authorization`: com uma chave presente, os cabeçalhos registrados não têm `Authorization`.
  - `test_retries_429_then_succeeds`: o roteiro é `[429, 429, 200]`, há 3 requisições registradas, e as chamadas registradas a `sleep` são iguais a `[0.5, 1.0]`.
  - `test_401_not_retried`: uma requisição, `code == "key_rejected"`, e a string da chave não está em `str(exc)`.
  - `test_deadline_bounds_retry_storm`: o roteiro é sempre 429, `timeout_seconds=1.0`, e `clock` e `sleep` são falsos que avançam um contador. Levanta `timed_out` e o tempo total simulado é <= 1.0.
  - `test_insecure_endpoint_refused`: `http://example.com/x` resulta em `endpoint_insecure`, `https://u:p@example.com/` resulta em `endpoint_credentials`, e nenhum dos dois faz requisição.
  - `test_missing_key_for_remote_endpoint`: o endpoint padrão sem chave faz `build_http_asker` levantar `key_missing`.
  - `test_body_without_answers_is_unparseable` e `test_non_json_body_is_invalid_json`.
  - `test_validate_questions_rules`: um `choice` com 1 opção, um `score` com 11 níveis, um `instructions` vazio e um `type` desconhecido levantam, cada um, `ValidationError`.

- [ ] **Passo 3: Execute-os e veja-os falhar**
  Execute: `PYTHONPATH=src python3 -m unittest tests.unit.test_jev_http -v`
  Esperado: ERROR, módulo não encontrado.

- [ ] **Passo 4: Implemente `jev_http.py`** com as interfaces acima. Adicione chaves i18n em `decisions.jev.why.` para cada novo código (`key_missing`, `key_rejected`, `http_status` com `{status}`, `retries_exhausted`, `network`, `endpoint_insecure`, `endpoint_credentials`) e `decisions.jev.error.invalid_questions` com `{why}`. O texto de `key_missing` nomeia os três lugares de onde uma chave é lida: `TYPESAFE_API_KEY`, `~/.config/wev-skills/.env` e o serviço do keychain do macOS `typesafe-api-key`.

- [ ] **Passo 5: Execute-os e veja-os passar.** Esperado: OK. Quebre a verificação do prazo de propósito e confirme que `test_deadline_bounds_retry_storm` falha.

- [ ] **Passo 6: Commit**
  ```bash
  git add src/wev_skills/decisions/jev_http.py tests/fixtures/fake_jev_server.py tests/unit/test_jev_http.py src/wev_skills/locales/decisions.*.json
  git commit -m "feat: ask JEV over HTTPS without an external program"
  ```

### Tarefa 3: Tornar o cliente embutido o caminho padrão do provedor

**Arquivos:**
- Modificar: `src/wev_skills/config.py:48-50` (padrão de `JevConfig.command`), `src/wev_skills/config.py:338-360` (`trust_errors`)
- Modificar: `src/wev_skills/decisions/jev.py:164-213` (`JevProvider.__init__` e `ask`)
- Modificar: `src/wev_skills/decisions/factory.py`, `src/wev_skills/decisions/jev_program.py` (`jev_warnings`)
- Teste: `tests/unit/test_decisions_factory.py`, `tests/unit/test_decisions_jev.py`, `tests/unit/test_jev_program.py`

**Interfaces:**
- Consome: `build_http_asker(timeout_seconds) -> HttpAsker` (Tarefa 2), `resolve_api_key` (Tarefa 1).
- Produz:
  - `BUILTIN = "builtin"` em `config.py`, que passa a ser o padrão de `JevConfig.command`.
  - `JevProvider.__init__` ganha o argumento nomeado `asker: Callable[[Mapping[str, Any], str], str] | None = None`. Quando definido, `ask()` devolve `asker(questions, redactor(state))` e não toca em `runner`. Quando é `None`, o caminho atual do programa fica inalterado.
  - A factory: quando `jev.command == BUILTIN`, passa `asker=LazyAsker(timeout)`, que chama `build_http_asker` no primeiro uso, de modo que uma chave ausente vira um `JevUnavailable` por chamada e um recurso à política local, não uma falha na inicialização.
  - `jev_warnings(config, root)`: com `BUILTIN`, avisa `decisions.jev.warning_key` quando `resolve_api_key` devolve `None` ou levanta exceção. Mantém a verificação atual do programa para qualquer outro comando.
  - `trust_errors` pula as regras de nome de programa quando `command == BUILTIN`.

- [ ] **Passo 1: Escreva os testes que falham**
  - `test_decisions_factory.py::test_builtin_is_default_and_uses_http`: o `Config()` padrão com `provider="jev"` e `JEV_API_URL` apontando para o servidor falso (fixture da Tarefa 2) faz `classify_task` não registrar nenhum motivo `jev.unavailable`, e o falso viu 1 requisição.
  - `test_decisions_factory.py::test_builtin_without_key_falls_back_locally`: o endpoint padrão, sem chave e com o keychain substituído por `None` resultam em uma classificação cujos motivos incluem o texto de `key_missing`, e o resultado do id do provedor é o valor local.
  - `test_decisions_jev.py::test_asker_receives_redacted_state`: um asker que registra seus argumentos, com um estado contendo `ghp_` seguido de 36 caracteres, não deve receber o token.
  - `test_jev_program.py::test_builtin_warns_when_no_key` e `test_builtin_no_warning_with_key`.
  - Mantenha todos os testes existentes que definem `command` como o caminho do programa falso. Eles devem continuar passando sem alteração.

- [ ] **Passo 2: Execute-os e veja-os falhar**
  Execute: `PYTHONPATH=src python3 -m unittest tests.unit.test_decisions_factory tests.unit.test_decisions_jev tests.unit.test_jev_program -v`
  Esperado: os testes novos FALHAM; os antigos passam.

- [ ] **Passo 3: Implemente** as mudanças de interface acima. Adicione `decisions.jev.warning_key` aos dois locales: "decision.provider is jev but no JEV key was found ({why}); the local policy is used".

- [ ] **Passo 4: Execute-os e veja-os passar**, mais `make test`. Esperado: tudo verde. O teste da linha de base de avaliação deve continuar reproduzindo byte a byte. Se não reproduzir, a mudança de padrão vazou para as avaliações: corrija o código, nunca a linha de base.

- [ ] **Passo 5: Commit**
  ```bash
  git add src/wev_skills/config.py src/wev_skills/decisions/ src/wev_skills/locales/ tests/unit/
  git commit -m "feat: use the built-in JEV client by default"
  ```

### Tarefa 4: Grupo de comandos `wev jev`

**Arquivos:**
- Criar: `src/wev_skills/commands/jev.py`
- Criar: `src/wev_skills/locales/jev.en.json`, `src/wev_skills/locales/jev.pt-BR.json`
- Teste: `tests/unit/test_cli_jev.py`

**Interfaces:**
- Consome: Tarefas 1 a 3; `commands/_scope.resolve_scope` para a configuração efetiva, como faz `commands/decide.py`.
- Produz (CLI, JSON na saída padrão):
  - `wev jev status` devolve `{"provider": "local"|"jev", "client": "builtin"|"program", "key_source": "env"|"env_file"|"keychain"|null, "key_error": str|null, "endpoint": str, "orchestration": "wev"|"harness"}`. `orchestration` é `"wev"` somente quando `provider == "jev"` e (para `builtin`) uma chave é resolvida ou o endpoint é loopback. Caso contrário é `"harness"`. O comando nunca faz chamada de rede e nunca imprime a chave. Sempre sai com 0.
  - `wev jev ask --questions FILE (--state TEXT | --state-file FILE)` devolve `{"answers": {...}}`. Valida as perguntas (saída 2 se inválidas) e redige o estado. Um `JevUnavailable` sai com 8.
  - `wev jev batch --questions FILE --items FILE.jsonl --out FILE.jsonl` recebe itens como `{"id", "state"}` por linha (saída 2 em linha inválida, nomeando o número da linha). Executa com concorrência de 4 (`ThreadPoolExecutor(max_workers=4)`) e grava uma linha JSON por item, `{"id", "answers"}` ou `{"id", "error"}`, na ordem de entrada. A saída padrão é `{"ok": n, "failed": m, "out": path}`. Sai com 8 quando `m > 0`, senão com 0.

- [ ] **Passo 1: Escreva os testes que falham** em `tests/unit/test_cli_jev.py`, que executam `bin/wev` em um subprocesso com `XDG_CONFIG_HOME` apontando para um diretório temporário, `JEV_API_URL` apontando para o servidor falso e `HOME` apontando para um diretório temporário:
  - `test_status_local_by_default`: sem configuração resulta em `provider == "local"` e `orchestration == "harness"`.
  - `test_status_jev_with_env_file_key`: um `wev.config.json` com `{"decision": {"provider": "jev"}}` no repositório do cwd, o endpoint padrão e um `.env` (modo 600) com a chave resultam em `key_source == "env_file"`, `orchestration == "wev"`, e a string da chave ausente da saída padrão e do stderr.
  - `test_status_jev_without_key_is_harness`: `orchestration == "harness"` e `key_error` não nulo.
  - `test_ask_prints_answers`, `test_ask_invalid_questions_exit_2`.
  - `test_batch_keeps_order_and_counts_failures`: 3 itens com o falso roteirizado como `[200, 500, 200]` (servido sem nova tentativa para o 500) resultam em um arquivo de saída com ids na ordem de entrada, `failed == 1` e saída 8.

- [ ] **Passo 2: Execute-os e veja-os falhar**
  Execute: `PYTHONPATH=src python3 -m unittest tests.unit.test_cli_jev -v`. Esperado: FALHA (nenhum grupo `jev`).

- [ ] **Passo 3: Implemente `commands/jev.py`** com `register(subparsers)`, seguindo `commands/decide.py` na estrutura e as strings de ajuda em `jev.<lang>.json`. Verifique que `adapters/claude_code/engine_cli.py` não precisa de nenhuma classe nova: `jev` não é nem um comando de operador nem um comando de run. Os testes de hook existentes devem continuar verdes.

- [ ] **Passo 4: Execute-os e veja-os passar**, mais `make test`. Esperado: verde.

- [ ] **Passo 5: Commit**
  ```bash
  git add src/wev_skills/commands/jev.py src/wev_skills/locales/jev.*.json tests/unit/test_cli_jev.py
  git commit -m "feat: add wev jev status, ask and batch"
  ```

### Tarefa 5: Chave de orquestração na skill e documentação

**Arquivos:**
- Modificar: `skills/wev-orchestrate/SKILL.md` (a seção antes do fluxo de run, perto das linhas 20 a 34)
- Modificar: `docs/guides/configuration-and-providers.md` e `.pt-BR.md` (a tabela `decision` e a seção `jev`, perto das linhas 37 a 41 e 141 a 175)
- Modificar: `CHANGELOG.md` (`[Unreleased]`), `docs/mvp-status.md` e `.pt-BR.md` (linha do JEV)
- Teste: `tests/unit/test_skills.py` (existente; verifica todo comando e flag que uma skill nomeia)

**Interfaces:**
- Consome: `wev jev status` (Tarefa 4).

- [ ] **Passo 1: Edite a skill.** Primeiro passo de toda sessão: execute `"${CLAUDE_PLUGIN_ROOT}/bin/wev" jev status`.
  - Se `orchestration` for `"wev"`, siga o fluxo de run como está escrito.
  - Se for `"harness"`, não execute `run start` nem os comandos de tarefa. Planeje e acompanhe o trabalho com as ferramentas do próprio harness.
  - Os hooks de guarda, as aprovações e a detecção de laços continuam ativos nos dois modos (decisão 14 da spec). Informe `key_error` ao usuário quando estiver definido e diga que executar o setup novamente liga o JEV.

- [ ] **Passo 2: Edite os guias**, EN e pt-BR, com as mesmas mudanças.
  - Padrão de `jev.command` `builtin`.
  - Ordem de busca da chave: `TYPESAFE_API_KEY`, `~/.config/wev-skills/.env` (modo 600, recusado caso contrário), keychain do macOS `typesafe-api-key`.
  - Regras de `JEV_API_URL`.
  - Nova tentativa e prazo.
  - O caminho do programa externo continua disponível definindo `command`.
  - `wev jev status|ask|batch`.
  - Rótulos de status: cliente embutido "implementado e testado contra um servidor falso local". Serviço real "não executado nesta mudança".
  - O que sai da máquina: o estado redigido e as perguntas, como antes.

- [ ] **Passo 3: Execute as verificações de documentação**
  Execute: `PYTHONPATH=src python3 -m unittest tests.unit.test_skills tests.unit.test_docs -v && bin/wev readme check && bin/wev claude-md check`
  Esperado: OK, e cada `check` sai com 0.

- [ ] **Passo 4: Verificação completa**
  Execute: `make check`. Esperado: testes OK, ruff e mypy limpos.

- [ ] **Passo 5: Commit**
  ```bash
  git add skills/wev-orchestrate/SKILL.md docs/guides/configuration-and-providers*.md docs/mvp-status*.md CHANGELOG.md
  git commit -m "docs: switch orchestration on JEV status and document the client"
  ```
