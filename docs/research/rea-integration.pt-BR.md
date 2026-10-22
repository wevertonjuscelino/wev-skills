Nota de trabalho, não é documentação para o usuário

# Pesquisa de integração do rea (morluto/rea, npm rea-agents)

Versão em inglês: [rea-integration.md](rea-integration.md).

Escopo: pesquisa somente de leitura da interface, para a parte 5 do wev-skills. Fontes: `gh api repos/morluto/rea/contents/...` (branch padrão, obtido em 2026-10-22) e `npm view rea-agents` (última 6.7.0, modificada em 2026-10-18). Nada foi instalado nem executado. Os caminhos são caminhos do repositório; "docs/" significa `docs/` em morluto/rea. A documentação descreve a `main`, que pode estar à frente da 6.7.0; as afirmações válidas só para a main estão marcadas.

Rótulos: documentado (lido na documentação do rea, não executado por nós); desconhecido (não encontrado nas fontes obtidas).

## 1. Instalação e registro de agentes

Pontos de entrada: `npx rea-agents setup` (docs/installation.md, "Start setup"). `install.sh` (raiz do repositório) verifica Node (22.19+, 24.11+ ou 26+), curl e npm, instala o pacote npm globalmente (`npm install --global`, ou `--prefix ~/.local`) e só então executa `rea setup`, quando há um terminal disponível. `--no-setup` ou `--no-prompt` pula o setup. Documentado.

Agentes que o setup pode registrar (docs/installation.md, "Supported agents"; valores de `--client`): claude_code, claude_desktop, codex, cursor, gemini_cli, windsurf, devin, opencode, antigravity, copilot_cli, commandcode, qwen_code, kimi, vscode, grok_build, omp, pi, hermes, qoder, droid, trae, workbuddy, zcode, dsh. Sete deles (droid, dsh, kimi, qoder, trae, workbuddy, zcode) exigem rea-agents 6.5.0 ou posterior. Documentado.

O que ele grava (docs/client-configuration.md):
- Claude Code: `mcpServers.rea` em `~/.claude.json` (ou `$CLAUDE_CONFIG_DIR/.claude.json`); skill em `~/.claude/skills`. JSON.
- Claude Desktop: `mcpServers.rea` em `claude_desktop_config.json` (macOS `~/Library/Application Support/Claude`; Linux `$XDG_CONFIG_HOME/Claude`; Windows `%APPDATA%\Claude`). Feche o aplicativo antes de aprovar. JSON.
- Codex: tabela MCP em `$CODEX_HOME/config.toml` (padrão `~/.codex`), com `startup_timeout_sec = 30` e um `tool_timeout_sec`. TOML.
- Gemini CLI: `mcpServers.rea` em `$GEMINI_CLI_HOME/.gemini/settings.json`. Entradas de workspace ou de sistema substituem a entrada do usuário. JSON.
- OpenCode: `mcp.rea` (V1) ou `mcp.servers` (V2) em sua configuração JSON ou JSONC, respeitando `OPENCODE_CONFIG_DIR`. JSON.
- Grok Build: `[mcp_servers.rea]` e `[mcp_servers.rea.env]` em `$GROK_HOME/config.toml` (padrão `~/.grok`). TOML.
- Hermes: `mcp_servers.rea` em `config.yaml`. YAML.
- Qwen Code: `mcpServers` em `~/.qwen/settings.json`. JSON.
- Pi: `mcpServers.rea` (tipo stdio) em `~/.pi/agent/mcp.json`. JSON.
- OMP: `~/.omp/agent/mcp.json`. JSON.
- Qoder: `mcpServers.rea` em `~/.qoder/settings.json`. JSON.
- Factory Droid: `mcpServers.rea` em `~/.factory/mcp.json`. JSON.
- Trae: `mcp.json` no escopo do usuário, no diretório de usuário no estilo do VS Code. JSON.
- WorkBuddy: `~/.workbuddy/mcp.json`. JSON.
- ZCode: `~/.zcode/cli/config.json`. JSON.
- DeepSeek Harness (dsh): entrada em `$DSH_HOME/cordis.patch.yml` (padrão `~/.dsh`). YAML.
- Devin: `devin/mcp_config.json` (fora do Windows, respeita XDG_CONFIG_HOME). JSON.
- Kimi Code: `~/.kimi-code/mcp.json` (ou `$KIMI_CODE_HOME`). JSON.
- GitHub Copilot CLI: `mcpServers.rea` em `mcp-config.json` (o caminho completo não consta no texto obtido).
- Caminhos MCP do Cursor, Windsurf, VS Code e Antigravity: desconhecidos na documentação obtida. O Cursor aparece apenas na tabela de clientes suportados.

