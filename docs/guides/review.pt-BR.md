# Revisão em camadas

[English](review.md).

A revisão em camadas é uma verificação opcional entre "as verificações da tarefa passam" e `run finish`. Vários agentes somente leitura (localizadores) procuram defeitos no que a execução mudou, outros agentes (verificadores) votam em cada candidato, e `run finish` se recusa a encerrar uma execução que ainda tenha um achado Important aberto. Vem desligada (`review.depth: off`).

Situação de cada parte (os rótulos seguem [o glossário](../glossary.md)):

| Parte | Rótulo |
|---|---|
| Formato do `REVIEW.md`, achados, votação, rodadas, teto de rodadas, comandos `review`, porta do `run finish`, estatísticas, regras de plano e de PR | implementado e testado, com agentes falsos (sem modelo, sem rede) |
| Uma rodada real com localizadores e verificadores `claude -p` | implementado mas não testado até o responsável rodar |
| Uma nota real do revisor nos casos de revisão (`specialists score`, `--compare`) | implementado mas não testado até o responsável rodar |
| Limitar ao workspace as leituras de arquivo dos localizadores | apenas documentado (próximo passo; veja "Limites") |

## Ligue

Em `wev.config.json` (as chaves estão em [configuração e provedores](configuration-and-providers.pt-BR.md), seção `review`):

```json
{ "review": { "agent": "wev-reviewer", "depth": "standard" } }
```

`agent` é obrigatório quando `depth` não é `off`. Predefinições de profundidade, localizadores / verificadores / quórum: `quick` 1/1/1, `standard` 3/3/2, `deep` 5/5/3. Uma execução de risco alto usa pelo menos `standard` quando a revisão está ligada; `off` continua desligado seja qual for o risco. A configuração é fixada por `run start`, como as demais chaves.

Com a revisão ligada, `run start` também registra uma árvore-base: o HEAD mais as mudanças não commitadas e não rastreadas, gravada com um índice temporário e sem filtros nem drivers de atributos. É um objeto git inalcançável, então `git gc --prune` pode apagá-lo. Uma execução mais antiga que a janela de poda (duas semanas por padrão) com a revisão ligada falha fechada (`review_tree_failed`). Com `review.depth` desligado, o `run start` não grava árvore e a execução não registra base: a revisão desligada não muda nada para a execução, o relatório nem o `run finish`.

## Escreva o `REVIEW.md`

O `REVIEW.md` na raiz do repositório diz aos revisores o que é um defeito aqui. É conteúdo do repositório, então os revisores o tratam como texto não confiável. A ausência do arquivo significa os padrões. Valide com `wev review md check`. Os títulos de segundo nível reconhecidos (os nomes em inglês também valem) e mais nenhum:

```markdown
# Guia de revisão de <projeto>

## Como é uma falha

- Um texto voltado ao usuário fica fora dos arquivos de tradução.
- Uma regra que importa existe só em prosa, sem código nem teste que a imponha.

## Ignorar

- generated/*
- evals/reports/*

## Nits

max: 3

Aponte um nit só quando ele induziria o leitor ao erro.

## Importante

Um defeito em autenticação, pagamentos ou exclusão de dados, e um limite que rejeita entrada válida.
```

- `Como é uma falha` (`What failure looks like`): o que procurar.
- `Ignorar` (`Skip`): globs de caminho, um por item; os arquivos que casam não são revisados (a rodada informa quantos foram ignorados).
- `Nits`: `max: N` limita os achados Nit mantidos por rodada (0 a 50, padrão 3); o resto da seção é orientação.
- `Importante` (`Important`): o que conta como Important neste repositório.

O arquivo é lido até 20.000 caracteres; um título desconhecido ou um `max` inválido é recusado com o número da linha. O [REVIEW.md](../../REVIEW.md) deste repositório é um exemplo funcional.

## Rode uma rodada

```sh
bin/wev review run     # uma rodada sobre as mudanças da execução ativa
bin/wev review show    # a última rodada e os achados ainda abertos
bin/wev review stats   # ruído por profundidade, a partir de .wev/reviews.jsonl
```

