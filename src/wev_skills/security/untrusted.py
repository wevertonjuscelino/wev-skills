"""Mark external content as data and report instruction-like text inside it.

Repository files, logs, tool output and remote output are untrusted. ``sanitize``
removes terminal escape sequences and invisible characters, ``wrap`` fences such
text between markers that say it is data, and ``scan`` reports patterns that look
like instructions aimed at an agent.

Pattern matching cannot catch every injection: paraphrases, other languages,
encodings, look-alike letters and split payloads all get through. ``scan`` only
informs. The real control is structural: the engine never executes text returned
by tools, and every command still goes through the permission policy and approval
gates.
"""

from __future__ import annotations

import re
import secrets
import unicodedata
from dataclasses import dataclass

from wev_skills import i18n
from wev_skills.core._codec import Serializable
from wev_skills.security.redact import redact

MARKER_STEM = "WEV_UNTRUSTED_DATA"
NEUTRALIZED = "[neutralized-marker]"
MAX_EXCERPT = 160
MAX_FINDINGS = 100
MAX_SOURCE = 200
MAX_WRAP_CHARS = 200_000

_STEM_LOOKALIKE = re.compile(r"WEV[\W_]{0,8}UNTRUSTED[\W_]{0,8}DATA", re.IGNORECASE)
_STEM_KEY = "WEVUNTRUSTEDDATA"
_NOT_ALNUM = re.compile(r"[\W_]")
# ``[ \t]*`` right after a line anchor is linear: only line starts can match it. ``\s``
# there would also cross newlines, which makes every line start rescan the lines after it.
_FENCE_END = re.compile(r"^(?P<indent>[ \t]*)<{3,}[ \t]*(?=END)", re.IGNORECASE | re.MULTILINE)
_NONCE = re.compile(r"[0-9a-f]{8,64}")

_ESCAPES = re.compile(
    r"\x1b\[[0-?]{0,64}[ -/]{0,8}[@-~]"  # CSI: colors, cursor movement, erase
    r"|\x1b\][^\x07\x1b\n]{0,4096}(?:\x07|\x1b\\)?"  # OSC up to BEL or ST: titles, links
    r"|\x1b[P^_X][^\x1b\n]{0,4096}(?:\x1b\\)?"  # DCS, PM, APC and SOS strings
    r"|\x1b[ -/]{0,8}[0-~]?"  # any other escape, and a lone ESC
)
_LINE_SEPARATORS = (0x2028, 0x2029)
_CONTROL_CODES = (*range(0x00, 0x20), 0x7F, *range(0x80, 0xA0))
_KEPT_CONTROLS = frozenset({0x09, 0x0A})
_INVISIBLE_CODES = (
    0x00AD,  # soft hyphen
    0x034F,  # combining grapheme joiner
    0x061C,  # arabic letter mark
    *range(0x180B, 0x180F),  # mongolian variation selectors and vowel separator
    *range(0x200B, 0x2010),  # zero-width space and joiners, direction marks
    *range(0x202A, 0x202F),  # bidirectional embeddings and overrides
    *range(0x2060, 0x2065),  # word joiner and invisible operators
    *range(0x2066, 0x2070),  # bidirectional isolates and deprecated format characters
    0xFEFF,  # zero-width no-break space
    *range(0xFFF9, 0xFFFC),  # interlinear annotation marks
    *range(0xE0000, 0xE0080),  # tag characters
)
_SANITIZE_TABLE: dict[int, str | None] = {
    **{code: None for code in _CONTROL_CODES if code not in _KEPT_CONTROLS},
    **{code: None for code in _INVISIBLE_CODES},
    **{code: "\n" for code in _LINE_SEPARATORS},
}
_VARIATION_SELECTORS = (*range(0xFE00, 0xFE10), *range(0xE0100, 0xE01F0))
_SCAN_TABLE: dict[int, str | None] = {
    **_SANITIZE_TABLE,
    **{code: None for code in _VARIATION_SELECTORS},
}
# A few Cyrillic and Greek letters that look like the Latin letters of the marker stem.
# Not a full confusables table: it only makes the commonest look-alike fences fail.
_CONFUSABLES = str.maketrans(
    "АВЕЅТаеѕԁԜԝѴѵΑΕΝΤνυ",
    "ABESTaesdWwVvAENTvu",
)


@dataclass(frozen=True)
class Finding(Serializable):
    """One instruction-like match. ``start`` is an offset into ``normalize(text)``."""

    category: str
    excerpt: str
    start: int


