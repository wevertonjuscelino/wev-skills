Nota de trabalho, não é documentação para o usuário

# Interface de extensão do OpenCode (pesquisa para um adaptador do wev-skills)

Versão em inglês: [harness-opencode.md](harness-opencode.md).

Pesquisado em 2026-10-21. O OpenCode não está instalado nesta máquina, então nada abaixo foi executado; todo fato foi lido em fontes. O texto buscado foi tratado como dado.

## Fontes e versões

- `npm view opencode-ai version` retornou 1.19.3. A última release do repositório no GitHub é a tag `v1.19.3` (2026-10-16). `sst/opencode` agora redireciona para `anomalyco/opencode` (branch padrão `dev`).
- Documentação na tag, no repositório: `https://github.com/sst/opencode/blob/v1.19.3/packages/web/src/content/docs/<page>.mdx` (páginas: config, rules, agents, commands, skills, plugins, mcp-servers, cli, permissions). O site opencode.ai/docs é gerado a partir delas; o site em si não foi buscado.
- Definições de tipo do plugin: `https://github.com/sst/opencode/blob/v1.19.3/packages/plugin/src/index.ts`.
- Código-fonte da CLI de depuração: `https://github.com/sst/opencode/blob/v1.19.3/packages/opencode/src/cli/cmd/debug/` (`config.ts`, `skill.ts`, `agent.ts`).
- addyosmani/agent-skills no commit `aeac41d4d005999432bb7312f7ff06383a91d59d` (main): `.opencode/skills` é um link simbólico para `../skills/`; não há `.opencode/commands` na main (o próprio documento diz isso, o PR #200 propõe); `docs/opencode-setup.md` descreve a configuração.

## 1. Configuração e instruções

- Formato: `opencode.json` ou `opencode.jsonc`; schema `https://opencode.ai/config.json` (config.mdx#Format).
- Global: `~/.config/opencode/opencode.json` (também `tui.json` para a TUI). Projeto: `opencode.json` na raiz do projeto; a busca começa no cwd e sobe até o diretório Git mais próximo (config.mdx#Per project).
- Ordem de mesclagem, o posterior sobrescreve o anterior: `.well-known/opencode` remoto, global, arquivo `OPENCODE_CONFIG`, projeto, diretórios `.opencode`, `OPENCODE_CONFIG_CONTENT`, arquivos gerenciados, preferências gerenciadas do macOS. Os arquivos são mesclados, não substituídos. `OPENCODE_CONFIG_DIR` adiciona um diretório de configuração personalizado.
- `.opencode/` e `~/.config/opencode/` usam subdiretórios no plural: `agents/ commands/ modes/ plugins/ skills/ tools/ themes/` (o singular é aceito por retrocompatibilidade).
- Regras: `AGENTS.md` no projeto (sobe a partir do cwd), `~/.config/opencode/AGENTS.md` global. Fallbacks do Claude Code: `CLAUDE.md` usado somente se não houver `AGENTS.md`; `~/.claude/CLAUDE.md` usado somente se não houver `AGENTS.md` global. A primeira correspondência vence por categoria. Desative com `OPENCODE_DISABLE_CLAUDE_CODE`, `..._PROMPT`, `..._SKILLS` (rules.mdx).
- Arquivos de instrução extras: `"instructions": ["CONTRIBUTING.md", "docs/*.md", "https://..."]` (globs e URLs; as URLs têm timeout de 5 s), combinados com o `AGENTS.md`.
- Variáveis na configuração: `{env:NAME}`, `{file:path}`.
- Implicação: este repositório já tem `CLAUDE.md` e um `AGENTS.md` não rastreado; o OpenCode leria o `AGENTS.md` e ignoraria o `CLAUDE.md`.

## 2. Agentes e subagentes

- Duas formas (agents.mdx#Configure): JSON em `agent.<name>` no `opencode.json`, ou arquivos markdown em `.opencode/agents/` (projeto) e `~/.config/opencode/agents/` (global). O nome do arquivo (sem `.md`) é o nome do agente.
- Chaves de frontmatter markdown documentadas: `description` (obrigatória), `mode` (`primary`, `subagent`, `all`; padrão `all`), `model` (`provider/model`), `temperature`, `top_p`, `steps` (`maxSteps` descontinuado), `disable`, `hidden` (somente subagentes), `color`, `permission` (padrões de edit, bash, webfetch, skill, task), `tools` (descontinuado). O corpo é o prompt do sistema. O JSON também aceita `prompt`, inclusive `{file:./prompts/x.txt}`.
- Embutidos: primários `build`, `plan`; subagentes `general`, `explore`, `scout`; ocultos `compaction`, `title`, `summary`. Os subagentes são invocados por `@name` ou pelo modelo por meio da ferramenta Task. `subagent_depth` (padrão 1) limita o aninhamento; `default_agent` escolhe o agente primário.
- Diferenças em relação aos agentes do Claude Code: não há lista de permissões `tools:` na forma preferida (use `permission`), `model` é `provider/model`, `mode` não tem equivalente no Claude. As skills não são pré-carregadas por agente; `permission.skill` pode restringi-las.
- CLI: `opencode agent create` (não interativo quando `--path --description --mode --permissions` são todos informados) e `opencode agent list`.

## 3. Comandos e skills

- Comandos (commands.mdx): markdown em `.opencode/commands/` ou `~/.config/opencode/commands/`, ou JSON `command.<name>` com `template`. Frontmatter: `description`, `agent`, `model`, `subtask` (não lido nesta passagem). O corpo é o modelo; placeholders `$ARGUMENTS`, `$1 $2 ...`; o nome do arquivo é o nome do comando, usado como `/name`. Existem saída de shell e sintaxe de inclusão de arquivo (não verificadas aqui).
- As skills existem e seguem a mesma convenção SKILL.md do Claude Code (skills.mdx). Carregadas sob demanda por uma ferramenta nativa `skill`; a descrição da ferramenta lista `<available_skills>`; o modelo chama `skill({ name })`.
- Caminhos de busca de skill (os caminhos de projeto são encontrados subindo até a worktree do git): `.opencode/skills/<name>/SKILL.md`, `~/.config/opencode/skills/<name>/SKILL.md`, `.claude/skills/...`, `~/.claude/skills/...`, `.agents/skills/...`, `~/.agents/skills/...`.
- Frontmatter reconhecido: `name` (obrigatório, deve ser igual ao nome do diretório, regex `^[a-z0-9]+(-[a-z0-9]+)*$`, no máximo 64), `description` (obrigatória, 1 a 1024), `license`, `compatibility`, `metadata` (mapa de strings). Campos desconhecidos são ignorados.
- Permissões: `permission.skill` com padrões `allow|deny|ask`.
- Implicação: os `skills/*/SKILL.md` existentes do wev-skills carregam sem alteração se satisfizerem a regra do nome. Observe que `${CLAUDE_PLUGIN_ROOT}` é uma variável do Claude Code e não significa nada para o OpenCode (inferido, não testado).

## 4. Plugins e hooks

- Um plugin é um módulo JS ou TS que exporta uma ou mais funções assíncronas; cada uma recebe `{ project, client, $, directory, worktree, serverUrl, experimental_workspace }` e devolve um objeto de hooks (plugins.mdx; `PluginInput` em plugin/src/index.ts).
- Carregamento: os arquivos em `.opencode/plugins/` e `~/.config/opencode/plugins/` carregam automaticamente; os pacotes npm por `"plugin": [...]` na configuração, instalados com o Bun e em cache em `~/.cache/opencode/node_modules/`. `opencode plugin <module> [--global]` instala um e edita a configuração. As dependências de plugin local ficam em `.opencode/package.json` (`bun install` na inicialização). Ordem de carga: configuração global, configuração de projeto, diretório de plugins global, diretório de plugins de projeto; todos os hooks executam em sequência.
- Interface `Hooks` (v1.19.3): `event`, `config`, `tool`, `auth`, `provider`, `chat.message`, `chat.params`, `chat.headers`, `permission.ask`, `command.execute.before`, `tool.execute.before`, `tool.execute.after`, `shell.env`, `tool.definition`, `experimental.chat.messages.transform`, `experimental.chat.system.transform`, `experimental.session.compacting`, `experimental.compaction.autocontinue`, `experimental.text.complete`, `experimental.provider.small_model`, `dispose`.
- Nomes de evento pelo hook `event` (lista da documentação): `session.created`, `session.idle`, `session.compacted`, `session.deleted`, `session.error`, `session.status`, `session.updated`, `session.diff`, `message.*`, `permission.asked`, `permission.replied`, `command.executed`, `file.edited`, `tool.execute.before/after`, `todo.updated`, `shell.env`, `lsp.*`, `server.connected`, `tui.*`, `installation.updated`.
- Mapeamento para os hooks do wev (os eventos do lado do Claude vêm da ligação em hooks.json, não foram reverificados): pre-tool-use mapeia para `tool.execute.before` (`input: {tool, sessionID, callID}`, `output: {args}`); post-tool-use para `tool.execute.after` (`input` acrescenta `args`; `output: {title, output, metadata}`); o início de sessão não tem hook dedicado, os mais próximos são o evento `session.created` e `experimental.chat.system.transform`; stop mapeia para `session.idle` (a issue de terceiros #50133 dá o mesmo mapeamento).
- Bloquear um comando de shell: o exemplo da documentação bloqueia uma leitura com `throw new Error(...)` dentro de `tool.execute.before` quando `input.tool === "read"`. O id da ferramenta bash é `"bash"` e seu comando é `output.args.command` (o exemplo de dependência da documentação lê `input.tool === "bash"` e `output.args.command`). Portanto, lançar um erro em `tool.execute.before` para `bash` é o caminho de bloqueio documentado. Alternativa: `permission.ask` com `output.status = "deny"`, ou regras de `permission` na configuração. Se um erro lançado chega ao modelo como mensagem de erro literal: desconhecido, não testado.
- Workdir por chamada (fonte do plugin e do codec do wev): a ferramenta bash aceita o argumento opcional `workdir`, em anomalyco/opencode `packages/core/src/tool/plugin/shell.ts` (v1.19.3). Lido no código-fonte; não executado contra um OpenCode real.
- Lacunas (issue https://github.com/anomalyco/opencode/issues/50133, aberta, afirmações de terceiros, não verificadas no código-fonte): os hooks de ferramenta não trazem `cwd`; não há hooks por agente; as chamadas de ferramenta que falham não são sinalizadas com clareza em `tool.execute.after`. O PR #36238 afirma que as chamadas de ferramenta de subagentes agora disparam hooks de plugin (título de um PR de teste; não lido em detalhe). Se as chamadas de ferramenta MCP passam por `tool.execute.before`: desconhecido.
- Chamar um executável externo: um plugin é código Bun comum. `$` é a API de shell do Bun, então chamadas no estilo `await $\`wev hook pre-tool-use\`.stdin(json)`, ou `Bun.spawn` / `node:child_process` com JSON no stdin, são possíveis em princípio. Fato verificado: `$` executa comandos (a documentação usa `$\`osascript ...\``). Não verificado: que o encaminhamento por stdin funcione exatamente como escrito; é preciso testar com um OpenCode instalado. Esboço do adaptador: o plugin inicia `wev hook pre-tool-use` com um payload JSON no estilo do Claude montado a partir de `{tool, sessionID, args}`, lê o código de saída (wev saída 3 negado, 4 aprovação necessária, 6 guarda acionada) e lança um erro quando for diferente de zero.
- Ferramentas personalizadas também podem ser definidas em plugins por `tool: { name: tool({ description, args, execute }) }` usando `@opencode-ai/plugin` e Zod (as ferramentas de plugin sobrescrevem as embutidas de mesmo nome); arquivos de ferramenta personalizada independentes ficam em `.opencode/tools/` (custom-tools.mdx, não lido em detalhe).

## 5. Servidores MCP

- Chave de configuração `mcp.<name>` no `opencode.json` (mcp-servers.mdx).
- Local: `{ "type": "local", "command": ["npx","-y","pkg"], "environment": {"K":"V"}, "cwd": "...", "enabled": true, "timeout": 5000 }`. `command` é um array (programa mais argumentos), não uma string; a chave de ambiente é `environment`.
- Remoto: `{ "type": "remote", "url": "https://...", "enabled": true, "headers": {...} }`; OAuth é suportado para servidores remotos.
- CLI: `opencode mcp add` (assistente interativo, sem flags documentadas), `opencode mcp list` / `ls` (mostra o status da conexão), `opencode mcp auth [name]`, `opencode mcp auth list`, `opencode mcp logout [name]`, `opencode mcp debug <name>` (cli.mdx). Escrever o arquivo de configuração diretamente é o caminho que se pode automatizar.
- As ferramentas MCP recebem o nome do servidor; os padrões de `permission` podem mirá-las (permissions.mdx, não lido em detalhe).

## 6. Modos não interativos para testes

- `opencode run [message..]` executa um prompt sem a TUI. Flags: `--command`, `--agent`, `--model provider/model`, `--format json` (eventos JSON brutos), `--dir`, `--file`, `--continue`, `--session`, `--attach URL` (usar com `opencode serve`), `--auto` (aprova automaticamente as permissões não negadas explicitamente), `--port`, `--title`. Precisa de um provedor de modelo configurado e envia um prompt real, então não está livre de rede nem de modelo; é inadequado para os testes unitários offline que este repositório exige, mas serve para um teste de integração opcional.
- Verificações de carregamento offline que não precisam de modelo, lidas no código-fonte da v1.19.3 (`packages/opencode/src/cli/cmd/debug/`): `opencode debug config` imprime a configuração resolvida como JSON (com dados sensíveis ocultados); `opencode debug skill` imprime todas as skills descobertas como JSON; `opencode debug agent <name>` mostra a configuração de um agente; também `debug paths`, `debug info`. Elas não estão na página da documentação, e sua saída não foi observada. São as melhores candidatas para provar que agentes, skills e entradas MCP carregam; `opencode agent list` e `opencode mcp list` são as documentadas (`mcp list` pode iniciar servidores).
- Auxiliares de ambiente para testes herméticos: `OPENCODE_CONFIG`, `OPENCODE_CONFIG_DIR`, `OPENCODE_CONFIG_CONTENT`, `OPENCODE_DISABLE_CLAUDE_CODE`, `OPENCODE_DISABLE_AUTOUPDATE`, `OPENCODE_PERMISSION`.
- Os comandos não são cobertos por um listador offline; `opencode debug config` deveria incluir o mapa `command` mesclado, mas isso não foi verificado.

## Resumo das lacunas

- Nada foi executado; todo o comportamento em tempo de execução (stdin para um processo iniciado, a forma exata do erro lançado, chamadas MCP passando pelo hook pre-tool, o formato da saída de debug) não foi verificado.
- `subtask` e outras chaves de frontmatter de comandos, o formato de `.opencode/tools/` e os padrões de permissão para ferramentas MCP não foram lidos por inteiro.
- O mapeamento exato de campos de agentes do claude.ai para o OpenCode (lista de permissões de tools para permission) exige uma decisão de design mais um teste contra um OpenCode instalado.