Uma rodada inicia os localizadores e depois os verificadores como execuções `claude -p` sem supervisão, cada uma só com `Read`, `Glob` e `Grep`. Pode demorar muito, então inicie `review run` de um terminal ou em segundo plano, não numa chamada curta do Bash. Antes da primeira execução de agente ela imprime o número planejado de execuções e o teto `review.max_runs_per_round` (padrão 12); uma rodada acima do teto não roda nada (`review_over_cap`, saída 6). Nenhuma tarefa pode estar em andamento, e a execução precisa da árvore-base registrada.

- Cada achado recebe a etiqueta Important, Nit ou Pre-existing. Um achado permanece quando os votos dos verificadores atingem o quórum.
- O texto do modelo não é confiável: é redigido e cercado antes de ser guardado ou mostrado, e um achado que não pode ser lido é descartado.
- Uma rodada em que ninguém revisou de verdade falha (`review_incomplete`, ou `review_agent_failed` quando todos os localizadores terminaram sem resposta) em vez de relatar "nada a corrigir", e não registra rodada. Uma execução só conta como respondida quando a resposta é um objeto JSON com uma lista `findings` (localizadores) ou `votes` (verificadores); prosa, JSON malformado, chave ausente ou resposta longa demais contam como sem resposta.
- O prompt de um localizador ou de um verificador tem teto de 100.000 caracteres. Um maior é recusado antes de qualquer agente rodar (`review_diff_too_large`, saída 5, com o tamanho): divida o trabalho em execuções menores. O diff nunca é cortado em silêncio. Na pontuação, um caso de revisão cujo prompt passa do teto reprova aquela amostra com esse motivo e sem rodar agente (o caso precisa de um diff menor).
- No máximo `review.max_rounds` rodadas (padrão 3) por execução. As primeiras `review.full_rounds` (padrão 2) rodam todos os localizadores sobre a mudança inteira; as seguintes olham só o diff e se restringem ao que mudou desde a última rodada.
- Atingir o teto de rodadas dispara a guarda `review_rounds` (saída 6, visível em `wev guard check`). Uma pessoa a libera com `guard acknowledge`, o que permite mais uma rodada.

## Feche achados

```sh
bin/wev review resolve <achado> --as wrong|intentional|does-not-matter --reason "<palavras>"
bin/wev review dismiss <achado> --as wrong|intentional|does-not-matter --reason "<palavras>"
```

Um agente pode usar `resolve` num achado Nit ou Pre-existing. Um achado Important só se fecha com `review dismiss`, comando do operador humano: exige um terminal, mostra o achado e pede uma palavra digitada (o mesmo atrito de `approval grant`). Um agente que acha errado um achado Important para e pergunta a uma pessoa. Um achado que o motor vê corrigido numa rodada posterior é fechado como `fixed`. Os rótulos de desfecho são exatamente `wrong`, `intentional`, `does-not-matter` (e `fixed`, definido pelo motor). O `.wev/reviews.jsonl` guarda só ids, etiquetas, desfechos e contagens, nunca o texto dos achados; `review stats` lê esse arquivo.

## A porta do finish

Com a revisão ligada, `run finish` recusa:

| Código | Quando |
|---|---|
| `review_open_important` | um achado Important ainda está aberto |
| `review_stale` | não há rodada, ou o conteúdo da árvore de trabalho difere da árvore que a última rodada revisou (um commit que deixa os arquivos como estavam não torna a rodada desatualizada) |
| `reviewer_unscored` | o `REVIEW.md` ou a especificação do revisor mudou e nenhum registro de `specialists score --compare` para a árvore atual mostra o revisor mantendo a nota: nenhum caso perde uma aprovação (um empate vale) |
| `review_config_weakened` | a configuração de revisão resolvida de novo é mais baixa que a fixada |

Com a revisão desligada, `run finish` não faz trabalho de git para a revisão e não lê o `.wev/scores.jsonl`.

