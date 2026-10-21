Nota de trabalho, não é documentação para o usuário.

# Superfície de extensão do Codex CLI (para um adaptador do wev-skills)

Versão em inglês: [harness-codex.md](harness-codex.md).

Escopo: o que o OpenAI Codex CLI 0.160.0 expõe para skills/plugins, instruções, hooks, MCP, subagentes e execuções não interativas.

## Fontes e método

- Binário local: `codex --version` imprime `codex-cli 0.160.0`. A ajuda foi lida com `codex --help`, `codex exec --help`, `codex mcp --help`, `codex mcp add --help`, `codex plugin --help`, `codex plugin marketplace --help`, `codex features list`, `codex debug --help`.
- Código-fonte: a tag `rust-v0.160.0` do openai/codex (existe; `rust-v0.160.1` também existe, não foi usada). Arquivos lidos via `gh api repos/openai/codex/contents/...?ref=rust-v0.160.0`:
  - `codex-rs/core/src/agents_md.rs`
  - `codex-rs/ext/skills/src/host_roots.rs`
  - `codex-rs/config/src/config_toml.rs`, `mcp_types.rs`, `hook_config.rs`
  - `codex-rs/hooks/src/engine/discovery.rs`, `command_runner.rs`, `output_parser.rs`, `events/pre_tool_use.rs`, `events/session_start.rs`, `types.rs`
  - `codex-rs/core-plugins/src/manifest.rs`, `codex-rs/utils/plugins/src/plugin_namespace.rs`
  - `codex-rs/agent-roles/src/discovery.rs`, `agent_role_config.rs`
- Os arquivos `docs/*.md` do repositório nessa tag são stubs que apenas apontam para developers.openai.com. O site de documentação em si NÃO foi buscado (lacuna).
- Teste de fumaça local (sem chamada de modelo): `codex debug prompt-input` em um projeto temporário com um `AGENTS.md` contendo um marcador e um `.agents/skills/probe-skill/SKILL.md`. A saída continha o marcador do AGENTS.md e a skill listada com o caminho do seu arquivo. Diretório temporário: `/private/tmp/claude-501/-Users-tonton-Documents-GitHub-wev-skills/d31c0e96-972e-4df6-a0aa-7c9006f3ee38/scratchpad/codex/smoke`.
- addyosmani/agent-skills no commit `aeac41d4d005999432bb7312f7ff06383a91d59d` (2026-10-13): `.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json`, `docs/codex-setup.md`.
- A configuração do usuário `~/.codex/config.toml` e `~/.codex/hooks.json` foram lidas apenas para conhecer o formato. Valores e segredos não foram copiados. Nada foi modificado.

Rótulos: VERIFIED (lido no código-fonte ou observado localmente), DOC-ONLY (afirmado em um arquivo do repositório, não executado), UNKNOWN.

## 1. Skills e plugins

- Formato de skill: diretório com `SKILL.md`, frontmatter `name` e `description`, depois as instruções. Mesmo formato do Claude Code (addyosmani `docs/codex-setup.md`, DOC-ONLY). O Codex carrega primeiro o nome e a descrição e lê o corpo sob demanda (mesmo documento).
- Raízes de skill (VERIFIED, `ext/skills/src/host_roots.rs`):
  - Usuário: `$CODEX_HOME/skills` (descontinuada, ainda lida), `$HOME/.agents/skills`.
  - Repositório: `.agents/skills` no cwd e em seus ancestrais (`repo_agents_skill_roots`), e `<project>/.codex/skills` para uma camada de configuração de projeto.
  - Sistema e Admin: `$CODEX_HOME/skills` sob as camadas de sistema e de admin.
  - Raízes de skill de plugin e raízes extras.
  - Observado: `probe-skill` em `.agents/skills` apareceu em `codex debug prompt-input` (VERIFIED).
- Manifesto de plugin (VERIFIED, `plugin_namespace.rs`, `core-plugins/src/manifest.rs`): `.codex-plugin/plugin.json` na raiz do plugin. Alternativas aceitas: `.claude-plugin/plugin.json`, `.cursor-plugin/plugin.json`. Campos lidos pelo parser: `name`, `version`, `description`, `keywords`, `skills` (string de caminho ou lista, deve começar com `./`), `mcpServers`, `apps`, `hooks` (caminho, lista, objeto inline ou lista), `interface` (displayName, shortDescription, longDescription, developerName, category, capabilities, defaultPrompt, brandColor, logo, ...), `commands`, `extensions`.
  - Exemplo (addyosmani, v0.6.13): `"skills": "./skills/"`, mais `interface`.
