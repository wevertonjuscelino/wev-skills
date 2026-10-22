# Entrevista do objetivo

[English](intake.md).

`wev intake` registra a entrevista antes da execução. O agente pode extrair campos já
informados no pedido com `--source request` e perguntar somente pelos campos obrigatórios
faltantes. Cada `next` consome uma rodada e devolve no máximo três perguntas. O engine
exige objetivo (`goal`), evidências de conclusão (`done`), escopo e tipo de trabalho;
restrições são opcionais, e o resultado (`outcome`) também: o que deve acontecer depois
que o objetivo for atingido. Um pedido claro dispensa perguntas.

```sh
wev intake start --request 'Adicionar exportação CSV aos relatórios'
wev intake set ID --field goal --value 'Baixar relatórios como CSV' --source request
wev intake next ID
wev intake set ID --field done --value 'Download contém todas as linhas selecionadas' --value 'Testes passam'
wev intake set ID --field scope --value 'Somente relatórios'
wev intake set ID --field kind --value feature
wev intake finish ID
wev run start --from-intake ID
```

Substitua `ID` pelo identificador devolvido por `start`. `show ID` recupera a entrevista,
incluindo o briefing finalizado e o comando sugerido. `finish` recusa registros incompletos;
entrevistas finalizadas não podem ser editadas.

Configure `intake.max_rounds` em `wev.config.json` (padrão 3, inteiro de 1 a 10). Ao esgotar
as rodadas, `next` não devolve perguntas e lista `must_assume`. Não inventa respostas
silenciosamente: registre uma suposição conservadora com
`set --field CAMPO --source assumption`, opcionalmente incluindo `--value`, e informe-a
ao usuário. Valores ausentes recebem padrões conservadores. O briefing separa suposições
de respostas confirmadas.

Os registros ficam em `<state_dir>/intakes`, ignorados pelo Git, privados para o usuário
atual e gravados atomicamente sob bloqueio por registro. O texto é limpo e padrões
conhecidos de segredos são ocultados; isso não garante reconhecer todo segredo possível.

`run start --from-intake ID` exige entrevista finalizada e usa seu objetivo. Um
`--objective` explicitamente diferente é recusado. Operações preservam o sinal de efeito
externo e suposições estabelecem um mínimo de incógnitas. O briefing completo é copiado
para o estado da execução e o evento de auditoria `run.intake_attached`, e devolvido
ao chamador. Lembretes do plano carregam escopo, restrições, resultado e critérios de conclusão. O
resultado é contexto, não escopo: a skill `wev-orchestrate` manda o agente propor ao usuário
uma abordagem mais ampla quando ela servir melhor ao resultado, e nunca adotá-la sozinho.
Perto do limite de tamanho do lembrete, o resultado é o primeiro a sair. Um registro com
resultado não pode ser lido por versões anteriores; um registro sem ele não muda. A entrevista e
suas evidências descrevem intenção; verificações de execução e portões humanos continuam
aplicáveis.
