# Plano de implementação dos adaptadores de harness

Versão em inglês: [2026-10-21-harness-adapters.md](2026-10-21-harness-adapters.md).

> **Para quem executa como agente:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendada) ou superpowers:executing-plans para implementar este plano tarefa a tarefa. Os passos usam a sintaxe de caixa de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** Instalar as skills, os subagentes e os hooks de guarda do wev no Codex, no Gemini CLI e no OpenCode, como o Claude Code já recebe, por meio de `wev harness export|install|uninstall --target codex|gemini|opencode`.

**Arquitetura:** A lógica de guarda fica onde está. Um codec fino por harness converte a entrada de hook daquele harness no payload que `adapters/claude_code/hooks.py` já lê, e depois converte a resposta do Claude Code de volta para o formato de saída do harness. Um construtor de pacote por alvo renderiza as skills do repositório (trocando `"${CLAUDE_PLUGIN_ROOT}/bin/wev"` pelo caminho absoluto do `bin/wev` deste clone) e os agentes em um diretório. O `install` constrói esse pacote no diretório de dados do usuário e o registra no harness, pela própria CLI do harness quando ela existe, e grava cada caminho escrito em um manifesto, para que o `uninstall` remova somente esses.

**Stack técnica:** biblioteca padrão do Python 3.14, `unittest`; CLIs de harness falsas em `tests/fixtures/` para os testes de instalação. O Node é usado apenas por um teste do plugin do OpenCode, que é pulado quando `node` está ausente.

**Especificação:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.pt-BR.md](../specs/2026-10-20-setup-and-third-party-design.pt-BR.md), Parte 3, a seção "Calls I made without the owner" (decisões 4, 8, 9) e a decisão 14. Os fatos de interface vêm das notas de trabalho [docs/research/harness-codex.pt-BR.md](../../research/harness-codex.pt-BR.md), [harness-gemini.pt-BR.md](../../research/harness-gemini.pt-BR.md) e [harness-opencode.pt-BR.md](../../research/harness-opencode.pt-BR.md). Todo detalhe de formato que quem implementa usar deve vir dessas notas, com a fonte que elas citam. Um detalhe que as notas marcam como "unknown" não é adivinhado: a tarefa reporta NEEDS_CONTEXT.

## Restrições globais

- Somente biblioteca padrão, Python >= 3.14, mypy strict, dataclasses congeladas, funções com menos de 50 linhas, arquivos com menos de 400 linhas.
- Toda string voltada ao usuário passa por i18n, com chaves idênticas em `en` e `pt-BR`. A documentação muda em EN e pt-BR no mesmo commit.
- Os testes unitários não fazem chamadas de rede e nunca executam um harness real. As execuções reais de harness pertencem à parte e2e (especificação, "End-to-end tests").
- Decisão do dono (2026-10-21), para os harnesses cujos hooks não conseguem perguntar (Codex, Gemini; e o OpenCode, a menos que suas notas mostrem um ask verificado): um `ask` da guarda vira **allow mais um aviso** ao agente, e um `deny` da guarda continua deny. O SECURITY.md (EN e pt-BR) deve afirmar que, nesses harnesses, os asks da guarda são apenas lembretes.
- Rótulos de capacidade: "implemented and tested with fake harness CLIs" até que a parte e2e execute os reais. Nunca escreva "compatible with X" na documentação antes disso.
- Os comandos de hook gravados na configuração de um harness chamam o `bin/wev` deste clone por caminho absoluto, nunca um `wev` solto.
- O manifesto dos caminhos escritos fica em `$XDG_DATA_HOME/wev-skills/harness/<target>/manifest.json`, ou então em `~/.local/share/...`. O `uninstall` remove somente as entradas do manifesto e nunca edita um arquivo que não criou, exceto para remover as entradas exatas que ele adicionou.
- Assuntos de commit `<type>: <description>`, no máximo 72 caracteres, sem atribuição a IA. Nenhum push sem o ok do dono.