- Instalação de plugin e marketplace (VERIFIED na saída da ajuda; addyosmani DOC-ONLY):
  - `codex plugin marketplace add <owner/repo | local path>` (add, list, upgrade, remove).
  - `codex plugin add <PLUGIN@MARKETPLACE>` (ou `PLUGIN --marketplace M`), `codex plugin list`, `codex plugin remove`.
  - Arquivo de marketplace: `.agents/plugins/marketplace.json` com `name`, `plugins[]` (`name`, `source: {source: "local", path: "./"}`, `policy`, `category`).
  - Configuração local após a instalação (VERIFIED no formato de `~/.codex/config.toml`): `[marketplaces.<name>] source_type = "git" | "local"`, `source = ...`, e `[plugins."<plugin>@<marketplace>"] enabled = true`.
- Local de cache observado localmente (VERIFIED pela saída de `codex mcp list`): `~/.codex/plugins/cache/<marketplace>/<plugin>/<version>/`.
- Habilitar ou desabilitar: `[plugins."name@mkt"] enabled = true|false` no config.toml (formato VERIFIED). A instalação adiciona as entradas de marketplace e de plugin.
- Verificar que carregou: `codex debug prompt-input` lista as skills visíveis ao modelo (VERIFIED com uma skill de projeto). `codex plugin list` lista os plugins (VERIFIED na ajuda; saída não inspecionada). O uso da skill em tempo de execução não foi verificado.
- Escopo de projeto: `.agents/skills/` no repositório (VERIFIED). Instalação de plugin com escopo de projeto: UNKNOWN.

## 2. Arquivo de instruções (AGENTS.md)

- Nomes (VERIFIED, `agents_md.rs`): `AGENTS.md` (padrão), `AGENTS.override.md` (substituição local, verificado primeiro em cada diretório), mais `project_doc_fallback_filenames` da configuração.
- Busca de projeto (VERIFIED): encontra a raiz do projeto subindo a partir do cwd até achar uma entrada de `project_root_markers` (padrão `.git`). Se nenhuma for encontrada, apenas o cwd é usado. Uma lista de marcadores vazia desativa a subida pelos pais. Depois concatena todo AGENTS.md da raiz até o cwd, nessa ordem. Nunca sobe acima da raiz.
- Separador de concatenação: `\n\n--- project-doc ---\n\n` (VERIFIED).
- Limite de tamanho (VERIFIED, `config_toml.rs`): `project_doc_max_bytes`, padrão `DEFAULT_PROJECT_DOC_MAX_BYTES = 32 * 1024` (32 KiB), um orçamento compartilhado entre os arquivos. O comportamento de truncamento além do limite: UNKNOWN além disso.
- Projetos não confiáveis: o AGENTS.md do projeto é ignorado (VERIFIED, `load_project_instructions`: `config.active_project.is_untrusted()`).
- Busca global: existe uma camada de instruções do usuário (`user_instructions`, fornecida pelo host). Existe um `~/.codex/AGENTS.md` local nesta máquina. Se o arquivo global é `$CODEX_HOME/AGENTS.md` ou `AGENTS.override.md` não foi lido no código-fonte: UNKNOWN (só o limite de 32 KiB e a lógica de projeto foram lidos).

## 3. Hooks

