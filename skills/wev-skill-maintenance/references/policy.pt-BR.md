# Política de manutenção de skills

Inglês: `policy.md`. Origem: `upstream.json`.

## Instalação e procedência

A referência externa é [netresearch/skill-repo-skill](https://github.com/netresearch/skill-repo-skill),
versão 2.4.0, revisada no commit `42a5e85798a8cdfda2866afb0de9aadb04e187f3`.
Conteúdo CC-BY-SA-4.0; scripts MIT, copyright Netresearch DTT GmbH.
O plugin distribui uma skill original de coordenação e uma referência fixada, sem copiar o guia.
Instalar wev-skills sozinho não instala essa dependência externa.

Use o instalador de skills do seu ambiente com `--repo netresearch/skill-repo-skill`,
`--path skills/skill-repo` e `--ref` igual ao commit fixado. Instale no diretório global de skills do ambiente e recarregue as skills quando necessário.
Preserve os arquivos de licença
junto ao material baixado. Registre o commit no diretório instalado para comparar sua versão
com a referência. No Claude Code, instale o plugin externo separadamente pelo marketplace
Netresearch e compare a versão com a referência. Uma versão diferente exige revisão de
conciliação antes do uso.

## Padrões compartilhados e exceções locais

A referência fixada no repositório designado para coordenação é a fonte comum da operação.
Registre esse repositório e commit antes de começar. Outros repositórios podem ter uma cópia,
mas as atualizações partem do repositório coordenador.
Registre para cada repositório: caminho absoluto, branch, alterações existentes, versão
instalada da skill, instruções locais, manifestos, licenças, verificações exigidas e convenções
compartilhadas aplicáveis. Compare o inventário antes de editar. Monte uma tabela de padrão,
repositório, comportamento atual, proposta, exceção local e motivo. Resolva conflitos
explicitamente; a ordem das tarefas não determina quais regras prevalecem. Uma skill orienta;
não autoriza superar instruções do usuário, segurança local ou portões de aprovação humana.

No wev-skills preserve o motor Python somente com biblioteca padrão, a licença MIT existente,
`.claude-plugin/plugin.json` como manifesto atual, documentação em inglês e português brasileiro,
testes e lint existentes. Composer, marca Netresearch, licença dividida e CI upstream são
propostas opcionais de migração, nunca exigências automáticas. O validador estrutural Netresearch
só pode servir de critério de aceitação após revisar e tornar aplicáveis suas premissas.

## Revisar atualizações e conciliar repositórios

1. Ao iniciar manutenção, compare a referência com tags/commits upstream. Informe se foi
   verificada, permanece igual, há versão nova, está indisponível ou é incompatível. Não afirme
   atualização sem consulta.
2. Baixe a candidata em checkout temporário separado. Revise diff, licenças, scripts,
   referências e notas antes de executar. Preserve a instalação atual durante a revisão.
3. Prepare a alteração da referência e documente mudanças aplicáveis e exceções locais.
   Valide primeiro o coordenador. Rejeitar uma candidata mantém a referência anterior.
4. Aplique o commit comum revisado isoladamente a cada repositório do escopo. Não sobrescreva
   arquivos modificados nem permita que agentes paralelos disputem instalações globais.
   Um mantenedor designado faz a instalação após revisão, guardando cópia recuperável anterior.
5. Execute verificações próprias de cada repositório. Informe repositório, commit antes/depois,
   exceções, verificações, falhas e pendências. Publique somente no escopo autorizado.

Esta integração não possui consulta agendada nem sincronização automática entre repositórios.
O fluxo oferece revisão coordenada; não garante atualização permanente.
