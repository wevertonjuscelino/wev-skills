"""The local tool-selection policy: the floor, plus a tool only when the task asks for it.

Deterministic and offline. The task's title, objective and acceptance criteria are scanned
for whole words and fixed phrases, in English and Portuguese. Like the lexical floor of the
classifier, this is a word list: it has false positives and misses paraphrases. A tool it
drops by mistake can be restored for the task (``wev task tools``), which the report counts
as a selection miss.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.agents.tool_profile import SHELL_TOOL
from wev_skills.core.contracts import PlanTask
from wev_skills.decisions import lexicon
from wev_skills.decisions import tool_selection as rules
from wev_skills.decisions.tool_selection import Proposal, ToolAgent
from wev_skills.tools.registry import ToolSpec

WRITE_TOOL = "Write"
NETWORK_TERMS = (
    "documentation", "docs", "doc", "research", "url", "urls", "http", "https", "link",
    "links", "website", "api", "apis", "upgrade notes", "release notes", "changelog",
    "migration guide", "documentação", "documentacao", "pesquisa", "pesquisar", "pesquise",
    "notas de atualização", "notas de atualizacao", "notas de versão", "notas de versao",
    "guia de migração", "guia de migracao", "site",
)  # fmt: skip
CREATE_TERMS = (
    "create", "creates", "creating", "add", "adds", "adding", "new file", "new files",
    "new module", "new modules", "scaffold", "scaffolds", "scaffolding", "generate",
    "criar", "crie", "cria", "adicionar", "adicione", "adiciona", "novo arquivo",
    "novos arquivos", "novo módulo", "novo modulo", "gerar", "gere",
)  # fmt: skip
SHELL_TERMS = (
    "run", "runs", "running", "execute", "executes", "command", "commands", "script",
    "scripts", "shell", "terminal", "install", "build", "compile", "executar", "rodar",
    "rode", "comando", "comandos", "instalar", "instale", "compilar", "compile",
)  # fmt: skip
NOTEBOOK_TERMS = ("notebook", "notebooks", "jupyter", "ipynb")
NOTEBOOK_MARK = "notebook"

_NETWORK = lexicon.compile_terms(NETWORK_TERMS)
_CREATE = lexicon.compile_terms(CREATE_TERMS)
_SHELL = lexicon.compile_terms(SHELL_TERMS)
_NOTEBOOK = lexicon.compile_terms(NOTEBOOK_TERMS)

Added = dict[str, str]
"""Base tool name to the reason it was added, in the order the rules fired."""


def task_text(task: PlanTask) -> str:
    """The only task text selection reads: title, objective and acceptance criteria."""
    return "\n".join([task.title, task.objective, *task.acceptance_criteria])


def _term(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text)
    return " ".join(match.group(0).lower().split()) if match else ""


def _network(text: str, have: Sequence[str], specs: dict[str, ToolSpec]) -> Added:
    term = _term(_NETWORK, text)
    wanted = [n for n in have if n in specs and specs[n].network and not specs[n].remote]
    return {n: i18n.t("decisions.tools.local.network", tool=n, term=term) for n in wanted if term}


def _create(text: str, have: Sequence[str], writes: bool) -> Added:
    term = _term(_CREATE, text)
    if not term or not writes or WRITE_TOOL not in have:
        return {}
    return {WRITE_TOOL: i18n.t("decisions.tools.local.create", tool=WRITE_TOOL, term=term)}


def _remote(text: str, have: Sequence[str], specs: dict[str, ToolSpec], allowed: bool) -> Added:
    """The remote tools, and the shell that remote commands are driven from."""
    term = lexicon.first_term(text, lexicon.REMOTE)
    if not term or not allowed:
        return {}
    wanted = [n for n in have if (n in specs and specs[n].remote) or n == SHELL_TOOL]
    return {n: i18n.t("decisions.tools.local.remote", tool=n, term=term) for n in wanted}


def _shell(text: str, have: Sequence[str]) -> Added:
    term = _term(_SHELL, text)
    if not term or SHELL_TOOL not in have:
        return {}
    return {SHELL_TOOL: i18n.t("decisions.tools.local.shell", tool=SHELL_TOOL, term=term)}


def _named(text: str, have: Sequence[str], specs: dict[str, ToolSpec], writes: bool) -> Added:
    """A tool the task names outright, and notebook tools for a task about notebooks.

    A tool that changes things is not added by name to a task or an agent that may not.
    """
    notebook = bool(_NOTEBOOK.search(text))
    added: Added = {}
    for name in have:
        if name in specs and specs[name].mutating and not writes:
            continue
        named = re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None
        if named or (notebook and NOTEBOOK_MARK in name.lower()):
            added[name] = i18n.t("decisions.tools.local.named", tool=name)
    return added


def additions(task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec]) -> Added:
    """Every tool beyond the floor that the task gives a reason for, with that reason."""
    have = rules.bases(rules.candidate_tools(agent))
    specs = {spec.name: spec for spec in available}
    text = task_text(task)
    writes = not task.read_only and rules.may_mutate(agent)
    found: Added = {}
    for group in (
        _network(text, have, specs),
        _create(text, have, writes),
        _remote(text, have, specs, rules.may_use_remote(agent)),
        _shell(text, have),
        _named(text, have, specs, writes),
    ):
        found.update({name: why for name, why in group.items() if name not in found})
    return found


def propose(
    task: PlanTask, agent: ToolAgent, available: Sequence[ToolSpec], profile: str, source: str
) -> Proposal:
    """The floor plus the additions, with one reason per tool kept, added or dropped."""
    candidates = rules.candidate_tools(agent)
    floor = rules.floor_tools(task, agent, candidates)
    added = {n: why for n, why in additions(task, agent, available).items() if n not in floor}
    selected = (*floor, *added)
    dropped = [name for name in rules.bases(candidates) if name not in selected]
    reasons = (
        *rules.floor_reasons(task, agent, candidates),
        *added.values(),
        *(i18n.t("decisions.tools.local.dropped", tool=name) for name in dropped),
    )
    return Proposal(selected, profile, reasons, source)
