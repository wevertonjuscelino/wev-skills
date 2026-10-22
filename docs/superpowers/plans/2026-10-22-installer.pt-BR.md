# Plano de Implementação do Instalador

Versão em inglês: [2026-10-22-installer.md](2026-10-22-installer.md).

> **Para agentes de execução:** SUB-SKILL OBRIGATÓRIA: use superpowers:subagent-driven-development (recomendado) ou superpowers:executing-plans para implementar este plano tarefa por tarefa. Os passos usam a sintaxe de caixa de seleção (`- [ ]`) para acompanhamento.

**Objetivo:** um único `install.sh` que a pessoa roda como `curl -fsSL <url>/install.sh | bash` (ou `bash install.sh` a partir de um clone), que faz algumas perguntas, recebe a chave do JEV sem eco, instala o wev-skills na versão mais recente mais as skills de terceiros nas versões mais novas, registra tudo nos harnesses que a pessoa escolheu, configura o rea, mostra um resumo, e pode rodar de novo com segurança ou desinstalar.

**Arquitetura:** o script é fino. Ele verifica o sistema, faz as perguntas e depois chama a CLI `wev` para tudo que tem regras: `wev skills update` (Parte 4) instala o próprio wev-skills, o rea e as agent-skills lado a lado com verificações de saúde; `wev harness install` (Parte 3) e os comandos de plugin do Claude Code registram os harnesses; `wev rea mode|build-image` (Parte 5) configuram o rea; um novo `wev jev key set` grava o arquivo da chave; `wev config validate` verifica a configuração de nível de usuário que o script grava. Duas pequenas mudanças no motor tornam isso possível: uma **camada de configuração de nível de usuário** (`~/.config/wev-skills/wev.config.json`, lida abaixo do `wev.config.json` de um repositório e acima dos padrões) para que "JEV ligado" e o idioma persistam para a conta inteira, e o comando `jev key set`. Bootstrap: o script clona a tag da última versão em um diretório temporário e roda o `bin/wev skills update wev-skills` desse clone, que instala a versão no layout da Parte 4 e aponta `current` para ela; a partir daí o script usa `<data>/wev-skills/third-party/wev-skills/current/bin/wev` e apaga o clone temporário. O marketplace do Claude Code é adicionado a partir do diretório `current`, de modo que um `wev skills update wev-skills` posterior é aproveitado sem mexer no registro do plugin.

**Stack Técnica:** bash (POSIX quando não custa nada; o bash 3.2 do macOS é o piso, então sem arrays associativos e sem `mapfile`), `curl`, `git`, Python 3.14 (exigido pelo motor; o script só pode chamar `python3` depois de verificar a versão), a CLI `wev`. Testes: `unittest` do Python rodando `bash install.sh --yes …` com `claude`, `codex`, `gemini`, `opencode`, `docker`, `git` e `curl` falsos no `PATH` e `--source <este clone>` em vez de um download.

**Spec:** [docs/superpowers/specs/2026-10-20-setup-and-third-party-design.md](../specs/2026-10-20-setup-and-third-party-design.pt-BR.md), Parte 1, decisões 1–8, 12, 14, 16, e "Decisões que tomei sem o dono" (troca de modo no momento do uso; a configuração inicial não toca em `~/.claude/CLAUDE.md`). Interfaces: `docs/guides/installation.md` (comandos de plugin do Claude Code, lidos de `claude plugin --help`), `docs/research/harness-{codex,gemini,opencode}.md`, Parte 4 (`wev skills`), Parte 3 (`wev harness`), Parte 5 (`wev rea`).

## Restrições Globais

