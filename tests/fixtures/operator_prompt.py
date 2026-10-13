"""A scripted operator prompt for tests of the human-operator commands.

The real commands need a terminal and a typed confirmation word. Tests replace the prompt
factory in ``commands._human``; there is no flag or environment variable that does this.
"""

from __future__ import annotations

import json
import os
import pty
import re
import select
import subprocess
import time
from collections.abc import Callable, Sequence
from typing import Any
from unittest import mock

from wev_skills.commands import _human

TEST_TERMINAL = "/dev/ttys-test"


class ScriptedPrompt:
    """Answers with the word shown (or ``answer``), and keeps what the operator was shown."""

    def __init__(self, terminal: str | None = TEST_TERMINAL, answer: str | None = None) -> None:
        self._terminal = terminal
        self._answer = answer
        self.shown: list[str] = []
        self.words: list[str] = []

    def terminal(self) -> str | None:
        return self._terminal

    def confirm(self, summary: str, word: str) -> str:
        self.shown.append(summary)
        self.words.append(word)
        return word if self._answer is None else self._answer


def at_terminal(prompt: ScriptedPrompt | None = None) -> Any:
    """A ``mock.patch`` that puts an operator who confirms at a terminal."""
    scripted = prompt if prompt is not None else ScriptedPrompt()
    return mock.patch.object(_human, "prompt_factory", lambda: scripted)


def no_terminal() -> Any:
    """A ``mock.patch`` for a caller without a terminal (what an agent has)."""
    return at_terminal(ScriptedPrompt(terminal=None))


PTY_TIMEOUT_SECONDS = 60
_WORD = re.compile(r"Type (" + "|".join(_human.CONFIRM_WORDS) + r") and press Enter")
"""The English prompt line (callers pass ``--lang en``)."""


def _read_until(descriptor: int, done: Callable[[str], bool], deadline: float) -> str:
    """Read from the terminal until ``done`` accepts the text, it closes, or time runs out."""
    text = ""
    while not done(text) and time.monotonic() < deadline:
        ready, _, _ = select.select([descriptor], [], [], 0.1)
        if not ready:
            continue
        try:
            chunk = os.read(descriptor, 4096)
        except OSError:
            break
        if not chunk:
            break
        text += chunk.decode("utf-8", errors="replace")
    return text


def run_at_pty(
    argv: Sequence[str], cwd: str, env: dict[str, str], answer: str | None = None
) -> tuple[int, str, str]:
    """Run a real CLI process on a pseudo-terminal and type the confirmation word it shows.

    This is the real ``TerminalPrompt`` end to end. It is also exactly what a process that
    wants to pose as the operator can do, which is why the prompt is friction and not proof.
    Returns ``(exit code, what the terminal showed, stderr)``.
    """
    leader, follower = pty.openpty()
    process = subprocess.Popen(  # noqa: S603 - argv comes from the test
        list(argv), cwd=cwd, env=env, stdin=follower, stdout=follower, stderr=subprocess.PIPE
    )
    os.close(follower)
    deadline = time.monotonic() + PTY_TIMEOUT_SECONDS
    try:
        shown = _read_until(leader, lambda text: _WORD.search(text) is not None, deadline)
        found = _WORD.search(shown)
        typed = answer if answer is not None else (found.group(1) if found else "")
        os.write(leader, (typed + "\n").encode())
        shown += _read_until(leader, lambda _text: process.poll() is not None, deadline)
        shown += _read_until(leader, lambda _text: False, time.monotonic() + 0.3)
        code = process.wait(timeout=PTY_TIMEOUT_SECONDS)
        stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    finally:
        os.close(leader)
        if process.poll() is None:
            process.kill()
        if process.stderr:
            process.stderr.close()
    return code, shown, stderr


def last_json(text: str) -> Any:
    """The JSON object a CLI printed after its prompt on the same terminal."""
    start = text.rfind("\n{")
    return json.loads(text[start:].replace("\r\n", "\n")) if start >= 0 else None
