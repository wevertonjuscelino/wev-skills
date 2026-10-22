"""Install the wev package into OpenCode and undo it.

OpenCode has no CLI to register plugins or skills (docs/research/harness-opencode.md
sections 2 to 4), so the files are copied into its config directory: ``plugins/wev-guard.js``,
``skills/wev-<name>/`` and ``agents/wev-<id>.md``. Every written path is in the manifest next
to the other targets' (``<data_home>/wev-skills/harness/opencode/manifest.json``). Install
refuses to overwrite a file the previous manifest does not list; uninstall removes the
manifest's entries and nothing else, after checking each is still one of those wev entries.
The manifest also lists the ``plugins``/``skills``/``agents`` directories wev created, and
only those are removed (when empty).

Limits (for SECURITY.md):

- The plugin's ``console.warn`` warning likely never reaches the agent: an OpenCode "ask" is
  in practice a silent allow.
- ``spawnSync`` blocks the event loop up to 10 s per bash call.
- Manifest paths are unresolved: a changed ``XDG_CONFIG_HOME`` makes uninstall refuse until
  it is restored.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from wev_skills import i18n
from wev_skills.adapters import harness_opencode_mcp as mcp
from wev_skills.adapters.harness_install import (
    Manifest,
    check_placeholders,
    copy_tree,
    invalid,
    read_manifest,
    remove_files,
    root_for,
    write_manifest,
)
from wev_skills.adapters.harness_package import (
    OPENCODE_CONFIG,
    PACKAGE_NAME,
    build_package,
    opencode_mcp_entry,
)
from wev_skills.core.errors import NotFound, RemoteError, StateConflict, ValidationError
from wev_skills.core.fsutil import ensure_private_dir

TARGET = "opencode"
PREFIX = "wev-"
PLUGIN = Path("plugins") / "wev-guard.js"
KINDS = ("plugins", "skills", "agents")


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
    manifest = read_manifest(root, TARGET, lambda name: _allowed(name, config), ())
    allowed = {str(config / kind) for kind in KINDS}
    if manifest is not None and not set(manifest.created_dirs) <= allowed:
        raise invalid(root / "manifest.json", "created_dirs")
    return manifest


def _link_or_self(destination: Path, config: Path) -> Path:
    """The first symlink between the config dir and ``destination``, else ``destination``."""
    current = destination
    while current != config and current != current.parent:
        if current.is_symlink():
            return current
        current = current.parent
    return destination


def _check_destinations(targets: list[Path], config: Path, owned: set[str]) -> None:
    for destination in targets:
        if not _allowed(str(destination), config):
            path = _link_or_self(destination, config)
            message = i18n.t("harness.error.symlink", path=str(path))
            raise ValidationError("harness_symlink", message, {"path": str(path)})
        if os.path.lexists(destination) and str(destination) not in owned:
            message = i18n.t("harness.error.opencode_conflict", path=str(destination))
            raise StateConflict("harness_opencode_conflict", message, {"path": str(destination)})


def _prune(files: tuple[str, ...], config: Path, created: tuple[str, ...]) -> None:
    """Unlink the files, then the empty ``wev-`` skill directories and the empty directories
    wev created (a person's file or directory stays)."""
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
    for directory in created:
        try:
            Path(directory).rmdir()
        except OSError:
            continue


def install(data_home: Path, config: Path, wev_path: Path) -> Manifest:
    """Copy the package into ``config``; on any failure remove what this call created."""
    root = root_for(data_home, TARGET)
    base = data_home / PACKAGE_NAME
    created_base = None if base.exists() else base
    previous = _read(root, config)
    config_file = config / OPENCODE_CONFIG
    mcp.check(config_file, previous.mcp if previous else "")
    before = mcp.snapshot(config_file)
    owned = set(previous.files) if previous else set()
    kept = tuple(d for d in (previous.created_dirs if previous else ()) if Path(d).is_dir())
    created = (*kept, *(str(config / k) for k in KINDS if not (config / k).exists()))
    written: list[str] = []
    try:
        ensure_private_dir(root)
        staging = Path(tempfile.mkdtemp(dir=root, prefix=".staging-"))
        try:
            built = build_package(TARGET, staging, wev_path)
            check_placeholders(built)
            built = [b for b in built if b.relative_to(staging) != Path(OPENCODE_CONFIG)]
            targets = [config / _destination(b.relative_to(staging)) for b in built]
            _check_destinations(targets, config, owned)
            copy_tree(built, targets, written)
            entry = mcp.dump(opencode_mcp_entry(wev_path))
            manifest = Manifest(TARGET, tuple(str(t) for t in targets), (), created, entry)
            mcp.apply(config_file, opencode_mcp_entry(wev_path))
            _write(root, manifest)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    except BaseException:
        try:
            mcp.restore(config_file, before)
        finally:  # a failed restore still raises, with the install error as its context
            new = tuple(w for w in written if w not in owned)
            _prune(new, config, tuple(d for d in created if d not in kept))
            remove_files((), root, created_base)
        raise
    _prune(tuple(f for f in owned if f not in manifest.files), config, ())  # stale entries
    return manifest


def _write(root: Path, manifest: Manifest) -> None:
    try:
        write_manifest(root, manifest)
    except OSError as exc:
        message = i18n.t("harness.error.manifest_write", error=str(exc))
        raise RemoteError("harness_manifest_write", message) from exc


def uninstall(data_home: Path, config: Path) -> Manifest:
    """Remove the files the manifest lists, and only those."""
    root = root_for(data_home, TARGET)
    manifest = _read(root, config)
    if manifest is None:
        message = i18n.t("harness.error.not_installed", target=TARGET)
        raise NotFound("harness_not_installed", message)
    _prune(manifest.files, config, manifest.created_dirs)
    mcp.remove(config / OPENCODE_CONFIG, manifest.mcp)
    (root / "manifest.json").unlink()
    remove_files((), root, data_home / PACKAGE_NAME)  # empty now that the manifest is gone
    return manifest