## Foco da revisão

1. Um payload de hook de harness com formato inesperado (`tool_input` ausente, ferramenta que não é de shell, stdin que não é JSON) deve produzir a resposta "sem opinião" do harness ou o caminho de erro interno, nunca uma falha e nunca um stack trace. Testado na Tarefa 1.
2. Um `deny` da guarda deve chegar a cada harness como o deny daquele harness, exatamente como documentado (saída/JSON do Codex, `{"decision":"deny"}` do Gemini, erro lançado do OpenCode). Testado nas Tarefas 1 e 5.
3. Um caminho de clone com espaços ou aspas ainda deve produzir uma linha de comando de hook funcional em toda configuração gerada (quoting). Testado na Tarefa 2.
4. O `install` executado duas vezes não deve duplicar entradas; o `uninstall` depois que o usuário editou a configuração do harness deve preservar as entradas do próprio usuário. Testado nas Tarefas 3 a 5.
5. Uma CLI de harness que falha durante o install (saída diferente de zero) deve interromper com um erro claro e desfazer os arquivos escritos até então. Testado na Tarefa 3.

---

### Tarefa 1: Codecs de hook para Codex, Gemini e OpenCode

**Arquivos:**
- Criar: `src/wev_skills/adapters/harness_hooks.py`
- Modificar: `src/wev_skills/commands/hook.py` (adicionar `--harness {claude,codex,gemini,opencode}`, padrão `claude`)
- Modificar: `src/wev_skills/locales/hooks.en.json`, `hooks.pt-BR.json`
- Teste: `tests/unit/test_harness_hooks.py`, fixtures `tests/fixtures/harness_payloads/{codex,gemini,opencode}_*.json`

**Interfaces:**
- Produz:
  - `HARNESSES = ("claude", "codex", "gemini", "opencode")`
  - `def to_claude_payload(harness: str, payload: Mapping[str, Any]) -> dict[str, Any] | None`, que devolve o `{"tool_name": "Bash", "tool_input": {"command": ...}, "cwd": ...}` no formato do Claude para a ferramenta de shell daquele harness. Nomes da ferramenta de shell: Codex, da sua nota (a nota marca o nome como "unknown"; reporte NEEDS_CONTEXT se ele continuar desconhecido depois de ler o código-fonte), Gemini `run_shell_command`, OpenCode `bash`. Para qualquer outra ferramenta devolve `None`, que significa sem opinião.
  - `def from_claude_answer(harness: str, answer: str) -> HookOutput`, em que `@dataclass(frozen=True) class HookOutput: stdout: str; stderr: str; exit_code: int`. Mapeamento:
    - `deny` do Claude → o formato de deny daquele harness, exatamente como sua nota documenta;
    - `ask` do Claude → allow mais um aviso (decisão do dono): o aviso vai no campo de contexto ou de mensagem do sistema documentado do harness, se a nota mostrar um, senão no stderr com saída 0;
    - `""` → stdout vazio, saída 0.
- `wev hook pre-tool-use --harness X` lê o stdin, aplica `to_claude_payload`, chama o `hooks.pre_tool_use` existente e imprime `from_claude_answer`. Os erros seguem o contrato existente de `run_hook`, com o fallback de ask mapeado pela mesma regra.
- `wev hook session-context --harness X` imprime o mesmo texto de resumo no formato de contexto de SessionStart do harness, conforme sua nota. Para o OpenCode, o plugin consome o texto simples (Tarefa 5).

