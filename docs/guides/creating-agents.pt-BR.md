# Criando agentes

Versão em inglês: [creating-agents.md](creating-agents.md).

Um agente no wev-skills é dado, não código. Cada agente é um arquivo JSON versionado, validado contra um schema. Uma nova persona exige um novo arquivo e nunca uma mudança no código-fonte. O motor valida as specs, resolve a herança, impõe alguns dos campos abaixo (e só esses; a próxima seção diz quais) e exporta as specs como arquivos de subagentes do Claude Code. A skill `wev-agent-builder` guia o Claude Code pelos mesmos passos.

Status: carga de specs, validação, herança, teto de permissões e exportação estão implementados e testados (implemented and tested). Os arquivos de subagentes exportados não foram carregados por uma sessão real do Claude Code. Um agente exportado não roda sozinho: a sessão orquestradora delega a ele (veja o [guia de orquestração](orchestration.pt-BR.md)). O motor nunca deixa um agente iniciar outro.

Neste guia, `wev` significa `"$WEV_HOME/bin/wev"` (veja o [guia de instalação](installation.pt-BR.md)). As saídas são reais, de um diretório temporário, e estão abreviadas onde indicado.

## A spec

Fonte da verdade: `src/wev_skills/schemas/agent.schema.json`. Chaves desconhecidas são rejeitadas. Os campos que guardam texto (marcados "texto") aceitam uma string simples ou um objeto `{"en": "...", "pt-BR": "..."}`; `en` é obrigatório na forma de objeto e `pt-BR` é opcional.

| Campo | Obrigatório | Tipo e limites | Observações |
|---|---|---|---|
| `schema_version` | sim | o número `1` | |
| `id` | sim | letras minúsculas, dígitos e hifens simples, no máximo 64 | Vira o nome do subagente |
| `name` | sim | texto, no máximo 120 | |
| `description` | sim | texto, no máximo 1024 | O Claude Code a usa para decidir quando delegar, então diga o que o agente faz e quando |
| `specialties` | não | até 32 strings únicas de no máximo 64 | A regra de roteamento compara as palavras da tarefa primeiro com estas |
| `instructions` | não | texto, no máximo 20000 | O corpo do prompt de sistema do subagente |
| `responsibilities` | não | até 64 textos | |
| `extends` | não | um id de agente | Um único pai |
| `model` | não | um nível (`economy`, `standard`, `premium`) ou um id de modelo, no máximo 128 | Na exportação um nível vira `haiku`, `sonnet` ou `opus` |
| `model_policy` | não | `min_tier`, `max_tier`, `escalate_on_failure` | Os níveis que o roteador pode usar para este agente; `min_tier` não pode passar de `max_tier` |
| `tools` | não | `allow`, `deny`: até 64 nomes únicos de ferramentas cada | Nomes como `Read`, `Edit`, `Bash`, `Bash(git status:*)` |
| `skills` | não | até 32 nomes únicos de skills | Exportado como `skills` |
| `permissions` | não | `modes` (`plan`, `execute`), `max_risk` (`low`, `medium`, `high`), `may_mutate`, `may_use_remote`, `ceiling` | Veja abaixo |
| `budget` | não | `max_units` (pelo menos 1) | Exportado como `maxTurns` |
| `timeout_seconds` | não | pelo menos 1 | |
| `max_attempts` | não | inteiro de 1 a 100 | |
| `success_criteria`, `stop_conditions` | não | até 64 textos cada | |
| `escalation` | não | `on_failure` (`continue`, `change_strategy`, `reduce_scope`, `escalate`, `ask_human`, `stop`), `to` (um id de agente) | |
| `required_checks` | não | até 32 strings de comando de no máximo 512 | |
| `output_format` | não | texto, no máximo 20000 | |

A delegação não é um campo da spec. As instruções-base mandam os agentes não delegarem, e só a sessão orquestradora distribui contratos.

## O que o motor impõe e o que ele apenas carrega