- O script é um único arquivo, `install.sh` na raiz do repositório, com menos de 400 linhas, `set -euo pipefail`, sem `eval`, sem divisão por palavras de entrada do usuário em comandos; toda chamada externa é um comando literal com argumentos entre aspas. Ele nunca grava fora de `$XDG_DATA_HOME/wev-skills`, `$XDG_CONFIG_HOME/wev-skills`, dos diretórios de harness que a CLI `wev` já grava e do diretório temporário que cria com `mktemp -d` e remove na saída (`trap`).
- **As perguntas são lidas de `/dev/tty`,** nunca da entrada padrão: sob `curl | bash` a entrada padrão é o próprio script. Sem tty e sem `--yes`, o script para com uma mensagem que nomeia `--yes` e as flags; nunca adivinha uma resposta.
- A chave é lida com `read -rs` de `/dev/tty` e passada ao `wev jev key set` somente pela entrada padrão. Ela nunca aparece em um argumento, em uma variável de ambiente, em uma linha de log nem no resumo. O script não a repete na tela e não imprime o tamanho dela.
- Mensagens: uma tabela em dois idiomas dentro do script (`msg <key>`), inglês e português do Brasil com conjuntos de chaves idênticos; um teste compara os dois conjuntos. O idioma é perguntado primeiro (ou `--lang`), tem como padrão o prefixo de `LANG` e é passado a toda chamada `wev` como `--lang`.
- Nada que o script baixa é executado antes de a sua versão ser fixada: a tag da versão vem da API de releases do GitHub (`curl` para `api.github.com/repos/wevertonjuscelino/wev-skills/releases/latest`, interpretada com `python3 -c` depois da verificação do Python), o clone é `git clone --depth 1 --branch <tag> https://github.com/wevertonjuscelino/wev-skills.git`, e o script usa o clone somente para rodar `bin/wev skills update wev-skills`, que baixa de novo o tarball da versão pelas verificações da Parte 4. `--source DIR` pula o download e usa `DIR/bin/wev` para tudo (rota de desenvolvimento e de teste; também a rota e2e para uma branch não publicada); o resumo então diz que a instalação é "de uma fonte local, sem atualização automática".
- Python 3.14 ou Node ausentes: o script diz qual está faltando e se oferece para rodar exatamente um comando de instalação conhecido que encontrou na máquina (`uv python install 3.14`, `brew install python`, `brew install node`, `sudo apt-get install …`, `sudo dnf install …`), mostrado por inteiro antes do sim/não. Com `--yes` ele não instala pacotes do sistema: para e nomeia o comando. Nunca canaliza um script remoto para um shell para instalar uma dependência.
- Licença: as primeiras linhas de `LICENSE` (título e URL) e a frase "uso somente não comercial" são mostradas antes de qualquer coisa ser instalada; a pessoa confirma (`--yes` conta como lido, e o resumo repete a linha da licença).
- Os passos de operador humano que o script não pode fazer pela pessoa são impressos como próximos passos, nunca automatizados: confiança nos hooks do Codex, `gemini extensions link`, `codex mcp add rea -- …`.
- Reexecução: todo passo é idempotente pelas regras da própria CLI (`skills update` não faz nada na versão mais nova, `harness install` substitui os arquivos do próprio wev, `jev key set` sobrescreve apenas a linha `TYPESAFE_API_KEY`, `rea mode` reescreve um arquivo). Uma reexecução com respostas diferentes reconfigura. O resumo diz o que mudou.
- Desinstalação (`--uninstall`): `wev harness uninstall --target …` para cada manifesto presente, `claude plugin uninstall wev-skills` e `claude plugin marketplace remove wev-skills-marketplace` quando `claude` existe, `wev skills deactivate`, e depois remove `$XDG_DATA_HOME/wev-skills`. Ele pergunta antes de remover `$XDG_CONFIG_HOME/wev-skills` (o arquivo da chave e a configuração do usuário); com `--yes` mantém esse diretório, a menos que `--purge` também seja dado. Ele imprime o que removeu e o que manteve.
- A hospedagem do script (o `<url>`) é decisão do dono. A documentação mostra `bash install.sh` a partir de um clone, e a linha do `curl` com a URL raw do GitHub da `main` marcada como "depois que o dono publicar".
- Lado Python: biblioteca padrão, mypy strict, dataclasses congeladas, funções com menos de 50 linhas, arquivos com menos de 400, chaves de i18n idênticas em `en` e `pt-BR`, documentação EN + pt-BR no mesmo commit. Assuntos de commit `<type>: <description>`. Sem push sem o ok do dono.

## Foco da Revisão

