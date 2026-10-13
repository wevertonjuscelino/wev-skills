# Registro de pesquisa: "An Empirical Study of Harness Design for Coding Agents"

Versão em inglês: [harness-design-paper.md](harness-design-paper.md).
Consultado em: 2026-10-13. Este é um resumo para apoiar o projeto do wev-skills. Não substitui o artigo, e nenhum resultado abaixo é garantia para outro modelo, outro harness ou outro tipo de tarefa.

## 1. Dados bibliográficos e o que foi lido

- Título: An Empirical Study of Harness Design for Coding Agents.
- Autores: Run-Ze Fan, Zihao Zhang, Simin Ma, Yebowen Hu, Shouju Wang, Kaiqiang Song, Fei Liu, Hamed Zamani, Xiaoyang Wang. Afiliações na primeira página: UMass Amherst, Emory University, UNC Charlotte e uma terceira afiliação cujo nome se perdeu na extração do texto. O artigo marca três autores (Fan, Zhang, Wang) como tendo feito o trabalho durante estágios na Zoom Video Communications.
- Identificador: arXiv:2609.20804, versão v1, área cs.AI, enviado em 17 Sep 2026. A listagem do arXiv indica 43 páginas (página de resumo do arXiv, campo "Comments").
- Lido para este registro: a página de resumo, o texto extraído do PDF (texto principal, páginas 1 a 18, por inteiro) e partes do apêndice (Tabela 13 sobre uso de recall, início do Apêndice C). O Apêndice A (prompts), a maior parte do Apêndice B (descrições das ferramentas), o Apêndice C.2 (concordância entre o juiz LLM e anotadores humanos) e as demais figuras e tabelas do apêndice, exceto a Tabela 13, não foram lidos por inteiro. Qualquer afirmação abaixo que cite apenas uma tabela do apêndice não foi recalculada.
- O artigo é um preprint. Nada neste registro foi conferido com revisão por pares, código publicado ou dados publicados.

## 2. Configuração experimental

**Harness.** Um harness leve escrito pelos autores, com laço ReAct (Seção 2, Figura 2). O laço de execução é fixo. Três componentes variam: planning (Seção 2.1), action space (Seção 2.2) e context management (Seção 2.3). Ficam fixos em todas as ablações (Seção 2.4): workspace guard (resolução de caminhos, rejeição de fuga por symlink), verificação de leitura antes de escrita, uma camada de permissões (allow, ask, deny), diagnósticos pós-edição para arquivos Python (ruff, pyflakes ou um fallback só de sintaxe) e detecção de travamento (stuck detection).

**Modelos (Seção 3.1).** Nemotron-3 em 30B, 120B e 550B (um eixo de capacidade dentro da mesma família) e Mistral-Medium-3.5-128B (outra família). Servidos localmente com SGLang em BF16. Preços de token usados no custo, por 1M de tokens de entrada/saída (OpenRouter, acessado em agosto de 2026): US$ 0,05/0,20, 0,08/0,45, 0,50/2,20 e 1,50/7,50, respectivamente. O custo do artigo, portanto, é calculado a partir da contagem de tokens e desses preços.

**Benchmarks (Seção 3.1).** SWE-Bench Verified (500 issues reais do GitHub verificadas por humanos; a seção Limitations afirma que é somente Python) e Terminal-Bench 2.1 (89 tarefas de linha de comando). Métricas: taxa de sucesso por tarefa (SR) e custo médio por tarefa. A análise de trajetória usa um juiz LLM que rotula cada turno com uma fase do fluxo de trabalho (Seção 4; a concordância com humanos está no Apêndice C.2, não lido).

**Parâmetros de execução (Seção 3.1).** Temperatura 0, top-p 0,95, saída limitada a 16.384 tokens por turno. Construído sobre LangGraph, com os benchmarks conduzidos pelo Harbor. No máximo 300 passos por tarefa. Resultados de ferramentas truncados em 24 mil caracteres; até oito ferramentas somente leitura em paralelo por passo. Stuck detection: lembrete após cinco chamadas idênticas consecutivas ou cinco chamadas idênticas com falha consecutivas, encerramento após oito chamadas idênticas com falha consecutivas.

**Os três componentes variados.**