def _flags(pattern: str, ignore_case: bool = True) -> re.Pattern[str]:
    return re.compile(pattern, re.MULTILINE | (re.IGNORECASE if ignore_case else 0))


_SECRET_NOUNS = (
    r"(?:api[ _-]?keys?|passwords?|credentials?|secrets?|tokens?|private keys?|ssh keys?"
    r"|\.env\b|system prompt|senhas?|credenciais|chaves?)"
)
_ROLE_SUFFIX = r"(?: (?:prompt|message|override))?"
# Every gap is bounded and horizontal whitespace is ``[ \t]``, never ``\s``, so no pattern
# can rescan the same span from many starting points.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        _flags(
            r"\b(?:ignor(?:e|em|a|ar|en|ad)|disregard|forget|override"
            r"|desconsider(?:e|em|a|ar)|esque[çc]am?|olvid(?:a|e|en|ad))\b"
            r"[^.\n]{0,40}\b(?:instructions?|prompts?|rules|directives|guidelines"
            r"|instru[çc](?:ão|ões|ao|oes)|instrucci(?:ón|on|ones)|regras|reglas)\b"
        ),
    ),
    (
        "override_instructions",
        _flags(
            r"\b(?:new|updated|novas?|nuevas?) "
            r"(?:instructions?|instruções|instrucciones)[ \t]{0,8}:"
        ),
    ),
    (
        "authority_claim",
        _flags(rf"^[ \t]*(?:system|developer|assistant){_ROLE_SUFFIX}[ \t]{{0,8}}:"),
    ),
    (
        "authority_claim",
        _flags(
            r"(?<=[.!?;:])[ \t]{1,4}(?:SYSTEM|DEVELOPER|ASSISTANT)"
            r"(?: (?:PROMPT|MESSAGE|OVERRIDE))?[ \t]{0,4}:"
            r"|^[ \t]{0,3}#{1,6}[ \t]{1,8}(?:SYSTEM|DEVELOPER)"
            r"(?: (?:PROMPT|MESSAGE|OVERRIDE|INSTRUCTIONS))?[ \t]{0,8}:?[ \t]{0,8}$"
            r"|^[ \t]*\n(?:Human|Assistant)[ \t]{0,4}:",
            ignore_case=False,
        ),
    ),
    (
        "authority_claim",
        _flags(
            r"</?[ \t]{0,8}(?:system|developer)\b[^>\n]{0,40}>|\[(?:system|inst)\]"
            r"|<\|(?:im_start|im_end|system|user|assistant|start_header_id|eot_id|endoftext)\|>"
        ),
    ),
    (
        "authority_claim",
        _flags(
            r"\b(?:i am|this is|message from|as) (?:the |your )?"
            r"(?:system|developer|administrator|operator|anthropic)\b|\byou are now\b"
        ),
    ),
    (
        "credential_or_exfiltration",
        _flags(
            r"\b(?:send|post|upload|email|forward|exfiltrate|reveal|print|show|paste|share|leak"
            r"|envie|mostre|revele)\b[^\n]{0,80}?" + _SECRET_NOUNS
        ),
    ),
    (
        "disable_safety",
        _flags(
            r"\b(?:disable|bypass|skip|turn off|circumvent|without|desative|ignore)\b[^.\n]{0,40}"
            r"\b(?:safety|security|guardrails?|permissions?|approvals?|verification|sandbox|hooks?"
            r"|seguran[çc]a|aprova[çc](?:ão|ões))\b"
            r"|--no-verify\b|--dangerously-skip-permissions\b"
        ),
    ),
    (
        "piped_download",
        _flags(
            r"\b(?:curl|wget)\b[^\n|]{0,200}\|[ \t]{0,8}(?:sudo[ \t]{1,8})?"
            r"(?:(?:ba|z|da|k)?sh|python[\d.]{0,8})\b"
            r"|\b(?:ba|z)?sh[ \t]{1,8}<\([ \t]{0,8}(?:curl|wget)\b"
            r"|\biex[ \t]{0,8}\([ \t]{0,8}(?:iwr|irm)\b"
        ),
    ),
    (
        "operator_command",
        _flags(
            r"\bwev[ \t]{1,8}(?:approval[ \t]{1,8}grant|guard[ \t]{1,8}acknowledge"
            r"|task[ \t]{1,8}reopen|specialists[ \t]{1,8}(?:accept|retire))\b"
        ),
    ),
)


