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
