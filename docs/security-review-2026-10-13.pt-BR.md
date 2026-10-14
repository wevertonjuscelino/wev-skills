# Revisão de segurança — 2026-10-13

[English](security-review-2026-10-13.md).

Esta revisão local de código e regressões foi feita durante a preparação do repositório
público. Não é auditoria externa, teste de invasão ou certificação. A árvore de trabalho
continha outras alterações em andamento; os resultados descrevem os arquivos inspecionados
no momento da revisão.

## Escopo e abordagem

Foram inspecionados execução e classificação de comandos, lista de leitura, caminhos
protegidos, persistência e locks, vínculo e consumo de aprovações, redação de auditoria,
tratamento de saída não confiável, construção de comandos SSH e workflows do repositório.
As referências principais são a [política de segurança](../SECURITY.pt-BR.md) e os testes em
`tests/security/`. As reproduções usaram diretórios temporários e dados sintéticos. Nenhum
dado do projeto foi enviado a um serviço externo de classificação e nenhum host remoto
foi acessado.

## Achados

| Achado | Severidade no modelo de ameaças documentado | Situação |
|---|---|---|
| Logs de append recebiam permissões privadas depois da escrita | Baixa; divulgação local condicional | Corrigido |
| Helpers Git explícitos eram classificados como comandos comuns | Média; desvio de aprovação no modo execute | Corrigido |
| Helpers Git habilitados pela configuração existente do repositório | Média; limite residual de leitura | Aberto, documentado aqui |

### 1. Permissões privadas eram aplicadas tarde demais

`core/fsutil.py:append_line` usava `open(path, "a")`, escrevia e descarregava o registro, e
depois mudava o modo para `0600`. Com umask `022`, um arquivo novo tinha modo `0644` enquanto
o conteúdo já estava persistido. Arquivos existentes com permissões amplas tinham o mesmo
problema de ordem. Outra conta local poderia ler nessa janela se pudesse atravessar o
diretório pai. Diretórios novos criados pelo engine são `0700`, o que reduz a exposição;
diretórios preexistentes mantêm as permissões, portanto o problema é condicional. Logs
podem conter informações operacionais e segredos não reconhecidos pela redação heurística.

A correção cria arquivos de append com `os.open(..., 0600)` e restringe arquivos permissivos
da própria conta pelo descritor antes de escrever. O mesmo helper atende arquivos de lock.
O teste de regressão verifica permissões pelo descritor durante `fsync`, para arquivos novos
e existentes. A implementação anterior obtida de `HEAD` mostrou modo `0644` nesse instante
com dados sintéticos; os testes corrigidos passam com `0600`.

### 2. Helpers Git explícitos não exigiam aprovação

O classificador não identificava `git diff --ext-diff` ou `git show --textconv` como comandos
que executam helpers configurados. A lista de leitura já recusava `--ext-diff`, mas o modo
execute com risco baixo/médio ainda podia permitir a execução sem aprovação. `--textconv`
também escapava da decisão de leitura.

A correção classifica opções explícitas de helpers, incluindo prefixos longos reconhecidos,
como não analisáveis em `diff`, `show`, `log`, `blame`, `grep` e `cat-file`. Isso exige
aprovação e impede tratá-las como leitura. `--no-ext-diff --no-textconv` continua sem alerta.
O classificador de `HEAD` retornou `needs_approval=False` para os dois exemplos; o corrigido
retorna `True`. Os testes cobrem esses exemplos e os subcomandos relacionados.

### 3. Configuração Git existente ainda pode executar helpers implícitos

Um repositório temporário com `.gitattributes` e `diff.synthetic.textconv` apontando para um
script sintético executou esse script em um simples `git diff`, sem `--textconv`. Comandos
Git de leitura continuam permitidos pela heurística do engine. Outros recursos de
configuração/ambiente também podem executar helpers; esta revisão não esgotou essas opções.

A correção das opções explícitas não resolve configuração implícita. Inspecione configuração
e atributos de um repositório desconhecido antes de confiar nos comandos Git de leitura e
use isolamento do sistema operacional quando executar helpers arbitrários for inaceitável.
Uma implementação futura deve definir como desabilitar helpers nos comandos aprovados de
leitura sem alterar silenciosamente a semântica de execução e aprovação.

## Controles confirmados por inspeção e testes

- Execução usa argv em vez de shell; a resolução de executáveis simples usa o caminho
  configurado. Isso não limpa o ambiente dos programas filhos.
- Aprovações vinculam argv exato, diretório e run, expiram e são consumidas sob lock.
  Eventos correspondentes de auditoria evidenciam adulteração, sem provar identidade humana.
- Escritas de estado usam substituição atômica e locks consultivos; identificadores seguros
  de run restringem caminhos.
- A redação cobre padrões conhecidos e registros de argv completo. Caracteres de controle e
  cercas de saída forjadas são neutralizados na saída não confiável da CLI.
- A construção SSH escapa argv e solicita verificação estrita de chave do host e modo batch.
- Referências de actions nos workflows usam SHAs de commit, permissões são de leitura e o
  checkout não persiste credenciais. Fixar um SHA não equivale a revisar a action.

## Validação e limites

Python utilizado: **3.14.7**.

- `PYTHONPATH=src python3 -m unittest discover -s tests/security -v`: **291 testes passaram**.
- `PYTHONPATH=src python3 -m unittest tests.unit.test_fsutil tests.security.test_classification_gaps -q`:
  **30 testes passaram**, incluindo as novas regressões.
- Verificações sintéticas antes/depois confirmaram a janela anterior e a falha nas opções de helpers.
- Reprodução Git local sintética confirmou que textconv implícito ainda pode executar código.

Nenhum host SSH real, modelo pago ou prompt real de permissão do agente foi exercitado.
Configurações GitHub, relatos privados de vulnerabilidades, proteção de branch e varredura
de segredos não foram verificadas. A suíte completa e lint são relatados separadamente pela
preparação do repositório, sem inferir esses resultados dos testes focados.

O engine compartilha a conta do agente e não é uma sandbox: um processo malicioso na mesma
conta pode reescrever estado e auditoria, usar pseudoterminal nos prompts do operador ou
executar scripts fora da visibilidade do classificador. Corridas de symlink entre verificação
e uso, formatos de segredo desconhecidos e paráfrases de injeção continuam como limites na
política de segurança. As alterações de entrevista/especialistas em andamento foram
preservadas e não receberam certificação independente nesta revisão.
