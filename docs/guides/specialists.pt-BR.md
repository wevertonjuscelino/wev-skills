# Especialistas do projeto e orçamento do motor

[English](specialists.md).

Crie um especialista do projeto a partir de um papel resolvido do catálogo:

```sh
bin/wev specialists create project-engineer --template senior-engineer --specialty implementation
bin/wev specialists list
bin/wev specialists export --lang pt-BR
```

As especificações ficam em `wev-specialists/` por padrão (`agents.project_dir`). O
roteamento e os comandos `wev agent` descobrem esses arquivos automaticamente. As
exportações ficam em `.claude/agents/`. A criação preserva ferramentas, limites de
permissão, política de modelo e verificações do papel original. O projeto pode manter até
`specialists.max_per_project` especialistas (cinco por padrão). A criação nunca substitui
identificadores existentes. Diretórios e arquivos de especialistas não podem ser links
simbólicos.

Depois de executar e verificar trabalho atribuído ao especialista, reconstrua suas
observações:

```sh
bin/wev specialists learn project-engineer
bin/wev specialists export --lang pt-BR
```

O aprendizado só propõe. Uma lição nova fica com status `proposed` e não aparece em lugar
nenhum até a pessoa no terminal aceitá-la; uma lição que o motor aceitou antes desta etapa
existir (`accepted_by` igual a `engine`) volta a ser proposta e não aparece mesmo antes de o
aprendizado rodar de novo. O operador revisa as lições em
`wev specialists list` e decide cada uma:

```sh
bin/wev specialists accept project-engineer lesson-0123456789abcdef01234567
bin/wev specialists retire project-engineer lesson-0123456789abcdef01234567
```

Os dois são comandos do operador humano, como `approval grant`: exigem terminal em stdin e
stdout, mostram a lição, seu texto completo, seus trechos de autoria e nota e sua evidência,
pedem uma palavra exibida na tela e registram o usuário do sistema operacional em
`accepted_by` e o usuário e o terminal no log de auditoria. O evento de auditoria é gravado
antes do arquivo do especialista, então uma auditoria que falha não deixa decisão. Se a lição
mudou depois de exibida, nada é decidido (saída 5) e o comando precisa ser rodado de novo. O
nome de usuário `engine` é reservado e recusado. Um agente nunca os executa; o hook de Bash
do plugin responde `ask` para eles. Aceite e aposentadoria sobrevivem ao reaprendizado, e
quando há mais lições do que o limite permite, as propostas saem antes das lições decididas;
os contadores continuam sendo recalculados.

O aprendizado recalcula os contadores a partir das execuções armazenadas pelo motor;
repetir o comando não acrescenta confirmações. Uma verificação bem-sucedida contribui
somente quando a tarefa está verificada e o registro indica `all_met`. Verificações que
falharam contam como contradições; ocorrências de guardas viram armadilhas. Verificações
triviais, execuções de referência, texto de revisão e notas do modelo não viram lições.
Assinaturas identificam comandos registrados sem transformar seu texto em instruções.
Cada lição aponta para a execução, tarefa e data do registro mais recente que a sustenta.

No máximo 30 lições são armazenadas, inclusive em chamadas diretas à função de
aprendizado. Lições ativas precedem as antigas; depois vêm confirmações e contradições.
Lições não observadas por `specialists.stale_after_runs` execuções (20 por padrão) ficam
antigas. Até `specialists.max_lessons_rendered` lições ativas aparecem nas exportações e
contratos (12 por padrão), também com limite de caracteres. A experiência é consultiva e
não amplia ferramentas ou permissões. A reconstrução usa o histórico local preservado;
apagá-lo também remove sua contribuição aos contadores. Os arquivos seguem o limite de
confiança do estado local do motor: o aprendizado não autentica estados fornecidos de
fora ou modificados manualmente.

`task start` registra os ids das lições que o contrato dela mostra como um evento
`lessons.shown` no `events.jsonl` do run (eles também aparecem como `lessons_shown` no
evento de auditoria `task.started`). Eles ficam fora do `state.json`, para que um run continue
podendo ser retomado pela versão 2.0.0, que recusa ali campos que não conhece; runs gravados
pela 3.0.0 guardam os ids no campo `lessons_shown` da tarefa, que continua sendo lido e
contado. Antes de
gravar, o início lê de novo o arquivo do especialista sob o lock que `specialists accept` e
`specialists retire` usam; se o arquivo sumiu ou as lições mudaram desde que o comando as
carregou, o início é recusado (`lessons_changed`, saída 5) e precisa ser rodado de novo. Todo
início gravado escreve um evento, mesmo sem lições, com o agente e a tentativa, e só depois
de o estado ser gravado: todo registro é um início que aconteceu. Se o evento não puder ser
escrito, o início vale, não é contado e é auditado como `lessons.shown_failed`; o desenho
prefere perder uso a creditar uma lição que nunca foi mostrada. Pelo mesmo motivo os
registros que a 4.0.0 gravou (antes do commit, sem agente) não são contados. O aprendizado
conta só os registros do agente que terminou a tarefa e, depois de uma reabertura, só o
último ciclo de inícios; ids que um run da 3.0.0 guardou na tarefa só contam enquanto nenhum
registro mostrar outro agente ou um novo ciclo. Uma linha do `events.jsonl` cortada no meio
é ignorada, e o aprendizado lê os eventos apenas dos runs deste repositório. Uma decisão tomada depois
do início vale a partir do próximo início. O aprendizado então conta,
por lição, as tarefas do agente que a receberam e terminaram verificadas (`shown_verified`)
ou com falha, bloqueio ou resultado parcial (`shown_unverified`); tarefas não terminadas não
entram em nenhum dos dois.