1. Segredos: a chave nunca chega ao argv, ao ambiente, a um log nem ao resumo (a gravação passa por um arquivo temporário 0600 no mesmo diretório, renomeado para o lugar); o arquivo da chave é 0600 em um diretório 0700; um `jev key set` interrompido não deixa arquivo parcial (grava em um arquivo temporário no mesmo diretório, `chmod`, depois `rename`). Testado na Tarefa 2 e na Tarefa 4.
2. Segurança do `curl | bash`: todos os prompts leem `/dev/tty`; sem tty o script recusa, a menos que haja `--yes`; `set -e` mais `trap` remove o clone temporário em todo caminho de saída; uma chamada `wev` que falha para o script mostrando o erro JSON dessa chamada, nunca um sucesso silencioso com instalação pela metade. Testado na Tarefa 4.
3. Cadeia de confiança: o script roda código somente do clone da tag fixada e de `current`; `--source` é a única forma de rodar código de outro lugar e o resumo diz isso; sem `eval`, sem `sh -c "$var"`. Testado na Tarefa 4 (verificações no nível do grep no script mais verificações de comportamento).
4. A camada de configuração de nível de usuário não pode afrouxar as regras de um repositório: o arquivo do repositório sobrepõe o do usuário, `--config` sobrepõe os dois, `trust_errors` vale para o resultado combinado, uma execução fixa o resultado combinado e `config show` nomeia as duas fontes. Testado na Tarefa 1.
5. A desinstalação remove apenas o que o wev gravou (passa pelos manifestos da CLI) e nunca o arquivo da chave sem um sim explícito ou `--purge`. Testado na Tarefa 4.

---

### Tarefa 1: Camada de configuração de nível de usuário

**Arquivos:**
- Modificar: `src/wev_skills/config.py` (`resolve_config`, `ResolvedConfig.source`), `src/wev_skills/commands/config.py` (saída de `config show`), `src/wev_skills/locales/core.*.json` se uma mensagem mudar
- Teste: `tests/unit/test_config_resolution.py` (novo ou o módulo de testes de configuração existente)

**Interfaces:**
- `user_config_path() -> Path` = `user_config_home() / "wev.config.json"`.
- `resolve_config(explicit, root)`: `explicit` → somente esse arquivo (sem mudança); senão o arquivo do usuário (se for um arquivo regular) é interpretado primeiro e o `wev.config.json` do repositório (se existir) é combinado por cima com mesclagem profunda, usando a maquinaria existente `deep_merge`/`parse_config(path, overrides)` (ler o objeto JSON do arquivo do repositório e passá-lo como `overrides` sobre o arquivo do usuário, de modo que um único caminho de código valide os dois); `source` passa a ser `"<user path> + <repo path>"`, `"<user path>"`, `"<repo path>"` ou `"defaults"`. `config show` imprime `config_source` como antes e acrescenta `config_sources: [...]` (lista, possivelmente vazia). A execução fixa o resultado combinado exatamente como hoje.
- `trust_errors` é aplicado à configuração combinada (já é o caso pelos chamadores; acrescentar um teste).
- O hook já protege `user_config_home()` (Parte 5), então um agente não consegue gravar o arquivo do usuário pelo Bash.

- [ ] **Passo 1: Testes que falham.** O arquivo do usuário sozinho define `decision.provider: jev` e `language`; o arquivo do repositório sobrepõe uma chave e mantém o resto; `--config` ignora os dois; um arquivo de usuário que seja um link simbólico ou um diretório é ignorado (não seguido); um arquivo de usuário inválido falha com o erro `config_invalid` existente nomeando o caminho do usuário; `config show` lista as duas fontes; `run start` fixa o digest combinado.
- [ ] **Passos 2–5:** rodar/falhar, implementar, rodar/passar; quebra deliberada: fazer o arquivo do usuário sobrepor o do repositório e confirmar que um teste falha; restaurar. **Commit** `feat: read a user-level wev.config.json below the repository one`

### Tarefa 2: `wev jev key set`

**Arquivos:**
- Modificar: `src/wev_skills/decisions/jev_key.py` (`write_env_key(path, key)`), `src/wev_skills/commands/jev.py` (`key set`), `src/wev_skills/adapters/claude_code/engine_cli.py` (set somente para a pessoa), locales `decisions.*.json` / `core.*.json`
- Teste: `tests/unit/test_jev_key_set.py`, testes do hook

**Interfaces:**
- `write_env_key(path: Path, key: str) -> None`: recusa uma chave vazia, com espaço em branco ou caracteres de controle, ou maior que 512 bytes (`ValidationError("jev_key_invalid")`); cria o diretório pai 0700; grava o arquivo de forma atômica (arquivo temporário no mesmo diretório, 0600, `os.replace`); mantém todas as outras linhas de um arquivo existente e substitui ou acrescenta `TYPESAFE_API_KEY=<key>`; recusa um arquivo ou diretório que seja link simbólico (`ValidationError("env_file_refused")`).
- `wev jev key set` lê a chave da entrada padrão (uma linha, removendo apenas a quebra de linha final), chama `write_env_key(env_file_path(), key)`, depois roda a lógica de status existente e imprime `{"written": "<path>", "key_source": "env_file", "usable": true|false}` — nunca a chave. Com um tty na entrada padrão e sem dados, diz para canalizar a chave.
- Hook: `("jev", "key")` entra no conjunto somente-pessoa (pergunta no Claude Code, nega nos demais) com o motivo `engine_jev` ou um novo; os textos das skills não o mencionam (a pessoa o roda pelo instalador ou por um terminal).

