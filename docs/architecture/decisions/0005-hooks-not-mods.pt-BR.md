# ADR 0005: Hooks simples, não mods do Claude Code

Versão em inglês: [0005-hooks-not-mods.md](0005-hooks-not-mods.md).

Status: aceito (2026-10-13)

## Contexto

O wev-skills precisa agir dentro de uma sessão do Claude Code: reinjetar o resumo (brief) da execução ativa depois da compactação e a cada prompt, e checar os comandos Bash contra a política de permissões da execução (ver o ADR 0002 e a seção 4.14 da [arquitetura](../architecture.pt-BR.md)).

Em 2026-10-13 o responsável pelo projeto avaliou duas formas de fazer isso no Claude Code:

- **Hooks simples**: entradas em `hooks/hooks.json` que executam um comando (`wev hook <nome>`), entregam a ele o JSON do hook na entrada padrão e leem a decisão da saída padrão. Fazem parte do formato de plugin.
- **Mods**: módulos JavaScript de hooks que também podem desenhar interface ao vivo (um painel, uma faixa acima do prompt, uma linha de status). Foram considerados porque uma visão ao vivo da execução (fase, tarefas, aprovações pendentes) seria útil para quem acompanha uma sessão.

## Decisão

Manter os hooks simples. Não adotar mods.

## Motivos

- Hooks simples rodam em toda superfície do Claude Code que aceita hooks de plugin. Mods que desenham interface ao vivo dependem de uma superfície capaz de exibi-la, e o responsável não quis um recurso que funciona em alguns lugares e em outros não.
- Mods dependem de uma API de acesso antecipado (early access). Um harness cujo objetivo é ser previsível não deve se apoiar numa interface que pode mudar.
- Um mod é JavaScript que roda sem sandbox, com as permissões da pessoa usuária. O responsável não quis distribuir isso. Não se afirma que hooks tenham sandbox: um hook de comando também roda com as permissões da pessoa usuária. A diferença está no que é preciso confiar. Um hook é uma linha de comando que a pessoa pode ler em `hooks.json` e que chama o mesmo motor Python, que tem testes. Um mod seria um segundo programa, em outra linguagem, que também teria de ser auditado. A posição de segurança do projeto (ver [SECURITY.pt-BR.md](../../../SECURITY.pt-BR.md)) é que os controles ficam no motor, em código testado; um segundo caminho de código ao lado dele vai contra isso.
- O motor já tem tudo que um hook precisa. Um hook de comando é só um ponto de entrada fino (`wev hook ...`), então a lógica fica num único lugar testado e pode servir outro ambiente mais tarde, por meio de outro adaptador.

## Consequências

- Não há interface ao vivo. O plugin só acrescenta à sessão texto injetado no contexto e uma decisão `ask` ou `deny` para um comando Bash. Quem quiser ver o estado de uma execução roda `wev run status` ou `wev run brief`.
- Os hooks mantêm os limites registrados no ADR 0002: checam só a ferramenta Bash, só ficam em silêncio quando nenhuma execução é encontrada (com uma execução conhecida, um erro interno vira `ask`), só podem negar ou perguntar (nunca permitir), não consultam o repositório de aprovações e não foram exercitados dentro de uma sessão real do Claude Code.
- Este registro não define condições para rever a decisão. Se os inconvenientes acima deixarem de valer, um novo ADR pode reabri-la.

## Alternativas consideradas

- Mods para a visão ao vivo e hooks simples para as checagens: rejeitado por ora. Dobraria a superfície a testar e documentar por uma conveniência, e a conveniência não existiria em todas as superfícies.
- Nenhum hook: rejeitado. Sem eles o resumo se perde na compactação e os comandos Bash comuns passam fora da política do motor (ADR 0002).

## Rótulo de evidência

Apenas documentado (documented only). Este registro descreve uma decisão. Os hooks que ele mantém estão implementados e cobertos por testes unitários e de subprocesso (ver [mvp-status.pt-BR.md](../../mvp-status.pt-BR.md)); nem os hooks nem os mods foram medidos ou exercitados numa sessão real para tomar esta decisão.
