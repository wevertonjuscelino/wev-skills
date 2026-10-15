# Suporte

Versão em inglês: [SUPPORT.md](SUPPORT.md).

O wev-skills é mantido por uma pessoa, Weverton Juscelino. Esta página diz aonde levar uma dúvida, um bug ou uma vulnerabilidade, o que é suportado e o que esperar em troca.

## Onde perguntar

| Você quer | Vá para |
|---|---|
| Perguntar como usar o wev-skills ou discutir uma ideia | [GitHub Discussions](https://github.com/wevertonjuscelino/wev-skills/discussions), categoria Q&A (a ser habilitada pelo mantenedor) |
| Relatar um bug ou um documento errado | Uma issue, pelos [formulários](https://github.com/wevertonjuscelino/wev-skills/issues/new/choose) |
| Propor uma mudança | O formulário de solicitação de funcionalidade, depois de uma conversa curta nas Discussions se a ideia não estiver firme |
| Relatar uma vulnerabilidade | Relato privado, como descrito no [SECURITY.pt-BR.md](SECURITY.pt-BR.md). Nunca em uma issue pública nem nas Discussions |

Antes de perguntar, leia o [guia de instalação](docs/guides/installation.pt-BR.md), os outros [guias](docs/guides/) e o [roteiro](ROADMAP.pt-BR.md). Para um bug, inclua a versão do Python, o sistema operacional, a versão ou o commit do wev-skills, os comandos exatos e a saída sem segredos. Não cole segredos, tokens, nomes de hosts nem dados privados em lugar nenhum.

## O que é suportado

- Python 3.14 ou mais novo. Interpretadores mais antigos, incluindo o `/usr/bin/python3` do macOS (3.9), não são suportados.
- macOS e Linux. O workflow de CI roda a suíte de testes no Ubuntu e no macOS; consulte o histórico de Actions para o resultado em um commit. O armazenamento de estado no Windows não é suportado.
- O plugin do Claude Code, até onde o `claude plugin validate .` aceita os manifestos. Evidência hoje: apenas documentado para uma sessão real do Claude Code; veja o [estado do MVP](docs/mvp-status.pt-BR.md). Nenhum outro ambiente de agente é suportado.
- A última versão. As correções de segurança seguem a tabela do [SECURITY.pt-BR.md](SECURITY.pt-BR.md).

O motor é uma proteção para um agente falível, não uma fronteira de segurança contra um agente adversário. Um relato que dependa da suposição contrária é um limite conhecido, não um bug.

## O que esperar

- O suporte é de melhor esforço, sem nível de serviço e sem prazo de resposta comprometido.
- Issues e perguntas são lidas e podem ser rotuladas, respondidas, movidas para as Discussions ou fechadas. Uma issue que não se reproduz a partir do relato pode esperar com `status: needs-repro`.
- Um pedido pode ser recusado, por exemplo quando exige uma dependência em tempo de execução ou prende o núcleo a uma plataforma (veja o [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md)).
- Pull requests são bem-vindos depois de uma issue ou de uma conversa nas Discussions, seguindo o [CONTRIBUTING.pt-BR.md](CONTRIBUTING.pt-BR.md) e o [Código de Conduta](CODE_OF_CONDUCT.md).