- [ ] **Passo 1: Testes que falham.** Ida e volta, outras linhas preservadas, modo 0600 e pai 0700, link simbólico recusado, chaves inválidas recusadas, atomicidade (simular `os.replace` lançando erro: nenhum arquivo parcial, arquivo antigo intacto), o payload da CLI não tem material da chave (verificar que a string da chave está ausente de stdout e stderr), hook pergunta/nega.
- [ ] **Passos 2–5** como antes; quebra deliberada: pular o `chmod` e confirmar que o teste de modo falha. **Commit** `feat: add wev jev key set for the installer`

### Tarefa 3: `install.sh`

**Arquivos:**
- Criar: `install.sh` (bit de execução definido, `#!/usr/bin/env bash`)

**Comportamento, em ordem (cada passo imprime uma linha do que faz e do resultado):**
1. Interpretar as flags: `--yes`, `--lang en|pt-BR`, `--harness claude,codex,gemini,opencode` (padrão: os detectados), `--jev` / `--no-jev` (padrão: perguntar), `--rea-mode isolated|direct` (padrão: isolated quando `docker` é encontrado), `--source DIR`, `--uninstall`, `--purge`, `--help`. Flag desconhecida → uso, saída 2.
2. Idioma (perguntar ou `--lang`), depois o bloco da licença e a confirmação.
3. Sistema: `uname` é Darwin ou Linux (senão parar); `git` e `curl` presentes (senão parar com a dica de instalação); Python ≥ 3.14 encontrado como `python3.14`, `python3` ou `python` (comparar com `python3 -c 'import sys; print(sys.version_info >= (3, 14))'`); Node/npm presentes (necessários ao modo direto do rea e à verificação de saúde; se ausentes e a pessoa quiser o rea, oferecer o comando de instalação, ou pular o rea com uma nota). A presença do Docker é detectada, não exigida.
4. Detecção de harness (`command -v` para `claude`, `codex`, `gemini`, `opencode`), perguntar em quais instalar (`--yes`: os detectados, ou `--harness`).
5. Bootstrap do wev (a menos que `--source`): última tag da API de releases, clone raso no diretório temporário, `bin/wev --lang L skills update wev-skills`, depois `WEV=<data>/wev-skills/third-party/wev-skills/current/bin/wev`; `"$WEV" version` deve imprimir a versão da tag.
6. JEV: perguntar (ou flags). Sim → `read -rs` de `/dev/tty`, canalizar para `"$WEV" jev key set`, depois uma sonda real `"$WEV" jev ask --questions <arquivo temporário com uma pergunta noul> --state "installer probe"`; em caso de falha, mostrar o erro, oferecer uma nova tentativa e, se falhar de novo, continuar com o JEV desligado. Em caso de sucesso, gravar a configuração do usuário `{"decision": {"provider": "jev"}, "language": "<lang>"}` em `$XDG_CONFIG_HOME/wev-skills/wev.config.json` (0600) e rodar `"$WEV" config validate` nela. Não → gravar somente `{"language": "<lang>"}` (para que uma configuração `jev` anterior seja desligada em uma reexecução).
7. rea: `"$WEV" rea mode <mode>`; isolated → perguntar se constrói a imagem agora (`"$WEV" rea build-image`, que pode levar minutos), `--yes` constrói.
8. Terceiros: `"$WEV" skills update rea`, `"$WEV" skills update agent-skills`, `"$WEV" skills activate`. Uma verificação de saúde que falha é relatada e o passo continua (a Parte 4 deixa a versão anterior ativa).
9. Harnesses: `claude` → `claude plugin marketplace add "<current dir>"` e depois `claude plugin install wev-skills@wev-skills-marketplace` (com `--source`, o marketplace é o diretório da fonte); `codex|gemini|opencode` → `"$WEV" harness install --target X` e imprimir o `next_steps` dele; para o codex, imprimir também a linha `codex mcp add rea -- <python> <wev> rea serve`.
10. Verificar e resumir: `"$WEV" version`, `"$WEV" jev status` (`orchestration`), `"$WEV" rea status` (modo), `"$WEV" skills list` (versões ativas), os resultados dos harnesses; uma tabela de instalado / ignorado (com o motivo) / próximos passos que a pessoa faz; a linha da licença de novo.
- `--uninstall`: como nas restrições.