- [ ] **Passo 1: Escrever as fixtures** a partir dos exemplos de payload de cada nota de pesquisa (uma chamada de shell e uma chamada que não é de shell por harness), com a seção da nota citada em uma linha de comentário do teste.
- [ ] **Passo 2: Escrever os testes que falham:**
  - `test_shell_payload_maps_to_claude_shape` (um por harness);
  - `test_non_shell_tool_is_no_opinion`;
  - `test_deny_maps_to_harness_deny` (cada harness, saída exata);
  - `test_ask_becomes_allow_with_warning` (cada harness: saída 0, nenhum deny, texto do aviso presente no canal documentado);
  - `test_malformed_stdin_never_crashes`;
  - `test_claude_default_unchanged`: sem a flag, a saída é idêntica byte a byte à de hoje.
- [ ] **Passo 3: Executar** `PYTHONPATH=src python3 -m unittest tests.unit.test_harness_hooks -v`. Esperado: FAIL, módulo ausente.
- [ ] **Passo 4: Implementar** o módulo e a flag. Adicionar a chave i18n `hooks.reason.ask_as_warning` (en e pt-BR: "wev would ask before this command; this harness cannot ask, so it was allowed: {reason}").
- [ ] **Passo 5: Executar** os testes do módulo e os testes de hook existentes (`tests.unit.test_hooks`, `test_hook_bypasses`). Esperado: OK. Quebrar de propósito o mapeamento de deny de um harness e confirmar que um teste falha.
- [ ] **Passo 6: Commit** `feat: translate guard hooks for codex, gemini and opencode`

### Tarefa 2: Construtor de pacote e `wev harness export`

**Arquivos:**
- Criar: `src/wev_skills/adapters/harness_package.py`, `src/wev_skills/commands/harness.py`, `src/wev_skills/locales/harness.en.json`, `harness.pt-BR.json`
- Teste: `tests/unit/test_harness_package.py`

**Interfaces:**
- Consome: os `skills/*/` do repositório (cada `SKILL.md` e seus `references/`), `agent-specs/` pelo exportador existente (`adapters/claude_code/subagent.py`) para o texto dos agentes, e `bin/wev`.
- Produz:
  - `def render_skill_text(text: str, wev_path: Path) -> str`, que troca cada `"${CLAUDE_PLUGIN_ROOT}/bin/wev"` (e a forma sem aspas) por `wev_path` absoluto com quoting de shell (`shlex.quote`).
  - `def build_package(target: str, out: Path, wev_path: Path) -> list[Path]`. Escreve o layout do alvo e devolve todos os arquivos escritos. Os layouts seguem as notas:
    - **codex:** `.codex-plugin/plugin.json` (campos da nota: name, version a partir de `pyproject.toml`, `skills`, `hooks`), `skills/<name>/SKILL.md`, `hooks.json` com SessionStart e PreToolUse → `<wev> hook … --harness codex`.
    - **gemini:** `gemini-extension.json` (name, version, description, `contextFileName` somente se um arquivo de contexto for distribuído), `skills/<name>/SKILL.md`, `agents/<id>.md` (frontmatter name, description, tools, model como a nota mostra), `hooks/hooks.json` com SessionStart e BeforeTool (matcher `run_shell_command`).
    - **opencode:** `skills/<name>/SKILL.md`, `agents/<id>.md` (frontmatter `description`, `mode: subagent`), `plugins/wev-guard.js` (a Tarefa 5 escreve o conteúdo; a Tarefa 2 escreve um arquivo a partir de uma string de modelo definida no módulo da Tarefa 5, então a Tarefa 2 apenas reserva o caminho).
  - Papéis de subagente do Codex: somente quando o formato `[agents.<role>]` da nota for totalmente conhecido. Caso contrário, pule-os e registre "subagents not exported for codex: format unknown" no resultado da exportação.
- CLI: `wev harness export --target T --out DIR [--wev PATH]` imprime `{"target", "out", "files": [...], "skipped": [...]}`. `--wev` tem como padrão o `bin/wev` deste clone resolvido.
- [ ] **Passo 1: Testes que falham:**
  - `test_render_replaces_every_placeholder` (as 7 skills; nenhum `CLAUDE_PLUGIN_ROOT` restante);
  - `test_render_quotes_a_path_with_spaces` (Foco da revisão 3);
  - `test_codex_layout`, `test_gemini_layout`, `test_opencode_layout`: conjuntos exatos de arquivos, e todo JSON é válido;
  - `test_hook_commands_use_absolute_wev`;
  - `test_export_is_deterministic`: duas execuções produzem árvores idênticas byte a byte.