| Componente | Variantes | Fonte |
|---|---|---|
| Planning | ligado (um plano persistente que o modelo mantém com `update_plan`, injetado a cada turno) ou desligado | Seção 2.1 |
| Action space | ferramentas predefinidas (`read_file`, `write_file`, `edit_file`, `list_files`, `glob_files`, `grep_text`, `web_fetch`, `bash`) ou somente bash | Seção 2.2, Tabela 1 |
| Context management | cinco níveis (tiers), abaixo | Seção 2.3, Tabela 2 |

**Níveis de contexto.** Três mecanismos: M1 elision (trocar o corpo de uma observação antiga de ferramenta por um stub), M2 recall (guardar os originais elididos fora do contexto e expor `recall_event(id)`), M3 summarization (uma chamada separada, sem ferramentas, ao mesmo modelo, que resume turnos antigos em um resumo contínuo).

| Tier | M1 | M2 | M3 | Comportamento |
|---|---|---|---|---|
| T0 | não | não | não | Sem compactação; a execução termina com erro quando a janela estoura |
| T1 | sim | não | não | Só elision, originais descartados; age no limite rígido |
| T2 | sim | sim | não | Elision mais recall |
| T3 | não | não | sim | Só summarization; age no limite rígido |
| T4 | sim | sim | sim | Em estágios: elision no limite suave B1, summarization no limite rígido B2 (Algoritmo 1) |

Os limites são 0,6 (suave) e 0,85 (rígido) da janela utilizável. O prompt de sistema, a descrição da tarefa e uma janela recente (orçamento de 0,3 da janela, no mínimo dois turnos) ficam literais; só a região do meio é compactada (Seção 3.1, Algoritmo 1).

**Desenho e estatística.** Janelas de contexto de 32k, 64k, 96k e 128k tokens. T0 a T4 em cada janela dão 20 configurações por par modelo-benchmark. Planning desligado e somente-bash rodam uma vez cada, apenas em T4/128k. São 22 configurações por par e 4 x 2 x 22 = 176 no total (Seção 3.1). Cada configuração roda cada tarefa uma vez. As comparações são pareadas por tarefa: testes exatos de McNemar bilaterais, com controle da taxa de falsas descobertas de Benjamini-Hochberg em 0,05, dentro de três famílias (tier gerenciado vs T0, planning ligado vs desligado, ferramentas completas vs somente bash). Um asterisco nas Tabelas 3 e 4 marca diferença significativa em relação à referência pareada.

**"%" versus pontos percentuais.** O artigo escreve "%" em várias diferenças de taxa de sucesso na Seção 3.2 (por exemplo "raises success by 15.0%"). As tabelas mostram que são diferenças absolutas: para o Nemotron-3 30B no SWE-Bench, 25,20 menos 10,20 dá 15,0; para o 120B, 44,0 menos 42,4 dá 1,6; para o 550B, 69,4 menos 65,8 dá 3,6; para o Mistral, 68,6 menos 45,4 dá 23,2 (Tabela 3). Neste registro esses valores são pontos percentuais. Variações de custo citadas como "%" (por exemplo 53% menos custo) são variações relativas.

## 3. Resultados

### 3.1 Context management

