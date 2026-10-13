# ADR 0001: Motor em Python com biblioteca padrão

Versão em inglês: [0001-python-stdlib-engine.md](0001-python-stdlib-engine.md).

Status: aceito (2026-10-13)

## Contexto

O harness precisa de código determinístico para estado, permissões, detecção de laços, execução de comandos e validação. A máquina de desenvolvimento tem Python 3.14.7 e Node 24.15.0, sem linters, verificadores de tipos, executores de teste nem bibliotecas de schema instalados. O briefing do projeto pede uma base de código simples e auditável e testes que rodem sem acesso à rede nem provedores pagos.

## Decisão

Escrever o motor como um pacote Python (`wev_skills`) voltado ao Python 3.14+ (veja o adendo de 2026-10-13) e que importa, em tempo de execução, apenas a biblioteca padrão. Os testes usam `unittest`. `ruff` e `mypy` rodam no CI e são opcionais localmente.

## Motivos

- Nada precisa ser instalado para rodar o motor ou seus testes, o que também elimina a superfície de cadeia de suprimentos de uma árvore de dependências.
- A biblioteca padrão já cobre as partes difíceis: `subprocess` sem shell, `shlex`, resolução de links simbólicos com `pathlib`, `os.replace` para escrita atômica, travas com `fcntl`, `argparse`, `dataclasses`.
- Skills do ecossistema Agent Skills costumam trazer auxiliares em Python ou shell, então uma CLI em Python combina com o modo como skills chamam ferramentas.

## Consequências

- Não há parser de YAML nem biblioteca de JSON Schema, então configuração e specs de agentes são JSON, validados por um pequeno validador do próprio repositório que aceita um subconjunto documentado de JSON Schema (ADR 0003).
- A verificação de tipos não é imposta numa máquina de desenvolvimento a menos que o `mypy` esteja instalado; o CI é o portão.
- As travas de arquivo usam `fcntl`, então o armazenamento de estado funciona em macOS e Linux. Windows não é suportado no MVP.

## Alternativas consideradas

- TypeScript em Node: boa tipagem, mas a verificação de tipos exige o pacote `typescript`, e uma etapa de build acrescenta peças móveis a uma CLI deste tamanho.
- Go: binário único e tipagem forte, mas é menos provável que quem contribui com repositórios de skills tenha uma toolchain Go, e um binário é mais difícil de auditar no lugar.

## Adendo (2026-10-13): Python mínimo elevado para 3.14

A decisão acima mirava inicialmente o Python 3.10 e mais novos. Em 2026-10-13, antes da primeira publicação, o dono decidiu que o projeto exige Python 3.14 ou mais novo (`requires-python = ">=3.14"`). O motivo apresentado é suportar apenas a versão em que o dono desenvolve e testa.

Consequências:

- Sintaxe mais nova é permitida no motor (por exemplo `StrEnum`, aliases com `type` e a sintaxe de funções genéricas).
- O `bin/wev` continua escrito em sintaxe que um interpretador antigo consegue analisar, para que a sua verificação de versão possa imprimir uma mensagem em vez de um erro de sintaxe. Com um `python3` mais antigo, os subcomandos de hook saem com 0 e não verificam nada, e os demais comandos saem com 1 e uma mensagem.
- Uma execução anterior da suíte no Python 3.10 passou antes desta mudança. O Python 3.10 a 3.13 não são mais suportados nem testados.