def sanitize(text: str) -> str:
    """``text`` without terminal escape sequences, control or invisible characters.

    Removes CSI, OSC and other escape sequences, C0 and C1 control characters and DEL
    (``\\n`` and ``\\t`` stay, ``\\r`` is dropped), and zero-width, bidirectional and tag
    characters. Unicode line separators become ``\\n`` so a line is always a visible line.
    Visible text is otherwise unchanged, and sanitizing twice changes nothing more.
    """
    return _ESCAPES.sub("", str(text)).translate(_SANITIZE_TABLE)


def normalize(text: str) -> str:
    """The form of ``text`` that ``scan`` reads: sanitized and NFKC-folded.

    Full-width and other compatibility characters become their plain form and variation
    selectors are removed, so hidden insertions do not split a phrase.
    """
    folded = unicodedata.normalize("NFKC", sanitize(text).translate(_SCAN_TABLE))
    return folded.translate(_SCAN_TABLE)


def _fold_marker(text: str) -> str:
    if text.isascii():
        return text
    return unicodedata.normalize("NFKC", text).translate(_CONFUSABLES)


def _has_stem(folded: str) -> bool:
    return _STEM_KEY in _NOT_ALNUM.sub("", folded).upper()


def _neutralize_line(line: str) -> str:
    folded = _fold_marker(line)
    if _has_stem(folded):
        return NEUTRALIZED
    fence = _FENCE_END.match(folded)
    if fence is None:
        return line
    return f"{fence.group('indent')}{NEUTRALIZED} {folded[fence.end() :]}"


def _neutralize(text: str) -> str:
    """Replace anything in ``text`` that could be read as one of the fence markers.

    Plain look-alikes are replaced in place. A line that only resembles the marker after
    Unicode folding (full-width letters, look-alike letters, long separator runs) is
    replaced whole, and a line that starts like a closing fence loses its ``<<<``.
    """
    replaced = _STEM_LOOKALIKE.sub(NEUTRALIZED, text)
    folded = _fold_marker(replaced)
    if not _has_stem(folded) and _FENCE_END.search(folded) is None:
        return replaced
    return "\n".join(_neutralize_line(line) for line in replaced.split("\n"))


def _clean_source(source: str) -> str:
    flat = _neutralize(" ".join(sanitize(source).split()))
    flat = flat.replace("<", "(").replace(">", ")").replace('"', "'")
    return flat[:MAX_SOURCE] or "unknown"


def _truncate(body: str, max_chars: int) -> tuple[str, int]:
    limit = max(0, max_chars)
    return body[:limit], max(0, len(body) - limit)


def wrap(text: str, source: str, nonce: str | None = None, max_chars: int = MAX_WRAP_CHARS) -> str:
    """Fence ``text`` as data from ``source`` that must not be followed as instructions.

    The body and the source label are sanitized first. The closing marker carries a random
    id, and anything in ``text`` that resembles a marker is neutralized, so the content
    cannot close the fence and continue as if it were trusted. A body longer than
    ``max_chars`` (counted after sanitizing) is cut, and a line inside the fence says how
    many characters were dropped. ``nonce`` exists for deterministic tests; leave it unset
    otherwise.
    """
    token = nonce if nonce and _NONCE.fullmatch(nonce) else secrets.token_hex(8)
    label = _clean_source(source)
    kept, dropped = _truncate(sanitize(text), max_chars)
    body = _neutralize(kept)
    if dropped:
        body = f"{body}\n{i18n.t('security.untrusted.truncated', dropped=dropped)}"
    notice = i18n.t("security.untrusted.notice", source=label)
    return (
        f'<<<{MARKER_STEM} id={token} source="{label}">>>\n'
        f"{notice}\n"
        f"{body}\n"
        f"<<<END_{MARKER_STEM} id={token}>>>"
    )


def scan(text: str) -> tuple[Finding, ...]:
    """Report instruction-like patterns in ``text``; never rewrites it.

    Matching runs on ``normalize(text)``, so escape sequences, zero-width characters and
    full-width letters do not hide a phrase, and each ``Finding.start`` is an offset into
    that normalized text (equal to the offset in ``text`` when nothing was removed or
    folded). Runs in time linear in the length of the text.

    This informs a reviewer or a log, it does not make the text safe: pattern matching
    cannot catch every injection. The real control is that the engine never executes
    text returned by tools.
    """
    content = normalize(text)
    found: list[Finding] = []
    for category, pattern in _PATTERNS:
        for match in pattern.finditer(content):
            excerpt = redact(" ".join(match.group(0).split())[:MAX_EXCERPT])
            found.append(Finding(category, excerpt, match.start()))
            if len(found) >= MAX_FINDINGS:
                return tuple(sorted(found, key=lambda item: item.start))
    return tuple(sorted(found, key=lambda item: item.start))
