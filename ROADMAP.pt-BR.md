# Roteiro

Versão em inglês: [ROADMAP.md](ROADMAP.md).

Esta é a direção do wev-skills, não uma promessa. <!-- wev:release-status -->Última versão publicada: [v5.0.0](https://github.com/wevertonjuscelino/wev-skills/releases/tag/v5.0.0), em 2026-10-20. Milestone aberto da próxima versão: [v6.0.0](https://github.com/wevertonjuscelino/wev-skills/milestone/5).<!-- /wev:release-status --> O número maior conta as versões publicadas em `main` (cada pull request de `dev` para `main` que é mesclado publica o próximo maior); ele não sinaliza mudanças incompatíveis como no Versionamento Semântico, então leia o [changelog](CHANGELOG.md) para saber o que mudou. O esquema está no [guia de manutenção](docs/guides/maintaining.pt-BR.md). Não promete datas nem ordem dentro de uma seção. Cada item diz o que é verdade sobre ele hoje, com os rótulos de evidência do projeto: implementado e testado; implementado mas não testado; simulado com mocks; apenas documentado; bloqueado. Um item sem implementação é "apenas documentado". As fontes são a [especificação](docs/spec.pt-BR.md), o [estado do MVP](docs/mvp-status.pt-BR.md), os limites conhecidos do [SECURITY.pt-BR.md](SECURITY.pt-BR.md) e as [hipóteses](docs/research/hypotheses.pt-BR.md).

## Como ler

- Uma seção é uma direção. Subir ou descer um item não exige aviso, e um item pode ser descartado.
- "Evidência hoje" é o estado do trabalho agora. Nunca é evidência de que o trabalho pronto vai ajudar: nenhuma melhoria medida é alegada para qualquer item.
- Um item passa para o [changelog](CHANGELOG.md) quando é entregue, com o seu rótulo.

## Agora: endurecimento

Trabalho que torna o comportamento existente confiável e verificado. Nenhuma capacidade nova.

- **Testar o plugin em uma sessão real do Claude Code**: carregá-lo, rodar o `wev-orchestrate` em uma tarefa pequena, ver os hooks dispararem e os subagentes carregarem. Evidência hoje: apenas documentado. O `claude plugin validate .` passa com um aviso esperado; nada foi visto carregando em uma sessão real.
- **Rodar o módulo remoto contra um tmux real e um host SSH real.** Evidência hoje: simulado com mocks para SSH; os testes locais de integração com tmux rodam no workflow principal de CI, então consulte o histórico de Actions para o resultado.
- **Reverificação independente das correções feitas depois da última rodada de revisão.** Evidência hoje: não feita; não existe registro de reverificação.
- **Segundo leitor para os documentos em português e para as alegações de estado e compatibilidade.** Evidência hoje: não feito.
- **Aplicar as configurações pretendidas do repositório no GitHub** (rulesets, relato privado de vulnerabilidades, varredura de segredos, labels) descritas no [guia de manutenção](docs/guides/maintaining.pt-BR.md). Evidência hoje: apenas documentado; a aplicar.
- **Estreitar os limites conhecidos que uma regra consegue estreitar**, por exemplo mais comandos Git que executam helpers, listados em "Limites conhecidos" do [SECURITY.pt-BR.md](SECURITY.pt-BR.md). Evidência hoje: implementado e testado para as opções explícitas `--textconv` e `--ext-diff`; helpers implícitos habilitados pela configuração do repositório seguem como limite aberto.
- **Decidir o aviso do `CLAUDE.md` na raiz do plugin** no `claude plugin validate` (mover o arquivo ou aceitar). Evidência hoje: o aviso é conhecido e aceito por enquanto.

## Próximo: 0.3.0

Candidatos à próxima versão menor. Cada um precisa de desenho e testes próprios antes de ser prometido.

- **Hooks para ferramentas além do Bash**, por exemplo conferir Edit e Write contra os arquivos declarados de uma tarefa. Evidência hoje: apenas documentado (a especificação o lista como fora do escopo do MVP). Só o Bash passa pelo hook agora.
- **Avaliação com modelos reais** e comparação medida entre configurações, seguindo [o plano de experimentos](docs/research/experiments.pt-BR.md). Evidência hoje: o harness com script é implementado e testado e nada diz sobre qualquer modelo. Os mecanismos das hipóteses H1 a H10 são implementados; o efeito deles em um modelo real não foi medido.
- **Uma ferramenta de recall exposta ao modelo durante a sessão.** Evidência hoje: `wev context recall` é implementado e testado como comando da CLI; nada o expõe a um modelo.
- **Validação ao vivo da entrevista de objetivo e dos especialistas de projeto** com um modelo real. Evidência hoje: implementado e testado com testes unitários focados; entrevistas ao vivo e especialistas exportados em uma sessão real não foram validados.

## Depois

Direções sem plano. Podem nunca ser entregues.

- **Adaptadores para ambientes de agente além do Claude Code.** Evidência hoje: apenas documentado. O núcleo não importa um adaptador, mas só existe o do Claude Code, então nenhuma outra compatibilidade é alegada.
- **Entrada em YAML para specs de agentes.** Evidência hoje: apenas documentado; as specs são JSON ([ADR 0003](docs/architecture/decisions/0003-json-specs-and-schema-subset.pt-BR.md)).
- **Suporte a Windows para o armazenamento de estado.** Evidência hoje: apenas documentado. As plataformas documentadas são macOS e Linux.
- **Distribuição além do clone ou da rota do marketplace do Claude Code**, como um pacote no PyPI. Evidência hoje: apenas documentado; não há pacote nem decisão de publicar um.

## Fora do plano

Declarado para que ninguém espere por isso.

- **Uma fronteira de segurança contra um agente adversário na mesma conta de usuário.** O motor é uma proteção para um agente falível ([ADR 0006](docs/architecture/decisions/0006-guardrail-not-boundary.pt-BR.md)). Isolamento do sistema operacional é a resposta a essa ameaça, e fica fora deste projeto.
- **Dependências em tempo de execução no núcleo.** O motor usa só a biblioteca padrão ([ADR 0001](docs/architecture/decisions/0001-python-stdlib-engine.pt-BR.md)); ruff, mypy e uvx continuam sendo ferramentas.
- **Suporte a Python anterior ao 3.14.**
- **Alegações de economia de tokens ou ganho de qualidade sem medições**, e alegações de compatibilidade com uma plataforma sem adaptador e teste de integração.
- **Conceder aprovações em nome do operador humano.** Os comandos de operador continuam só humanos.

## Como o roteiro é acompanhado

O trabalho é acompanhado no GitHub com milestones (um por versão planejada) e as labels de [.github/labels.json](.github/labels.json). Uma issue só é ligada a um milestone quando um mantenedor a aceita (`status: accepted`). Os milestones levam o nome da versão que alimentam (`v3.0.0` é a próxima); os milestones antigos `0.2.x` e `0.3.0` serão renomeados para combinar. Este arquivo é o resumo; os milestones e as issues são o detalhe, e onde divergirem, a issue e o changelog são o registro mais atual. Para propor uma mudança, abra uma solicitação de funcionalidade ou inicie uma conversa nas Discussions (veja [SUPPORT.pt-BR.md](SUPPORT.pt-BR.md)).
