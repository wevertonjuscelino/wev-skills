# ADR 0002: O motor impõe, as skills instruem

Versão em inglês: [0002-engine-enforces-skills-instruct.md](0002-engine-enforces-skills-instruct.md).

Status: aceito (2026-10-13)

## Contexto

Uma skill do Claude Code é Markdown que um modelo lê. Instruções em Markdown moldam o comportamento, mas não o garantem. O briefing exige que a segurança não dependa só de instruções em Markdown e que o núcleo continue independente de qualquer ambiente de agente.

## Decisão

Dividir o sistema em duas camadas:

1. Um motor com interface de linha de comando em JSON, dono de toda regra que código consegue verificar: validade do plano, transições de estado das tarefas, decisões de permissão, portões de aprovação, detecção de laços, registros de evidência e propriedade das sessões remotas.
2. Adaptadores para cada ambiente. Para o Claude Code, são skills que dizem ao modelo quando chamar o motor, um exportador que gera arquivos de subagentes a partir das specs de agentes e hooks de plugin que chamam o motor de dentro da sessão (acrescentados em 2026-10-13; ver Consequências).

O modelo raciocina e edita. O motor registra, decide o que é permitido e recusa transições inválidas com código de saída diferente de zero.

## Consequências

- O motor pode ser testado sem modelo, e o mesmo motor pode sustentar outro ambiente de agente mais tarde por meio de um novo adaptador.
- A imposição se limita às ações que passam pelo motor. Um modelo que edita um arquivo diretamente com suas próprias ferramentas contorna o portão de comandos do motor e pode reescrever o estado da execução, o arquivo de aprovações, o log de auditoria e o registro de execuções por usuário. O ADR 0006 diz o que decorre disso: o motor é uma proteção contra erros e um registrador, não uma fronteira de segurança.
- Os hooks reduzem a lacuna para comandos de shell. Um hook `PreToolUse` para a ferramenta Bash julga o comando sob a configuração fixada, o modo e o risco da execução ativa e responde `deny` ou `ask`; nunca responde `allow` e nunca lê o repositório de aprovações, então só pode apertar as permissões que o usuário já tem. A resposta da pessoa no prompt de permissão do Claude Code é o portão humano. Os hooks `SessionStart` (após compactação ou retomada) e `UserPromptSubmit` injetam o resumo, sanitizado e delimitado, da execução ativa.
- Os hooks só ficam em silêncio enquanto nenhuma execução é encontrada para o diretório, os diretórios que o contêm ou os caminhos que o comando cita. Quando uma execução é conhecida, estado ilegível, erro interno, entrada grande demais ou malformada e comando longo demais para análise viram `ask`. O texto anterior deste registro dizia que os hooks falham abertos em qualquer erro interno; isso foi substituído em 2026-10-13. Com Python anterior ao 3.10, `bin/wev` sai sem alarde nos subcomandos de hook e avisa no stderr, então o hook não verifica nada nesse caso. `wev exec` continua sendo o portão que falha fechado.
- Limites que permanecem: edições feitas com as ferramentas do próprio Claude (Edit, Write) não são vistas; no modo execute, `python3 script.py`, `make`, `mv`, `sed -i`, redirecionamentos e programas desconhecidos em caminho absoluto não passam por portão; um script que conduz um pseudoterminal não é visto pelo hook; os hooks têm testes unitários e de subprocesso, mas não foram exercitados dentro de uma sessão real do Claude Code.
- A delegação é centralizada. A sessão orquestradora pede um contrato de tarefa por vez e registra o resultado; o motor não deixa um agente iniciar outros agentes. O próprio Claude Code permite subagentes aninhados, então as skills enunciam a regra e o motor detecta ciclos de repasse.
- O que cada campo da spec de agente significa está no ADR 0003: alguns campos são impostos pelo motor, outros seguem como instruções no contrato da tarefa.

## Alternativas consideradas

- Só skills, sem motor: o mais simples de entregar, mas toda regra seria apenas uma recomendação.
- Um runtime de agente próprio que chama APIs de modelo: duplica o que o Claude Code já faz e exigiria acesso a provedor pago para testar.
