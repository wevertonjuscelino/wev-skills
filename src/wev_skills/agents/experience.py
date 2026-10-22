"""Experience of a project specialist: reviewed lessons, shown as advisory text.

A lesson is derived from the engine's own records of a run (``learning.derive``) and
stored in the specialist's spec by an explicit learning command, as ``proposed``; it is shown
only after the person at a terminal accepts it, or after a score run accepts it
(``accepted_by`` ``score``, see ``evaluation.scoring``); a person's decision is final against
score. It is text the agent reads: nothing in this module, in the factory or in the exporter
lets a lesson change tools, permissions or any other field of the spec, and experience is
not inherited through ``extends``.

The lesson's own text is built from structured fields and shown as one cleaned line. Text a
person or an agent wrote (a criterion, a review summary, the optional note) is kept apart in
``authored`` and ``note`` and is always shown inside the untrusted-data fence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.textsafe import clean_text
from wev_skills.security import untrusted

KIND_PRACTICE, KIND_PITFALL, KIND_NEED, KIND_MODEL = "practice", "pitfall", "need", "model"
LESSON_KINDS = (KIND_PRACTICE, KIND_PITFALL, KIND_NEED, KIND_MODEL)
ACTIVE, STALE, RETIRED, PROPOSED = "active", "stale", "retired", "proposed"
LESSON_STATUSES = (ACTIVE, STALE, RETIRED, PROPOSED)
PROPOSER = "engine"
"""``accepted_by`` of a lesson no person has accepted yet."""
SCORER = "score"
"""``accepted_by`` of a lesson a score run decided on; reserved like ``PROPOSER``."""
LESSON_TEXT_MAX = 600
"""The schema's bound on a lesson's text; rendering cleans the text to the same length."""
AUTHORED_MAX = 240
"""Cut for one authored excerpt and for the agent note, applied where they are created."""
MAX_EXPERIENCE_CHARS = 6000
"""Characters the rendered list may take in an exported file or a task contract."""
PRIOR_WEIGHT = 3
"""Virtual tasks at the agent's average added to every lesson's rate (shrinkage)."""
MIN_SHOWN = 3
"""Ended tasks a lesson needs before its rate may demote it."""
DEMOTE_MARGIN = 0.1
"""How far below the agent's average the adjusted rate must fall to demote a lesson."""
NOTE_LABEL = "agent note, unverified"
_NONCE_LENGTH = 16


@dataclass(frozen=True)
class RecordRef(Serializable):
    """One engine record a lesson came from: its type and how to find it in the run."""

    type: str
    id: str


@dataclass(frozen=True)
class LessonEvidence(Serializable):
    run_id: str
    task_id: str
    records: tuple[RecordRef, ...] = ()


@dataclass(frozen=True)
class AuthoredText(Serializable):
    """Text a person or an agent wrote (criterion, review summary): data, shown fenced."""

    label: str
    text: str


@dataclass(frozen=True)
class Lesson(Serializable):
    id: str
    kind: str
    text: str
    evidence: LessonEvidence
    created_at: str
    accepted_by: str
    confirmations: int = 0
    contradictions: int = 0
    last_seen_run: str = ""
    status: str = ACTIVE
    derivation: str = ""
    key: tuple[str, ...] = ()
    """With ``derivation``, what makes a later candidate the same lesson (deduplication)."""
    contains_authored_text: bool = False
    authored: tuple[AuthoredText, ...] = ()
    note: str = ""
    """The calling model's note, kept only when the operator accepted it explicitly."""
    shown_verified: int = 0
    """Tasks that were shown this lesson and ended verified, recounted on every learning."""
    shown_unverified: int = 0
    """Tasks that were shown this lesson and ended failed, blocked or partial."""


def check_key(argv: Sequence[str]) -> tuple[str, ...]:
    """What identifies a lesson learned from a check: a digest of its argv, never its text."""
    return ("check", hashlib.sha256("\0".join(argv).encode()).hexdigest())


MODEL_LABEL = "model-written lesson"


def _fenced(lesson_id: str, label: str, text: str, limit: int = AUTHORED_MAX) -> str:
    """``text`` in the untrusted-data fence, with a marker id derived from the lesson so the
    same lesson always renders the same bytes (the export is compared with the file)."""
    digest = hashlib.sha256(f"{lesson_id}\0{label}".encode()).hexdigest()
    return untrusted.wrap(clean_text(text, limit), label, digest[:_NONCE_LENGTH])