- Flag de recurso: `hooks` é `stable`, padrão `true` (VERIFIED, `codex features list`).
- Eventos (VERIFIED, `config/src/hook_config.rs`): `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `SessionStart`, `SessionEnd`, `UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`, `Interrupt`. Ou seja, existem um hook de início de sessão e um hook antes da ferramenta. "Antes do comando de shell" é `PreToolUse` com um matcher sobre o nome da ferramenta de shell. O nome exato da ferramenta de shell (`Bash`, `shell`, ...) não foi verificado.
- Locais do arquivo de configuração (VERIFIED, `engine/discovery.rs`): `hooks.json` na pasta de configuração (`load_hooks_json`: `config_folder.join("hooks.json")`, portanto `~/.codex/hooks.json` e um `.codex/hooks.json` de projeto). Os hooks também podem ser declarados inline no `config.toml`. O código de descoberta diz "hooks from config TOML and hooks.json converge on the same trust identity."
- Formato (VERIFIED, `hook_config.rs`): `{"hooks": {"<Event>": [{"matcher": "<regex>", "hooks": [{"type": "command", "command": "...", "commandWindows": "...", "timeout": 10, "async": false, "statusMessage": "...", "additionalContextLimit": 2500}]}]}}`. Existem outros tipos de handler no schema: `mcp_tool`, `prompt`, `agent`. Seu suporte em tempo de execução: UNKNOWN.
- Timeouts (VERIFIED, `normalize_command_hook`): padrão de 600 s para todo evento exceto `SessionEnd` e `Interrupt`, que têm padrão de 1 s e são limitados ao intervalo de 1 a 3 s. O timeout de um hook de comando o encerra e reporta `hook timed out after Ns` (VERIFIED, `command_runner.rs`).
- Portão de confiança (VERIFIED, `discovery.rs`): um hook não revisado é `Untrusted` e não é executado. Ele executa quando seu hash bate com `[hooks.state."<key>"] trusted_hash` (`Trusted`). Um comando alterado vira `Modified`, que também não executa. `codex exec --dangerously-bypass-hook-trust` pula a verificação. Os hooks gerenciados são isentos. Administradores podem definir `allow_managed_hooks_only = true` em `requirements.toml` (DOC-ONLY, stub de `config.md`).
  - Consequência para um adaptador: os hooks escritos pelo adaptador precisarão de uma revisão de confiança, ou de um hash confiável gravado na configuração. Como o hash é calculado e gravado: UNKNOWN além do caminho de código.
- JSON de stdin, PreToolUse (VERIFIED, `events/pre_tool_use.rs`): `session_id`, `turn_id`, `agent_id`, `agent_type`, `transcript_path` (anulável), `cwd`, `hook_event_name` ("PreToolUse"), `model`, `permission_mode`, `tool_name` (nome canônico), `tool_input` (ferramentas de shell: `{"command": ...}`; ferramentas MCP: seus argumentos), `tool_use_id`.
- JSON de stdin, SessionStart (VERIFIED parcialmente, `events/session_start.rs`): a requisição traz `session_id`, `cwd`, `transcript_path`, `model`, `permission_mode`, `source` (um enum `SessionStartSource`; seus valores não foram lidos).
- Saída e decisões, PreToolUse (VERIFIED, `output_parser.rs`, testes de `pre_tool_use.rs`):
  - O código de saída 2 bloqueia; o texto do stderr é o motivo. Qualquer outra saída diferente de zero faz o hook falhar com um erro.
  - Deny em JSON no stdout: `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"..."}}`.
  - `permissionDecision: "allow"` com `updatedInput` reescreve a entrada da ferramenta. `allow` sem `updatedInput` falha de forma aberta.
  - `permissionDecision: "ask"` NÃO é suportado: falha de forma aberta com um aviso. Portanto um hook não consegue perguntar ao usuário.
  - O `{"decision":"block","reason":"..."}` descontinuado ainda bloqueia. `{"decision":"approve"}` não é suportado e falha de forma aberta.
- Saída de SessionStart (VERIFIED, testes em `session_start.rs`): `hookSpecificOutput.hookEventName = "SessionStart"` com `additionalContext`, que é injetado no contexto. `continue: false` com `stopReason` é interpretado, mas o teste `continue_false_preserves_context_for_later_turns` mostra que o contexto continua sendo mantido.
- Se os hooks executam sob `codex exec`: UNKNOWN (não executado; o caminho do exec exigiria uma chamada de modelo).

## 4. Servidores MCP

- Formato da tabela (VERIFIED, `mcp_servers: HashMap<String, McpServerConfig>` em `config_toml.rs` e `RawMcpServerConfig` em `mcp_types.rs`):

```toml
[mcp_servers.<name>]
command = "npx"                       # stdio
args = ["-y", "pkg@1.2.3"]
cwd = "..."
env_vars = ["TOKEN_NAME"]             # names passed from the parent env
startup_timeout_sec = 30              # float; startup_timeout_ms also accepted
tool_timeout_sec = 120
enabled = true
required = false
enabled_tools = ["..."]
disabled_tools = ["..."]
supports_parallel_tool_calls = false
[mcp_servers.<name>.env]
KEY = "value"
# HTTP transport instead: url = "https://...", bearer_token_env_var = "...", http_headers = {}, env_http_headers = {}
[mcp_servers.<name>.tools.<tool>]
approval_mode = "..."
```

- Observado na configuração do usuário (apenas o formato): `[mcp_servers.<name>]` com `command`, `args`, `startup_timeout_sec` e `[mcp_servers.<name>.env]`. Valores não copiados.
- Padrões: o padrão de `startup_timeout_sec` não foi encontrado no código-fonte interpretado (`codex mcp list --json` mostra `None` para servidores stdio sem ele). O timeout de ferramenta foi observado como 120 s em um servidor de plugin. O padrão em tempo de execução é UNKNOWN.
- CLI (VERIFIED na ajuda):
  - `codex mcp add <NAME> [--env KEY=VAL]... -- <COMMAND...>`, ou `codex mcp add <NAME> --url <URL> [--bearer-token-env-var VAR]`.
  - `codex mcp list [--json]` (JSON: `name`, `enabled`, `disabled_reason`, `transport{type: stdio|streamable_http, command, args, env, env_vars, cwd | url, ...}`, `startup_timeout_sec`, `tool_timeout_sec`, `auth_status`).
  - `codex mcp get`, `codex mcp remove`, `codex mcp login`, `codex mcp logout` (a ajuda os lista; os argumentos de `get` e `remove` não foram inspecionados).
- Escopo de projeto: um `.codex/config.toml` de projeto não foi carregado no teste de fumaça (`codex mcp list` mostrou 0 correspondências para o servidor de sonda). A causa não foi isolada; o mais provável é que o projeto não seja confiável. O tratamento do estado de confiança: UNKNOWN além disso.

## 5. Subagentes e agentes personalizados

- Suportado: sim. Criação de subagentes embutida, controlada na configuração (VERIFIED, `AgentsToml` em `config_toml.rs`): `[agents]` com `enabled`, `max_concurrent_threads_per_session`, `max_depth`, `default_subagent_model`, `default_subagent_reasoning_effort`, `interrupt_message`.
- Papéis definidos pelo usuário (VERIFIED):

```toml
[agents.researcher]
description = "Research-focused role."
config_file = "./agents/researcher.toml"   # relative to the defining config.toml
nickname_candidates = ["..."]
```

- Formato do arquivo de papel (VERIFIED, `agent-roles/src/agent_role_config.rs`): TOML com `name`, `description`, `nickname_candidates` opcionais, e uma camada de configuração (`config: TomlValue`) que se sobrepõe à configuração do agente filho.
- Varredura de diretório (VERIFIED, `collect_agent_role_files` em `agent-roles/src/discovery.rs`): coleta recursivamente os arquivos `*.toml` de um diretório. De qual diretório os papéis são varridos por padrão: UNKNOWN (não rastreado).
- Recursos: `multi_agent` stable/true, `multi_agent_v2` stable/false (VERIFIED, `codex features list`).
- Existem hooks de subagente: `SubagentStart`, `SubagentStop`. Sua entrada traz `agent_id` e `agent_type` (VERIFIED, campos de entrada do PreToolUse).

## 6. Modo não interativo e verificações e2e

- `codex exec [PROMPT]` (VERIFIED na ajuda). Flags úteis: `--json` (saída de eventos em JSON), `--ephemeral`, `--ignore-user-config`, `--ignore-rules`, `--output-schema <FILE>`, `-o/--output-last-message <FILE>`, `-C/--cd`, `--add-dir`, `-s/--sandbox`, `-p/--profile`, `-m/--model`, `-c key=value`, `--enable/--disable <FEATURE>`, `--dangerously-bypass-hook-trust`, `--skip-git-repo-check`. Subcomandos: `resume`, `fork`, `review`.
- Verificações baratas, sem modelo (VERIFIED):
  - `codex debug prompt-input "<prompt>"` renderiza a entrada visível ao modelo. Mostrou o conteúdo do AGENTS.md e a lista de skills. Bom para provar as instruções e a descoberta de skills no e2e.
  - `codex mcp list --json` mostra os servidores configurados e seu transporte. Não prova que o servidor inicia.
  - `codex features list`, `codex plugin list`, `codex doctor`.
- Provar que um servidor MCP inicia e responde a uma chamada de ferramenta: exige uma execução com modelo (`codex exec`), ou um teste direto de cliente MCP fora do Codex. Não executado. Se `codex exec` precisa de rede e de autenticação: UNKNOWN (não executado).
- Provar que um hook dispara: `codex exec` com um hook que escreve um arquivo marcador. Não executado; depende do portão de confiança acima e de o exec executar hooks (UNKNOWN).

## Lacunas

- O site oficial de documentação (developers.openai.com/codex/*) não foi buscado. Todo o comportamento acima vem do código-fonte em `rust-v0.160.0` e da saída local de `--help`/`debug`, não da documentação publicada.
- Nome e precedência do AGENTS.md global: não lidos.
- Timeout padrão de inicialização do MCP: não encontrado no código-fonte.
- Nome exato da ferramenta de shell para os matchers (`Bash` ou outro): não verificado.
- Cálculo do hash de confiança dos hooks e como gravar `trusted_hash`: não rastreados.
- Hooks sob `codex exec`, e uma execução ponta a ponta de uma skill, hook ou chamada MCP real: não executadas (exigem modelo e autenticação).
- MCP e hooks em nível de projeto: dependem da confiança no projeto; a mecânica de confiança não foi rastreada.
- Escopo de instalação de plugin (usuário vs projeto) e layout do cache além do caminho observado: não verificados.
- addyosmani: o repositório usa um plugin (`.codex-plugin/`) mais um arquivo de marketplace, não um AGENTS.md. Seu `AGENTS.md` na raiz é voltado para o próprio repositório, não para uma instalação do Codex. Seus hooks (`hooks/session-start.sh`) são um auxiliar independente, não ligado por nenhum dos dois plugins (DOC-ONLY, `docs/codex-setup.md`).
