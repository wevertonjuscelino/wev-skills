"""Free-text redaction rules: credential shapes that can be recognized without context.

Every quantifier is bounded and no rule can rescan the same span from many starting
points, so hostile input cannot make a substitution quadratic. Small bounds sit where a
pattern continues after the repeated part and could backtrack. A value that ends its
pattern cannot backtrack, so its bound (``MAX_VALUE``) is large: a secret is masked whole,
not up to a short limit with the rest left visible.
"""

from __future__ import annotations

import re
from collections.abc import Callable

MARKER = "[REDACTED]"
MAX_VALUE = 1_000_000

Replacement = str | Callable[[re.Match[str]], str]

# Lookarounds keep ordinary words out: ``author``, ``passenger``, ``token_count``, an
# uppercase ``PWD=/path`` and a test summary ``pass=12`` are not secret names.
_SECRET_WORDS = (
    r"pass(?:word|wd|phrase)"
    r"|(?<=[_-])pass(?![a-z])"
    r"|(?<![a-z0-9_-])pass(?=[ \t]{0,8}=[ \t]{0,8}(?!\d{1,9}\b))"
    r"|(?<=[_-])pwd"
    r"|(?<![a-z0-9_-])pwd(?=[ \t]{0,8}[:=][ \t]{0,8}[^\s/~$.])"
    r"|secret|token(?![a-z]|_(?:count|usage|limit|budget|type))"
    r"|api[_-]?key|access[_-]?key|private[_-]?key|account[_-]?key"
    r"|(?<=[a-z0-9][_-])(?<!public[_-])(?<!primary[_-])(?<!foreign[_-])(?<!sort[_-])"
    r"(?<!partition[_-])(?<!cache[_-])key(?![a-z0-9])"
    r"|authorization"
    r"|(?<=[_-])auth(?![a-z]|[_-](?:type|method|mode|scheme|url|uri|host|port|enabled))"
    r"|(?<![a-z0-9_-])auth(?=[ \t]{0,8}=)"
    r"|cookie|credential|session[_-]?id"
    r"|(?<![a-z])(?:senha|chave)"
)
SECRET_NAME = re.compile(_SECRET_WORDS, re.IGNORECASE)
# Names too short or too common to match inside a longer word, secret when they stand alone.
_BARE_SECRET_NAMES = frozenset({"pass", "pwd", "pw", "passwd", "auth", "senha", "chave"})


def is_secret_name(name: object) -> bool:
    """True when ``name`` (a mapping key or an option name) names a secret."""
    if not isinstance(name, str):
        return False
    return name.strip("_-").lower() in _BARE_SECRET_NAMES or SECRET_NAME.search(name) is not None


_QUOTED_DOUBLE = rf"\"(?:[^\"\\\n]|\\.){{0,{MAX_VALUE}}}\""
_QUOTED_SINGLE = rf"'(?:[^'\\\n]|\\.){{0,{MAX_VALUE}}}'"
_SCHEME = r"(?:(?:bearer|basic|token|digest)[ \t]{1,8})?"
_ASSIGNMENT = re.compile(
    rf"((?:{_SECRET_WORDS})[\w.-]{{0,64}}(?:\\?[\"']){{0,2}}[ \t]{{0,8}}(?:=>|[:=])[ \t]{{0,8}})"
    rf"(?:(?P<double>{_QUOTED_DOUBLE})|(?P<single>{_QUOTED_SINGLE})"
    rf"|(?P<escaped>\\\"[^\"\\\n]{{0,{MAX_VALUE}}}\\\")"
    rf"|(?P<open>(?:\\?[\"'])?){_SCHEME}[^\s,;&\"']{{1,{MAX_VALUE}}})",
    re.IGNORECASE,
)


def _mask_assignment(match: re.Match[str]) -> str:
    prefix = match.group(1)
    if match.group("double") is not None:
        return f'{prefix}"{MARKER}"'
    if match.group("single") is not None:
        return f"{prefix}'{MARKER}'"
    if match.group("escaped") is not None:
        return f'{prefix}\\"{MARKER}\\"'
    return f"{prefix}{match.group('open') or ''}{MARKER}"