Comando registrado: forma de executor de pacote `npx -y rea-agents@<exact version> mcp` (ou `bunx rea-agents@<version> mcp`; envolvido em `cmd.exe /d /c` no Windows). O setup fixa a versão exata instalada. Uma instalação global pode ser registrada diretamente: `npm install --global rea-agents` e depois `rea setup` registra o ponto de entrada instalado. Documentado (docs/installation.md, "Package runners and global installation" e "MCP Registry").

Skills e fluxo de trabalho: sim. O setup instala a skill empacotada e suas referências no diretório pessoal de skills de cada cliente selecionado. `--skill=false` desativa isso. Sem nenhum cliente selecionado, a skill vai para `~/.agents/skills`. Documentado (docs/installation.md, "Skill destinations").

Consentimento e uso não interativo: o setup mostra um plano com os caminhos e as mudanças exatos e exige aprovação; recusar ou Ctrl-C não altera nada. Os prompts só aparecem quando stdin, stdout e stderr são todos TTYs. Não interativo: `rea setup --client <id> --yes`, ou `--all-detected --yes`. `--yes` sozinho toca apenas registros já existentes do próprio REA. `--dry-run` devolve um plano com saída 0; `--json` informa o plano sem aplicá-lo. Uma aplicação sem aprovação sai com 1 e `needs_confirmation`. Instalar o Hopper também exige `--install-hopper`. Documentado.

## 2. Execução de `rea mcp`

Comando: `rea mcp` (stdio; o cliente o inicia). `rea mcp --http [--host H] [--port N]` serve HTTP em streaming para um cliente por vez. Host e porta usam por padrão `MCP_HOST` e `MCP_PORT`, depois 127.0.0.1 e uma porta efêmera. Um bind fora do loopback relaxa as verificações e é registrado em log. Documentado (docs/cli.md, "Serve MCP over streamable HTTP"; docs/mcp-contracts.md). `rea mcp doctor [--json]` verifica a inicialização em produção.

Variáveis de ambiente citadas na documentação (lista não exaustiva):
- Log e MCP: REA_LOG_LEVEL (um valor inválido faz todos os escopos falharem), REA_MCP_INPUT_SCHEMA_PROFILE, REA_MCP_OUTPUT_SCHEMA_PROFILE (use `off` em hosts com quadros pequenos), REA_MCP_MAX_RESPONSE_BYTES, MCP_HOST, MCP_PORT, REA_ANALYSIS_PROVIDER.
- Caminhos e tempos limite dos provedores: REA_GHIDRA_STARTUP_TIMEOUT_MS, REA_HOPPER_STARTUP_TIMEOUT_MS, REA_JEB_MCP_TIMEOUT_MS, REA_JEB_MCP_URL, REA_JADX_OPERATION_TIMEOUT_MS, REA_ADB_PATH, REA_BROWSER_EXECUTABLE, REA_ELECTRON_EXECUTABLE, REA_GDB_COMMAND, REA_RIZIN_COMMAND, REA_OBJDUMP_COMMAND, REA_APKTOOL_COMMAND, REA_KUNA_COMMAND, REA_IDA_MCP_CONFIG, REA_GHIDRA_SEED_FILE, REA_GHIDRA_LANGUAGE_ID, REA_GHIDRA_COMPILER_SPEC_ID, REA_GHIDRA_DISABLED_ANALYZERS, REA_WABT_BIN_DIRECTORY, REA_WAKARU_COMMAND.
- Instalações externas: GHIDRA_INSTALL_DIR, JAVA_HOME, HOPPER_LAUNCHER_PATH.
Documentado em docs/installation.md, client-configuration.md, testing.md e adb-device-analysis.md.

