"""A scripted ``AgentRunner`` for tests: no model, no network."""

import threading
from collections.abc import Callable, Sequence
from pathlib import Path

from wev_skills.agents.spec import AgentSpec
from wev_skills.core.contracts import AgentRunResult

Reply = str | AgentRunResult


class FakeAgent:
    """Writes the fix for the cases ``fixes(spec)`` names; ``ask`` gives scripted answers.

    Review runs are told apart by the objective: a verifier prompt asks for ``"votes"``.
    ``finder_replies`` and ``verifier_replies`` are consumed one per run (any thread takes
    the next); when empty a finder reports nothing and a verifier votes on nothing. A plain
    string is a normal answer, an ``AgentRunResult`` is returned as it is.
    """

    def __init__(
        self,
        fixes: Callable[[AgentSpec], set[str]] = lambda spec: set(),
        answers: tuple[str, ...] = (),
        finder_replies: Sequence[Reply] = (),
        verifier_replies: Sequence[Reply] = (),
    ):
        self.fixes, self.answers = fixes, list(answers)
        self.finder_replies, self.verifier_replies = list(finder_replies), list(verifier_replies)
        self.runs = 0
        self.prompts: list[str] = []
        self.tools: list[tuple[str, ...]] = []
        self.on_run: Callable[[], None] = lambda: None
        self.extra_file = False
        self.outcome: AgentRunResult | None = None
        self._lock = threading.Lock()

    def _scripted(self, objective: str) -> AgentRunResult | None:
        verifier = '"votes"' in objective
        queue = self.verifier_replies if verifier else self.finder_replies
        if not queue:
            empty = '{"votes": []}' if verifier else '{"findings": []}'
            return AgentRunResult(True, empty) if verifier or '"findings"' in objective else None
        reply = queue.pop(0)
        return reply if isinstance(reply, AgentRunResult) else AgentRunResult(True, reply)

    def run_agent(self, workspace: Path, spec: AgentSpec, objective: str, timeout: float, tools=()):  # type: ignore[no-untyped-def]
        with self._lock:
            self.runs += 1
            self.tools.append(tuple(tools))
            scripted = self._scripted(objective)
        self.on_run()
        if self.extra_file:
            (workspace / "scratch.txt").write_text("agent-wrote-this\n")
        if objective in self.fixes(spec):
            (workspace / f"fix-{objective}.txt").write_text("x")
        if scripted is not None:
            return scripted
        return self.outcome or AgentRunResult(True, "done")

    def ask(self, prompt: str, timeout: float):  # type: ignore[no-untyped-def]
        with self._lock:
            self.prompts.append(prompt)
            return AgentRunResult(True, self.answers.pop(0) if self.answers else "no")
