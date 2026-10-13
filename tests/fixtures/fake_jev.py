#!/usr/bin/env python3
"""Stand-in for the ``jev`` CLI. Behavior comes from the environment.

FAKE_JEV_MODE: ok (the recorded real response) | high-risk | complex | parallel-yes |
               low-confidence | mid-confidence | uncertain-noul | bad-index | negative-index |
               unknown-choice | wrong-types | bool-score | bool-noul | noul-out-of-range |
               bad-confidence | badshape | missing-answer | error | garbage | slow
Tool selection: when the questions file holds ``tool_<Name>`` or ``profile`` questions the
fake answers those instead (shapes follow the recorded response: ``noul`` is a number in
[0, 1] with no confidence, ``choice`` carries ``choice`` and ``confidence``).
FAKE_JEV_TOOL_ANSWERS: JSON object of tool name to noul value; others get FAKE_JEV_TOOL_DEFAULT
               (default 0.9).
FAKE_JEV_PROFILE / FAKE_JEV_PROFILE_CONFIDENCE: the ``profile`` choice (structured, 1).
FAKE_JEV_MODE for tools: tools-badshape (a noul given as text) | tools-missing (one answer
               absent) | tools-not-object (a list) | tools-bad-profile | error | garbage | slow
FAKE_JEV_STATE_COPY: path where the state file content seen by the fake is written.
FAKE_JEV_QUESTIONS_COPY: path where the questions file content is written.
FAKE_JEV_ARGV_COPY: path where the received argv is written as JSON.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SLOW_SECONDS = 30
TOOL_PREFIX = "tool_"
PROFILE_KEY = "profile"
FIXTURE = Path(__file__).with_name("jev_ask_response_2026-10-13.json")


def _arg(name: str) -> str:
    argv = sys.argv
    return argv[argv.index(name) + 1] if name in argv else ""


def _copy(env_name: str, text: str) -> None:
    target = os.environ.get(env_name)
    if target:
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _fixture() -> dict[str, dict[str, object]]:
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)  # type: ignore[no-any-return]


def _with(
    data: dict[str, dict[str, object]], key: str, **fields: object
) -> dict[str, dict[str, object]]:
    return {**data, key: {**data[key], **fields}}


def _answers(mode: str) -> dict[str, object]:
    """Every mode derives from the recorded real response (the ``ok`` mode serves it as is)."""
    data = _fixture()
    variants = {
        "high-risk": lambda: _with(data, "risk", choice="high"),
        "complex": lambda: _with(data, "complexity", score=3),
        "parallel-yes": lambda: _with(data, "parallelizable", noul=0.9),
        "low-confidence": lambda: _with(
            _with(data, "complexity", score=3, confidence=0.3), "risk", choice="low", confidence=0.5
        ),
        "mid-confidence": lambda: _with(data, "complexity", score=2, confidence=0.8),
        "uncertain-noul": lambda: _with(data, "parallelizable", noul=0.5),
        "bad-index": lambda: _with(data, "complexity", score=4),
        "negative-index": lambda: _with(data, "complexity", score=-1),
        "unknown-choice": lambda: _with(data, "risk", choice="extreme"),
        "wrong-types": lambda: _with(data, "complexity", score="0"),
        "bool-score": lambda: _with(data, "complexity", score=False),
        "bool-noul": lambda: _with(data, "parallelizable", noul=True),
        "noul-out-of-range": lambda: _with(data, "parallelizable", noul=1.5),
        "bad-confidence": lambda: _with(data, "risk", confidence=2),
        "badshape": lambda: {**data, "complexity": {"unexpected": 1}},
        "missing-answer": lambda: {k: v for k, v in data.items() if k != "parallelizable"},
    }
    return variants.get(mode, lambda: data)()


def _tool_answers(mode: str, questions: dict[str, object]) -> object:
    """Answers for a tool-selection questions file, in the recorded answer shapes."""
    given = json.loads(os.environ.get("FAKE_JEV_TOOL_ANSWERS", "{}"))
    default = float(os.environ.get("FAKE_JEV_TOOL_DEFAULT", "0.9"))
    answers: dict[str, object] = {}
    for key in questions:
        if key == PROFILE_KEY:
            choice = (
                "turbo"
                if mode == "tools-bad-profile"
                else os.environ.get("FAKE_JEV_PROFILE", "structured")
            )
            sure = float(os.environ.get("FAKE_JEV_PROFILE_CONFIDENCE", "1"))
            answers[key] = {"type": "choice", "choice": choice, "confidence": sure}
        else:
            value = given.get(key[len(TOOL_PREFIX) :], default)
            answers[key] = {"type": "noul", "noul": "yes" if mode == "tools-badshape" else value}
    if mode == "tools-missing":
        answers.pop(next(iter(answers)))
    return list(answers) if mode == "tools-not-object" else answers


def _is_tool_request(questions: dict[str, object]) -> bool:
    return any(key == PROFILE_KEY or key.startswith(TOOL_PREFIX) for key in questions)


def main() -> int:
    mode = os.environ.get("FAKE_JEV_MODE", "ok")
    _copy("FAKE_JEV_ARGV_COPY", json.dumps(sys.argv[1:]))
    _copy("FAKE_JEV_STATE_COPY", _read(_arg("--state-file")))
    questions_text = _read(_arg("--questions"))
    _copy("FAKE_JEV_QUESTIONS_COPY", questions_text)
    if mode == "error":
        sys.stderr.write("jev: boom\n")
        return 1
    if mode == "slow":
        time.sleep(SLOW_SECONDS)
    if mode == "garbage":
        sys.stdout.write("this is not json")
        return 0
    questions = json.loads(questions_text)
    if _is_tool_request(questions):
        sys.stdout.write(json.dumps(_tool_answers(mode, questions)))
        return 0
    sys.stdout.write(json.dumps(_answers(mode)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
