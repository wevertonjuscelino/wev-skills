"""Install the wev package into a harness and undo it, recorded in a manifest.

Codex and Gemini CLI have an installer. The package is built under
``<data_home>/wev-skills/harness/<target>/package`` and registered with the harness CLI
(Codex: ``plugin marketplace add`` then ``plugin add``; Gemini: ``extensions validate``;
the ``extensions link`` step is the person's, because it asks them to accept a security
warning, so the manifest lists it only to name its inverse; docs/research/harness-*.md
section 1). The CLI runs through the injected ``Runner``, never a shell. The manifest next
to the package lists every file written and every registration with its
inverse, so ``uninstall`` removes those entries and nothing else. Hook trust is the person's step.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.harness_package import PACKAGE_NAME, build_package
from wev_skills.core.errors import NotFound, RemoteError, ValidationError, WevError
from wev_skills.core.fsutil import atomic_write_text, ensure_private_dir
from wev_skills.core.ports import Runner

INSTALLABLE = ("codex", "gemini")
PLACEHOLDER_MARK = "// wev-placeholder"
MARKETPLACE_FILE = ".agents/plugins/marketplace.json"
CODEX = "codex"
GEMINI = "gemini"
PERSON_LINKS = (GEMINI,)  # targets whose registration the person runs in a terminal
CLI_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True)
class Manifest:
    """``registrations`` hold pairs of argv in order: a registration, then its inverse."""

    target: str
    files: tuple[str, ...]
    registrations: tuple[tuple[str, ...], ...]
    created_dirs: tuple[str, ...] = ()  # directories wev created (opencode config dir)


def root_for(data_home: Path, target: str) -> Path:
    return data_home / PACKAGE_NAME / "harness" / target


def _check_target(target: str) -> None:
    if target not in INSTALLABLE:
        message = i18n.t("harness.error.not_installable", target=target)
        raise ValidationError("harness_not_installable", message)


def invalid(path: Path, why: str) -> ValidationError:
    message = i18n.t("harness.error.manifest_invalid", path=str(path), why=why)
    return ValidationError("harness_manifest_invalid", message, {"path": str(path)})


def _confined(name: object, package: Path) -> bool:
    """A path strictly inside ``package``, written without ``..`` and without symlinks."""
    if not isinstance(name, str):
        return False
    lexical = Path(os.path.normpath(name))
    try:
        relative = lexical.relative_to(package)
    except ValueError:
        return False
    if relative == Path("."):
        return False
    return Path(os.path.realpath(lexical)) == package.resolve() / relative


def _read(root: Path, expected: str) -> Manifest | None:
    package = root / "package"
    return read_manifest(
        root, expected, lambda name: _confined(name, package), _registrations(expected, package)
    )


def read_manifest(
    root: Path,
    expected: str,
    confined: Callable[[object], bool],
    registrations: tuple[tuple[str, ...], ...],
) -> Manifest | None:
    """The manifest, checked: it is data, so what it holds is compared, never obeyed."""
    path = root / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files, regs = data["files"], data["registrations"]
        target = data["target"]
        stored = tuple(tuple(r) for r in regs)
        dirs = data.get("created_dirs", [])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise invalid(path, type(exc).__name__) from exc
    if target != expected or not isinstance(files, list) or not isinstance(dirs, list):
        raise invalid(path, "target or files")
    if stored != registrations:
        raise invalid(path, "registrations")
    if not all(confined(name) for name in files):
        raise invalid(path, "files")
    return Manifest(target, tuple(files), stored, tuple(dirs))


def write_manifest(root: Path, manifest: Manifest) -> None:
    data = {
        "target": manifest.target,
        "files": list(manifest.files),
        "registrations": [list(r) for r in manifest.registrations],
    }
    if manifest.created_dirs:
        data["created_dirs"] = list(manifest.created_dirs)
    atomic_write_text(root / "manifest.json", json.dumps(data, indent=2) + "\n")


def _run(runner: Runner, argv: tuple[str, ...]) -> None:
    result = runner.run(argv, None, CLI_TIMEOUT_SECONDS, None)
    if result.exit_code == 0:
        return
    detail = (result.stderr or result.stdout).strip()[:300]
    message = i18n.t("harness.error.cli_failed", command=" ".join(argv), detail=detail)
    raise RemoteError("harness_cli_failed", message, {"argv": list(argv)})


def _undo(
    runner: Runner, registrations: tuple[tuple[str, ...], ...], strict: bool
) -> list[list[str]]:
    """Run the inverses newest first; return the ones that failed (``strict`` raises instead)."""
    failed: list[list[str]] = []
    first_error: RemoteError | None = None
    for inverse in reversed(registrations[1::2]):
        try:
            _run(runner, inverse)
        except RemoteError as exc:
            failed.append(list(inverse))
            first_error = first_error or exc
    if strict and first_error is not None:
        raise first_error
    return failed


def _roll_back(runner: Runner, done: tuple[tuple[str, ...], ...], error: BaseException) -> None:
    failed = _undo(runner, done, strict=False)
    if failed and isinstance(error, WevError):
        error.details["undo_failed"] = failed


def remove_files(files: tuple[str, ...], root: Path, extra: Path | None = None) -> None:
    """Unlink the listed files, then drop the empty directories wev made (package, root, the
    harness directory and ``extra``)."""
    package = root / "package"
    for name in files:
        Path(name).unlink(missing_ok=True)
    inner = {p for name in files for p in Path(name).parents if p.is_relative_to(package)}
    outer = {package, root, root.parent, *([extra] if extra else [])}
    for directory in sorted(inner | outer, key=lambda p: len(p.parts), reverse=True):
        try:
            directory.rmdir()  # only an empty directory goes: a file of the person stays
        except OSError:
            continue


def _marketplace_text() -> str:
    source = {"source": "local", "path": "./"}
    plugin = {"name": PACKAGE_NAME, "source": source}
    return json.dumps({"name": PACKAGE_NAME, "plugins": [plugin]}, indent=2) + "\n"


def check_placeholders(files: list[Path]) -> None:
    for path in files:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0].strip()
        if first == PLACEHOLDER_MARK:
            message = i18n.t("harness.error.placeholder", path=str(path))
            raise ValidationError("harness_placeholder", message, {"path": str(path)})


def _refuse_symlinks(destination: Path, package: Path) -> None:
    """A symlink at the package or inside it would make the copy write elsewhere."""
    current = destination.parent
    while current != package and current != current.parent:
        if current.is_symlink():  # name the link itself, not the file behind it
            raise _unsafe(current)
        current = current.parent
    if package.is_symlink():
        raise _unsafe(package)
    if not _confined(str(destination), package):
        raise _unsafe(destination)


def _unsafe(path: Path) -> ValidationError:
    message = i18n.t("harness.error.symlink", path=str(path))
    return ValidationError("harness_symlink", message, {"path": str(path)})


def _copy(source: Path, destination: Path) -> None:
    """Copy one file; an OSError becomes a RemoteError (exit 8), like the manifest write."""
    try:
        atomic_write_text(destination, source.read_text(encoding="utf-8"))
    except OSError as exc:
        message = i18n.t("harness.error.copy_failed", path=str(destination), error=str(exc))
        raise RemoteError("harness_copy_failed", message, {"path": str(destination)}) from exc


def copy_tree(sources: list[Path], destinations: list[Path], written: list[str]) -> None:
    """Copy each source to its destination, recording each in ``written`` as it is copied."""
    for source, destination in zip(sources, destinations, strict=True):
        _copy(source, destination)
        written.append(str(destination))


def _populate(
    target: str,
    runner: Runner,
    root: Path,
    wev_path: Path,
    previous: Manifest | None,
    written: list[str],
) -> None:
    """Build in a staging directory and check it, then undo the previous install and copy
    into the package, so a file of the person already in the package never blocks the build
    and a failed check leaves the previous install intact. ``written`` records each copied
    file as it is copied, so a failure part-way can still be rolled back."""
    package = root / "package"
    ensure_private_dir(root)
    staging = Path(tempfile.mkdtemp(dir=root, prefix=".staging-"))
    try:
        built = build_package(target, staging, wev_path)
        if target == CODEX:
            market = staging / MARKETPLACE_FILE
            atomic_write_text(market, _marketplace_text())
            built = [*built, market]
        check_placeholders(built)
        _check_package(runner, target, staging)
        if previous is not None:
            _undo_previous(runner, previous, root)
        targets = [package / source.relative_to(staging) for source in built]
        for destination in targets:
            _refuse_symlinks(destination, package)
        copy_tree(built, targets, written)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _registrations(target: str, package: Path) -> tuple[tuple[str, ...], ...]:
    if target == GEMINI:
        return _gemini_registrations(package)
    return _codex_registrations(package)


def _gemini_registrations(package: Path) -> tuple[tuple[str, ...], ...]:
    return (
        (GEMINI, "extensions", "link", str(package)),
        (GEMINI, "extensions", "uninstall", PACKAGE_NAME),
    )


def _check_package(runner: Runner, target: str, package: Path) -> None:
    """Gemini validates the extension before any registration; a failure stops the install."""
    if target == GEMINI:
        _run(runner, (GEMINI, "extensions", "validate", str(package)))


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
    except BaseException as exc:
        _roll_back(runner, tuple(done), exc)
        raise


def _rollback_failures(
    runner: Runner, registrations: tuple[tuple[str, ...], ...], error: OSError
) -> RemoteError:
    """The OSError as a RemoteError (exit 8) that lists the inverses that failed."""
    message = i18n.t("harness.error.manifest_write", error=str(error))
    wrapped = RemoteError("harness_manifest_write", message)
    _roll_back(runner, registrations, wrapped)
    return wrapped


def _undo_previous(runner: Runner, previous: Manifest, root: Path) -> None:
    # a person's link points at the package directory, which stays: reinstall keeps it
    registrations = () if previous.target in PERSON_LINKS else previous.registrations
    failed = _undo(runner, registrations, strict=False)
    if failed:  # keep the old manifest and files: the person can retry the uninstall
        message = i18n.t("harness.error.undo_previous", command=" ".join(failed[0]))
        raise RemoteError("harness_undo_failed", message, {"undo_failed": failed})
    remove_files(previous.files, root)
    (root / "manifest.json").unlink(missing_ok=True)  # it would list undone registrations


def install(target: str, runner: Runner, data_home: Path, wev_path: Path) -> Manifest:
    """Build and register the package; on any failure undo what this call did."""
    _check_target(target)
    root = root_for(data_home, target)
    base = data_home / PACKAGE_NAME
    created_base = None if base.exists() else base
    previous = _read(root, target)
    files: list[str] = []
    try:
        _populate(target, runner, root, wev_path, previous, files)
        registrations = _registrations(target, root / "package")
        performed = () if target in PERSON_LINKS else registrations
        _register(runner, performed)
    except BaseException:
        remove_files(tuple(files), root, created_base)
        raise
    manifest = Manifest(target, tuple(files), registrations)
    try:
        write_manifest(root, manifest)
    except OSError as exc:
        wrapped = _rollback_failures(runner, performed, exc)
        remove_files(tuple(files), root, created_base)
        raise wrapped from exc
    except BaseException:
        remove_files(tuple(files), root, created_base)
        raise
    return manifest


def uninstall(target: str, runner: Runner, data_home: Path) -> Manifest:
    """Undo the registrations and remove the files the manifest lists, and only those."""
    _check_target(target)
    root = root_for(data_home, target)
    manifest = _read(root, target)
    if manifest is None:
        message = i18n.t("harness.error.not_installed", target=target)
        raise NotFound("harness_not_installed", message)
    _undo(runner, manifest.registrations, strict=True)
    remove_files(manifest.files, root)
    (root / "manifest.json").unlink()
    remove_files((), root, data_home / PACKAGE_NAME)  # empty now that the manifest is gone
    return manifest