Um campo de uma spec é de um de dois tipos, e a diferença importa na hora de decidir em que confiar.

| Imposto pelo motor | Como |
|---|---|
| `required_checks` | Entram nas verificações da tarefa e precisam passar; aparecem no contrato |
| `budget.max_units` | Vira o orçamento da tarefa na guarda de execução (sem ele, a tarefa não tem orçamento) |
| `max_attempts`, `timeout_seconds` | Vale o menor entre o valor do agente e o da execução, para as tarefas daquele agente |
| `permissions.may_mutate` | Um agente com `may_mutate: false` pode rodar por `wev exec` comandos de somente leitura, as verificações declaradas da própria tarefa e os comandos de verificação descobertos no repositório em `run start` (por exemplo `make test`, `make lint`), por correspondência exata do argv, porque rodar a suíte de testes é como um revisor verifica. Todo o resto é recusado com `agent_read_only`. Esses comandos ainda passam pela política, então um que exige aprovação continua exigindo. Em uma execução no modo execute o comando age por uma tarefa em andamento (`--task` precisa nomear uma tarefa em andamento, ou usa-se a única em andamento e a saída avisa), então isso não depende de quem chama nomear a tarefa; com duas tarefas em andamento, quem chama ainda escolhe qual, e o motor não sabe dizer qual agente está digitando |
| `permissions.modes`, `permissions.max_risk` | Uma tarefa fora deles não pode ser atribuída ao agente nem iniciada por ele |
| `permissions.may_use_remote` | `wev remote start` exige que o agente da tarefa o tenha |
| `permissions.ceiling` | Descendentes não podem ampliar as permissões de um ancestral (verificado quando as specs são carregadas) |

| Levados apenas como instruções | O que acontece |
|---|---|
| `stop_conditions`, `success_criteria`, `escalation`, `output_format` | Chegam ao agente no contrato da tarefa e no prompt exportado. Nada no motor verifica se foram seguidos. O escalonamento para um nível de modelo mais alto é decidido pelas regras de tentativas do próprio motor, não pelo `escalation` da spec |

`tools.allow` e `tools.deny` moldam o arquivo de subagente exportado e a lista de ferramentas do contrato. Quem os impõe é o Claude Code, quando o arquivo é carregado lá, não o motor, e as ferramentas de arquivo do próprio agente estão fora da visão do motor. Trate a tabela como a lista do que o motor vai recusar; para todo o resto, confira o diff.

## Templates e agentes incluídos

Os templates ficam em `agent-specs/templates/` e existem para ser estendidos. Valores reais, já resolvidos:

| Template | Ferramentas permitidas | Ferramentas negadas | Modos | Risco máximo | Pode alterar arquivos |
|---|---|---|---|---|---|
| `base` | Read, Grep, Glob | nenhuma | plan | low | não |
| `base-engineer` | Read, Grep, Glob, Edit, Write, Bash | nenhuma | plan, execute | medium | sim |
| `base-reviewer` | Read, Grep, Glob, Bash | Edit, Write, NotebookEdit | plan, execute | high, com `ceiling: true` | não |

`agent-specs/examples/` traz dez agentes: `architect`, `code-reviewer`, `context-manager`, `decision-judge`, `frontend-engineer`, `remote-ops`, `researcher`, `security-auditor`, `senior-engineer`, `test-engineer`. `agent list` mostra ids, pais e modelos; `agent show <id> --resolved` mostra uma spec com a herança aplicada. Os arquivos do diretório `agents/`, na raiz, são gerados a partir dessas specs por `wev agent export`; são saída, não fonte. Edite a spec e exporte de novo.

## Herança (`extends`)

`extends` indica um único pai. Ciclos e pais desconhecidos são erros. Ao resolver uma spec, a fábrica:

