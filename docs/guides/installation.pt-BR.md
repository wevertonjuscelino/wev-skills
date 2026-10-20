# Guia de instalação

Versão em inglês: [installation.md](installation.md).

O wev-skills foi publicado pela primeira vez em 2026-10-13 (v1.0.0, anunciada então como 0.1.0 e renumerada em 2026-10-15) em <https://github.com/wevertonjuscelino/wev-skills>. Não há pacote no PyPI nem entrada em um marketplace oficial. Cada rota abaixo parte de um clone desse repositório ou do repositório como origem de marketplace do Claude Code. Nenhuma das rotas foi executada: o clone, a rota pelo marketplace publicado e os comandos de instalação estão apenas documentados, e o plugin nunca foi carregado em uma sessão real do Claude Code.

Os rótulos de status seguem a convenção do projeto: implementado e testado (implemented and tested), implementado mas não testado (implemented but untested), simulado com mocks (simulated with mocks), apenas documentado (documented only) e bloqueado (blocked). Veja o [glossário](../glossary.md).

## Requisitos

| Requisito | Para quê | Observações |
|---|---|---|
| Python 3.14 ou mais novo | O motor e seus testes | Só biblioteca padrão; não há nada para instalar com `pip`. Interpretadores mais antigos, inclusive o `/usr/bin/python3` original do macOS (3.9), não são suportados. A suíte rodou pela última vez no Python 3.14.7 (ver [mvp-status.pt-BR.md](../mvp-status.pt-BR.md)) |
| macOS ou Linux | O armazenamento de estado | Usa travas de arquivo POSIX. Windows não é suportado |
| `git` | `wev run start`, `wev run resume`, `wev state drift` | O motor tira um instantâneo do estado do repositório. Fora de um repositório git as execuções ainda funcionam, com menos coisa a comparar |
| Claude Code | O plugin: skills, subagentes, hooks | Só para os passos do plugin. A CLI funciona sem ele. Testado com o Claude Code 2.1.296 apenas no `claude plugin validate`; nada mais foi executado pelo Claude Code |
| `ssh` e `tmux` no host | O módulo remoto opcional | Ver o [guia de operações remotas](remote-ops.pt-BR.md) |
| `ruff`, `mypy` (ou `uvx`) | Só o `make lint` | Opcional; ver [Rodando os testes e o lint](#rodando-os-testes-e-o-lint) |

## Instalar a partir de um clone local

Clone o repositório (status: apenas documentado; o comando não foi executado). Nos exemplos, `$WEV_HOME` é o clone.

```sh
git clone https://github.com/wevertonjuscelino/wev-skills.git
export WEV_HOME="$PWD/wev-skills"
"$WEV_HOME/bin/wev" version
```

Saída real (o launcher foi executado para este guia):

```text
{
  "version": "5.0.0"
}
```

`bin/wev` é um launcher que acrescenta `src/` ao caminho de importação e executa a CLI, então não precisa de instalação. Três formas equivalentes de chamá-lo:

1. Pelo caminho: `"$WEV_HOME/bin/wev" ...`.
2. Por um link simbólico no seu `PATH`. O launcher resolve o próprio caminho real, então o link funciona (executado para este guia com um link num diretório temporário):

   ```sh
   mkdir -p ~/.local/bin
   ln -s "$WEV_HOME/bin/wev" ~/.local/bin/wev
   wev version
   ```

3. Como módulo, a partir da raiz do repositório: `PYTHONPATH=src python3 -m wev_skills ...`. O `Makefile` e o README de avaliação usam essa forma.

O `pyproject.toml` declara um script de console `wev` para o `pip install`. Instalar o pacote com `pip` não foi executado para este guia, então considere-o implementado mas não testado. Se instalar, saiba que o harness de avaliação e os exemplos procuram `evals/` ao lado da árvore de código e falham com `evals_dir_not_found` sem ele (passe `--tasks-dir` e `--configs`).

O estado é gravado em `.wev/` na raiz do repositório git em que você roda (o diretório mais próximo, acima do atual, com uma entrada `.git`; o diretório atual se não houver), e não no diretório em que você por acaso está. `.wev/` tem o próprio `.gitignore`, que ignora tudo o que há nele, então nada precisa ser acrescentado ao do projeto. Uma execução também acrescenta uma entrada a um registro por usuário, `$XDG_STATE_HOME/wev-skills/active-runs.json` (senão sob `~/.local/state`), que o hook usa para achar uma execução a partir de um caminho citado em um comando. A configuração é lida de `--config`, senão de `<raiz do repositório>/wev.config.json`, senão dos padrões, e é fixada na execução quando ela começa (veja o [guia de configuração](configuration-and-providers.pt-BR.md)).

## Carregar o plugin em uma sessão

```sh
claude --plugin-dir "$WEV_HOME"
```

`--plugin-dir` carrega um plugin de um diretório só para aquela sessão. O plugin é composto por:

| Parte | Onde | Status |
|---|---|---|
| Manifesto | `.claude-plugin/plugin.json` | `claude plugin validate` passa, com um aviso (abaixo) |
| Sete skills | `skills/wev-orchestrate`, `wev-agent-builder`, `wev-harness-evaluation`, `wev-remote-ops`, `wev-claude-md`, `wev-readme`, `wev-skill-maintenance` | Formato checado por testes unitários e pelo `claude plugin validate`; nunca exercitadas numa sessão real do Claude Code |
| Dez subagentes | `agents/*.md`, gerados a partir de `agent-specs/` | A geração está implementada e testada; nunca exercitados numa sessão real |
| Três hooks | `hooks/hooks.json` | Implementados e testados com testes unitários e de subprocesso; nunca exercitados numa sessão real |

O modelo pode escolher `wev-skill-maintenance` pela descrição para atualizar skills e
padronizar múltiplos repositórios, ou o usuário pode invocar
`/wev-skills:wev-skill-maintenance`. O frontmatter habilita explicitamente a invocação pelo
modelo. O plugin expõe a skill por `skills/wev-skill-maintenance/SKILL.md`; o comando
`select-tools` do engine reduz ferramentas de operação e não seleciona skills. O guia
externo `skill-repo` continua sendo uma dependência instalada separadamente e conferida
contra o commit fixado. A seleção depende da relevância da tarefa e das configurações do ambiente; não é garantida.
A seleção carrega orientações; não autoriza manutenção ou publicação.
Veja a [referência de invocação do ambiente](https://code.claude.com/docs/en/skills#control-who-invokes-a-skill).

Os hooks chamam `"${CLAUDE_PLUGIN_ROOT}/bin/wev"`, que começa com `#!/usr/bin/env python3`, então o `python3` precisa estar no `PATH` que o Claude Code enxerga e precisa ser o Python 3.14 ou mais novo. O `/usr/bin/python3` original do macOS é o 3.9 e, como qualquer interpretador mais antigo, não é suportado: com um `python3` mais antigo primeiro no `PATH`, os hooks saem quietos (uma linha em stderr) e não verificam nada. Confira com `python3 --version` e, com `command -v python3`, veja qual deles é usado.

Não se observou se uma skill, um subagente ou um hook se comporta como estes documentos descrevem depois que o Claude Code os carrega. A primeira sessão real é o primeiro teste; veja "Depois de publicar" em [mvp-status.pt-BR.md](../mvp-status.pt-BR.md).

## Adicionar o marketplace e instalar

Estas rotas instalam o plugin para que fique disponível em todas as sessões, e não em uma só.

Rota publicada, pelo GitHub (status: apenas documentado; não executada, porque altera a configuração do Claude Code da máquina):

```sh
claude plugin marketplace add wevertonjuscelino/wev-skills
claude plugin install wev-skills@wev-skills-marketplace
```

Os mesmos dois passos dentro de uma sessão do Claude Code são `/plugin marketplace add wevertonjuscelino/wev-skills` e `/plugin install wev-skills@wev-skills-marketplace` (apenas documentado).

Rota local, a partir do seu clone:

```sh
claude plugin marketplace add "$WEV_HOME"
claude plugin install wev-skills@wev-skills-marketplace
```

Os nomes vêm de `.claude-plugin/marketplace.json` (marketplace `wev-skills-marketplace`, plugin `wev-skills`, origem `./`). Status (as duas rotas): apenas documentado. Os comandos e suas opções foram lidos em `claude plugin --help`, `claude plugin marketplace add --help` e `claude plugin install --help`; não foram executados, porque alteram a configuração do Claude Code da máquina em que rodam.

Ambos aceitam `--scope user|project|local` (o padrão é user). O nome do marketplace e o do plugin são os mesmos nas duas rotas. Os manifestos usam a origem relativa `./` para o plugin, então um marketplace adicionado pelo repositório do GitHub instala o plugin desse mesmo repositório.

## Atualizar

| Como você instalou | Atualização |
|---|---|
| `--plugin-dir` | Altere os arquivos do diretório (ou `git pull` no seu clone) e inicie uma nova sessão |
| Marketplace | Atualize o marketplace e depois o plugin; o Claude Code pede um reinício para aplicar |

```sh
claude plugin marketplace update wev-skills-marketplace
claude plugin update wev-skills@wev-skills-marketplace
```

Status: apenas documentado (a partir de `claude plugin update --help`; não executado). Os registros de execução em `.wev/` não são tocados por uma atualização. Retomar uma execução com uma versão do motor diferente da que a iniciou não foi testado; o `state.json` traz um `schema_version`, um arquivo de estado escrito por um layout incompatível não carrega (`state_version_unsupported`), então consulte o changelog antes de fazer isso.

## Desinstalar

```sh
claude plugin uninstall wev-skills
claude plugin marketplace remove wev-skills-marketplace
```

Status: apenas documentado (não executado). Desinstalar o plugin deixa seus diretórios `.wev/` e quaisquer arquivos de agentes que você exportou para `.claude/agents/`. Apague-os você mesmo se quiser: `.wev/` guarda os registros de execução, as aprovações e o log de auditoria daquele projeto, e o registro por usuário `active-runs.json` (veja acima) guarda entradas de execuções que nunca foram encerradas. Se você criou o link simbólico acima, remova-o com `rm ~/.local/bin/wev`.

## Verificar a instalação

Cada verificação diz o que ela prova.

1. A CLI inicia: `"$WEV_HOME/bin/wev" version`. Prova que o Python e o launcher funcionam.
2. Os agentes incluídos carregam: `"$WEV_HOME/bin/wev" agent list`. Prova que as specs de agentes são válidas.
3. A configuração é válida: `"$WEV_HOME/bin/wev" config show`. Imprime a configuração efetiva, inclusive o diretório de estado que será usado.
4. A suíte de testes passa: `make test` a partir de `$WEV_HOME`. Prova que o motor se comporta, na sua máquina e na sua versão do Python, como seus testes dizem. As linhas exatas de resultado das últimas execuções, com a data, estão em [mvp-status.pt-BR.md](../mvp-status.pt-BR.md); o número de testes cresce conforme testes são acrescentados. Os 8 testes ignorados são os testes de integração locais com tmux, ignorados porque o tmux não estava instalado lá. Seus números serão diferentes quando houver mais testes.
5. Os manifestos do plugin são válidos: `claude plugin validate "$WEV_HOME"`. Prova que manifestos e estrutura são lidos corretamente. Na última execução passou com um aviso, o de que um `CLAUDE.md` na raiz do plugin não é carregado como contexto do projeto, e falha com `--strict` só por causa desse aviso. O aviso trata do arquivo de projeto do próprio repositório e não afeta as skills.
6. Os hooks ficam em silêncio fora de uma execução: em qualquer diretório em que nenhuma execução seja conhecida, `echo '{"tool_name":"Bash","tool_input":{"command":"ls"},"cwd":"/tmp"}' | "$WEV_HOME/bin/wev" hook pre-tool-use` não imprime nada e sai com 0. Prova que o ponto de entrada do hook roda; não prova que o Claude Code o chama.

Depois de uma sessão real com o plugin, `claude plugin list` mostra se ele está instalado e habilitado. Se o Claude Code passa a usar as skills como previsto não é coberto por nenhuma verificação aqui.

## Reverter

- Plugin carregado com `--plugin-dir`: inicie a sessão sem a opção.
- Plugin instalado pelo marketplace: `claude plugin disable wev-skills` o desliga sem removê-lo, e os comandos de desinstalação acima o removem.
- Árvore de código: no seu clone, faça checkout da tag ou do commit anterior (`git checkout v1.0.0`, por exemplo) e atualize o plugin como acima. Toda release tem uma tag `vX.0.0`; `git tag --list` mostra todas.
- Estado das execuções: `.wev/runs/<id>/` são arquivos simples. Uma execução ruim pode ser deixada de lado (ela deixa de ser a execução ativa depois de `wev run finish`) ou apagada, removendo seu diretório. O motor não escreve nada fora de `.wev/`, exceto o registro de execuções por usuário e os arquivos que uma tarefa altera.

## O que precisa de acesso à rede

| Passo | Rede |
|---|---|
| Rodar a CLI, os testes, o harness de avaliação, os hooks | Nenhuma |
| Clonar o repositório | Sim |
| `uvx ruff` e `uvx mypy` (o que o `make lint` usa sem as ferramentas instaladas) | Sim, na primeira vez, para baixar as ferramentas. Depois ficam em cache |
| `pip install` | Sim, se você optar por ele |
| O próprio Claude Code e os modelos que ele usa | Sim, fora deste projeto |
| O provedor de decisão JEV, se você habilitar | Sim: envia o objetivo da tarefa (classificação) ou o título, o objetivo e os critérios de aceitação de uma tarefa (seleção de ferramentas) a um terceiro (ver o [guia de configuração](configuration-and-providers.pt-BR.md)) |
| O módulo remoto | SSH para os hosts que você configurou |
| Workflows do GitHub Actions | Sim, quando rodam no GitHub; nenhum concluiu uma execução |

## Rodando os testes e o lint

```sh
make test   # unittest discover, sem rede, sem modelo
make lint   # ruff check, ruff format --check, mypy strict no pacote
```

O `make lint` usa `ruff` e `mypy` do `PATH`; se não houver, roda-os via `uvx`; se também não houver, informa que pulou. As ferramentas não são dependências de execução.