Diretório de trabalho: a CLI resolve caminhos relativos a partir do cwd; clientes MCP devem passar caminhos absolutos. Documentado (docs/cli.md).

Artefatos e evidências: a Evidence da análise é mantida na sessão em execução, sob um Evidence ID. `export_evidence_bundle` grava um pacote completo, de forma atômica, em um caminho informado pelo chamador. O estado e o cache do REA ficam em `~/.rea`, removidos apenas por `rea uninstall --purge-data`. Cache de versões do Hopper: `${XDG_CACHE_HOME:-$HOME/.cache}/rea/hopper-releases/`. Local padrão das evidências em uma sessão simples: desconhecido. Documentado (docs/mcp-contracts.md; docs/installation.md).

Rede em tempo de execução: o setup baixa pacotes (o pacote oficial do Hopper; npm). Em execução, a análise de bundle busca source maps apenas quando `fetch_source_maps` é selecionado, com verificação de origem exata e sem credenciais. A observação do navegador se conecta a um Chrome que o usuário iniciou com `--remote-debugging-port` no loopback; o REA não o inicia. A lista completa de chamadas de saída em tempo de execução: desconhecida.

Alvos de download ou execução: sim, com as permissões do próprio usuário.
- `capture_process_scenario` executa um comando escolhido pelo chamador e registra evidências (docs/process-capture.md). Não é um sandbox.
- Frida: `start_frida_session` anexa ou inicia; `load_frida_script` executa JavaScript dentro do alvo, com a memória, o sistema de arquivos e a autoridade de rede dele (docs/frida-instrumentation.md).
- ADB: `install_adb_package`, `push_adb_file`, `uninstall_adb_package`, `start_adb_app`, `start_adb_activity`, `stop_adb_app` alteram o estado do dispositivo (docs/adb-device-analysis.md).
- Navegador: `capture_browser_scenario`, `observe_web_session`, `inspect_web_page` agem sobre um navegador anexado; o evaluate genérico do CDP não é exposto (docs/browser-observation.md).
- Electron: `capture_electron_scenario`.
- Ferramentas nativas executam binários locais: rizin, gdb, Cutter, objdump (`execute_rizin_command`, `gdb_console`, `cutter_command`, `inspect_with_objdump`).
- `analyze_web_bundle` faz o parsing sem executar (docs/browser-observation.md).

## 3. Isolamento e contêineres