- Valores únicos (`instructions`, `model`, `output_format`, `timeout_seconds`, `max_attempts`) ficam com o valor do filho quando ele define um.
- Listas (`specialties`, `responsibilities`, `skills`, `success_criteria`, `required_checks`, `stop_conditions`) são as entradas do pai seguidas das do filho, sem duplicatas.
- Objetos (`model_policy`, `budget`, `escalation`, `permissions`) são mesclados campo a campo.
- `tools`: as listas `allow` são unidas, as listas `deny` são unidas, e depois tudo que foi negado é removido de `allow`. Negar vence, e um filho não consegue remover uma entrada deny do pai. Negar `Bash` também remove as variantes `Bash(...)`.

Exemplo real de herança de deny: um filho de `code-reviewer` que pede `Edit` não ganha nada com isso.

```text
$ wev agent create --template code-reviewer --id r2 --set 'tools.allow=["Edit"]'
  tools: {"allow": ["Read", "Grep", "Glob", "Bash"], "deny": ["Edit", "Write", "NotebookEdit"]}
```

## Permissões e o teto

Sem teto, as permissões são herança simples: o objeto é mesclado campo a campo e vale o valor do filho, em qualquer profundidade. Um filho de `base-engineer` pode, portanto, elevar `max_risk` ou acrescentar um modo. Exemplo real: `--set 'permissions.max_risk="high"'` num filho de `base-engineer` é aceito e resolve para `max_risk: high`, `may_mutate: true`.

`permissions.ceiling` é um booleano opcional. Quando qualquer ancestral define `ceiling: true`, todo descendente pode estreitar, mas nunca ampliar, os `max_risk`, `may_mutate`, `may_use_remote` ou `modes` resolvidos desse ancestral (menos ou os mesmos modos, risco menor ou igual, e nenhum dos dois sinalizadores pode virar verdadeiro quando o do ancestral é falso), e não pode definir `ceiling: false`. Um descendente pode definir `ceiling: true` de novo num nível mais estreito, e esse teto passa a valer para os descendentes dele. Recusas reais:

```text
$ wev agent create --template code-reviewer --id fixer --set 'permissions.may_mutate=true'      # saída 2
{"error": {"code": "permission_widening",
  "message": "permissions.may_mutate: the ancestor 'code-reviewer' sets a permission ceiling; a descendant may narrow its permissions but not widen them",
  "details": {"field": "permissions.may_mutate", "ancestor": "code-reviewer"}}}

$ wev agent create --template code-reviewer --id fixer2 --set 'permissions.ceiling=false'       # saída 2
{"error": {"code": "ceiling_unset",
  "message": "permissions.ceiling: the ancestor 'code-reviewer' sets a permission ceiling and a descendant cannot unset it", ...}}
```

O teto é definido por `base-reviewer`, `code-reviewer`, `decision-judge`, `security-auditor` e `researcher`. Nada derivado deles pode ganhar acesso de escrita ou remoto. `base` e `base-engineer` não têm teto.

Padrões quando nada define: modos apenas `plan`, `max_risk` low, `may_mutate` falso, `may_use_remote` falso.

Outras checagens: um agente que permite `Edit`, `Write` ou `NotebookEdit` precisa ter `may_mutate` verdadeiro, ou falha com `mutating_tool_without_permission`; `create` se recusa a sobrescrever `extends`, e todo agente novo precisa de um id.

O que o teto faz e o que não faz: restringe o que a spec pode declarar. É checado em código quando as specs são carregadas. Não coloca o agente numa sandbox em tempo de execução; a lista de ferramentas e as permissões de uma tarefa vêm da spec, e a política de permissões checa os comandos que passam pelo motor. Veja o [guia de segurança](security.pt-BR.md).

## Campos de texto bilíngues

Escreva `name`, `description`, `instructions` e os demais campos de texto como objeto para atender os dois idiomas:

```json
"name": { "en": "Docs writer", "pt-BR": "Redator de documentação" }
```

A exportação gera o idioma escolhido com `--lang` (padrão: o idioma da CLI, vindo de `--lang`, `WEV_LANG` ou `LANG`). Uma string simples vale para todos os idiomas. Identificadores e nomes de campos ficam em inglês.

## Validar

