"""The friction shared by the human-operator commands.

``approval grant``, ``approval deny``, ``approval request --reopen-denied``, ``guard
acknowledge``, ``task reopen`` and ``run adopt`` need a terminal on stdin and stdout, show
the full action and make the operator type a word printed on screen. There is no flag and
no environment variable that replaces this.

It is friction and a record, not authentication. Inside one user account the CLI cannot tell
who is typing, and a determined process can allocate a pseudo-terminal and answer the
prompt. That is why the Claude Code hook also routes these commands to Claude Code's own
permission prompt, which is the gate a person can rely on. What is recorded is what the
engine can actually observe: the operating-system user, the terminal device and the time.
"""

from __future__ import annotations

import os
import pwd
import secrets
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import PermissionDenied
from wev_skills.core.ports import Clock, SystemClock
from wev_skills.governance.audit import AuditLog

NOT_A_TERMINAL = "stdin and stdout are not both a terminal"
WRONG_WORD = "the confirmation word did not match"
UNKNOWN_OPERATOR = "unknown"
UNKNOWN_TERMINAL = "unknown-terminal"
CONFIRM_WORDS = (
    "amber", "cedar", "delta", "ember", "flint", "harbor", "maple", "onyx", "river", "willow",
)  # fmt: skip
"""Shown on screen; the operator types the one picked for this call."""


class OperatorPrompt(Protocol):
    """How the engine reaches the person at the keyboard. Tests inject a scripted one."""

    def terminal(self) -> str | None:
        """The terminal device when stdin and stdout are both one, else ``None``."""

    def confirm(self, summary: str, word: str) -> str:
        """Show ``summary``, ask for ``word`` and return what was typed."""


class TerminalPrompt:
    """The real prompt: reads the controlling terminal through stdin and stdout."""

    def terminal(self) -> str | None:
        streams = (sys.stdin, sys.stdout)
        try:
            if any(stream is None or not stream.isatty() for stream in streams):
                return None
            return os.ttyname(sys.stdin.fileno())
        except OSError, ValueError, AttributeError:
            return None

    def confirm(self, summary: str, word: str) -> str:
        sys.stdout.write(f"{summary}\n{i18n.t('security.human.type_word', word=word)} ")
        sys.stdout.flush()
        try:
            return sys.stdin.readline()
        except OSError, ValueError:
            return ""


prompt_factory: Callable[[], OperatorPrompt] = TerminalPrompt
"""Replaced in tests (``tests.fixtures.operator_prompt``). Nothing a caller passes can set it."""


@dataclass(frozen=True)
class Confirmation(Serializable):
    """What the engine observed when the operator confirmed: a record, not an identity."""

    os_user: str
    terminal: str
    at: float

    def label(self) -> str:
        return f"terminal:{self.terminal} user:{self.os_user}"


def operator_name() -> str:
    """The operating-system user of this process (from the user id, not from ``$USER``)."""
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError, OSError:
        return UNKNOWN_OPERATOR


def confirm_human(
    audit: AuditLog,
    refused_event: str,
    subject: Mapping[str, Any],
    message: str,
    summary: str,
    clock: Clock | None = None,
) -> Confirmation:
    """Show ``summary`` to the operator and require the confirmation word; refuse otherwise.

    Without a terminal the call is refused with ``human_required`` and ``message``, which
    tells an agent to stop and ask the human. A wrong word is ``confirmation_mismatch``.
    Both refusals are audited.
    """
    prompt = prompt_factory()
    device = prompt.terminal()
    if device is None:
        audit.append(refused_event, {**subject, "why": NOT_A_TERMINAL})
        raise PermissionDenied("human_required", message, dict(subject))
    word = secrets.choice(CONFIRM_WORDS)
    typed = prompt.confirm(summary, word)
    if typed.strip().lower() != word:
        audit.append(refused_event, {**subject, "why": WRONG_WORD, "terminal": device})
        text = i18n.t("security.human.mismatch")
        raise PermissionDenied("confirmation_mismatch", text, dict(subject))
    now = (clock or SystemClock()).now()
    return Confirmation(operator_name(), device or UNKNOWN_TERMINAL, now)


def summary_lines(title: str, fields: Mapping[str, object]) -> str:
    """The text shown before the confirmation word: a title and one ``name: value`` per line."""
    width = max((len(name) for name in fields), default=0)
    rows = [f"  {name.ljust(width)}  {value}" for name, value in fields.items()]
    return "\n".join((title, *rows, i18n.t("security.human.limit")))