_KEY_LABEL = r"[A-Z0-9 ]{0,40}PRIVATE KEY(?: BLOCK)?"
_KEY_BREAK = r"(?:\r?\n|\\r\\n|\\n)"
_KEY_GAP = r"(?:\r?\n|\\r\\n|\\n|[ \t]){1,16}"
_KEY_CHUNK = r"[A-Za-z0-9+/=][A-Za-z0-9+/=:,.()_-]{0,4095}"
_KEY_HEADER = r"(?:Proc-Type|DEK-Info|Version|Comment|Hash|Charset):[ \t][^\r\n\\\"']{0,256}"
_KEY_LINE = rf"(?:[A-Za-z0-9+/=]{{1,4096}}|{_KEY_HEADER}|)(?=\r?\n|\\[rn]|\Z|[\"'])"
# A complete block, whatever separates its lines (LF, CRLF, JSON-escaped breaks, spaces).
_KEY_BLOCK = re.compile(
    rf"-----BEGIN {_KEY_LABEL}-----"
    rf"(?:(?:{_KEY_GAP})?{_KEY_CHUNK}(?:{_KEY_GAP}{_KEY_CHUNK}){{0,4096}})?"
    rf"(?:{_KEY_GAP})?-----END {_KEY_LABEL}-----",
    re.IGNORECASE,
)
# A block with no END line: only the lines that still look like key material are masked.
_KEY_BLOCK_OPEN = re.compile(
    rf"-----BEGIN {_KEY_LABEL}-----(?:{_KEY_BREAK}{_KEY_LINE}){{0,4096}}", re.IGNORECASE
)

_HEADER_NAMES = (
    r"(?:proxy-)?authorization|(?:set-)?cookie"
    r"|x-(?:[a-z0-9]{1,24}-){0,4}(?:api-?key|key|auth|token|secret|signature|password|credential)"
    r"(?:-[a-z0-9]{1,24}){0,3}"
)
# A header quoted as a whole (``-H "Name: value"``, JSON) ends at that quote; an unquoted
# one runs to the end of the line, quotes inside the value included.
_HEADER = re.compile(
    rf"(?<![\w-])(?P<lead>[\"'])?(?P<name>(?:{_HEADER_NAMES})(?:\\?[\"']){{0,2}}[ \t]{{0,8}}:"
    rf"[ \t]{{0,8}}(?:\\?[\"'])?)"
    rf"(?(lead)(?:(?!\\?(?P=lead))[^\r\n]){{1,{MAX_VALUE}}}|[^\r\n]{{1,{MAX_VALUE}}})",
    re.IGNORECASE,
)

_URL_REST = rf"[^\s\"'<>]{{1,{MAX_VALUE}}}"
_WEBHOOK = re.compile(
    r"\b(https://(?:hooks\.slack\.com/(?:services|workflows|triggers)/"
    r"|(?:(?:canary|ptb)\.)?discord(?:app)?\.com/api/(?:v\d{1,2}/)?webhooks/"
    r"|[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63}){0,3}\.webhook\.office\.com/"
    r"|outlook\.office(?:365)?\.com/webhook/))" + _URL_REST,
    re.IGNORECASE,
)
_URL_SCHEME = r"[a-z][a-z0-9+.-]{0,20}://"
_URL_USER = r"[^\s:/@\[\]\"'<>]"
# ``host:8080/path/name@example.com`` is a port and a path, not a password.
_URL_PASSWORD = re.compile(
    rf"\b({_URL_SCHEME}{_URL_USER}{{0,256}}):(?!\d{{1,5}}(?:[/?#\s]|\Z))[^\s@\"'<>]{{1,512}}@",
    re.IGNORECASE,
)
_URL_USER_TOKEN = re.compile(rf"\b({_URL_SCHEME}){_URL_USER}{{20,256}}@", re.IGNORECASE)
_QUERY_PARAMETER = re.compile(
    r"([?&](?:(?:[\w.-]{0,24}[_.-])?"
    r"(?:token|key|sig|signature|secret|password|passwd|pwd|auth|credential)|apikey|code)=)"
    rf"[^\s&#\"'<>,;]{{1,{MAX_VALUE}}}",
    re.IGNORECASE,
)

