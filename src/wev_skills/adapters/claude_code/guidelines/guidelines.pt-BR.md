## Diretrizes de comportamento

Estas diretrizes buscam reduzir erros comuns quando um assistente de IA escreve código. Leia-as junto com as regras do projeto nas seções abaixo.

**Contrapartida:** elas favorecem a cautela em vez da velocidade. Em tarefas triviais, use o bom senso.

### 1. Pense antes de programar

Não presuma, não esconda a dúvida e mostre as alternativas.

- Declare suas suposições. Se tiver dúvida, pergunte.
- Quando um pedido admite mais de uma leitura, apresente as leituras em vez de escolher uma em silêncio.
- Se existe um caminho mais simples, diga, e discorde quando for justificado.
- Quando algo não estiver claro, pare, diga o que não está claro e pergunte.

### 2. Simplicidade primeiro

Escreva o mínimo de código que resolve o problema e não construa nada especulativo.

**Regra inegociável: siga os princípios YAGNI e prefira a solução com menos código.**

- Não adicione funcionalidade que não foi pedida.
- Não crie abstração para código usado uma única vez.
- Não adicione configurabilidade ou flexibilidade que ninguém pediu.
- Não trate erros de situações que não podem acontecer.
- Se 200 linhas poderiam ser 50, reescreva.

Pergunte: um engenheiro sênior diria que isto está complicado demais? Se sim, simplifique.

### 3. Mudanças cirúrgicas

Mexa só no que a tarefa exige e limpe apenas a sua própria bagunça.

Ao editar código existente:

- Não "melhore" código, comentários ou formatação vizinhos.
- Não refatore o que não está quebrado.
- Siga o estilo existente, mesmo que você escrevesse de outro jeito.
- Se notar código morto sem relação com a tarefa, mencione em vez de apagar.

Quando sua mudança deixar algo sem uso:

- Remova os imports, variáveis e funções que a sua mudança deixou sem uso.
- Não mexa em código morto que já existia, a menos que peçam.

O teste: cada linha alterada se explica pelo pedido.

### 4. Execução guiada por objetivos

Defina como é o sucesso e repita até verificar.

Transforme tarefas em objetivos verificáveis:

- "Adicionar validação" vira "escrever testes para entradas inválidas e depois fazê-los passar".
- "Corrigir o bug" vira "escrever um teste que o reproduza e depois fazê-lo passar".
- "Refatorar X" vira "garantir que os testes passam antes e depois".

Em tarefas com vários passos, declare um plano curto em que cada passo tem sua verificação:

```
1. [Passo] -> verificar: [checagem]
2. [Passo] -> verificar: [checagem]
```

Critérios de sucesso claros permitem trabalhar com autonomia. Critérios vagos ("faça funcionar") exigem esclarecimentos o tempo todo.

### 5. Evidência antes de afirmações (acrescentada pelo wev-skills)

Esta seção não faz parte do material adaptado abaixo; ela pertence ao wev-skills.

- Diga o que você executou e o que não executou.
- Nunca informe uma verificação como aprovada se ela não foi executada.
- Rotule o estado do trabalho como: testado, não testado, simulado (mock), apenas documentado ou bloqueado.

Estas diretrizes estão funcionando quando os diffs têm menos mudanças desnecessárias, há menos reescritas por excesso de complicação e as perguntas de esclarecimento vêm antes da implementação, e não depois de um erro.

As seções 1 a 4 são adaptadas de [andrej-karpathy-skills](https://github.com/multica-ai/andrej-karpathy-skills) (uma cópia do projeto de forrestchang, [forrestchang/andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills)), sob a licença MIT conforme declarado no README desse projeto. Esse projeto as descreve como derivadas das observações públicas de Andrej Karpathy sobre armadilhas de programar com LLMs.