- [ ] **Passo 1:** escrever o script. **Passo 2:** `bash -n install.sh`; `shellcheck` se disponível (não é dependência; dizer se rodou). **Commit** junto com a Tarefa 4.

### Tarefa 4: Testes do `install.sh`

**Arquivos:**
- Criar: `tests/unit/test_install_sh.py`, `tests/fixtures/fake_bin/` (pequenos scripts de shell `claude`, `codex`, `gemini`, `opencode`, `docker`, `git`, `curl` que acrescentam o argv a `$FAKE_LOG` e imprimem o JSON/texto mínimo que o script lê)
- Cada teste roda `bash install.sh --yes --source <repo root> …` com `PATH=<fake_bin>:<um diretório com bash, python3 e coreutils reais>`, `HOME` e `XDG_*` em um diretório temporário, e `WEV_SKILLS_NO_NETWORK=1` respeitado pelo cliente de registro da Parte 4 somente se tal chave existir; caso contrário os testes passam `--source` e pré-carregam o estado de terceiros para que `skills update` não faça nada (ou trocam a URL do registro pelo gancho de teste existente em `tests/fixtures/fake_registry_server.py`, rodado no mesmo processo).

- [ ] **Testes (cada um nomeado pelo comportamento):** sem tty e sem `--yes` → saída 2 e a mensagem nomeando `--yes`; `--help` imprime todas as flags; os conjuntos de chaves de mensagem EN/pt-BR são idênticos (interpretar a tabela); o script não tem `eval` nem `$` sem aspas em posição de comando (nível do grep); o texto da licença é impresso antes da primeira chamada de instalação (ordem em `FAKE_LOG` versus stdout); a chave pela entrada padrão cai no arquivo da chave 0600, diretório 0700, ausente de stdout/stderr/`FAKE_LOG`; falha da sonda do JEV → a configuração do usuário não tem `jev` e o resumo diz isso; `--no-jev` em uma máquina em que a configuração do usuário tinha `jev` → desligado; `--rea-mode direct` grava rea.json; apenas os harnesses detectados → o log do `claude` falso mostra `marketplace add` + `install`, codex/gemini/opencode passam por `harness install` (verificar nos manifestos que a Parte 3 grava); reexecução com as mesmas flags → sem registros duplicados (os logs falsos mostram um segundo `install`, manifestos inalterados); `--uninstall --yes` deixa o diretório de dados removido e o diretório de configuração presente; `--uninstall --yes --purge` remove ambos; uma chamada `wev` que falha (`docker` falso com saída 1 durante o build-image) → saída diferente de zero, diretório temporário removido, o erro JSON na saída.
- [ ] Quebra deliberada: remover o redirecionamento `/dev/tty` de um `read`; confirmar que o teste sem tty falha. **Commit** `feat: add the interactive installer and its tests`

### Tarefa 5: Documentação

**Arquivos:** `docs/guides/installation.md` + pt-BR (nova primeira seção "Quick install" com as duas linhas e a tabela de flags; uma subseção de reexecução e desinstalação; mover a rota do clone para baixo dela); `README.md` + pt-BR (linha de instalação no topo; o aviso do README feito por `claude plugin validate` quer também a linha de instalação pelo marketplace); `SECURITY.md` + pt-BR (seção "Installer": o que ele lê do tty, onde grava, o que nunca faz, a nota de confiança de `--source`, os passos de operador que deixa para a pessoa); `CHANGELOG.md`; `docs/mvp-status.md` + pt-BR.

Rótulos: "implementado e testado com CLIs de harness falsas e uma fonte local (testes unitários)"; "a rota de download, um `claude plugin install` real, Codex/Gemini/OpenCode reais e uma sonda real do JEV não são executados nesta mudança (parte e2e)"; a linha do `curl` "depois que o dono publicar".

- [ ] **Editar; rodar** `make check`, `bin/wev readme check`, `bin/wev claude-md check`, `claude plugin validate .` (o aviso do README deve sumir). **Commit** `docs: document the installer`