```text
$ wev agent validate specs/docs-writer.json
{"valid": true, "path": "specs/docs-writer.json", "id": "docs-writer"}
```

`validate` confere o arquivo contra o schema e contra as regras da fábrica (o pai existe, ferramentas e permissões são coerentes). `--dir` acrescenta um diretório de specs (repetível; diretórios posteriores sobrescrevem os anteriores) e pode ser definido uma vez em `agents.directories` na configuração. Um diretório precisa ficar dentro do repositório ou do diretório de configuração do usuário, e uma spec de um diretório assim não pode reutilizar o id de um agente embutido a menos que `agents.allow_override` seja verdadeiro (do contrário é recusada). Um arquivo `.json` nesse diretório que tenha `schema_version` ou `id` declara ser uma spec e precisa ser válido, ou o comando falha; um JSON sem nenhum dos dois (um `package.json`, por exemplo) é ignorado e citado na lista `warnings`.

## Um exemplo completo

Crie um redator de documentação que pode editar arquivos, mas só com risco baixo. Esta sequência foi executada como está escrita.

```text
$ wev agent create --template base-engineer --id docs-writer \
    --set 'name={"en":"Docs writer","pt-BR":"Redator de documentação"}' \
    --set 'description={"en":"Writes and updates documentation files only.","pt-BR":"Escreve e atualiza apenas arquivos de documentação."}' \
    --set 'specialties=["documentation"]' \
    --set 'model="standard"' \
    --set 'permissions.max_risk="low"' \
    --out specs/docs-writer.json
```

`--set chave=valor` sobrescreve um campo; pontos aninham e os valores são lidos como JSON, com texto simples como alternativa. O comando imprime o agente resolvido e, com `--out`, grava apenas a spec filha (`--force` sobrescreve):

```json
{
  "schema_version": 1,
  "name": { "en": "Docs writer", "pt-BR": "Redator de documentação" },
  "description": { "en": "Writes and updates documentation files only.", "pt-BR": "Escreve e atualiza apenas arquivos de documentação." },
  "specialties": ["documentation"],
  "model": "standard",
  "permissions": { "max_risk": "low" },
  "id": "docs-writer",
  "extends": "base-engineer"
}
```

A herança é resolvida quando o arquivo é carregado. Confira o resultado:

```text
$ wev agent validate specs/docs-writer.json
$ wev agent show docs-writer --dir specs --resolved
  tools.allow: Read, Grep, Glob, Edit, Write, Bash   permissions: modes plan+execute, max_risk low, may_mutate true
```

Exporte para o Claude Code. O motor escreve somente dentro da raiz do repositório e nunca em `.git`, no diretório de estado nem em `.claude`, com uma exceção para este comando: `<raiz do repositório>/.claude/agents`, onde o Claude Code lê os subagentes de um projeto. `agent export` cria esse diretório se ele não existir e grava nele somente arquivos `<id>.md`:

```text
$ wev agent export --dir specs --id docs-writer --out .claude/agents
{"exported": [".../.claude/agents/docs-writer.md"], "lang": "en", "tool_profile": "structured", "warnings": []}

$ wev agent export --dir specs --id docs-writer --out .claude/hooks      # saída 3
{"error": {"code": "output_refused", "message": "Recusando gravar .claude/hooks: nada é gravado em .git ou .claude sob ...", ...}}
```

Todo outro caminho sob `.claude` continua recusado: `settings.json`, `settings.local.json`, `hooks/`, `commands/`, `skills/`, um subdiretório de `agents/` e uma grafia que difira só na caixa das letras. Um `.claude` ou `.claude/agents` que seja link simbólico também é recusado, então a exportação não pode ser apontada para fora do repositório. Um arquivo que já esteja em `.claude/agents` só é substituído se tiver a marca de arquivo gerado; um arquivo de agente escrito à mão nunca é sobrescrito. `wev agent create --out` continua recusando tudo sob `.claude`.

