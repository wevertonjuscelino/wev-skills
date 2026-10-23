"""Ask the model for one lesson and filter its answer; every doubt drops the lesson."""

from __future__ import annotations

import json
import re
import unicodedata

from wev_skills import i18n
from wev_skills.agents.experience import LESSON_TEXT_MAX
from wev_skills.evaluation.cases import Case
from wev_skills.security.redact import redact
from wev_skills.security.untrusted import _SCAN_TABLE, normalize, sanitize, scan, wrap

FORBIDDEN = re.compile(
    r"(?i)(allowed[-_ ]?tools|permission|bypass|dangerously|--tools|tools\s*:|model\s*:"
    r"|\bsudo\b|\bchmod\b|specialists\s+(accept|retire))"
)
# JSON escapes may widen each character to six, plus the object around it.
MAX_ANSWER_CHARS = LESSON_TEXT_MAX * 6 + 64
_FENCE_LIKE = re.compile(r"<<<|>>>|UNTRUSTED[\W_]{0,8}DATA", re.IGNORECASE)


def _fenced(text: str, source: str) -> str:
    return wrap(redact(text), source=source)


def lesson_request(case: Case, check_output: str, diff: str, lang: str) -> str:
    return i18n.t(
        "evaluation.lesson.request",
        lang,
        limit=LESSON_TEXT_MAX,
        objective=_fenced(case.objective, "case objective"),
        output=_fenced(check_output, "check output"),
        diff=_fenced(diff, "agent diff"),
    )


def _is_safe(text: str) -> bool:
    if not 1 <= len(text) <= LESSON_TEXT_MAX:
        return False
    # Controls, invisibles and newlines are refused, not repaired; so are lone surrogates
    # (json.loads accepts them, UTF-8 cannot encode them). Accents and typographic
    # characters pass.
    if sanitize(text).translate(_SCAN_TABLE) != text or "\n" in text:
        return False
    if any(unicodedata.category(char) == "Cs" for char in text):
        return False
    # These checks must stay on the normalized form so full-width look-alikes are caught.
    folded = normalize(text)
    return not (_FENCE_LIKE.search(folded) or FORBIDDEN.search(folded) or scan(text))


def parse_lesson(answer: str) -> str | None:
    """The lesson text, or ``None`` unless the answer is exactly ``{"lesson": <safe text>}``."""
    if len(answer) > MAX_ANSWER_CHARS:
        return None
    try:
        data = json.loads(answer)
    except ValueError, RecursionError:
        return None
    if not isinstance(data, dict) or set(data) != {"lesson"}:
        return None
    text = data["lesson"]
    return text if isinstance(text, str) and _is_safe(text) else None
