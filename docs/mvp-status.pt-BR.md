# Status do MVP

English version: [mvp-status.md](mvp-status.md).

Data de todas as verificações abaixo: 2026-10-13. Máquina: macOS (Darwin), Python 3.14.7 (veja "Resultados da verificação"); Claude Code para `claude plugin validate`. Nada foi executado em Linux nem em Windows.

Estado do repositório: <!-- wev:release-status -->Última versão publicada: [v5.0.0](https://github.com/wevertonjuscelino/wev-skills/releases/tag/v5.0.0), em 2026-10-20.<!-- /wev:release-status --> Repositório público: <https://github.com/wevertonjuscelino/wev-skills>. A primeira publicação (2026-10-13) é a v1.0.0, publicada primeiro como 0.1.0 e renumerada em 2026-10-15. Até este commit: os workflows de CI existem; consulte o histórico de Actions para resultados por commit; nada foi exercitado em uma sessão real do Claude Code; não houve execução real com tmux ou SSH; três rodadas de revisão independente foram seguidas de correções, e as correções feitas depois da última rodada não foram verificadas de novo de forma independente; a posição de segurança é a do [SECURITY.pt-BR.md](../SECURITY.pt-BR.md). Tags e releases do GitHub são criadas fora da árvore de trabalho: o dono refaz as tags `v1.0.0` e `v2.0.0`, e as próximas releases saem do workflow de release (veja "Depois de publicar").

Este documento é rigoroso. Um critério que depende de algo que não foi executado é marcado como parcial ou bloqueado, com o motivo. "Atendido" significa que a evidência indicada na [especificação](spec.pt-BR.md) existe e o comando registrado passa; não significa que a coisa tenha sido usada em campo. Rótulos: implementado e testado; implementado mas não testado; simulado com mocks; apenas documentado; bloqueado (veja o [glossário](glossary.md)).

## Resultados da verificação

Esta seção é o único lugar deste documento que guarda as linhas de resultado da suíte inteira e dos linters.

Em 2026-10-13, ao fim do trabalho que preparou a publicação da 0.1.0, o `make test` e o `make lint` foram executados no Python 3.14.7 (macOS). Os blocos abaixo guardam, nesta ordem, as linhas de resultado do `make test` e do `make lint` (ruff e mypy via `uvx`). Vêm da máquina do dono, não do CI. Uma execução anterior da suíte no Python 3.10 passou antes de o Python mínimo ser elevado para 3.14; o Python 3.10 não é mais testado.

```text
Ran 2076 tests in 167.282s
OK (skipped=8)
```

```text
All checks passed!
280 files already formatted
Success: no issues found in 146 source files
```

## Recursos acrescentados depois do MVP

A entrevista de objetivo e os especialistas de projeto foram acrescentados depois da verificação original do MVP acima. A [entrada de objetivos](guides/intake.pt-BR.md) limita cada rodada a três perguntas e associa o brief concluído à execução. Os [especialistas de projeto](guides/specialists.pt-BR.md) mantêm os limites de permissão, recalculam até 30 lições a partir de registros do motor para o mesmo repositório e avisam a 80% dos limites globais. Unidades de comando e tentativas de início de tarefa são orçamentos separados; não representam tokens de modelo nem dinheiro.

Testes focados de CLI, persistência, aprendizado, roteamento e orçamento cobrem esses acréscimos. O resultado da suíte completa pertence ao commit posterior e deve ser consultado na saída de CI/checks dele, não inferido dos números históricos acima. Entrevistas conduzidas por modelos e especialistas exportados numa sessão real continuam sem validação. A [revisão local de segurança](security-review-2026-10-13.pt-BR.md) registra as correções de permissões na escrita incremental e helpers Git explícitos, com os limites restantes.

Os adaptadores de harness para Codex, Gemini CLI e OpenCode (`wev harness export|install|uninstall`, `wev hook ... --harness`) foram acrescentados depois. Status: implementado e testado com CLIs de harness falsas; ainda não executado contra os harnesses reais (parte e2e). O plugin do OpenCode foi testado sob node com um `wev` falso e nunca rodou dentro do OpenCode. Eles não acrescentam linha aos 16 critérios; os limites estão em [SECURITY.pt-BR.md](../SECURITY.pt-BR.md#outros-harnesses).

As atualizações de skills de terceiros (`wev skills ...`, o hook da verificação diária) foram acrescentadas depois. Situação: implementado e testado com um registro local falso, um npx falso e tarballs locais; os registros reais, os downloads e o servidor rea real não são executados nesta alteração (parte e2e). Elas não acrescentam linha aos 16 critérios; os limites estão em [SECURITY.pt-BR.md](../SECURITY.pt-BR.md#atualizações-de-skills-de-terceiros).

A integração com o rea (`wev rea serve|status|mode|build-image`, a imagem de contêiner `wev-rea`, o registro no Claude Code, Gemini CLI e OpenCode) foi acrescentada depois. Situação: implementado e testado com executáveis `npx` e `docker` falsos (testes unitários); o servidor rea real, o build real do contêiner e os carregadores reais dos harnesses não são executados nesta alteração (parte e2e). A skill `wev-reverse` está apenas documentada. Ela não acrescenta linha aos 16 critérios; os limites estão em [SECURITY.pt-BR.md](../SECURITY.pt-BR.md#rea-servidor-de-engenharia-reversa).

O instalador (`install.sh`), o nível de configuração do usuário (`~/.config/wev-skills/wev.config.json` lido abaixo do arquivo do repositório) e o `wev jev key set` foram acrescentados depois. Situação: implementado e testado com CLIs de harness falsas e uma fonte local (testes unitários, offline). A rota de download (API de releases e `git clone` da tag), um `claude plugin install` real, Codex, Gemini CLI e OpenCode reais, um teste real do JEV e o caminho interativo de instalação de dependências não são executados nesta mudança (parte e2e); a linha `curl | bash` é apenas documentada até o dono publicar o script. Veja o [guia de instalação](guides/installation.pt-BR.md#instalação-rápida) e o [SECURITY.pt-BR.md](../SECURITY.pt-BR.md#instalador).

Execução de ponta a ponta de 2026-10-22 ([relatório](../evals/reports/e2e-2026-10-22.md)), por área. Instalador, rota de fonte local: testado de ponta a ponta no macOS com HOME isolado (não uma máquina limpa); 13 de 13 verificações passaram contra o registro npm e as releases do GitHub reais, cobrindo instalação, nova execução, atualização, reversão (estado semeado), instalação quebrada, `rea serve` em modo direto e desinstalação `--purge`. Instalador, rota de download: não executada. Linux: contêiner em branco, ainda não executado (pulado, daemon do Docker parado). Modo isolado e imagem do rea: não executados (mesmo motivo). Claude Code, Codex, Gemini CLI, OpenCode, JEV ao vivo e a verificação diária de atualização: não executados contra o harness ou serviço real (cenários implementados mas não testados). Nenhuma alegação de "compatível com" é feita para qualquer harness.

## Resumo

| # | Critério | Situação |
|---|---|---|
| 1 | A skill de entrada existe com frontmatter válido | Atendido |
| 2 | A instalação local está documentada e testada | Parcial |
| 3 | O fluxo básico de orquestração roda de ponta a ponta | Atendido |
| 4 | Pelo menos dois agentes são customizáveis por configuração | Atendido |
| 5 | O roteamento tem interface documentada e implementação funcional | Atendido |
| 6 | A criação e a validação de agentes têm testes | Atendido |
| 7 | Plano e estado persistem e podem ser retomados | Atendido |
| 8 | A proteção contra laços tem testes determinísticos | Atendido |
| 9 | O contexto gerenciado tem estratégia de compactação testável | Atendido |
| 10 | Os controles de permissão são verificados por testes | Parcial |
| 11 | A integração SSH e tmux é isolada e testada com mocks | Atendido (simulado com mocks; tmux real não executado) |
| 12 | A documentação existe em português e em inglês | Atendido |
| 13 | Os workflows de CI estão configurados | Parcial |
| 14 | Os comandos de teste executados têm resultados registrados | Atendido |
| 15 | Sem segredos, sem referências quebradas conhecidas, sem alegações de compatibilidade sem suporte | Parcial |
| 16 | O projeto está publicado como pré-lançamento e seu estado está registrado | Parcial |

O critério 10 é Parcial porque a posição de segurança do projeto (veja o [ADR 0006](architecture/decisions/0006-guardrail-not-boundary.pt-BR.md) e o [SECURITY.pt-BR.md](../SECURITY.pt-BR.md)) é que o motor é uma proteção e um registro, não uma fronteira, e porque as correções feitas depois da última de três rodadas de revisão independente não foram verificadas de novo de forma independente.

## Os 16 critérios

Nos comandos abaixo, `PYTHONPATH=src` está definido e o diretório de trabalho é a raiz do repositório. "Resultado" é a última linha de resumo impressa.

### 1. A skill de entrada existe com frontmatter válido: Atendido

- Comando: `python3 -m unittest tests.unit.test_skills`. Resultado: `OK`. Verifica frontmatter, tamanho do corpo, tratamento do português, links relativos, se todo comando e flag mostrado em uma skill existe na CLI, manifestos e arquivos de exemplo.
- Comando: `claude plugin validate .`. Resultado: `Validation passed with warnings`; um aviso, "CLAUDE.md at the plugin root is not loaded as project context".
- Falta: nenhuma skill foi carregada por uma sessão real do Claude Code. O aviso é sobre o arquivo do projeto na raiz do repositório, não sobre uma skill.

### 2. A instalação local está documentada e testada: Parcial

- Evidência: [guia de instalação](guides/installation.pt-BR.md). Executado: `bin/wev version` imprimiu `{"version": "0.1.0"}`; `claude plugin validate .` (critério 1).
- Não executado: `git clone` do repositório publicado, `claude --plugin-dir` (inicia uma sessão), `claude plugin marketplace add` (com o caminho local e com `wevertonjuscelino/wev-skills`), `claude plugin install`, `update`, `uninstall` (alteram a configuração do Claude Code da máquina) e `pip install`. Esses passos estão apenas documentados.
- Falta: carregar o plugin em uma sessão real; executar a instalação pelo marketplace em um perfil descartável; decidir se `pip install` será testado.

### 3. O fluxo básico de orquestração roda de ponta a ponta: Atendido

- Comando: `python3 -m unittest tests.integration.test_cli_flow`. Resultado: `OK`. Conduz a CLI real do pedido ao relatório, incluindo passos do operador digitados em um pseudoterminal, verificação estrita, detecção de baseline, fixação da configuração e execuções com aprovação.
- Falta: nenhum modelo participou. Quão bem um modelo segue a skill `wev-orchestrate` não foi observado.

### 4. Pelo menos dois agentes são customizáveis por configuração: Atendido

- Comando: `python3 -m unittest tests.unit.test_agent_catalog tests.unit.test_agents_spec tests.unit.test_adapter_claude_subagent`. Resultado: `OK`. As dez specs de exemplo carregam, validam e exportam.
- Verificação: `bin/wev agent export` em um diretório temporário produziu arquivos idênticos aos de `agents/` no repositório.
- Falta: os arquivos de subagente exportados não foram carregados por uma sessão real do Claude Code.

### 5. O roteamento tem interface documentada e implementação funcional: Atendido

- Comando: `python3 -m unittest tests.unit.test_models_router tests.unit.test_decisions_local tests.unit.test_decisions_jev tests.unit.test_decisions_factory tests.unit.test_routing_catalog`. Resultado: `OK`. Interface: arquitetura 4.2 e 4.4.
- O cliente HTTP embutido do JEV (padrão, `decision.jev.command` é `builtin`) e `wev jev status|ask|batch`: implementados e testados contra um servidor falso local. O serviço real da TypeSafe não foi executado nesta mudança.
- Falta: o adaptador do JEV é testado com um cliente falso e com o formato de resposta registrado; o JEV foi chamado de verdade três vezes com entradas sintéticas (uma classificação, duas seleções de ferramentas, 2026-10-13), e as respostas da seleção de ferramentas não foram salvas como fixtures. O roteamento e a seleção de ferramentas são heurísticas cuja utilidade não foi medida.

### 6. A criação e a validação de agentes têm testes: Atendido

- Comando: `python3 -m unittest tests.unit.test_agents_factory tests.unit.test_agents_registry tests.unit.test_commands_agent`. Resultado: `OK`.
- Falta: nada para este critério.

### 7. Plano e estado persistem e podem ser retomados: Atendido

- Comando: `python3 -m unittest tests.unit.test_state_store tests.unit.test_state_resume tests.unit.test_state_model`. Resultado: `OK`. Cobre commits condicionais à revisão carregada, o tempo limite do lock, o campo opcional `remote_runs` e a recusa de arquivos de estado antigos.
- Falta: retomar com uma versão do motor diferente da que gravou o estado não foi testado.

### 8. A proteção contra laços tem testes determinísticos: Atendido

- Comando: `python3 -m unittest tests.unit.test_guard_execution tests.unit.test_guard_reset`. Resultado: `OK`.
- Falta: o efeito do guard sobre um agente real não foi observado.

### 9. O contexto gerenciado tem estratégia de compactação testável: Atendido

- Comando: `python3 -m unittest tests.unit.test_context_manager`. Resultado: `OK`.
- Falta: o gerenciador de contexto atende `wev context compact` e o harness de avaliação; o fluxo de orquestração não o usa, e ele não consegue controlar a janela de contexto do próprio Claude Code. Seu efeito sobre um modelo não foi medido.

### 10. Os controles de permissão são verificados por testes: Parcial

- Comando: `python3 -m unittest discover -s tests/security -t .`. Resultado: `OK`. `python3 -m unittest tests.unit.test_hooks`: `OK`.
- Falta: três rodadas de revisão independente em 2026-10-13, antes da publicação, acharam os controles de aprovação e de hook contornáveis pelo agente restringido; cada rodada foi seguida de correções, implementadas e testadas, mas as correções feitas depois da última rodada não foram verificadas de novo de forma independente (não existe registro de nova verificação). O motor é uma proteção para um agente falível, não uma fronteira de segurança contra um agente adversário na mesma conta de usuário. Limites abertos conhecidos: as ferramentas de arquivo do próprio agente podem reescrever o estado, as aprovações, o log de auditoria e o registro; um pseudoterminal pode digitar a palavra de confirmação, e um script que conduz um não é visto pelo hook; `python3 script.py`, `make`, `mv`, `sed -i`, redirecionamentos e programas desconhecidos por caminho absoluto não passam por portão no modo execute; processos filhos herdam o ambiente de quem os chama. Veja o [ADR 0006](architecture/decisions/0006-guardrail-not-boundary.pt-BR.md).

### 11. A integração SSH e tmux é isolada e testada com mocks: Atendido, simulado com mocks

- Comando: `python3 -m unittest tests.unit.test_remote_inventory tests.unit.test_remote_transport tests.unit.test_remote_tmux tests.unit.test_remote_tmux_status tests.unit.test_commands_remote tests.security.test_remote_safety tests.unit.test_remote_run_state tests.unit.test_remote_cli_run`. Resultado: `OK`.
- Comando: `python3 -m unittest tests.integration.test_tmux_local`. Resultado: `OK`, com todos os testes pulados: o tmux não está instalado nesta máquina, então todos os testes com tmux real foram pulados.
- Falta: o módulo nunca rodou contra um tmux real nem contra um servidor real.

### 12. A documentação existe em português e em inglês: Atendido

- Comando: `python3 -m unittest tests.unit.test_docs`. Resultado: `OK`. Verifica que os documentos têm gêmeos com a mesma estrutura, que os links relativos resolvem e regras de estrutura relacionadas.
- Falta: o teste verifica estrutura, não qualidade de tradução. O português não foi revisado por uma segunda pessoa.

### 13. Os workflows de CI estão configurados: Parcial

- Evidência: `.github/workflows/ci.yml` e `.github/workflows/remote-integration.yml` (manual, tmux local) existem.
- Falta: verificar os resultados de Actions para o commit que será lançado. As actions estão fixadas em SHAs de commit (`actions/checkout` v7.0.1 e `actions/setup-python` v7.0.0, consultadas em 2026-10-13). A matriz é Ubuntu e macOS, só com Python 3.14.

### 14. Os comandos de teste executados têm resultados registrados: Atendido

- Este documento. Veja [Comandos executados](#comandos-executados).

### 15. Sem segredos, sem referências quebradas conhecidas, sem alegações de compatibilidade sem suporte: Parcial

- Segredos: `python3 scripts/scan_secrets.py`. Resultado: `scan_secrets: no credential patterns found.` O `tests/unit/test_repo_hygiene.py` também falha com caminhos de diretório pessoal, textos pessoais e endereços de e-mail que não sejam de exemplo em qualquer arquivo que o git rastrearia. O script é um alarme estreito, ignora `tests/` e não detectaria uma credencial sem formato reconhecível. O teste unitário do próprio script imprime uma linha sobre `b.txt` de uma fixture fabricada; isso não é um achado.
- Referências quebradas: a verificação de links de `tests.unit.test_docs` passa. Ela confere arquivos, não âncoras de títulos nem URLs externas.
- Alegações de compatibilidade: os documentos alegam compatibilidade com o Claude Code apenas até onde `claude plugin validate` aceita os manifestos, e não alegam nada para outros ambientes. Não existe revisão independente das alegações.
- Falta: revisão independente das alegações; uma varredura dos arquivos rastreados depois do primeiro commit (até lá, o `python3 scripts/scan_secrets.py` lê o sistema de arquivos).

### 16. O projeto está publicado como pré-lançamento e seu estado está registrado: Parcial

- Publicado: o dono autorizou a publicação em 2026-10-13 como 0.1.0 (renumerada v1.0.0 em 2026-10-15) em <https://github.com/wevertonjuscelino/wev-skills> (público). A árvore de trabalho foi preparada para isso: URL do repositório nos manifestos e documentos, git hooks, CODEOWNERS, Dependabot, actions fixadas, um teste de higiene, um guia de manutenção.
- Não estabelecido: nada foi exercitado em uma sessão real do Claude Code; nenhuma execução real com tmux ou SSH; as correções posteriores à última rodada de revisão não foram verificadas de novo de forma independente. Veja [Depois de publicar](#depois-de-publicar).
- Versionamento e automação de release, verificados em 2026-10-15 (macOS, Python 3.14): `scripts/versioning.py`, `scripts/release_prep.py` e `scripts/collect_release_prs.py` são implementados e testados (`tests.unit.test_versioning` e `tests.unit.test_release_prep`, com repositórios git temporários e cópias dos arquivos reais); `make test` (2187 testes, OK), `make lint`, `bin/wev readme check`, `bin/wev claude-md check` e `python3 scripts/scan_secrets.py` passaram com estas mudanças; um ensaio em uma cópia temporária imprimiu `2.2.2` para um dev com dois pull requests mesclados de dois commits cada, `3.0.0` como próxima release, e `release_prep.py --version 3.0.0` reescreveu 13 arquivos. Os workflows `release.yml` (push em `main`) e `pr-policy.yml` são implementados mas não testados: só rodam no GitHub e ainda não houve execução. As chamadas de rede (`gh`) e os pushes com o token do job não foram exercitados.
- Não feito na árvore de trabalho: o commit, o push, a tag `v1.0.0`, a release do GitHub e todas as configurações do repositório. O dono faz isso.

## Comandos executados

Todos em 2026-10-13, depois da última mudança de código.

| Comando | Resultado |
|---|---|
| `make test` | veja "Resultados da verificação" |
| `make lint` (ruff e mypy via `uvx`) | veja "Resultados da verificação" |
| `python3 scripts/scan_secrets.py` | `scan_secrets: no credential patterns found.` |
| `bin/wev readme check` | `"ok": true`, no findings, no warnings |
| `bin/wev claude-md check` | `"ok": true`, exit 0 |
| `PYTHONPATH=src python3 -m unittest tests.unit.test_docs tests.unit.test_skills tests.unit.test_repo_hygiene` | `Ran 42 tests`, `OK` |
| `claude plugin validate .` | `Validation passed with warnings` (1 warning, see criterion 1) |
| os comandos unittest por critério acima | todos `OK` |
| `bin/wev --help` e `--help` de cada grupo e subcomando | impressos; usados para escrever os guias e as skills |
| Sequências de comandos executadas à mão em um repositório git temporário fora deste (run, plan, task, exec, report, agent, config, claude-md, hooks) | as saídas estão citadas nos guias e nas skills; nenhuma contatou rede, modelo, SSH nem o `jev` real |

Os testes pulados são os de `tests/integration/test_tmux_local.py`.

Não executados de propósito: `wev approval grant`, `wev approval deny`, `wev guard acknowledge` e `wev task reopen` (são passos do operador humano), o `jev` real, qualquer SSH (com uma exceção não intencional: ao documentar, um `wev remote start` contra o alias de exemplo `staging-1` iniciou o cliente `ssh` do sistema, que não conseguiu resolver o alias e falhou com `remote_connection_failed`; nenhuma conexão foi feita), `claude -p`, `claude --plugin-dir` e os comandos de marketplace e de instalação.

## Não verificado

- Nada foi executado em uma sessão real do Claude Code: skills, subagentes exportados e hooks não foram vistos carregando, disparando nem sendo seguidos.
- Os resultados do GitHub Actions precisam ser conferidos para o commit que será lançado.
- Nenhum tmux real e nenhum host SSH real: o módulo remoto é simulado apenas com mocks.
- Nada foi executado em Linux, e só o Python 3.14.7 foi usado. O Python 3.10 a 3.13 não são suportados nem testados; a única execução anterior no 3.10 é anterior à mudança do mínimo.
- O JEV está verificado por três chamadas reais com entradas sintéticas apenas: uma resposta de classificação (registrada como fixture) e duas respostas de seleção de ferramentas (não salvas). Isso estabelece o formato da resposta para este uso e nada sobre economia de tokens ou sucesso de tarefas.
- Três rodadas de revisão independente foram seguidas de correções. As correções feitas depois da última rodada não foram verificadas de novo de forma independente; não existe registro de nova verificação.
- `pip install` do pacote e do console script `wev`, `git clone` do repositório publicado, e `claude --plugin-dir`, marketplace add (caminho local e GitHub), install, update e uninstall.
- Os git hooks de `.githooks/` foram executados por seus testes em repositórios temporários (com o `make` trocado por um programa falso no `pre-push`); o `make hooks` não foi executado neste repositório.
- O efeito de qualquer mecanismo derivado da pesquisa (planejamento condicional, perfis de ferramentas, seleção de ferramentas, lembrete do plano, compactação em estágios, guards) sobre um modelo real, e qualquer melhoria medida. O harness de avaliação usa um agente roteirizado e unidades simuladas e não diz nada sobre nenhum modelo.
- Revisão do texto em português por um segundo leitor.
- Retomar uma execução com outra versão do motor.

## Depois de publicar

O repositório está publicado; nenhum destes itens foi feito. As configurações do repositório não podem ser definidas pela árvore de trabalho, então os itens sobre configurações são intenção documentada para o dono, não coisas já habilitadas.

- [ ] Conferir a execução do CI para o commit do lançamento no GitHub (`ci.yml`: testes no Ubuntu e no macOS com Python 3.14, lint, skills, git hooks e documentos, varredura de segredos) e corrigir o que ele apontar.
- [x] Aplicado em 2026-10-15 pela API do GitHub (`gh repo edit`, `gh api`), conforme a seção "Configurações do repositório" do [guia de manutenção](guides/maintaining.pt-BR.md): descrição e topics, recursos (Issues e Discussions ligados, Wiki e Projects desligados), merge, relato privado de vulnerabilidades, varredura de segredos e proteção de push, alertas e atualizações de segurança do Dependabot, o ruleset de branch `main protection` e o ruleset de tags `release tags`, as labels de `.github/labels.json` e os milestones `0.2.x` e `0.3.0` (a renomear para `v3.0.0` e seguintes). Evidência: as respostas da API no momento; confira a página de configurações do repositório para o estado atual.
- [ ] A fazer (configurações da conta do dono, não do repositório): "keep my email address private" e "block command line pushes that expose my email".
- [ ] Experimentar o plugin em uma sessão real do Claude Code: carregá-lo com `--plugin-dir`, executar `wev-orchestrate` em uma tarefa pequena, verificar se os hooks disparam e se os subagentes carregam. Depois experimentar a rota publicada (`claude plugin marketplace add wevertonjuscelino/wev-skills`). Registrar o resultado.
- [ ] Executar o workflow manual `remote-integration.yml` (tmux real, localmente no runner) e `tests/integration/test_tmux_local.py` em uma máquina com tmux.
- [ ] Executar `make hooks` no clone e confirmar que os commits trazem o nome de autor Weverton Juscelino, um e-mail no-reply do GitHub e nenhum trailer de coautoria.
- [ ] A fazer (dono): refazer as tags das duas versões publicadas sob o esquema de contagem de releases (`v1.0.0` em `4ab225b`, `v2.0.0` em `e6035b7`) e recriar suas releases do GitHub como releases finais; aplicar os rulesets de `main` e `dev` e as configurações de merge do guia de manutenção; criar `dev` a partir de `main`; renomear os milestones antigos. O novo workflow de release (`.github/workflows/release.yml`) e o de política de PR são implementados mas não testados: só rodam no GitHub. O primeiro merge de dev em main depois disso é a primeira execução real.
- [ ] Fazer com que as correções posteriores à última rodada de revisão sejam verificadas de novo de forma independente.
- [ ] Decidir sobre o aviso do `CLAUDE.md` na raiz do plugin (mover o arquivo ou aceitar).
- [ ] Pedir a uma segunda pessoa que leia os documentos em português e as alegações de compatibilidade e de status.
