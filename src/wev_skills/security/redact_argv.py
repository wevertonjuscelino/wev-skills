"""Command-line redaction: secrets that only the surrounding command reveals.

``--password VALUE`` or ``mysql -pVALUE`` carry a secret that has no shape of its own.
``mask_argv`` works on a real argument vector, where token boundaries are exact;
``apply_cli_rules`` applies the same knowledge to a command written inside free text,
where the program is looked for earlier on the same line.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Sequence
from functools import partial

from wev_skills.security.redact_rules import MARKER, MAX_VALUE, is_secret_name

CONTEXT_CHARS = 300
_COMMAND_BREAKS = "\n|;&"

_PASSWORD_CLIENTS = frozenset({"mysql", "mariadb", "mysqldump", "mysqladmin", "sshpass"})
_LOGIN_CLIENTS = frozenset({"docker", "podman"})
_LOGIN = "login"
_REDIS_CLIENT = "redis-cli"
_WEB_CLIENTS = frozenset({"curl", "wget"})
_KNOWN_PROGRAMS = _PASSWORD_CLIENTS | _LOGIN_CLIENTS | _WEB_CLIENTS | {_LOGIN, _REDIS_CLIENT}
_LONG_USER_FLAGS = frozenset({"--user", "--proxy-user"})
_PASSWORD_FLAG = "-p"
_REDIS_PASSWORD_FLAG = "-a"
_SHORT_USER_FLAG = "-u"
_EXECUTABLE_SUFFIX = ".exe"
# Options that name a secret but take something else: a file, a prompt, a setting.
_VALUE_ELSEWHERE = re.compile(r"[_-](?:stdin|file|path|fd|prompt|env|jar|name|type|ttl|length)$")

_FLAG_NAME = re.compile(r"--?[a-z][\w.-]{1,60}", re.IGNORECASE)

_EXPECT_NOTHING = ""
_EXPECT_SECRET = "secret"
_EXPECT_USER_PASSWORD = "user_password"


def is_secret_flag(flag: str) -> bool:
    """True for an option such as ``--password`` whose value is a secret."""
    if _FLAG_NAME.fullmatch(flag) is None or _VALUE_ELSEWHERE.search(flag.lower()):
        return False
    return is_secret_name(flag)


def _program_name(token: str) -> str:
    """Lower-case basename of ``token`` when it is a program this module knows, else ''."""
    if token.startswith("-"):
        return ""
    name = token.replace("\\", "/").rsplit("/", 1)[-1].lower()
    name = name[: -len(_EXECUTABLE_SUFFIX)] if name.endswith(_EXECUTABLE_SUFFIX) else name
    return name if name in _KNOWN_PROGRAMS else ""


def _takes_password_flag(programs: frozenset[str]) -> bool:
    if programs & _PASSWORD_CLIENTS:
        return True
    return _LOGIN in programs and bool(programs & _LOGIN_CLIENTS)


def _mask_user_password(value: str) -> str:
    user, separator, password = value.partition(":")
    return f"{user}:{MARKER}" if separator and password else value


def _mask_option_with_value(name: str, value: str, programs: frozenset[str]) -> str:
    """``--name=value`` with the value masked when the option carries a secret."""
    if not value:
        return f"{name}="
    if is_secret_flag(name):
        return f"{name}={MARKER}"
    if name in _LONG_USER_FLAGS and programs & _WEB_CLIENTS:
        return f"{name}={_mask_user_password(value)}"
    return f"{name}={value}"


def _mask_long_option(token: str, programs: frozenset[str]) -> tuple[str, str]:
    """A ``--name`` or ``--name=value`` token and what the next token is expected to be."""
    name, separator, value = token.partition("=")
    if separator:
        return _mask_option_with_value(name, value, programs), _EXPECT_NOTHING
    if is_secret_flag(token):
        return token, _EXPECT_SECRET
    if token in _LONG_USER_FLAGS and programs & _WEB_CLIENTS:
        return token, _EXPECT_USER_PASSWORD
    return token, _EXPECT_NOTHING


def _mask_short_option(token: str, programs: frozenset[str]) -> tuple[str, str]:
    """A ``-x`` or joined ``-xVALUE`` token and what the next token is expected to be."""
    takes_password = _takes_password_flag(programs)
    is_web_client = bool(programs & _WEB_CLIENTS)
    if token == _PASSWORD_FLAG and takes_password:
        return token, _EXPECT_SECRET
    if token == _REDIS_PASSWORD_FLAG and _REDIS_CLIENT in programs:
        return token, _EXPECT_SECRET
    if token == _SHORT_USER_FLAG and is_web_client:
        return token, _EXPECT_USER_PASSWORD
    if token.startswith(_PASSWORD_FLAG) and takes_password:
        return f"{_PASSWORD_FLAG}{MARKER}", _EXPECT_NOTHING
    if token.startswith(_SHORT_USER_FLAG) and is_web_client:
        joined = token[len(_SHORT_USER_FLAG) :]
        return f"{_SHORT_USER_FLAG}{_mask_user_password(joined)}", _EXPECT_NOTHING
    return token, _EXPECT_NOTHING


def _mask_token(token: str, expected: str, programs: frozenset[str]) -> tuple[str, str]:
    is_option = token.startswith("-") and len(token) > 1
    if not is_option:
        if expected == _EXPECT_SECRET:
            return MARKER, _EXPECT_NOTHING
        if expected == _EXPECT_USER_PASSWORD:
            return _mask_user_password(token), _EXPECT_NOTHING
        return token, _EXPECT_NOTHING
    if token.startswith("--") or is_secret_flag(token.partition("=")[0]):
        return _mask_long_option(token, programs)
    return _mask_short_option(token, programs)


def mask_argv(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """``tokens`` with option values that are secrets masked; same length, new tuple.

    A program counts from the token where it appears (matched by basename), so the
    ``-p`` of ``grep -p mysql`` is left alone. A token that starts with ``-`` is always
    read as an option, never as the value of the option before it.
    """
    masked: list[str] = []
    programs: frozenset[str] = frozenset()
    expected = _EXPECT_NOTHING
    for token in tokens:
        value, expected = _mask_token(token, expected, programs)
        masked.append(value)
        program = _program_name(token)
        if program:
            programs = programs | {program}
    return tuple(masked)


_VALUE = re.compile(
    rf"(?P<double>\"(?:[^\"\\\n]|\\.){{0,{MAX_VALUE}}}\")"
    rf"|(?P<single>'(?:[^'\\\n]|\\.){{0,{MAX_VALUE}}}')"
    rf"|(?P<bare>[^\s\"'-][^\s\"']{{0,{MAX_VALUE}}})"
)
_USER_PASSWORD = re.compile(rf"(?P<bare>[^\s\"']{{1,{MAX_VALUE}}})")
# These match the option and the gap after it; the value is matched separately, so an
# option that is left alone never swallows the option that follows it.
_LONG_FLAG = re.compile(r"(?<![\w-])(?P<flag>--?[a-z][\w.-]{1,60})(?:=|[ \t]{1,8})", re.IGNORECASE)
_SHORT_FLAG = re.compile(r"(?<![\w-])(?P<flag>-[pa])(?P<gap>[ \t]{0,8})")
_USER_FLAG = re.compile(
    r"(?<![\w-])(?:-u[ \t]{0,8}|(?:--user|--proxy-user)(?:=|[ \t]{1,8}))[\"']?"
    r"[^\s:\"'-][^\s:\"']{0,255}:"
)
_PROGRAM = r"(?<![\w.-])(?:{names})(?:\.exe)?(?![\w-])"
_PASSWORD_CONTEXT = re.compile(
    _PROGRAM.format(names="|".join(sorted(_PASSWORD_CLIENTS)))
    + "|"
    + _PROGRAM.format(names="|".join(sorted(_LOGIN_CLIENTS)))
    + r"[^\n|;&]{0,80}?(?<![\w-])login(?![\w-])",
    re.IGNORECASE,
)
_REDIS_CONTEXT = re.compile(_PROGRAM.format(names=re.escape(_REDIS_CLIENT)), re.IGNORECASE)
_WEB_CONTEXT = re.compile(_PROGRAM.format(names="|".join(sorted(_WEB_CLIENTS))), re.IGNORECASE)


def _program_ends(pattern: re.Pattern[str], text: str) -> tuple[int, ...]:
    """Offsets where a program matched by ``pattern`` ends in ``text``, in order."""
    return tuple(match.end() for match in pattern.finditer(text))


def _follows_program(ends: Sequence[int], match: re.Match[str]) -> bool:
    """True when ``match`` sits in the same command as a program, shortly after it."""
    position = match.start()
    index = bisect_right(ends, position) - 1
    if index < 0 or position - ends[index] > CONTEXT_CHARS:
        return False
    between = match.string[ends[index] : position]
    return not any(separator in between for separator in _COMMAND_BREAKS)


def _masked_value(value: re.Match[str]) -> str:
    groups = value.groupdict()
    if groups.get("double") is not None:
        return f'"{MARKER}"'
    if groups.get("single") is not None:
        return f"'{MARKER}'"
    return MARKER


def _mask_values(
    text: str,
    option: re.Pattern[str],
    value: re.Pattern[str],
    carries_secret: Callable[[re.Match[str]], bool],
) -> str:
    """``text`` with the value after each ``option`` match masked when it carries a secret."""
    pieces: list[str] = []
    cursor = 0
    for found in option.finditer(text):
        if found.start() < cursor or not carries_secret(found):
            continue
        secret = value.match(text, found.end())
        if secret is None:
            continue
        pieces.append(text[cursor : secret.start()])
        pieces.append(_masked_value(secret))
        cursor = secret.end()
    pieces.append(text[cursor:])
    return "".join(pieces)


def _is_secret_long_flag(found: re.Match[str]) -> bool:
    return is_secret_flag(found.group("flag"))


def _is_password_flag(
    found: re.Match[str], password_ends: Sequence[int], redis_ends: Sequence[int]
) -> bool:
    if found.group("flag") == _PASSWORD_FLAG:
        return _follows_program(password_ends, found)
    return bool(found.group("gap")) and _follows_program(redis_ends, found)


def apply_cli_rules(text: str) -> str:
    """``text`` with secret option values masked in the commands it contains.

    A short option such as ``-p`` is masked only when one of the known programs appears
    before it in the same command (same line, no ``|``, ``;`` or ``&`` in between, at most
    ``CONTEXT_CHARS`` characters back).
    """
    result = _mask_values(text, _LONG_FLAG, _VALUE, _is_secret_long_flag)
    password_ends = _program_ends(_PASSWORD_CONTEXT, result)
    redis_ends = _program_ends(_REDIS_CONTEXT, result)
    if password_ends or redis_ends:
        is_password = partial(_is_password_flag, password_ends=password_ends, redis_ends=redis_ends)
        result = _mask_values(result, _SHORT_FLAG, _VALUE, is_password)
    web_ends = _program_ends(_WEB_CONTEXT, result)
    if web_ends:
        follows_web_client = partial(_follows_program, web_ends)
        result = _mask_values(result, _USER_FLAG, _USER_PASSWORD, follows_web_client)
    return result
