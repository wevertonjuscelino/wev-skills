"""Token estimation for budgeting the context the engine assembles."""

from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text`` as characters divided by 4, rounded up.

    This is an estimate, not a tokenizer: real counts depend on the model and the language of
    the text, and can differ substantially. Empty text is 0; any non-empty text is at least 1.
    """
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
