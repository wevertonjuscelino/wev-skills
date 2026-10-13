"""What "the same action" means for an approval: its id, what a grant covers, what a denial follows.

- The id and the grant follow the exact argv, token for token. A grant is also bound to the
  resolved working directory, the run and the request it answers (``binding_hash``).
- A denial follows the words of the action and the run, and nothing else (``denial_key``):
  not the directory, the stated risk, the reason, nor how the words were quoted, spaced or
  grouped into tokens. For a remote action the host alias is the first word, so a denial is
  per host. The comparison is conservative: two commands whose words are the same in the
  same order share a denial even when their tokens were grouped differently.

A different spelling of the same target (``build`` and ``./build``) is a different action;
the comparison is on words, it does not resolve paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from collections.abc import Sequence

from wev_skills import i18n
from wev_skills.core.errors import ValidationError

ID_PREFIX = "apr-"
ID_HASH_CHARS = 16

Action = str | Sequence[str]


def normalize_action(action: Action) -> tuple[str, ...]:
    """Tokens of an action. A string is split like a command line; an argv is kept verbatim."""
    if isinstance(action, str):
        try:
            tokens = tuple(shlex.split(action))
        except ValueError:
            tokens = (action.strip(),)
    else:
        tokens = tuple(action)
    if not tokens or any(not isinstance(token, str) for token in tokens) or not any(tokens):
        raise ValidationError("empty_action", i18n.t("security.approval.empty_action"), {})
    return tokens


def _digest(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def action_hash(action: Action) -> str:
    return _digest(list(normalize_action(action)))


def approval_id(action: Action) -> str:
    return ID_PREFIX + action_hash(action)[:ID_HASH_CHARS]


def binding_hash(tokens: Sequence[str], cwd: str, run_id: str, generation: int) -> str:
    """What a grant covers: the argv, where it runs, in which run, for which request."""
    return _digest([list(tokens), cwd, run_id, generation])


def resolved_cwd(cwd: str | os.PathLike[str] | None) -> str:
    """The directory a grant is bound to; ``""`` for an action that has none."""
    return os.path.realpath(os.fspath(cwd)) if cwd else ""


def denial_key(action: Action) -> tuple[str, ...]:
    """The words a denial follows: every token split like a command line, blanks dropped."""
    words: list[str] = []
    for token in normalize_action(action):
        try:
            words.extend(shlex.split(token))
        except ValueError:
            words.extend(token.split())
    return tuple(words)