A ordenação usa esses contadores de forma conservadora, contra a média do próprio agente: a
fração de tarefas verificadas entre todos os términos das suas lições ativas, recalculada a
cada aprendizado, de modo que a régua acompanha o agente quando ele melhora ou piora. A
fração de cada lição é puxada para essa média por três tarefas virtuais, então uma lição com
poucos términos fica perto dela. Uma lição com pelo menos três términos cuja fração ajustada
fique mais de 0,1 abaixo da média vai para depois das outras. A taxa nunca promove, esconde
ou aposenta uma lição: a rebaixada continua contando no limite exibido, mantém seus
contadores e volta à posição quando a fração se recupera. A correlação entre uma lição e um
resultado não é evidência de que a lição o causou.

No contrato de uma tarefa, uma lição aprendida com um check que a tarefa vai rodar (mesmo
argv) vem antes das demais, depois do rebaixamento acima; a relevância nunca esconde uma
lição nem levanta uma rebaixada. Subagentes exportados não têm tarefa e mantêm a ordem
simples.

O orçamento da execução usa unidades de comandos do motor, **não dinheiro ou tokens**:
`limits.run_budget_units` vale 400 por padrão; `limits.run_max_attempts_total` permite 12
inícios de tarefas. Execução local, verificações, verificações de referência e inícios
remotos registrados consomem uma unidade cada. Comandos fora de uma execução ativa ficam
fora dessa contagem. As respostas avisam ao atingir 80% de qualquer limite; em 100% das
unidades de comandos o motor recusa novo trabalho. O teto de inícios recusa novos inícios,
permitindo concluir a última tarefa admitida. Reiniciar guardas ou reabrir tarefas por
operação humana não apaga o consumo da execução inteira.

As operações de execução compartilham um bloqueio por execução. Lotes são comparados
com o orçamento restante antes de rodar, considerando seu número máximo de comandos.
Assim, um lote que possa exceder o orçamento é recusado antecipadamente. Um processo
remoto já iniciado pode continuar quando o teto é atingido; esse orçamento não encerra
processos. Os limites e guardas existentes por tarefa continuam aplicáveis.

O aprendizado utiliza apenas execuções cujo repositório registrado corresponde ao projeto
atual; estados sem identificação de repositório ou pertencentes a outro projeto são ignorados.

## Lições decididas pela nota

`wev specialists score <id>` pode decidir lições sem uma pessoa, rodando os casos guardados do [guia de avaliação](evaluation.pt-BR.md) com e sem uma lição candidata. Status: implementado e testado com falsos; o caminho real de `claude -p` está implementado mas não testado até o dono rodá-lo. O comando é só humano (o Claude Code pergunta, os outros harnesses negam, um agente nunca o executa) porque gasta tokens. Com `specialists.score_on_finish` verdadeiro, `run finish` inicia as mesmas execuções sem assistência sem esse portão, e por isso a chave vem desligada. Uma execução da nota pode demorar muito mais do que uma chamada Bash de um agente permite (a ferramenta Bash do Claude Code interrompe um comando após 2 minutos por padrão, 10 no máximo), então rode-a, e o `run finish` com `score_on_finish`, em um terminal ou em segundo plano; uma execução interrompida deixa tokens gastos e um diretório temporário `wev-scoring-*` para trás. Antes da primeira execução de agente ela imprime em stderr o número de execuções previstas e o limite.

- Uma lição entra como `active` com `accepted_by` `score` (valor reservado como `engine`) somente quando nenhum caso perde um passe e o total sobe. Empate fica `proposed`. A ablação aposenta uma lição ativa aceita por nota pela mesma regra. Cada decisão grava um evento de auditoria (`specialists.auto_accept` ou `specialists.auto_retire`) antes do arquivo do especialista.
- A aceitação ou aposentadoria de uma pessoa é final diante da nota. Uma lição que a nota aposentou volta como `proposed` no próximo `specialists learn`.
- Além das lições aprendidas dos registros do motor, a nota pode pedir ao modelo no máximo `specialists.score_max_new_lessons` lições por execução, escritas só a partir de casos que falharam. A resposta é texto não confiável: é filtrada (tamanho, caracteres de controle e invisíveis, quebras de linha, imitações da cerca, uma lista fixa em inglês de termos proibidos, a varredura de texto não confiável) e mostrada só dentro da cerca de dados não confiáveis, sob uma linha fixa dizendo que foi escrita pelo modelo e aceita por nota. O filtro descarta algumas lições legítimas em inglês. Uma lição de modelo que perde ou empata não é guardada.
- Variantes cuja lição candidata não é exibida (acima de `max_lessons_rendered`) são puladas, e o trabalho acima de `score_max_runs` é adiado. `score_on_finish` pontua no `run finish`.
- Os controles são proteções contra um agente falível, não uma fronteira contra um adversário; veja [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md), "Execução não assistida da nota", e seus limites conhecidos.
