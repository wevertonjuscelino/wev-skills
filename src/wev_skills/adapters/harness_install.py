"""Install the wev package into a harness and undo it, recorded in a manifest.

Only Codex has an installer. The package is built under
``<data_home>/wev-skills/harness/<target>/package`` and registered with the harness CLI
(``codex plugin marketplace add`` then ``codex plugin add``, docs/research/harness-codex.md
section 1). The CLI runs through the injected ``Runner``, never a shell. The manifest next
to the package lists every file written and every registration with its inverse, so
``uninstall`` removes those entries and nothing else. Hook trust is the person's step.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.harness_package import PACKAGE_NAME, build_package
from wev_skills.core.errors import NotFound, RemoteError, ValidationError
from wev_skills.core.fsutil import atomic_write_text
from wev_skills.core.ports import Runner

INSTALLABLE = ("codex",)
PLACEHOLDER_MARK = "// wev-placeholder"
MARKETPLACE_FILE = ".agents/plugins/marketplace.json"
CODEX = "codex"
CLI_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class Manifest:
    """``registrations`` hold pairs of argv in order: a registration, then its inverse."""

    target: str
    files: tuple[str, ...]
    registrations: tuple[tuple[str, ...], ...]


def _root(data_home: Path, target: str) -> Path:
    return data_home / PACKAGE_NAME / "harness" / target


def _check_target(target: str) -> None:
    if target not in INSTALLABLE:
        message = i18n.t("harness.error.not_installable", target=target)
        raise ValidationError("harness_not_installable", message)


def _read(root: Path) -> Manifest | None:
    path = root / "manifest.json"
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    regs = tuple(tuple(r) for r in data["registrations"])
    return Manifest(data["target"], tuple(data["files"]), regs)


def _write(root: Path, manifest: Manifest) -> None:
    data = {
        "target": manifest.target,
        "files": list(manifest.files),
        "registrations": [list(r) for r in manifest.registrations],
    }
    atomic_write_text(root / "manifest.json", json.dumps(data, indent=2) + "\n")


def _run(runner: Runner, argv: tuple[str, ...]) -> None:
    result = runner.run(argv, None, CLI_TIMEOUT_SECONDS, None)
    if result.exit_code == 0:
        return
    detail = (result.stderr or result.stdout).strip()[:300]
    message = i18n.t("harness.error.cli_failed", command=" ".join(argv), detail=detail)
    raise RemoteError("harness_cli_failed", message, {"argv": list(argv)})


def _undo(runner: Runner, registrations: tuple[tuple[str, ...], ...], strict: bool) -> None:
    """Run the inverses newest first. ``strict`` raises on the first failure."""
    first_error: RemoteError | None = None
    for inverse in reversed(registrations[1::2]):
        try:
            _run(runner, inverse)
        except RemoteError as exc:
            first_error = first_error or exc
    if strict and first_error is not None:
        raise first_error


def _remove_files(files: tuple[str, ...]) -> None:
    parents: set[Path] = set()
    for name in files:
        path = Path(name)
        path.unlink(missing_ok=True)
        parents.update(path.parents)
    for directory in sorted(parents, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()  # only an empty directory goes: a file of the person stays
        except OSError:
            continue


def _marketplace_text() -> str:
    source = {"source": "local", "path": "./"}
    plugin = {"name": PACKAGE_NAME, "source": source}
    return json.dumps({"name": PACKAGE_NAME, "plugins": [plugin]}, indent=2) + "\n"


def _check_placeholders(files: list[Path]) -> None:
    for path in files:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0].strip()
        if first == PLACEHOLDER_MARK:
            message = i18n.t("harness.error.placeholder", path=str(path))
            raise ValidationError("harness_placeholder", message, {"path": str(path)})


def _build(target: str, package: Path, wev_path: Path) -> tuple[str, ...]:
    if package.exists():
        shutil.rmtree(package)
    files = build_package(target, package, wev_path)
    market = package / MARKETPLACE_FILE
    atomic_write_text(market, _marketplace_text())
    files = [*files, market]
    _check_placeholders(files)
    return tuple(str(p) for p in files)


def _codex_registrations(package: Path) -> tuple[tuple[str, ...], ...]:
    plugin = f"{PACKAGE_NAME}@{PACKAGE_NAME}"
    return (
        (CODEX, "plugin", "marketplace", "add", str(package)),
        (CODEX, "plugin", "marketplace", "remove", PACKAGE_NAME),
        (CODEX, "plugin", "add", plugin),
        (CODEX, "plugin", "remove", plugin),
    )


def _register(runner: Runner, registrations: tuple[tuple[str, ...], ...]) -> None:
    done: list[tuple[str, ...]] = []
    try:
        for register, inverse in zip(registrations[0::2], registrations[1::2], strict=True):
            _run(runner, register)
            done.extend((register, inverse))
    except BaseException:
        _undo(runner, tuple(done), strict=False)
        raise


def install(target: str, runner: Runner, data_home: Path, wev_path: Path) -> Manifest:
    """Build and register the package; on any failure leave nothing behind."""
    _check_target(target)
    root = _root(data_home, target)
    previous = _read(root)
    if previous is not None:
        _undo(runner, previous.registrations, strict=False)
        _remove_files(previous.files)
    package = root / "package"
    try:
        files = _build(target, package, wev_path)
    except BaseException:
        shutil.rmtree(package, ignore_errors=True)
        raise
    registrations = _codex_registrations(package)
    try:
        _register(runner, registrations)
        manifest = Manifest(target, files, registrations)
        _write(root, manifest)
    except BaseException:
        _remove_files(files)
        shutil.rmtree(package, ignore_errors=True)
        raise
    return manifest


def uninstall(target: str, runner: Runner, data_home: Path) -> Manifest:
    """Undo the registrations and remove the files the manifest lists, and only those."""
    _check_target(target)
    root = _root(data_home, target)
    manifest = _read(root)
    if manifest is None:
        message = i18n.t("harness.error.not_installed", target=target)
        raise NotFound("harness_not_installed", message)
    _undo(runner, manifest.registrations, strict=True)
    _remove_files(manifest.files)
    (root / "manifest.json").unlink()
    return manifest