_BEARER = re.compile(rf"\b(bearer[ \t]{{1,8}})[A-Za-z0-9._~+/=-]{{16,{MAX_VALUE}}}", re.IGNORECASE)
_MORE = rf",{MAX_VALUE}}}"  # closes a ``{low,`` repeat whose value ends the pattern
_TOKEN_SHAPES = (
    r"(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[A-Z0-9]{16}\b",  # AWS access key id
    r"gh[pousr]_[A-Za-z0-9]{20" + _MORE,  # GitHub
    r"github_pat_[A-Za-z0-9_]{20" + _MORE,
    r"glpat-[A-Za-z0-9_-]{16" + _MORE,  # GitLab
    r"xox[abeoprs]-[A-Za-z0-9-]{10" + _MORE,  # Slack
    r"[sr]k_(?:live|test)_[A-Za-z0-9]{10" + _MORE,  # Stripe secret and restricted keys
    r"whsec_[A-Za-z0-9+/=]{16" + _MORE,  # Stripe webhook signing secret
    r"sk-(?:ant|proj|svcacct|admin)-[A-Za-z0-9_-]{16" + _MORE,  # Anthropic, OpenAI
    r"[sr]k[-_][A-Za-z0-9_-]{20" + _MORE,  # other sk- and rk- style keys
    r"AIza[A-Za-z0-9_-]{30" + _MORE,  # Google API key
    r"ya29\.[A-Za-z0-9._-]{20" + _MORE,  # Google OAuth access token
    r"hf_[A-Za-z0-9]{20" + _MORE,  # Hugging Face
    r"SG\.[A-Za-z0-9_-]{16,128}\.[A-Za-z0-9_-]{16" + _MORE,  # SendGrid
    r"do[opr]_v1_[A-Za-z0-9]{32" + _MORE,  # DigitalOcean
    r"pypi-AgEI[A-Za-z0-9_-]{16" + _MORE,  # PyPI
    r"npm_[A-Za-z0-9]{30" + _MORE,  # npm
)
# A JWT continues after each long segment, so it may start only where the character before
# it could not belong to one: a long run is then read once, not once per position in it.
_JWT_SEGMENT = r"[A-Za-z0-9_-]{8" + _MORE
_JWT = rf"(?<![A-Za-z0-9_-])eyJ{_JWT_SEGMENT}\.eyJ{_JWT_SEGMENT}\.[A-Za-z0-9_-]{{4,{MAX_VALUE}}}"
_TOKEN = re.compile(r"\b(?:" + "|".join(_TOKEN_SHAPES) + ")|" + _JWT)

# Order matters: whole blocks, then headers and URLs, then named assignments, then bare
# token shapes.
_RULES: tuple[tuple[re.Pattern[str], Replacement], ...] = (
    (_KEY_BLOCK, MARKER),
    (_KEY_BLOCK_OPEN, MARKER),
    (_HEADER, rf"\g<lead>\g<name>{MARKER}"),
    (_WEBHOOK, rf"\g<1>{MARKER}"),
    (_URL_PASSWORD, rf"\g<1>:{MARKER}@"),
    (_URL_USER_TOKEN, rf"\g<1>{MARKER}@"),
    (_QUERY_PARAMETER, rf"\g<1>{MARKER}"),
    (_ASSIGNMENT, _mask_assignment),
    (_BEARER, rf"\g<1>{MARKER}"),
    (_TOKEN, MARKER),
)


def apply_text_rules(text: str) -> str:
    """``text`` with every context-free credential shape replaced by the marker."""
    result = text
    for pattern, replacement in _RULES:
        result = pattern.sub(replacement, result)
    return result
