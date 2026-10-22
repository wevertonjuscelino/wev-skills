"""Split a shell command line into simple commands without running a shell.

``security.commands.parse`` refuses any string whose meaning depends on a shell. A hook
that sees the command a model wants to run needs more: ``cd src && make test`` is two
ordinary commands. ``split_commands`` cuts a line at the control operators, respecting
quotes, and lifts redirections out of each argv, so every part can be judged by the same
policy as a single argv.

It is deliberately small and refuses (returns ``None``) whatever it cannot split with
certainty: unbalanced quotes, command and process substitution, here-documents, subshells
and groups, shell keywords, and a redirection target that comes from a variable. Refusing
is safe because the caller then asks a human instead of deciding. A command word that comes
from a variable is reported as ``dynamic`` rather than refused, so the caller can still
recognize a known program path such as ``"$ROOT/bin/tool"`` by its name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

CONTROL_CHARS = ";|&\n"
BLANK_CHARS = " \t"
GLOB_CHARS = "*?[{"
TEST_COMMAND = "["
DOUBLE_QUOTE_ESCAPES = '"\\$`\n'
SHELL_KEYWORDS = frozenset(
    {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac",
     "function", "select", "time", "coproc", "!", "{", "}", "[["}
)  # fmt: skip
_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_FD = re.compile(r"[0-9]+")
_DUP_TARGET = re.compile(r"[0-9]+-?|-")


@dataclass(frozen=True)
class SimpleCommand:
    """One command of a line: its argv and the files its redirections read or write."""

    argv: tuple[str, ...]
    redirects: tuple[str, ...] = ()
    dynamic: bool = False
    """The command word holds a ``$`` expansion, so which program runs is unknown here."""
    assignments: tuple[str, ...] = ()
    """Names set by leading ``NAME=value`` words; a part may be nothing but assignments."""
    unresolved: bool = False
    """Some word depends on the shell: a parameter expansion, ``$'...'``, a glob, a brace
    expansion or ``~user``. What the program receives is unknown here."""
    expands: bool = False
    """Some word holds a ``$`` expansion, so a path it names cannot be known here."""
    rewritten: tuple[bool, ...] = field(default=(), compare=False)
    """Per word of ``argv``: the shell would rewrite it (see ``unresolved``). A detail of
    ``unresolved``, so it takes no part in equality."""


class _Unsafe(Exception):
    """The line cannot be split with certainty."""


@dataclass(frozen=True)
class _Word:
    text: str
    quoted: bool = False
    """Any part was quoted or escaped, so the word is never an fd number or a comment."""
    expands: bool = False
    """Holds an unquoted or double-quoted ``$``: its value is unknown here."""
    head: str = ""
    """The characters typed before the first quote or escape (``NAME=`` of ``NAME='a b'``)."""
    glob: bool = False
    """Holds an unquoted ``*``, ``?``, ``[`` or ``{``: the shell may rewrite the word."""


@dataclass(frozen=True)
class _Part:
    """A simple command being read: its words, and whether a redirection awaits its target."""

    words: tuple[_Word, ...] = ()
    redirects: tuple[str, ...] = ()
    pending: str = ""
    """``"file"`` or ``"dup"`` while a redirection operator still needs its target."""


@dataclass(frozen=True)
class _Scan:
    done: tuple[_Part, ...] = ()
    part: _Part = field(default_factory=_Part)
    word: _Word | None = None


def _end_word(scan: _Scan) -> _Scan:
    """Close the word being read: it is an argument, or the target of a pending redirection."""
    word, part = scan.word, scan.part
    if word is None:
        return scan
    if part.pending == "dup" and not word.quoted and _DUP_TARGET.fullmatch(word.text):
        return replace(scan, part=replace(part, pending=""), word=None)
    if part.pending:
        if word.expands or not word.text:
            raise _Unsafe
        closed = replace(part, redirects=(*part.redirects, word.text), pending="")
        return replace(scan, part=closed, word=None)
    return replace(scan, part=replace(part, words=(*part.words, word)), word=None)


def _end_part(scan: _Scan) -> _Scan:
    closed = _end_word(scan)
    if closed.part.pending:
        raise _Unsafe
    return _Scan((*closed.done, closed.part))


def _append(
    scan: _Scan, text: str, quoted: bool = False, expands: bool = False, glob: bool = False
) -> _Scan:
    word = scan.word or _Word("")
    plain = not (word.quoted or quoted)
    head = word.head + text if plain else word.head
    grown = _Word(
        word.text + text, word.quoted or quoted, word.expands or expands, head, word.glob or glob
    )
    return replace(scan, word=grown)


def _single_quoted(line: str, start: int, scan: _Scan) -> tuple[_Scan, int]:
    end = line.find("'", start + 1)
    if end < 0:
        raise _Unsafe
    return _append(scan, line[start + 1 : end], quoted=True), end + 1


def _double_quoted(line: str, start: int, scan: _Scan) -> tuple[_Scan, int]:
    index, current = start + 1, _append(scan, "", quoted=True)
    while index < len(line):
        char = line[index]
        if char == '"':
            return current, index + 1
        if char == "`" or line.startswith("$(", index):
            raise _Unsafe
        if char == "\\" and line[index + 1 : index + 2] in tuple(DOUBLE_QUOTE_ESCAPES):
            escaped = line[index + 1]
            current = _append(current, "" if escaped == "\n" else escaped)
            index += 2
            continue
        current = _append(current, char, expands=char == "$")
        index += 1
    raise _Unsafe


def _redirection(line: str, index: int, scan: _Scan) -> tuple[_Scan, int]:
    """Read the operator at ``index`` (``>``, ``>>``, ``>|``, ``<``, ``>&``, ``<&``, ``&>``)."""
    word = scan.word
    is_fd = word is not None and not word.quoted and _FD.fullmatch(word.text) is not None
    current = replace(scan, word=None) if is_fd else _end_word(scan)
    if current.part.pending:
        raise _Unsafe
    both = line[index] == "&"
    at = index + 1 if both else index
    arrow, rest = line[at], line[at + 1 : at + 2]
    if rest == "(" or (arrow == "<" and rest in ("<", ">")):
        raise _Unsafe  # process substitution, here-document, here-string, read-write
    width = 2 if rest in (">", "|", "&") and (arrow == ">" or rest == "&") else 1
    kind = "dup" if rest == "&" and not both else "file"
    return replace(current, part=replace(current.part, pending=kind)), at + width


def _control(line: str, index: int, scan: _Scan) -> tuple[_Scan, int]:
    """A control operator ends the command; ``&>`` and ``&>>`` are redirections instead."""
    if line.startswith("&>", index):
        return _redirection(line, index, scan)
    width = 2 if line[index : index + 2] in ("&&", "||", "|&", ";;") else 1
    return _end_part(scan), index + width


def _step(line: str, index: int, scan: _Scan) -> tuple[_Scan, int]:
    """Consume the token at ``index``; returns the new scan and the next index."""
    char = line[index]
    if char in BLANK_CHARS:
        return _end_word(scan), index + 1
    if char == "#" and scan.word is None:
        end = line.find("\n", index)
        return scan, len(line) if end < 0 else end
    if char == "'":
        return _single_quoted(line, index, scan)
    if char == '"':
        return _double_quoted(line, index, scan)
    if char == "\\":
        if index + 1 >= len(line):
            raise _Unsafe
        escaped = line[index + 1]
        return (scan if escaped == "\n" else _append(scan, escaped, quoted=True)), index + 2
    if char in "`()" or line.startswith("$(", index):
        raise _Unsafe
    if char in "<>":
        return _redirection(line, index, scan)
    if char in CONTROL_CHARS:
        return _control(line, index, scan)
    return _append(scan, char, expands=char == "$", glob=char in GLOB_CHARS), index + 1


def _unresolved(word: _Word) -> bool:
    """The shell would rewrite this word: expansion, glob, brace list or ``~user``."""
    tilde = word.head.startswith("~") and word.head[1:2] not in ("", "/")
    glob = word.glob and word.text != TEST_COMMAND
    return word.expands or glob or tilde


def _finish(part: _Part) -> SimpleCommand | None:
    """The command of one part: leading assignments dropped, keywords and unknowns refused."""
    words, names = list(part.words), []
    while words and _ASSIGNMENT.match(words[0].head):
        names.append(words[0].head.split("=", 1)[0].rstrip("+"))
        words = words[1:]
    unresolved = any(_unresolved(word) for word in part.words)
    expands = any(word.expands for word in part.words)
    if not words:
        if not names and not part.redirects:
            return None
        return SimpleCommand((), part.redirects, False, tuple(names), unresolved, expands)
    head = words[0]
    if not head.quoted and head.text in SHELL_KEYWORDS:
        raise _Unsafe
    if any(not word.quoted and word.text in ("{", "}") for word in words):
        raise _Unsafe
    argv = tuple(word.text for word in words)
    rewritten = tuple(_unresolved(word) for word in words)
    return SimpleCommand(
        argv, part.redirects, head.expands, tuple(names), unresolved, expands, rewritten
    )


def split_commands(line: str) -> tuple[SimpleCommand, ...] | None:
    """The simple commands of ``line`` in order, or ``None`` when it cannot be split safely.

    An empty tuple means the line runs nothing (blank, a comment, only assignments).
    """
    if not isinstance(line, str) or "\x00" in line:
        return None
    scan, index = _Scan(), 0
    try:
        while index < len(line):
            scan, index = _step(line, index, scan)
        parts = _end_part(scan).done
        commands = [_finish(part) for part in parts]
    except _Unsafe:
        return None
    return tuple(command for command in commands if command is not None)