`wev agent create --out` e `wev agent export` não sobrescrevem um arquivo que não seja já uma spec de agente ou um arquivo de subagente gerado (`--force` vale só para um arquivo que já é uma spec). O `wev agent create --out` também recusa o nome reservado `wev.config.json` (em qualquer diretório e em qualquer combinação de maiúsculas e minúsculas) e qualquer arquivo existente que não seja uma spec de agente. Com o plugin instalado e uma execução wev ativa, o hook PreToolUse responde `ask` para os dois comandos quando consegue ler a linha de comando, então você confirma uma exportação para `.claude/agents` dentro do Claude Code.

O arquivo começa assim:

```markdown
---
name: "docs-writer"
description: "Writes and updates documentation files only."
tools: "Read, Grep, Glob, Edit, Write, Bash"
model: "sonnet"
maxTurns: 40
---
<!-- Generated from specs/docs-writer.json. Do not edit by hand. -->

# Docs writer
```

## Exportar para subagentes do Claude Code

`wev agent export --out DIR` grava arquivos `<id>.md`. Sem `--id` exporta todo agente que não seja template; `--id` é repetível; `--lang en|pt-BR` escolhe o idioma do texto.

- O frontmatter traz apenas campos que a documentação do Claude Code lista: `name`, `description`, `tools`, `disallowedTools`, `model`, `skills`, `maxTurns`, cada um quando a spec o define. Um nível vira `haiku`, `sonnet` ou `opus`; um id de modelo concreto é repassado; sem `model`, o campo é omitido. `budget.max_units` vira `maxTurns`.
- Todo o resto (instruções, responsabilidades, critérios de sucesso, limites, escalonamento, verificações obrigatórias, condições de parada) vai para o corpo em Markdown, que é o prompt de sistema do subagente. O motor impõe `required_checks` e os limites de tentativas, de tempo e de orçamento quando distribui e registra tarefas; `escalation`, `stop_conditions`, `success_criteria` e `output_format` são apenas instruções.
- `--tool-profile structured|lean|auto` sobrescreve `harness.tool_profile` na exportação. `structured` (o padrão) mantém toda a lista allow. `lean` reduz um agente que pode alterar arquivos e tem `Bash` permitido a `Bash`, `Read` e `Edit` (até onde ele os tinha). `auto` usa `lean` só para agentes do nível premium. Um perfil nunca acrescenta uma ferramenta, nunca muda a lista deny e nunca muda as permissões. O efeito de um perfil em qualquer modelo não foi medido.
- Coloque os arquivos onde o Claude Code lê agentes. Para um projeto, `.claude/agents/` no repositório, de modo que os agentes pertençam àquele projeto e à sua equipe; `wev agent export --out .claude/agents` grava lá diretamente (veja acima), e nenhum outro caminho sob `.claude` é gravável. Os agentes que este plugin traz são chamados `wev-skills:<id>` ao delegar; um arquivo que você exporta é chamado pelo id simples.

A linha de comentário do arquivo gerado informa de qual spec ele veio. Não edite o arquivo exportado à mão.

## Como o motor escolhe um agente para uma tarefa

`plan set` atribui um agente a cada tarefa: o `agent_hint` do plano, se citar um agente conhecido; senão, a melhor pontuação de uma correspondência de palavra inteira entre o título e o objetivo da tarefa e cada agente (uma palavra de especialidade pesa 3, uma especialidade casada por inteiro soma 2, uma palavra da descrição pesa 1; empates se desfazem pelo id). Sem correspondência, a tarefa vai para `agents.default_agent` (padrão `senior-engineer`) quando esse agente pode alterar arquivos. Fora do modo plan uma tarefa vai para um agente que pode alterar arquivos, a menos que esteja marcada como `read_only`. Uma tarefa sobre sistemas remotos mantém os agentes com `may_use_remote`. É uma heurística: ela atribuiu `test-engineer` a uma tarefa de documentação no [guia de orquestração](orchestration.pt-BR.md). Leia o `agent_id` do contrato e sobrescreva com `agent_hint` quando não servir.