- O valor cresce quando a janela aperta. A diferença de taxa de sucesso entre os tiers gerenciados (T1 a T4) e T0, na média dos modelos, cai de 35,7 para 15,9, 5,5 e 2,7 pontos no SWE-Bench e de 9,5 para 7,5, 4,8 e 2,8 no Terminal-Bench, de 32k a 128k (Seção 3.2, Tabelas 3 e 4).
- O benefício acompanha o estouro de janela. A taxa média de estouro do T0 cai de 78,7% para 8,7% (SWE-Bench) e de 61,0% para 12,1% (Terminal-Bench) nas mesmas janelas; os tiers gerenciados têm zero falhas por estouro em todas as janelas (Seção 3.2, Figura 3).
- Em estágios é o mais eficiente em custo. O T4 alcança taxas de sucesso "comparáveis" às de T1-T3 (o artigo não traz testes de significância entre tiers gerenciados; os asteriscos comparam cada tier com T0), com o menor custo em sete dos oito painéis modelo-benchmark (Figura 4), a menor razão média de pico de contexto nas quatro janelas (Figura 5a), menos chamadas de M3 que o T3 em média em toda janela (Figura 5b) e o menor custo médio em toda janela (Figura 5c). Os autores atribuem isso ao fato de a elision antecipada resolver muitos casos antes de a summarization ser necessária (Seção 3.2).
- Recall não melhora a acurácia. Em 32 comparações modelo-benchmark-janela, T2 supera T1 em 15, perde em 14 e empata em 3; a diferença média com pesos iguais é -0,36 ponto (+0,40 no SWE-Bench, -1,12 no Terminal-Bench). Entre as 64 configurações T2 e T4, 36 (56,3%) nunca chamam `recall_event`. As chamadas médias por tarefa caem de 0,540 em 32k para 0,069, 0,011 e 0,007 em 64k, 96k e 128k. As 16 configurações de planning e action space não registram chamadas. O uso se concentra no Nemotron-3 30B; o caso mais intenso (30B, Terminal-Bench, 32k, T2) tem em média 4,326 chamadas por tarefa e fica 3,37 pontos abaixo do T1 (Seção 3.2, Tabela 13).
- Ressalva sobre o T4. O T4 inclui recall (T2 mais summarization). Não existe tier que combine elision e summarization sem recall, então o artigo não consegue separar o efeito do escalonamento do efeito do recall dentro do T4.
- Trajetórias. Em 32k, as execuções T0 têm medianas de 20 a 30 turnos e terminam em geral durante a localização; os tiers gerenciados têm medianas de cerca de 50 a 180 turnos. Em 128k os tiers diferem pouco em número de re-patches e na fração de execuções que terminam sem edição (menos de quatro pontos para três dos quatro modelos) (Seção 4).

### 3.2 Planning

Medido em T4/128k com o conjunto completo de ferramentas (Seção 3.2, Figura 6, Tabelas 3 a 5).

| Modelo | SR no SWE-Bench com plano vs sem plano | Efeito do planning no custo |
|---|---|---|
| Nemotron-3 30B | 25,2 vs 13,6 (+11,6 pontos, marcado como significativo) | Maior nos dois benchmarks; no Terminal-Bench +75% (Seção 4) |
| Nemotron-3 120B | 44,0 vs 46,6 (sem ganho consistente) | Maior no SWE-Bench, menor no Terminal-Bench (cerca de -26%, Seção 4) |
| Nemotron-3 550B | 65,8 vs 67,8 (-2,0 pontos) | Cerca de -30% no SWE-Bench |
| Mistral-Medium-3.5-128B | 68,6 vs 69,0 (-0,4 ponto) | Cerca de -32% no SWE-Bench; cerca de -40% no Terminal-Bench (Seção 4) |

- No Terminal-Bench o ganho do 30B é de +4,5 pontos (13,48 vs 8,99). Apenas o contraste de planning do 30B no SWE-Bench tem asterisco nas Tabelas 3 e 4.
- Mecanismo (Seção 4, Tabela 6, Figura 8). Sem planning, a trajetória mediana do 30B no SWE-Bench cai de 40 para 5 turnos, e 68,6% das execuções terminam sem edição (27,8% com planning). Para o 550B e o Mistral, o planning encurta a mediana no SWE-Bench (108 para 74 e 68 para 53 turnos), sobretudo removendo turnos de verificação pós-edição, com pouca mudança nas execuções que nunca editam.
- Resumo do próprio artigo: o planning passa de andaime de acurácia para modelos mais fracos a economia de custo para modelos mais fortes, e seu valor em capacidade intermediária "remains task-type-dependent". O planning estudado é um mecanismo único de prompt e ferramenta (Seção 2.1), não planejamento em geral.

### 3.3 Interface de ferramentas

Medido em T4/128k com planning ligado (Seção 3.2, Figura 7, Tabelas 3, 4, 7). As diferenças são ferramentas completas menos somente-bash, salvo indicação.

