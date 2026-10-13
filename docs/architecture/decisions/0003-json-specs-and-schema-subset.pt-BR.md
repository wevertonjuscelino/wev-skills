# ADR 0003: Specs de agentes em JSON validadas por um subconjunto de JSON Schema

Versão em inglês: [0003-json-specs-and-schema-subset.md](0003-json-specs-and-schema-subset.md).

Status: aceito (2026-10-13)

## Contexto

Os agentes devem ser definidos por configuração, versionados e validados antes do uso. O motor não tem dependências de terceiros (ADR 0001), então não há parser de YAML nem biblioteca de JSON Schema.

## Decisão

- Specs de agentes, configuração, planos, estado de execução e tarefas de avaliação são documentos JSON com um campo `schema_version`.
- Os schemas ficam em `src/wev_skills/schemas/` e são JSON Schema válidos (draft 2020-12), restritos a um subconjunto documentado de palavras-chave.
- `wev_skills.schema` implementa esse subconjunto e rejeita um schema que use uma palavra-chave não suportada, de modo que um schema nunca seja "validado" ignorando parte dele em silêncio.

## Consequências

- Qualquer editor ou validador externo pode apontar para os mesmos arquivos de schema.
- JSON não tem comentários, então as specs de agentes têm um campo `description` e os guias explicam cada campo.
- Entrada em YAML é trabalho futuro. Seria um formato de entrada convertido para a mesma estrutura JSON, atrás de uma dependência opcional.

## Spec de agente para subagente do Claude Code

A spec do agente é a fonte da verdade. O adaptador do Claude Code a transforma num arquivo Markdown de subagente usando apenas campos de frontmatter que a documentação oficial lista (`name`, `description`, `tools`, `disallowedTools`, `model`, `skills`, `maxTurns`). Campos sem equivalente no Claude Code vão para o corpo do prompt de sistema do arquivo de subagente, e os mesmos valores seguem no contrato da tarefa. Quais deles o motor verifica é decidido campo a campo (verificado em `src/wev_skills/core/agent_rules.py` e nos seus chamadores em 2026-10-13):

- **Impostos pelo motor:** `required_checks` (somadas às verificações da tarefa), `budget.max_units` (orçamento por tarefa na guarda de execução), `max_attempts`, `timeout_seconds`, `permissions.may_mutate` (uma tarefa de um agente assim executa apenas comandos somente leitura), `permissions.modes`, `permissions.max_risk`, `permissions.may_use_remote` (os comandos remotos recusam um agente sem ele) e `permissions.ceiling` (descendentes podem restringir as permissões, nunca ampliá-las).
- **Levados apenas como instruções:** `stop_conditions`, `success_criteria`, `escalation` e `output_format`. O agente os recebe no contrato e nada no motor os verifica. O campo `escalation` do agente é, portanto, texto; o escalonamento do próprio motor para um nível de modelo mais alto é outro mecanismo, que dispara na metade das tentativas (arredondada para cima) ou diante de uma assinatura de erro repetida, e não lê esse campo.