A desatualização é julgada pela árvore de conteúdo (uma árvore git escrita com um índice temporário), não pelo HEAD: commitar depois de uma revisão ou de uma comparação não muda nada; editar um arquivo muda. O registro da comparação guarda o `fingerprint` para o histórico, acrescenta a `tree` em que foi feito e traz `improves` (nenhum caso perde uma aprovação e o total sobe) e `not_lower` (nenhum caso perde uma aprovação). A porta recalcula `not_lower` a partir das contagens guardadas, então um sinalizador editado à mão não passa; as decisões de lição do `specialists score` continuam usando o `improves`, mais estrito. O responsável escolheu esta regra mais frouxa para mudanças no revisor para que uma edição neutra, como a correção de um erro de digitação no `REVIEW.md`, possa entrar; uma comparação empatada só vem do `specialists score --compare`, que só uma pessoa roda.

## Planos e corpo do pull request

Um plano para uma execução de risco médio ou alto precisa de `risk_notes` e `revert` (recusado com `plan_needs_revert`); o plano de uma tarefa que o motor sintetiza quando o planejamento é `never` está isento, e o corpo do PR diz "Not given.". `wev run report --format pr` imprime Summary, What was tested, Risk (nível, motivos, notas), How to revert e Review. A seção Review diz "Não revisado" quando nenhuma rodada rodou (também com a revisão desligada), diz que a revisão está desatualizada quando a árvore mudou depois da última rodada, e diz "Nada a corrigir" só para uma rodada atual sem nada aberto.

## Casos de revisão e nota do revisor

Os casos de revisão ficam junto dos outros em `evals/cases/` com `kind: review`, um `head_commit`, uma lista `expect` de arquivos e faixas de linhas (vazia para uma mudança limpa) e um `change.diff` guardado; os ids de commit precisam ser hexadecimais. `wev cases validate --at-base` regenera o diff. Este repositório traz 3 casos com defeito e 2 limpos para o `wev-reviewer`.

```sh
bin/wev specialists score wev-reviewer             # só pessoa; pontua os casos de revisão na profundidade fixada
bin/wev specialists score wev-reviewer --compare <rev>   # só pessoa; o revisor em <rev> contra a árvore de trabalho
```

`--compare` vale só para `review.agent` e registra a revisão resolvida; `run finish` lê esse registro para `reviewer_unscored`. Os dois gastam tokens e são só de pessoa: o Claude Code pergunta, os outros harnesses negam, um agente nunca os roda.

## Atualização

As revisões de tarefa (`task review`) registradas antes desta mudança não trazem impressão digital da árvore e deixam de contar como aceitas. Uma execução em andamento que exige revisão independente precisa ter as tarefas revisadas de novo depois da atualização.

## Limites

- A revisão é uma proteção para um agente falível, não uma fronteira contra um adversário. As ferramentas de arquivo do agente ainda podem editar o estado da execução, os achados e o `.wev/reviews.jsonl` (veja [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md)).
- `Read`, `Glob` e `Grep` são concedidos sem restrição de caminho, então um localizador pode ler arquivos fora do repositório, como as execuções sem supervisão da pontuação; o texto dos achados é redigido antes de ser guardado. Limitar as leituras ao workspace é um próximo passo.
- Uma execução iniciada com `--config` explícito pode editar o `wev.config.json` do repositório para baixar a revisão nas execuções seguintes que não passam `--config`. Só quem revisa o PR enxerga isso.
- Uma escrita em `.wev/reviews.jsonl` que falha depois de uma rodada ou de um fechamento já gravado é avisada como alerta, não como falha: a execução guarda a verdade, só as estatísticas ficam sem uma linha.
- O `.wev/scores.jsonl` é um arquivo local que o agente também pode editar: uma linha acrescentada com números compatíveis passa pelo `reviewer_unscored`. Veja [SECURITY.pt-BR.md](../../SECURITY.pt-BR.md).
- Os veredictos do modelo são sinais, não prova: um voto que concorda não é um achado correto. Confira os achados de pouca concordância.
