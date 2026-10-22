"""Install the wev package into OpenCode and undo it.

OpenCode has no CLI to register plugins or skills (docs/research/harness-opencode.md
sections 2 to 4), so the files are copied into its config directory: ``plugins/wev-guard.js``,
``skills/wev-<name>/`` and ``agents/wev-<id>.md``. Every written path is in the manifest next
to the other targets' (``<data_home>/wev-skills/harness/opencode/manifest.json``). Install
refuses to overwrite a file the previous manifest does not list; uninstall removes the
manifest's entries and nothing else, after checking each is still one of those wev entries.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters.harness_install import Manifest, _check_placeholders, _invalid, _root
from wev_skills.adapters.harness_package import build_package
from wev_skills.core.errors import NotFound, RemoteError, StateConflict, ValidationError
from wev_skills.core.fsutil import atomic_write_text, ensure_private_dir

TARGET = "opencode"
PREFIX = "wev-"
PLUGIN = Path("plugins") / "wev-guard.js"


def _destination(relative: Path) -> Path:
    """Where a built file goes under the config dir: agents get the ``wev-`` prefix."""
    if relative.parts[0] == "agents":
        return Path("agents") / (PREFIX + relative.name)
    return relative


def _allowed(name: object, config: Path) -> bool:
    """A wev entry of the config dir (the plugin, a ``wev-`` skill file, a ``wev-`` agent),
    written without ``..`` and without symlinks."""
    if not isinstance(name, str):
        return False
    lexical = Path(os.path.normpath(name))
    try:
        relative = lexical.relative_to(config)
    except ValueError:
        return False
    parts = relative.parts
    kind = parts[0] if parts else ""
    named = len(parts) > 1 and parts[1].startswith(PREFIX)
    ok = relative == PLUGIN or (kind == "skills" and named and len(parts) > 2)
    ok = ok or (kind == "agents" and named and len(parts) == 2 and parts[1].endswith(".md"))
    return ok and Path(os.path.realpath(lexical)) == config.resolve() / relative


def _read(root: Path, config: Path) -> Manifest | None:
    path = root / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        files, target = data["files"], data["target"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise _invalid(path, type(exc).__name__) from exc
    if target != TARGET or not isinstance(files, list):
        raise _invalid(path, "target or files")
    if not all(_allowed(name, config) for name in files):
        raise _invalid(path, "files")
    return Manifest(TARGET, tuple(files), ())


def _check_destinations(targets: list[Path], config: Path, owned: set[str]) -> None:
    for destination in targets:
        if not _allowed(str(destination), config):
            message = i18n.t("harness.error.symlink", path=str(destination))
            raise ValidationError("harness_symlink", message, {"path": str(destination)})
        if os.path.lexists(destination) and str(destination) not in owned:
            message = i18n.t("harness.error.opencode_conflict", path=str(destination))
            raise StateConflict("harness_opencode_conflict", message, {"path": str(destination)})


def _copy_all(built: list[Path], targets: list[Path], written: list[str]) -> None:
    for source, destination in zip(built, targets, strict=True):
        try:
            atomic_write_text(destination, source.read_text(encoding="utf-8"))
        except OSError as exc:
            message = i18n.t("harness.error.copy_failed", path=str(destination), error=str(exc))
            raise RemoteError("harness_copy_failed", message, {"path": str(destination)}) from exc
        written.append(str(destination))


def _remove(files: tuple[str, ...], config: Path) -> None:
    """Unlink the files, then the empty ``wev-`` skill directories (a person's file stays)."""
    for name in files:
        Path(name).unlink(missing_ok=True)
    skills = config / "skills"
    for name in files:
        for parent in Path(name).parents:
            if parent == skills or not parent.is_relative_to(skills):
                break
            try:
                parent.rmdir()
            except OSError:
                break


def install(data_home: Path, config: Path, wev_path: Path) -> Manifest:
    """Copy the package into ``config``; on any failure remove what this call created."""
    root = _root(data_home, TARGET)
    previous = _read(root, config)
    owned = set(previous.files) if previous else set()
    ensure_private_dir(root)
    staging = Path(tempfile.mkdtemp(dir=root, prefix=".staging-"))
    written: list[str] = []
    try:
        built = build_package(TARGET, staging, wev_path)
        _check_placeholders(built)
        targets = [config / _destination(b.relative_to(staging)) for b in built]
        _check_destinations(targets, config, owned)
        _copy_all(built, targets, written)
        manifest = Manifest(TARGET, tuple(str(t) for t in targets), ())
        _write_manifest(root, manifest)
    except BaseException:
        _remove(tuple(w for w in written if w not in owned), config)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    _remove(tuple(f for f in owned if f not in manifest.files), config)  # stale entries
    return manifest


def _write_manifest(root: Path, manifest: Manifest) -> None:
    text = json.dumps({"target": TARGET, "files": list(manifest.files), "registrations": []})
    try:
        atomic_write_text(root / "manifest.json", text + "\n")
    except OSError as exc:
        message = i18n.t("harness.error.manifest_write", error=str(exc))
        raise RemoteError("harness_manifest_write", message) from exc


def uninstall(data_home: Path, config: Path) -> Manifest:
    """Remove the files the manifest lists, and only those."""
    root = _root(data_home, TARGET)
    manifest = _read(root, config)
    if manifest is None:
        message = i18n.t("harness.error.not_installed", target=TARGET)
        raise NotFound("harness_not_installed", message)
    _remove(manifest.files, config)
    (root / "manifest.json").unlink()
    for directory in (root, root.parent, data_home / "wev-skills"):
        try:
            directory.rmdir()  # only an empty directory goes
        except OSError:
            break
    return manifest