- Não foi encontrada nenhuma imagem Docker oficial nem execução documentada em contêiner do servidor MCP no README, docs/installation.md, docs/cli.md, SECURITY.md ou DISCLAIMER.md.
- O único Dockerfile na documentação é gerado por `rea environment-export` para um pacote de ambiente de agente: base `node:24.18.0-bookworm-slim`, instala `rea-agents@<version>`, executa `environment-serve` com `MCP_HOST=0.0.0.0` e `MCP_PORT=18765` (docs/agent-environments.md). Ele serve um ambiente; não é um sandbox de análise.
- docs/installation.md diz que a separação em sala limpa exige restrições de sistema de arquivos e de rede aplicadas por "a separate account or container", porque um agente na mesma conta do sistema operacional ainda pode executar o REA e ler sua saída.
- SECURITY.md: "This is not a sandbox", e o arquivo não protege contra processos maliciosos do mesmo usuário.
- Requisitos do host, segundo a documentação: Node.js 22.19+, 24.11+ ou 26+ com npm (obrigatório). O Hopper (comercial; apenas macOS e Linux) precisa de um Python próprio para a sua ponte (`bridge/hopper_bridge.py` vem no pacote). O Ghidra é gerenciado pelo usuário e precisa de Java (`GHIDRA_INSTALL_DIR`, `JAVA_HOME`). IDA e Kuna têm guias próprios (docs/ida-provider.md, docs/kuna-provider.md; não lidos). As ferramentas ADB precisam do adb e de um dispositivo ou emulador. As ferramentas de navegador precisam de um navegador da família Chromium com porta de depuração. As ferramentas Electron precisam de um executável do Electron. O Frida precisa de bindings nativos.
- Uma receita de contêiner avaliada contra esses requisitos: desconhecida; o projeto original não fornece nenhuma.

## 4. DISCLAIMER.md e SECURITY.md

DISCLAIMER.md, em resumo: o REA serve para análise lícita (pesquisa de segurança, análise de malware, pesquisa de vulnerabilidades, CTFs, interoperabilidade, preservação e auditoria de software que você possui ou está autorizado a examinar). Ele recusa contornar DRM ou licenças, cheats de jogos, burlar controles de acesso em sistemas que você não está autorizado a testar, copiar código proprietário, driblar políticas de provedores de IA e revender acesso a IA. O usuário é responsável pela autorização, pela conformidade legal e pelo que direciona um agente a fazer. A autorização para inspecionar não cobre necessariamente execução, interceptação, mudanças em dispositivos ou interação. Os resultados podem estar incompletos ou errados. A saída não concede direitos sobre o programa original. Ferramentas comerciais (IDA, Hopper, JEB) devem ser obtidas legalmente. Garantia: AS IS, sob MIT.
Citação (menos de 15 palavras), DISCLAIMER.md: "does not by itself establish permission for every operation".

SECURITY.md, em resumo: vulnerabilidades devem ser reportadas pelo recurso de advisory privado do GitHub. Tokens de capacidade por sessão autenticam as pontes do Hopper e do Ghidra (sockets Unix, ou TCP de loopback autenticado no Windows). O arquivo afirma que não é um sandbox e que abrir um binário não confiável executa o parsing com as permissões do usuário. Os pacotes do Hopper para Linux vêm somente da origem HTTPS do Hopper, conferidos contra um valor SHA-1 publicado, que o arquivo chama de verificação de corrupção, não de assinatura.

Implicação para o wev: o rea coloca a autorização, a contenção e os direitos sobre a saída a cargo do usuário. O wev não deve descrever o rea como garantia de sala limpa nem de sandbox.

## 5. Catálogo de ferramentas para os dois usos

Os nomes de ferramentas abaixo vêm das entradas `mcp__rea__*` da lista de ferramentas adiadas desta sessão, um catálogo vivo cuja versão não foi verificada. A documentação cita ferramentas em docs/browser-observation.md, docs/adb-device-analysis.md, docs/frida-instrumentation.md, docs/mcp-prompts.md, docs/mcp-contracts.md e docs/client-configuration.md. Um documento da main informa 172 ferramentas no commit 04089d5be; a contagem exata para a 6.7.0: desconhecida. `docs/tools.md` não existe no repositório.

