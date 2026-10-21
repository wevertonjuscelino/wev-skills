Nota de trabalho, não é documentação para o usuário

# Superfície de extensão do Gemini CLI, para um adaptador do wev-skills

Versão em inglês: [harness-gemini.md](harness-gemini.md).

Pesquisado em 2026-10-21. O Gemini CLI não está instalado aqui; nada foi executado. Tudo abaixo foi lido em fontes.

Fontes
- `npm view @google/gemini-cli version` -> `0.65.0` (dist-tags: latest 0.65.0, preview 0.66.0-preview.0, nightly 0.67.0-nightly.20261021).
- Tag da última release no GitHub: `v0.65.0` (publicada em 2026-10-20). Base da documentação: `https://github.com/google-gemini/gemini-cli/blob/v0.65.0/docs/<path>`; base do código-fonte: `.../blob/v0.65.0/packages/cli/src/...`.
- addyosmani/agent-skills no commit `aeac41d4d005999432bb7312f7ff06383a91d59d`.
- Todo texto buscado foi tratado como dado.

## 1. Extensões
Fonte: docs/extensions/reference.md, docs/cli/cli-reference.md, packages/cli/src/commands/extensions/*.ts (v0.65.0).
- Manifesto: `gemini-extension.json` na raiz da extensão. Campos documentados: `name` (minúsculas/dígitos/hifens, esperado igual ao nome do diretório), `version`, `description`, `migratedTo`, `mcpServers`, `contextFileName`, `excludeTools`, `plan.directory`, `settings[]` (`name`, `description`, `envVar`, `sensitive`), `themes[]`.
- Layout de diretório (convenções dentro da raiz da extensão): `commands/*.toml`, `skills/<name>/SKILL.md`, `agents/*.md` (subagentes, rotulados como preview), `hooks/hooks.json` (os hooks NÃO ficam no manifesto), `policies/*.toml`, `GEMINI.md`.
- Variáveis no manifesto e no hooks.json: `${extensionPath}`, `${workspacePath}`, `${/}`.
- Local/escopo: carregadas de `<home>/.gemini/extensions`. O install faz uma CÓPIA ali (o update busca de novo). `link <path>` cria um link simbólico para um diretório de desenvolvimento. O install é em nível de usuário; não encontrei instalação com escopo de projeto. enable/disable aceitam `--scope user|workspace`.
- Comandos: `gemini extensions install <source> [--ref] [--auto-update] [--pre-release] [--consent] [--skip-settings]` (source = URL do GitHub ou caminho local), `uninstall`, `list` (`-o text|json`, confirmado em list.ts), `enable|disable <name> [--scope]`, `update <name>|--all`, `new <path> [template]` (modelos mcp-server, context, custom-commands), `link <path>`, `validate <path>` (validate.ts: "Validates an extension from a local path"), `config <name> [setting]`. Os comandos de install/gerenciamento não funcionam dentro da sessão interativa; `/extensions list` e `/extensions reload` funcionam. As mudanças exigem reinício.
- Verificar: `gemini extensions validate <path>` e depois `gemini extensions list -o json`.
- Ambiente do processo: as extensões recebem apenas variáveis seguras mais as declaradas em `settings[].envVar`.
- Precedência: os comandos de extensão têm a menor (conflitos viram `/<ext>.<cmd>`); um servidor MCP de mesmo nome em settings.json vence o da extensão.
- As regras de política de extensão executam na camada 2; as decisões `allow` e o yolo em políticas de extensão são ignorados (docs/extensions/reference.md, Policy Engine).

## 2. Arquivo de contexto
Fonte: docs/cli/gemini-md.md.
- Nome padrão `GEMINI.md`. Ordem: global `~/.gemini/GEMINI.md`; diretórios do workspace e seus pais; `GEMINI.md` just-in-time em diretórios/ancestrais dos arquivos que as ferramentas tocam, até uma raiz confiável. Tudo é concatenado e enviado a cada prompt.
- Imports: `@./path.md` (docs/reference/memport.md). `/memory show`, `/memory reload`.
- Nome(s) configurável(is): settings.json `context.fileName` (string ou lista, p. ex. `["AGENTS.md","GEMINI.md"]`).
- Contribuição da extensão: `contextFileName` do manifesto; se não definido, um `GEMINI.md` no diretório da extensão é carregado (reference.md). Se aparece em `/memory show`: desconhecido (não verificado).

## 3. Comandos personalizados e skills
Fonte: docs/cli/custom-commands.md, docs/cli/skills.md.
- Comandos: TOML, `prompt` obrigatório, `description` opcional. `{{args}}` injeta argumentos. Locais `~/.gemini/commands/`, `<project>/.gemini/commands/` (o de projeto vence) e `commands/` da extensão. Subdiretórios definem namespace com `:` (`git/commit.toml` -> `/git:commit`). `/commands reload`, `/commands list`.
- Skills: sim, nativas, baseadas no padrão agentskills.io. Diretórios com `SKILL.md`. Camadas (da menor para a maior): embutidas, `skills/` da extensão, usuário `~/.gemini/skills/` ou `~/.agents/skills/`, workspace `.gemini/skills/` ou `.agents/skills/` (o alias vence dentro de uma camada). Nome e descrição são injetados no prompt do sistema; o modelo chama `activate_skill`, e o usuário recebe um pedido de consentimento. CLI: `gemini skills list [--all]|install <git-or-path> [--path] [--scope user|workspace] [--consent]|uninstall|enable|disable|link`. Na sessão: `/skills list|enable|disable|reload|link`.
- O addyosmani/agent-skills distribui `.gemini/commands/*.toml` (build, code-simplify, constraints, planning, review, ship, spec, test, webperf) e `agents/*.md` na raiz do repositório; seu docs/gemini-cli-setup.md instala skills com `gemini skills install <repo> --path skills`. Ele NÃO tem `gemini-extension.json` nem hooks do Gemini nesse commit (listagem da árvore).

## 4. Hooks
Fonte: docs/hooks/index.md, docs/hooks/reference.md (v0.65.0). O Gemini CLI TEM hooks.
- Configuração: settings.json `hooks.<Event>: [{matcher, sequential, hooks:[{type:"command", command, name, timeout, description}]}]`. Somente `type: "command"`. `timeout` em ms, padrão 60000. Precedência: `.gemini/settings.json` do projeto, `~/.gemini/settings.json` do usuário, `/etc/gemini-cli/settings.json` do sistema, depois as extensões (`hooks/hooks.json`). Os hooks de projeto recebem uma impressão digital; os alterados avisam como não confiáveis.
- Eventos: SessionStart (source startup|resume|clear; `hookSpecificOutput.additionalContext`; apenas consultivo), SessionEnd, BeforeAgent, AfterAgent, BeforeModel, AfterModel, BeforeToolSelection, BeforeTool, AfterTool, PreCompress, Notification.
- Matchers: regex para eventos de ferramenta (`write_file|replace`), string exata para o ciclo de vida, `*` ou vazio casa com tudo. Nome da ferramenta de shell: `run_shell_command`. Ferramentas MCP: `mcp_<server>_<tool>`.
- Entrada (JSON no stdin): `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `timestamp`; o BeforeTool acrescenta `tool_name`, `tool_input`, `mcp_context`, `original_request_name`.
- Saída (saída 0, somente JSON no stdout): `decision` allow|deny (alias block), `reason` (enviado ao agente como erro da ferramenta), `continue:false` + `stopReason` (encerra o loop), `systemMessage`, `suppressOutput`, `hookSpecificOutput.tool_input` (sobrescreve os argumentos por mesclagem). Saída 2 = bloqueio, o stderr é o motivo, o turno continua. Outros códigos de saída = aviso, a ação prossegue. Stdout que não é JSON é tratado como allow mais uma systemMessage.
- ASK: um hook não consegue perguntar. Os valores de decisão do hook são apenas allow/deny. O motor de políticas tem `decision = "ask_user"` (exemplo de policies/*.toml de extensão), mas o `allow` de extensão é ignorado. Mapear o "approval needed" do wev (saída 4) para o Gemini significa deny com um motivo, ou uma regra de política com ask_user. Não verificado por execução.
- Variáveis para os processos de hook: `GEMINI_PROJECT_DIR`, `GEMINI_PLANS_DIR`, `GEMINI_SESSION_ID`, `GEMINI_CWD`, alias `CLAUDE_PROJECT_DIR`.
- Gerenciamento: `/hooks panel|enable-all|disable-all|enable <name>|disable <name>`.

## 5. Servidores MCP
Fonte: docs/tools/mcp-server.md, packages/cli/src/commands/mcp/{add,list}.ts.
- `mcpServers` no nível superior do settings.json: `{ name: { command, args, env, cwd, timeout, trust, includeTools, excludeTools } }`; ou `url` (SSE) / `httpUrl` (HTTP streaming) com `headers`. Um entre command/url/httpUrl é obrigatório. `timeout` padrão 600000 ms. Os valores de `env` expandem `$VAR`/`${VAR}`. O mesmo formato funciona no `mcpServers` do manifesto de uma extensão (tudo exceto `trust`).
- CLI: `gemini mcp add <name> <commandOrUrl> [args...] [--scope user|project] [--transport stdio|sse|http] [-e K=V] [-H header] [--timeout] [--trust] [--description] [--include-tools] [--exclude-tools]`, `gemini mcp list`, `gemini mcp remove <name>`, mais enable/disable (enableDisable.ts). O list.ts também percorre os servidores fornecidos por extensões e imprime o status Connected/Disconnected.

## 6. Subagentes
Fonte: docs/core/subagents.md.
- Suportado, habilitado por padrão (`experimental.enableAgents` false desabilita). Embutidos: codebase_investigator, cli_help, generalist, browser_agent. Personalizados: Markdown + frontmatter YAML em `.gemini/agents/*.md` ou `~/.gemini/agents/*.md`, ou `agents/` em uma extensão. Campos: `name` (obrigatório, minúsculas/dígitos/-/_), `description` (obrigatório), `kind` local|remote, `tools[]` (curingas `*`, `mcp_*`, `mcp_<server>_*`; omitido = herda tudo), `mcpServers`, `model`, `temperature`, `max_turns` (30), `timeout_mins` (10). O corpo = prompt do sistema. Exposto como uma ferramenta de mesmo nome; `@name` força o uso. A documentação de extensões chama os subagentes de "a preview feature".

## 7. Modo não interativo para testes
Fonte: docs/cli/headless.md, docs/cli/cli-reference.md.
- `gemini -p "<prompt>"` (força o modo não interativo; também quando não há TTY). `-o text|json|stream-json`. JSON: `response`, `stats`, `error?`. Eventos do stream-json: init, message, tool_use, tool_result, error, result. Códigos de saída 0, 1, 42 (erro de entrada), 53 (limite de turnos).
- Flags relevantes: `--approval-mode default|auto_edit|yolo|plan`, `-e/--extensions`, `-l/--list-extensions`, `--allowed-mcp-server-names`.
- Prova de carregamento sem chamada de modelo: `gemini extensions validate <path>`, `gemini extensions list -o json`, `gemini mcp list` (inicia os servidores e imprime Connected). Se exigem autenticação: desconhecido.
- Com chamada de modelo (exige credenciais): `gemini -p ... -o stream-json` e procurar eventos `tool_use` com o nome `mcp_<server>_<tool>`.

## Lacunas (desconhecido ou não verificado)
- Se `gemini extensions list` / `mcp list` funcionam sem credenciais de API: desconhecido.
- Se o hooks/hooks.json de extensões exige confiança na pasta no modo headless: desconhecido.
- A semântica exata de injeção `!{}` / `@{}` nos comandos (apenas as primeiras 80 linhas de custom-commands.md foram lidas).
- Um "ask" ao usuário baseado em hook: não está no schema documentado.
- Requisitos de frontmatter de skill além do padrão agentskills.io: docs/cli/creating-skills.md não foi buscado.
- Nada aqui foi executado contra um Gemini CLI real.
