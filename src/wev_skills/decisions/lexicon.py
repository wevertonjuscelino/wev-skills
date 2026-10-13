"""Deterministic lexical floor: risk signals read from the words of an objective.

A caller can forget a flag, or leave it out on purpose. The objective text is scanned for
whole words and fixed phrases, in English and Portuguese, that name production systems,
destructive operations, external effects, remote systems, credentials, and database or
schema changes. A hit raises the matching signal and is reported with the matched term.
It never lowers anything, and an explicit flag cannot clear it.

This is a word list. It has false positives ("release notes") and it misses paraphrases;
it is a floor under the explicit signals, not a classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from wev_skills import i18n
from wev_skills.core.contracts import TaskSignals

PRODUCTION = "touches_production"
DESTRUCTIVE = "destructive"
EXTERNAL = "external_side_effects"
REMOTE = "touches_remote"
CREDENTIALS = "touches_credentials"
DATA_SCHEMA = "changes_data_schema"

TERMS: dict[str, tuple[str, ...]] = {
    PRODUCTION: ("production", "prod", "produção", "producao"),
    DESTRUCTIVE: (
        "drop", "drops", "dropping", "dropped", "delete", "deletes", "deleting", "deleted",
        "truncate", "truncates", "truncating", "wipe", "wipes", "wiping", "force push",
        "force-push", "push --force", "push -f", "reset hard", "reset --hard", "rm -rf",
        "rm -fr", "apagar", "apague", "excluir", "exclua", "remover", "remova", "destruir",
        "destrua",
    ),
    EXTERNAL: (
        "deploy", "deploys", "deploying", "publish", "publishes", "publishing", "release",
        "releases", "releasing", "push", "pushes", "pushing", "merge", "merges", "merging",
        "send", "sends", "sending", "migrate", "migrates", "migrating", "publicar",
        "publique", "implantar", "implante", "enviar", "envie",
    ),
    REMOTE: ("server", "servers", "ssh", "cluster", "clusters", "servidor", "servidores"),
    CREDENTIALS: (
        "credential", "credentials", "secret", "secrets", "password", "passwords", "token",
        "tokens", "api key", "api keys", "private key", "private keys", "senha", "senhas",
        "credencial", "credenciais", "segredo", "segredos",
    ),
    DATA_SCHEMA: (
        "database", "databases", "schema", "schemas", "migration", "migrations",
        "banco de dados", "bancos de dados", "esquema", "esquemas", "migração", "migracao",
    ),
}  # fmt: skip
SECURITY_TERMS = (
    "security", "vulnerability", "vulnerabilities", "owasp", "segurança", "seguranca",
    "vulnerabilidade", "vulnerabilidades",
)  # fmt: skip
REVIEW_TERMS = (
    "review", "reviews", "audit", "audits", "auditing", "assessment", "revisão", "revisao",
    "revisar", "auditoria", "auditar", "avaliação", "avaliacao",
)  # fmt: skip


@dataclass(frozen=True)
class Hit:
    signal: str
    term: str


def _pattern(terms: tuple[str, ...]) -> re.Pattern[str]:
    """Whole-word alternation; spaces in a phrase match any run of whitespace."""
    ordered = sorted(terms, key=len, reverse=True)
    body = "|".join(r"\s+".join(re.escape(part) for part in term.split()) for term in ordered)
    return re.compile(rf"(?<![\w-])(?:{body})(?![\w-])", re.IGNORECASE)


_PATTERNS = {signal: _pattern(terms) for signal, terms in TERMS.items()}
_SECURITY = _pattern(SECURITY_TERMS)
_REVIEW = _pattern(REVIEW_TERMS)


def scan(text: str) -> tuple[Hit, ...]:
    """The first matched term of every signal family found in ``text``, in a fixed order."""
    found = []
    for signal, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if match:
            found.append(Hit(signal, " ".join(match.group(0).lower().split())))
    return tuple(found)


def mentions(text: str, signal: str) -> bool:
    return bool(_PATTERNS[signal].search(text))


def first_term(text: str, signal: str) -> str:
    """The first term of ``signal`` found in ``text``, lower-cased; ``""`` when none is."""
    match = _PATTERNS[signal].search(text)
    return " ".join(match.group(0).lower().split()) if match else ""


compile_terms = _pattern
"""Public name of the whole-word matcher, for other word lists of the decision layer."""


def is_security_review(text: str) -> bool:
    """The text names both security and a review or audit of it."""
    return bool(_SECURITY.search(text)) and bool(_REVIEW.search(text))


def floor_signals(signals: TaskSignals) -> tuple[TaskSignals, tuple[str, ...]]:
    """``signals`` with every signal the objective implies raised, and a reason per raise."""
    hits = [hit for hit in scan(signals.objective) if not getattr(signals, hit.signal)]
    raised = {hit.signal for hit in hits}
    floored = replace(
        signals,
        touches_production=signals.touches_production or PRODUCTION in raised,
        destructive=signals.destructive or DESTRUCTIVE in raised,
        external_side_effects=signals.external_side_effects or EXTERNAL in raised,
        touches_remote=signals.touches_remote or REMOTE in raised,
        touches_credentials=signals.touches_credentials or CREDENTIALS in raised,
        changes_data_schema=signals.changes_data_schema or DATA_SCHEMA in raised,
    )
    reasons = [i18n.t("decisions.floor.hit", term=hit.term, signal=hit.signal) for hit in hits]
    return floored, tuple(reasons)