- Nemotron-3 30B: ferramentas completas melhores em 15,0 pontos (SWE-Bench) e 10,1 pontos (Terminal-Bench), ambas marcadas como significativas. No Terminal-Bench, 66% das trajetórias somente-bash terminam após emitir chamadas a ferramentas que não existem naquele registro, e o tamanho médio cai de 71 para 15 turnos.
- Nemotron-3 120B: ferramentas completas melhores em 1,6 e 4,5 pontos, sem marca de significância; execuções médias encurtam de 101 para 77 turnos (SWE-Bench) e de 96 para 70 (Terminal-Bench).
- Nemotron-3 550B: somente-bash melhor em 3,6 pontos no SWE-Bench (marcado como significativo) e 5,6 no Terminal-Bench (sem marca), com custo 53% e 30% menor e 32% e 24% menos chamadas.
- Mistral-Medium-3.5-128B: ferramentas completas melhores em 23,2 pontos no SWE-Bench (marcado como significativo); somente-bash melhor em 6,7 no Terminal-Bench (sem marca). Com todas as ferramentas, 71,9% das ações de workspace dele no Terminal-Bench passam pelo bash, contra 40,4% no SWE-Bench. 32,8% das execuções somente-bash dele no SWE-Bench terminam sem edição, contra 1,2% com ferramentas completas (Tabela 12).
- Granularidade (Seção 4, Tabela 7): somente-bash reduz os re-patches médios por tarefa nos quatro modelos (por exemplo 3,3 para 0,4 no 30B) e desloca as escritas de arquivo do Terminal-Bench para criar-ou-substituir (por exemplo 28% para 64% no 30B).
- A intervenção é agrupada (ferramentas, prompts, rastreio de estado de arquivos, diagnósticos pós-edição), então não isola número de ferramentas nem granularidade (Seção 2.2, Limitations).

## 4. Custo e tamanho de trajetória

- Context management alonga as trajetórias sem mudar muito a proporção das fases (Seção 4). O custo depende do tier: o T4 tem o menor custo médio em toda janela (Figura 5c).
- Planning muda onde as trajetórias terminam (Seção 4): estende execuções que terminariam cedo (30B) e corta verificação pós-edição e caudas longas (550B, Mistral e 120B no Terminal-Bench). O custo acompanha o tamanho da trajetória (a Tabela 5 dá as variações percentuais em turnos, chamadas de ferramenta e tokens de entrada).
- Somente-bash encurta trajetórias de modelos capazes (por exemplo 550B no Terminal-Bench, mediana de 47 para 31 ações, Seção 4) e eleva a parcela de ações que escrevem código de 16% para 27%.
- Os custos são calculados a partir da contagem de tokens a preços fixos, não de gasto faturado (Seção 3.1).

## 5. Limitações declaradas pelos autores (seção Limitations)

1. Os resultados descrevem os componentes específicos como implementados: um prompt e mecanismo de atualização de planning, uma política de contexto baseada em limites com parâmetros fixos e uma mudança de action space agrupada.
2. Planning e action space são ablados somente em T4/128k; seria preciso um desenho fatorial completo para saber se os efeitos persistem em outras combinações.
3. Uma execução por tarefa por configuração; o Terminal-Bench tem apenas 89 tarefas, então muitos contrastes ali não são significativos, e as conclusões se apoiam na direção consistente entre modelos e janelas.
4. A validade externa é limitada pelos modelos (três tamanhos do Nemotron-3 e um modelo Mistral) e pelas tarefas; o SWE-Bench Verified é somente Python. O tamanho do modelo é um proxy imperfeito de capacidade. Os pontos de cruzamento devem ser validados antes de serem transferidos a outras famílias de modelos, outros harnesses ou tarefas fora de engenharia de software.

## 6. O que o artigo não afirma

- Não afirma haver um harness universalmente ótimo (Limitations).
- Não avalia modelos Claude, delegação multiagente, revisão independente, fluxos de aprovação, execução remota, políticas de permissão, stuck detection nem diagnósticos pós-edição como variáveis; foram mantidos fixos ou ausentes.
- Não testa valores de limite além de 0,6 e 0,85, nem outro desenho de recall além de `recall_event(id)`.
- Não traz testes de significância entre os tiers de contexto gerenciados, nem separa escalonamento de recall dentro do T4.
- Não mostra que planning ajuda ou atrapalha em tarefas classificadas por dificuldade; varia o modelo, não a trivialidade da tarefa.
- Não traz evidência de outras linguagens além de Python nem de tarefas fora de engenharia de software.
- Não apresenta os resultados como garantias; os autores chamam o desenho de harness de "a conditional systems problem" (Conclusão).