- [ ] **Passo 2: Executá-los e vê-los falhar.** **Passo 3: Implementar.** **Passo 4: Executá-los e vê-los passar,** depois quebrar a substituição do placeholder e confirmar que um teste falha.
- [ ] **Passo 5: Commit** `feat: build harness packages from the skills and agents`

### Tarefa 3: Install e uninstall para o Codex, com um manifesto

**Arquivos:**
- Criar: `src/wev_skills/adapters/harness_install.py`
- Modificar: `src/wev_skills/commands/harness.py`
- Teste: `tests/unit/test_harness_install.py`, CLI falsa `tests/fixtures/fake_codex.py`

**Interfaces:**
- Consome: `build_package` (Tarefa 2).
- Produz:
  - `@dataclass(frozen=True) class Manifest: target: str; files: tuple[str, ...]; registrations: tuple[tuple[str, ...], ...]`, em que `registrations` são os argv da CLI do harness usados para registrar e seus inversos, guardados para que o uninstall possa desfazê-los;
  - `def install(target: str, runner: Runner, data_home: Path, wev_path: Path) -> Manifest`;
  - `def uninstall(target: str, runner: Runner, data_home: Path) -> Manifest`.
- Install do Codex:
  - construir em `data_home/wev-skills/harness/codex/package`;
  - registrar com os comandos da nota do Codex (`codex plugin marketplace add <dir>`, depois `codex plugin add <name>@<marketplace>`), executados pelo `Runner` injetado, nunca por um shell;
  - gravar o manifesto.
- Confiança nos hooks do Codex: os hooks só executam depois que a pessoa confia neles (nota §3). O install NÃO contorna a confiança. Ele imprime, no `next_steps` do resultado, a ação exata que a pessoa executa (da nota) e para aí.
- Idempotente: reinstalar substitui o pacote e não adiciona um segundo registro (Foco da revisão 4).
- Uma saída diferente de zero da CLI do harness lança um WevError (saída 8). Os arquivos já escritos são removidos e os registros anteriores desfeitos (Foco da revisão 5).
- CLI: `wev harness install --target codex`, `wev harness uninstall --target codex`. Eles são adicionados ao RUN_COMMANDS (ask) do hook em `engine_cli.py`, já que mudam a configuração de harness do usuário, com testes de hook.
- [ ] Passos:
  - testes que falham com a CLI falsa: ela registra o argv e pode falhar sob demanda;
  - cobrir install, reinstall, uninstall, rollback em caso de falha, o conteúdo do manifesto e o hook pedindo confirmação para install/uninstall;
  - implementar, verificar, quebra deliberada;
  - commit `feat: install the wev package into codex`.

### Tarefa 4: Install e uninstall para o Gemini

**Arquivos:** Modificar `harness_install.py` e `commands/harness.py`. Teste `tests/unit/test_harness_install.py` (casos do Gemini), CLI falsa `tests/fixtures/fake_gemini.py`.

**Interfaces:** As mesmas funções da Tarefa 3. O registro do Gemini é `gemini extensions link <package>` e o inverso é `gemini extensions uninstall <name>`, ambos da nota. Antes de fazer o link, execute `gemini extensions validate <package>`; uma validação que falha interrompe antes de qualquer registro.

- [ ] Passos:
  - testes que falham: ordem validate-depois-link, uma falha de validação não gera registro, reinstall idempotente, uninstall;
  - implementar, verificar, quebra deliberada;
  - commit `feat: install the wev package into gemini cli`.

### Tarefa 5: Plugin do OpenCode e install