def render_lesson(lesson: Lesson, lang: str | None = None) -> str:
    """One lesson as advisory text: a cleaned line, then any authored text, fenced."""
    counts = i18n.t(
        "agents.experience.counts",
        lang,
        confirmations=lesson.confirmations,
        contradictions=lesson.contradictions,
    )
    kind = i18n.t(f"agents.experience.kind.{lesson.kind}", lang)
    if lesson.kind == KIND_MODEL:  # model-written text is never bare: fixed line, text fenced
        said = i18n.t("agents.experience.model_line", lang, by=lesson.accepted_by)
        head = f"[{kind}] {said} ({counts})"
        blocks = [_fenced(lesson.id, MODEL_LABEL, lesson.text, LESSON_TEXT_MAX)]
    else:
        head = f"[{kind}] {clean_text(lesson.text, LESSON_TEXT_MAX)} ({counts})"
        blocks = []
    blocks += [_fenced(lesson.id, item.label, item.text) for item in lesson.authored]
    if lesson.note:
        blocks.append(_fenced(lesson.id, NOTE_LABEL, lesson.note))
    return "\n".join([head, *blocks])


def pooled_rate(lessons: Iterable[Lesson]) -> float | None:
    """Share of verified endings over every task any of these lessons was shown to; ``None``
    while none has ended. It is the agent's own average, so the bar moves with the agent."""
    verified = shown = 0
    for lesson in lessons:
        verified += lesson.shown_verified
        shown += lesson.shown_verified + lesson.shown_unverified
    return verified / shown if shown else None


def adjusted_rate(lesson: Lesson, average: float) -> float:
    """The lesson's verified share pulled toward ``average`` by ``PRIOR_WEIGHT`` virtual
    tasks: a lesson with few endings stays near the average instead of swinging."""
    shown = lesson.shown_verified + lesson.shown_unverified
    return (lesson.shown_verified + PRIOR_WEIGHT * average) / (shown + PRIOR_WEIGHT)


def _demoted(lesson: Lesson, average: float | None) -> bool:
    """Below the average by more than the margin, with at least ``MIN_SHOWN`` endings."""
    if average is None or lesson.shown_verified + lesson.shown_unverified < MIN_SHOWN:
        return False
    return adjusted_rate(lesson, average) < average - DEMOTE_MARGIN


def active_lessons(
    lessons: Iterable[Lesson], relevant: Collection[tuple[str, ...]] = ()
) -> list[Lesson]:
    """Active lessons a person accepted, most confirmed first, with two exceptions applied in
    this order. A lesson stored as active but accepted only by the engine (before acceptance
    existed) is not shown until a person accepts it.

    A lesson clearly worse than the agent's average goes after the others; nothing is
    promoted or hidden by its rate, and a demoted lesson moves back once its rate recovers.
    Then a lesson whose key is in ``relevant`` (the checks the task will run) goes before
    the others. Ties go to the older lesson, then to the id.
    """
    found = [item for item in lessons if item.status == ACTIVE and item.accepted_by != PROPOSER]
    average = pooled_rate(found)
    return sorted(
        found,
        key=lambda item: (
            _demoted(item, average),
            item.key not in relevant,
            -item.confirmations,
            item.created_at,
            item.id,
        ),
    )


def _selection(
    lessons: Iterable[Lesson],
    max_lessons: int,
    max_chars: int,
    lang: str | None,
    relevant: Collection[tuple[str, ...]],
) -> list[tuple[Lesson, str]]:
    """At most ``max_lessons`` active lessons, most confirmed first; the first lesson that
    would take the list past ``max_chars`` ends it, so the list never grows without bound."""
    shown: list[tuple[Lesson, str]] = []
    used = 0
    for lesson in active_lessons(lessons, relevant)[: max(0, max_lessons)]:
        text = render_lesson(lesson, lang)
        if used + len(text) > max_chars:
            break
        shown.append((lesson, text))
        used += len(text)
    return shown


def rendered_lessons(
    lessons: Iterable[Lesson],
    max_lessons: int,
    max_chars: int = MAX_EXPERIENCE_CHARS,
    lang: str | None = None,
    relevant: Collection[tuple[str, ...]] = (),
) -> tuple[str, ...]:
    """The capped list an exported subagent and a task contract show (see ``_selection``)."""
    found = _selection(lessons, max_lessons, max_chars, lang, relevant)
    return tuple(text for _, text in found)


def shown_lesson_ids(
    lessons: Iterable[Lesson],
    max_lessons: int,
    max_chars: int = MAX_EXPERIENCE_CHARS,
    lang: str | None = None,
    relevant: Collection[tuple[str, ...]] = (),
) -> tuple[str, ...]:
    """The ids of the lessons ``rendered_lessons`` shows, in the same order."""
    found = _selection(lessons, max_lessons, max_chars, lang, relevant)
    return tuple(lesson.id for lesson, _ in found)


def lead_line(lang: str | None = None) -> str:
    """What the list is, said before it: observations, below the contract in authority."""
    return i18n.t("agents.experience.lead", lang)
