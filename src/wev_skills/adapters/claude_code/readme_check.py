"""Check a project's README files against the README standard (skill ``wev-readme``).

The rules are pure functions (text in, findings out); only ``resolve_directory``, ``read_text``,
``find_logo`` and ``check_directory`` touch the filesystem, and they only read. Every message goes
through the i18n catalog, so a finding carries a stable rule name and a localized sentence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.claude_code.claude_md import find_repo_root
from wev_skills.adapters.claude_code.readme_parse import (
    CODE_SPAN,
    README_NAME,
    README_PT_NAME,
    CodeBlock,
    Document,
    Finding,
    ReadmeError,
    ReadmeReport,
    link_location,
    make_finding,
    normalize_heading,
    parse,
    path_exists,
    resolve_link,
    targets,
)
from wev_skills.core.errors import NotFound
from wev_skills.security.paths import resolve_within

__all__ = ["MAX_RECOMMENDED_LINES", "ReadmeError"]

MAX_RECOMMENDED_LINES = 350
TWIN_LINK_WINDOW = 12
ADMONITION_KINDS = ("NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION")
CREDITS_HEADINGS = frozenset({"credits", "créditos", "creditos"})
FORBIDDEN_HEADINGS = frozenset(
    {
        "license", "licence", "licenses", "contributing", "contribute", "contributions",
        "how to contribute", "changelog", "change log", "code of conduct", "security",
        "security policy", "licença", "licenca", "licença de uso", "contribuindo",
        "contribuição", "contribuicao", "contribuições", "como contribuir",
        "registro de alterações", "histórico de alterações", "histórico de mudanças",
        "código de conduta", "segurança", "seguranca", "política de segurança",
    }
)  # fmt: skip
LOGO_DIRS = ("", "assets", "docs/assets", ".github")
LOGO_EXTENSIONS = frozenset({".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"})


_BEFORE_TITLE_OK = re.compile(r"^\s*(<|!\[|\[!\[)")
_QUOTE = re.compile(r"^\s{0,3}>(.*)$")
_MARKER = re.compile(r"^\s*\[!(\s*)([A-Za-z]+)(\s*)\](.*)$")
_SHORTCODE = re.compile(r"(?<![\w:/])(:[a-z0-9_+-]{2,}:)(?![\w:])")
_LOGO_NAME = re.compile(r"^(logo|icon)([-_.].*)?$", re.IGNORECASE)
_EMOJI = re.compile(
    "[\u231a-\u231b\u23e9-\u23f3\u23f8-\u23fa\u2600-\u27bf\u2b05-\u2b07\u2b1b-\u2b1c"
    "\u2b50\u2b55\ufe0f\u20e3\U0001f000-\U0001faff]"
)
_PLACEHOLDERS = (
    re.compile(r"\b(TODO|TBD)\b"),
    re.compile(r"lorem ipsum", re.IGNORECASE),
    re.compile(r"\byour-(org|username|user|name|repo|company)\b", re.IGNORECASE),
    re.compile(r"\bexample\.(com|org|net)\b", re.IGNORECASE),
    re.compile(r"github\.com/(username|user|owner|org|<[^>]+>)/", re.IGNORECASE),
)


# --- single-file rules -------------------------------------------------------------------------


def _title(doc: Document, name: str) -> list[Finding]:
    firsts = [h for h in doc.headings if h[1] == 1]
    found = []
    if len(firsts) != 1:
        found.append(
            make_finding("title_count", firsts[1][0] if firsts else 1, name, count=len(firsts))
        )
    if firsts:
        for number, line in doc.prose:
            if number >= firsts[0][0]:
                break
            if line.strip() and not _BEFORE_TITLE_OK.match(line):
                found.append(make_finding("title_first", number, name))
                break
    return found


def _forbidden(doc: Document, name: str) -> list[Finding]:
    return [
        make_finding("forbidden_section", number, name, heading=text)
        for number, _, text in doc.headings
        if normalize_heading(text) in FORBIDDEN_HEADINGS
    ]


def _emoji(text: str, doc: Document, name: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        match = _EMOJI.search(line)
        if match:
            found.append(make_finding("emoji", number, name, text=f"U+{ord(match.group()):04X}"))
    for number, line in doc.prose:
        match = _SHORTCODE.search(CODE_SPAN.sub("", line))
        if match:
            found.append(make_finding("emoji", number, name, text=match.group(1)))
    return found


def _links(doc: Document, name: str, root: Path, directory: Path) -> list[Finding]:
    found: list[Finding] = []
    for number, target in targets(doc.prose):
        where = link_location(target)
        if where is None:
            continue
        resolved = resolve_link(root, directory, where)
        if resolved is None:
            found.append(make_finding("link_outside_root", number, name, target=target))
        elif not path_exists(resolved):
            found.append(make_finding("link_missing", number, name, target=target))
    return found


def _marker_problem(match: re.Match[str], raw: str) -> str | None:
    kind = match.group(2)
    if kind.upper() not in ADMONITION_KINDS:
        return "admonition_kind"
    spaced = match.group(1) or match.group(3) or match.group(4).strip()
    if kind != kind.upper() or spaced or not raw.startswith(" "):
        return "admonition_syntax"
    return None


def _admonitions(doc: Document, name: str) -> list[Finding]:
    found: list[Finding] = []
    pending: int | None = None
    inside = False
    for number, line in [*doc.prose, (0, "")]:
        quote = _QUOTE.match(line)
        if quote is None:
            if pending is not None:
                found.append(make_finding("admonition_syntax", pending, name))
            pending, inside = None, False
            continue
        raw = quote.group(1)
        marker = _MARKER.match(raw)
        if marker is None:
            pending = pending if not raw.strip() else None
        else:
            problem = _marker_problem(marker, raw) if not inside else "admonition_syntax"
            kind = marker.group(2)
            if problem:
                found.append(make_finding(problem, number, name, kind=kind))
            else:
                pending = number
        inside = True
    return found


def _fences(doc: Document, name: str) -> list[Finding]:
    found = []
    for block in doc.blocks:
        if not block.closed:
            found.append(make_finding("fence_unclosed", block.line, name))
        if not block.language:
            found.append(make_finding("fence_language", block.line, name))
    return found


def _placeholders(text: str, name: str) -> list[Finding]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern in _PLACEHOLDERS:
            match = pattern.search(line)
            if match:
                found.append(make_finding("placeholder", number, name, text=match.group()))
                break
    return found


def check_document(text: str, name: str, root: Path, directory: Path) -> tuple[Finding, ...]:
    """Every single-file rule except length and credits, ordered by line."""
    doc = parse(text)
    found = [
        *_title(doc, name),
        *_forbidden(doc, name),
        *_emoji(text, doc, name),
        *_links(doc, name, root, directory),
        *_admonitions(doc, name),
        *_fences(doc, name),
        *_placeholders(text, name),
    ]
    return tuple(sorted(found, key=lambda f: f.line))


def length_warnings(text: str, name: str) -> tuple[Finding, ...]:
    count = len(text.splitlines())
    if count <= MAX_RECOMMENDED_LINES:
        return ()
    return (make_finding("readme_long", count, name, lines=count, limit=MAX_RECOMMENDED_LINES),)


def check_credits(text: str, name: str, *, required: bool = False) -> tuple[Finding, ...]:
    seconds = [h for h in parse(text).headings if h[1] == 2]
    credits = [h for h in seconds if normalize_heading(h[2]) in CREDITS_HEADINGS]
    if not credits:
        return (make_finding("credits_missing", 1, name),) if required else ()
    if seconds[-1] is credits[-1]:
        return ()
    return (make_finding("credits_last", credits[-1][0], name, heading=credits[-1][2]),)


# --- twins -------------------------------------------------------------------------------------


def _links_to(text: str, other: str) -> bool:
    head = parse("\n".join(text.splitlines()[:TWIN_LINK_WINDOW]))
    return any(Path(link_location(t) or "").name == other for _, t in targets(head.prose))


def check_twins(english: str, portuguese: str, names: tuple[str, str]) -> tuple[Finding, ...]:
    en_name, pt_name = names
    en, pt = parse(english), parse(portuguese)
    found: list[Finding] = []
    counts = [sum(1 for h in d.headings if h[1] == 2) for d in (en, pt)]
    if counts[0] != counts[1]:
        found.append(
            make_finding("twin_headings", 1, pt_name, english=counts[0], portuguese=counts[1])
        )
    for text, own, other in ((english, en_name, pt_name), (portuguese, pt_name, en_name)):
        if not _links_to(text, other):
            found.append(make_finding("twin_link", 1, own, other=other, lines=TWIN_LINK_WINDOW))
    mismatch = _first_block_mismatch(en.blocks, pt.blocks)
    if mismatch is not None:
        found.append(make_finding("twin_code", mismatch, pt_name, other=en_name))
    return tuple(found)


def _first_block_mismatch(en: tuple[CodeBlock, ...], pt: tuple[CodeBlock, ...]) -> int | None:
    for first, second in zip(en, pt, strict=False):
        if first.content != second.content:
            return second.line
    if len(en) != len(pt):
        longer = pt if len(pt) > len(en) else en
        return longer[min(len(en), len(pt))].line
    return None


# --- logo --------------------------------------------------------------------------------------


def find_logo(root: Path) -> Path | None:
    """The first logo-like image at the root or under assets/, docs/assets/ or .github/."""
    for relative in LOGO_DIRS:
        folder = root / relative if relative else root
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in LOGO_EXTENSIONS and _LOGO_NAME.match(path.stem):
                return path
    return None


def _header_uses(text: str, logo: Path, root: Path, directory: Path) -> bool:
    doc = parse(text)
    first_section = next((h[0] for h in doc.headings if h[1] == 2), doc.total_lines + 1)
    header = tuple((n, line) for n, line in doc.prose if n < first_section)
    for _, target in targets(header):
        where = link_location(target)
        resolved = resolve_link(root, directory, where) if where else None
        if resolved is not None and resolved == logo.resolve():
            return True
    return False


# --- filesystem --------------------------------------------------------------------------------


def resolve_directory(root: Path, directory: Path) -> Path:
    """``directory`` resolved inside ``root``; it must exist."""
    resolved = resolve_within(root, directory)
    if not resolved.is_dir():
        message = i18n.t("readme.error.no_dir", None, path=str(resolved))
        raise NotFound("readme_no_dir", message, {"path": str(resolved)})
    return resolved


def read_text(root: Path, path: Path) -> str | None:
    """File text, or ``None`` when absent. A path that leaves ``root`` raises PermissionDenied."""
    resolved = resolve_within(root, path)
    if not resolved.is_file():
        return None
    try:
        return resolved.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        message = i18n.t("readme.error.bad_encoding", None, path=str(path))
        raise ReadmeError("readme_bad_encoding", message, {"path": str(path)}) from exc
    except OSError as exc:
        message = i18n.t("readme.error.unreadable", None, path=str(path), reason=exc.strerror)
        raise NotFound("readme_unreadable", message, {"path": str(path)}) from exc


def _file_findings(
    texts: dict[str, str], root: Path, directory: Path, credits_last: bool | None
) -> tuple[list[Finding], list[Finding]]:
    findings: list[Finding] = []
    warnings: list[Finding] = []
    for name, text in texts.items():
        findings.extend(check_document(text, name, root, directory))
        warnings.extend(length_warnings(text, name))
        if credits_last is not False:
            findings.extend(check_credits(text, name, required=credits_last is True))
    return findings, warnings


def _logo_status(
    texts: dict[str, str], root: Path, directory: Path
) -> tuple[dict[str, Any] | None, list[Finding]]:
    logo = find_logo(root)
    if logo is None:
        return None, []
    relative = logo.relative_to(root).as_posix()
    missing = [n for n, t in texts.items() if not _header_uses(t, logo, root, directory)]
    findings = [make_finding("logo_unused", 1, name, logo=relative) for name in missing]
    return {"path": relative, "used": not missing}, findings


def check_directory(
    directory: Path,
    root: Path | None = None,
    *,
    twin: bool | None = None,
    credits_last: bool | None = None,
) -> ReadmeReport:
    """Check ``README.md`` (and ``README.pt-BR.md`` when present) in ``directory``. Read-only."""
    base = find_repo_root(directory) if root is None else root.resolve()
    texts: dict[str, str] = {}
    missing: list[Finding] = []
    for name in (README_NAME, README_PT_NAME):
        text = read_text(base, directory / name)
        if text is not None:
            texts[name] = text
        elif name == README_NAME or twin is True:
            rule = "readme_missing" if name == README_NAME else "twin_missing"
            missing.append(make_finding(rule, 1, name))
    twin_expected = twin is not False and len(texts) == 2
    findings, warnings = _file_findings(texts, base, directory, credits_last)
    if twin_expected:
        findings.extend(
            check_twins(texts[README_NAME], texts[README_PT_NAME], (README_NAME, README_PT_NAME))
        )
    logo, logo_findings = _logo_status(texts, base, directory)
    order = {name: index for index, name in enumerate(texts)}
    ordered = sorted(
        [*missing, *findings, *logo_findings], key=lambda f: (order.get(f.file, 9), f.line)
    )
    return ReadmeReport(
        tuple(texts),
        tuple(ordered),
        tuple(warnings),
        logo,
        twin_expected,
        credits_last is not False,
    )