**Arquivos:**
- Criar: `src/wev_skills/adapters/opencode_plugin.py` (a string de modelo em JS e seu renderizador)
- Modificar: `harness_install.py` e `commands/harness.py`
- Teste: `tests/unit/test_opencode_plugin.py`, `tests/unit/test_harness_install.py` (casos do OpenCode)

**Interfaces:**
- `def render_plugin(wev_path: Path) -> str` devolve um módulo ES.
  - Exporta uma função de plugin, no formato da nota do OpenCode §4. Seu handler `tool.execute.before`, quando `input.tool === "bash"`, inicia `[wev_path, "hook", "pre-tool-use", "--harness", "opencode"]` sem shell, escreve `{"tool": input.tool, "args": output.args, "cwd": directory}` como JSON no stdin e lê o JSON do stdout.
  - Em caso de deny, lança `new Error(reason)`. Em allow com aviso, retorna e registra o aviso pelo log do cliente documentado, se a nota mostrar um, senão por `console.warn`.
  - Qualquer falha ao iniciar o processo ou ao interpretar a saída lança um erro (fail closed), conforme a regra de segurança da guarda.
  - O codec para `opencode` (Tarefa 1) lê exatamente esse formato de JSON.
- O OpenCode não tem CLI de harness para registrar plugins ou skills. O install escreve em `~/.config/opencode/` (ou `$XDG_CONFIG_HOME/opencode/`):
  - `plugins/wev-guard.js`;
  - `skills/<name>/` (diretórios com o prefixo `wev-` para evitar conflitos);
  - `agents/wev-<id>.md`.
  Todo caminho vai no manifesto. O install se recusa a sobrescrever um arquivo que não criou (WevError saída 5, nomeando o arquivo).
- [ ] Passos:
  - testes que falham:
    - `test_plugin_spawns_absolute_wev_without_shell` (verificações de string no módulo renderizado);
    - `test_plugin_denies_on_guard_deny`: executa sob `node` com um script `wev` falso que imprime um JSON de deny, e verifica o erro lançado. Pulado quando `node` não está no PATH;
    - `test_plugin_fails_closed_when_wev_missing` (node, pulado da mesma forma);
    - os testes de install, reinstall, uninstall e recusa de sobrescrita;
  - implementar, verificar, quebra deliberada;
  - commit `feat: install the wev guard plugin and skills into opencode`.

### Tarefa 6: Documentação e declarações de segurança

**Arquivos:**
- Modificar: `SECURITY.md` e `.pt-BR.md` (nova seção "Other harnesses")
- Modificar: `docs/guides/installation.md` e `.pt-BR.md` (uma seção "Codex, Gemini CLI and OpenCode")
- Modificar: `README.md` e `README.pt-BR.md` (uma linha em cada, se o README lista harnesses)
- Modificar: `CHANGELOG.md` [Unreleased]
- Modificar: `docs/mvp-status.md` e `.pt-BR.md`

- [ ] **Passo 1: Escrever a documentação.**
  - Os comandos `wev harness export|install|uninstall`.
  - O que cada harness recebe: skills, agentes (Codex somente se exportados), hooks.
  - A decisão do dono: os asks viram allow mais um aviso no Codex, no Gemini e no OpenCode, então os asks da guarda são apenas lembretes ali, e os denies continuam denies.
  - O Codex precisa de uma confiança única nos hooks, dada pela pessoa.
  - A guarda do OpenCode roda em um plugin que chama o `wev`, e falha de forma fechada se o `wev` não puder ser executado.
  - Rótulos: "implemented and tested with fake harness CLIs"; "not run against the real harnesses yet (e2e part)".
  - Nenhuma afirmação "compatible with".
- [ ] **Passo 2: Executar** `make check`, `bin/wev readme check` e `bin/wev claude-md check`. Esperado: todos passam.
- [ ] **Passo 3: Commit** `docs: document harness adapters and their guard limits`