- Análise de aplicações web (bundle, rede, captura de tela): analyze_javascript_application, analyze_web_bundle, inspect_web_page, inspect_web_network_capture, inspect_web_event_listeners, capture_web_screenshot, compare_web_screenshots, compare_web_captures, observe_web_session, observe_web_execution, list_browser_targets, capture_browser_scenario, discover_webmcp_tools, export_web_scripts, recover_javascript_sources, compare_bundles, compare_source_to_bundle, inspect_packet_capture, inspect_pcap_capture, inspect_wasm_artifact.
- Nativo e binário estático: binary_overview, open_binary, binary_session, close_binary, list_procedures, procedure_pseudo_code, procedure_assembly, procedure_callers, procedure_callees, batch_decompile, search_strings, list_strings, xrefs, find_xrefs_to_name, get_call_graph, build_call_path, inspect_macho, inspect_pe_resources, inspect_go_binary, inspect_rust_binary, inspect_dart_aot, inspect_native_api, read_function_instructions, inspect_with_objdump, execute_rizin_command, cutter_command, gdb_console, start_gdb_session. Gerenciado e Android: inspect_android_class, inspect_android_method, decode_android_resources, inspect_apktool_client, decompile_jeb_item, inspect_managed_artifact, compare_managed_members.
- Observação em tempo de execução (Frida, navegador, Electron, ADB, UI nativa): list_frida_devices, list_frida_processes, start_frida_session, load_frida_script, unload_frida_script, resume_frida_session, close_frida_session, frida_session_status, instrument_with_frida, observe_native_calls, observe_native_ui, capture_native_ui_scenario, capture_process_scenario, observe_javascript_runtime, capture_electron_scenario, inspect_electron_page, inspect_electron_fuses, list_electron_targets, list_adb_devices, inspect_adb_package, capture_adb_screen, read_adb_logcat, collect_adb_bugreport. As ferramentas ADB que alteram o dispositivo estão listadas na seção 2.
- Exportação de evidências e pacotes: export_evidence_bundle, import_evidence_bundle, get_evidence_bundle, inspect_artifact, inspect_analysis_view, compare_artifacts, compare_process_captures, correlate_static_and_runtime, record_unknown, update_unknown, list_unknowns, verify_unknown_resolution.
- Reconstrução e verificação: build_reconstruction_obligation_ledger, evaluate_reconstruction_coverage, verify_reconstruction, verify_managed_native_boundaries, import_managed_reconstruction, compare_functions, compare_javascript_export_shapes, compare_wasm_interfaces, find_changed_behavior, reconcile_javascript_runtime, trace_feature, trace_application_feature. Descritas em docs/reconstruction-coverage.md e docs/reconstruction-obligation-ledgers.md (não lidas por completo).

## 6. Fixação de versão e manifesto do registro

- docs/installation.md (seção MCP Registry) traz a configuração manual `{"command":"npx","args":["-y","rea-agents@<version>","mcp"]}` e diz que registros persistentes devem usar uma única versão exata (6.7.0 na época). Documentado. Se `npx -y rea-agents@<version> mcp` inicia como servidor stdio em um host limpo: documentado, não verificado por nós.
- npm: `rea-agents` última 6.7.0. `bin` mapeia `rea` e `rea-agents` para `scripts/rea.mjs`. Engines: `^22.19.0 || ^24.11.0 || >=26.0.0`.
- `server.json` (raiz do repositório): nome `io.github.morluto/rea`, título REA, versão 6.7.0. Uma única entrada em `packages`: registryType npm, identifier `rea-agents`, versão 6.7.0, runtimeHint `npx`, transporte stdio, packageArguments com um argumento posicional `mcp`. Não declara `env` nem `runtimeArguments`. Schema 2025-12-11.

## Lacunas

- Caminhos dos arquivos MCP do Cursor, Windsurf, Antigravity e VS Code; caminho completo do Copilot.
- Local padrão das evidências em uma sessão simples; lista completa das chamadas de rede em tempo de execução.
- Se `npx -y rea-agents@<version> mcp` inicia em um host limpo (não executado, por decisão).
- Contagem e lista exatas de ferramentas da 6.7.0 (`npm pack` não foi usado).
- Receita de contêiner: nenhuma no projeto original.
- Não lidos por completo: docs/ida-provider.md, docs/kuna-provider.md, a documentação de reconstrução e a maior parte das seções por cliente.
