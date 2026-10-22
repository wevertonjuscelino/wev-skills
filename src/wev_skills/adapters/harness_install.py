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
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.harness_package import PACKAGE_NAME, build_package
from wev_skills.core.errors import NotFound, RemoteError, ValidationError, WevError
from wev_skills.core.fsutil import atomic_write_text, ensure_private_dir
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


def _invalid(path: Path, why: str) -> ValidationError:
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


def _read(root: Path) -> Manifest | None:
    """The manifest, checked: it is data, so what it holds is compared, never obeyed."""
    path = root / "manifest.json"
    if not path.is_file():
        return None
    package = root / "package"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files, regs = data["files"], data["registrations"]
        target = data["target"]
        stored = tuple(tuple(r) for r in regs)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _invalid(path, type(exc).__name__) from exc
    if target not in INSTALLABLE or not isinstance(files, list):
        raise _invalid(path, "target or files")
    if stored != _codex_registrations(package):
        raise _invalid(path, "registrations")
    if not all(_confined(name, package) for name in files):
        raise _invalid(path, "files")
    return Manifest(target, tuple(files), stored)


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


def _remove_files(files: tuple[str, ...], root: Path, extra: Path | None = None) -> None:
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


def _check_placeholders(files: list[Path]) -> None:
    for path in files:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0].strip()
        if first == PLACEHOLDER_MARK:
            message = i18n.t("harness.error.placeholder", path=str(path))
            raise ValidationError("harness_placeholder", message, {"path": str(path)})


def _refuse_symlinks(destination: Path, package: Path) -> None:
    """A symlink at the package or inside it would make the copy write elsewhere."""
    if not _confined(str(destination), package):
        raise _unsafe(destination)
    current = destination.parent
    while True:
        if current.is_symlink():
            raise _unsafe(current)
        if current == package:
            return
        current = current.parent


def _unsafe(path: Path) -> ValidationError:
    message = i18n.t("harness.error.symlink", path=str(path))
    return ValidationError("harness_symlink", message, {"path": str(path)})


def _build(target: str, root: Path, wev_path: Path, written: list[str]) -> None:
    """Build in a staging directory, then copy into the package, so a file of the person
    already in the package never blocks the build. ``written`` records each copied file as
    it is copied, so a failure part-way can still be rolled back."""
    package = root / "package"
    ensure_private_dir(root)
    staging = Path(tempfile.mkdtemp(dir=root, prefix=".staging-"))
    try:
        built = build_package(target, staging, wev_path)
        market = staging / MARKETPLACE_FILE
        atomic_write_text(market, _marketplace_text())
        built = [*built, market]
        _check_placeholders(built)
        targets = [package / source.relative_to(staging) for source in built]
        for destination in targets:
            _refuse_symlinks(destination, package)
        for source, destination in zip(built, targets, strict=True):
            atomic_write_text(destination, source.read_text(encoding="utf-8"))
            written.append(str(destination))
    finally:
        shutil.rmtree(staging, ignore_errors=True)


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
    failed = _undo(runner, previous.registrations, strict=False)
    if failed:  # keep the old manifest and files: the person can retry the uninstall
        message = i18n.t("harness.error.undo_previous", command=" ".join(failed[0]))
        raise RemoteError("harness_undo_failed", message, {"undo_failed": failed})
    _remove_files(previous.files, root)
    (root / "manifest.json").unlink(missing_ok=True)  # it would list undone registrations


def install(target: str, runner: Runner, data_home: Path, wev_path: Path) -> Manifest:
    """Build and register the package; on any failure undo what this call did."""
    _check_target(target)
    root = _root(data_home, target)
    base = data_home / PACKAGE_NAME
    created_base = None if base.exists() else base
    previous = _read(root)
    if previous is not None:
        _undo_previous(runner, previous, root)
    files: list[str] = []
    try:
        _build(target, root, wev_path, files)
        registrations = _codex_registrations(root / "package")
        _register(runner, registrations)
    except BaseException:
        _remove_files(tuple(files), root, created_base)
        raise
    manifest = Manifest(target, tuple(files), registrations)
    try:
        _write(root, manifest)
    except OSError as exc:
        wrapped = _rollback_failures(runner, registrations, exc)
        _remove_files(tuple(files), root, created_base)
        raise wrapped from exc
    except BaseException:
        _remove_files(tuple(files), root, created_base)
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
    _remove_files(manifest.files, root)
    (root / "manifest.json").unlink()
    return manifest
