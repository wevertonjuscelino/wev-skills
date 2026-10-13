"""Configuration: defaults, JSON loading, deep merge, schema validation, typed accessors."""

from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from wev_skills import schema
from wev_skills.core._codec import Serializable
from wev_skills.core.errors import NotFound, ValidationError

TIER_NAMES = ("economy", "standard", "premium")
AUTO = "auto"
PLANNING_POLICIES = (AUTO, "always", "never")
EXECUTOR_TIERS = (AUTO, *TIER_NAMES)
TOOL_PROFILES = (AUTO, "structured", "lean")
TOOL_SELECTION_MODES = ("off", "local", "provider")
DEFAULT_AGENT_ID = "senior-engineer"
DEFAULT_TASK_TIMEOUT_SECONDS = 3600.0
"""Shared by ``LimitsConfig`` and the guard's own limits so the two cannot drift."""
CONFIG_FILE_NAME = "wev.config.json"
SOURCE_DEFAULTS = "defaults"
GIT_MARKER = ".git"
USER_CONFIG_DIR = "wev-skills"
UNTRUSTED_PROGRAMS = frozenset(
    {"sh", "bash", "zsh", "dash", "ksh", "fish", "env", "xargs", "python", "node", "ruby", "perl"}
)
"""Programs a config may not name as the decision command: they run whatever they are given."""
DEFAULT_EXEC_PATH = (
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
)


@dataclass(frozen=True)
class JevConfig(Serializable):
    command: str = "jev"
    timeout_seconds: float = 10.0


@dataclass(frozen=True)
class DecisionConfig(Serializable):
    provider: str = "local"
    jev: JevConfig = field(default_factory=JevConfig)


@dataclass(frozen=True)
class TiersConfig(Serializable):
    """Model ids per tier, each in fallback order."""

    economy: tuple[str, ...] = ("claude-haiku-5-5",)
    standard: tuple[str, ...] = ("claude-sonnet-5-5",)
    premium: tuple[str, ...] = ("claude-opus-5-5", "claude-sonnet-5-5")


@dataclass(frozen=True)
class ModelsConfig(Serializable):
    tiers: TiersConfig = field(default_factory=TiersConfig)

    def tier(self, name: str) -> tuple[str, ...]:
        if name not in TIER_NAMES:
            raise ValidationError("unknown_tier", f"unknown model tier: {name!r}")
        return tuple(getattr(self.tiers, name))


@dataclass(frozen=True)
class LimitsConfig(Serializable):
    max_attempts: int = 3
    max_parallel: int = 3
    max_consecutive_failures: int = 3
    max_identical_commands: int = 3
    task_timeout_seconds: float = DEFAULT_TASK_TIMEOUT_SECONDS
    budget_units: float = 100.0
    max_polling_commands: int = 60
    """Consecutive ``--polling`` commands of one task before a person is asked."""
    lock_timeout_seconds: float = 30.0
    """How long a command waits for another process to release the state file."""


@dataclass(frozen=True)
class ContextConfig(Serializable):
    budget_tokens: int = 100000
    elide_at: float = 0.6
    summarize_at: float = 0.85


@dataclass(frozen=True)
class PermissionsConfig(Serializable):
    allowed_commands: tuple[str, ...] = ()
    denied_commands: tuple[str, ...] = ()
    allow_shell: bool = False
    protected_paths: tuple[str, ...] = (".git", ".env")
    approval_ttl_seconds: float = 900.0
    """How long a grant stays usable after the operator gives it."""
    exec_path: tuple[str, ...] = DEFAULT_EXEC_PATH
    """The only directories ``wev exec`` looks in for a program named without a path."""


@dataclass(frozen=True)
class RemoteHost(Serializable):
    alias: str
    environment: str = ""
    allow_mutating: bool = False


@dataclass(frozen=True)
class RemoteConfig(Serializable):
    hosts: tuple[RemoteHost, ...] = ()


@dataclass(frozen=True)
class AgentsConfig(Serializable):
    directories: tuple[str, ...] = ()
    default_agent: str = DEFAULT_AGENT_ID
    """Who gets a task that matches no agent's specialties or description."""
    allow_override: bool = False
    """Let a spec from a configured directory replace a built-in agent with the same id."""


@dataclass(frozen=True)
class HarnessSettings(Serializable):
    """Capability-dependent harness defaults (see docs/research/hypotheses.md, H4, H5, H8, H9).

    These are mechanisms with configurable defaults, not measured improvements: the paper
    that motivates them did not test Claude models.

    ``tool_profile`` defaults to ``structured`` because tools that are permission-checked one
    by one are easier to govern. ``lean`` (shell plus minimal read and edit tools) is an
    option the paper motivates for strong models on cost grounds only.
    """

    planning: str = AUTO
    executor_tier: str = AUTO
    plan_reminder: bool = True
    plan_reminder_max_chars: int = 600
    tool_profile: str = "structured"
    tool_selection: str = "off"
    """Per-task tool selection (H10): ``off`` hands out the agent's tool list as it is,
    ``local`` narrows it with the offline policy, ``provider`` asks ``decision.provider``."""
    baseline_checks: bool = True
    """Run a task's checks once when it starts, so checks that already passed before any
    work are not taken as evidence of the work. Off: only the starting tree is recorded."""


@dataclass(frozen=True)
class Config(Serializable):
    language: str = "en"
    state_dir: str = ".wev"
    decision: DecisionConfig = field(default_factory=DecisionConfig)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    permissions: PermissionsConfig = field(default_factory=PermissionsConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    agents: AgentsConfig = field(default_factory=AgentsConfig)
    harness: HarnessSettings = field(default_factory=HarnessSettings)


DEFAULT_CONFIG: dict[str, Any] = Config().to_dict()
"""Plain-dict defaults. Treat as read-only: ``parse_config`` always works on copies."""


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Return a new dict: nested mappings merge, everything else is replaced by ``override``."""
    merged: dict[str, Any] = copy.deepcopy(dict(base))
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, Mapping):
            merged[key] = deep_merge(current, value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def read_json_object(path: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise NotFound("file_not_found", f"file not found: {path}", {"path": path}) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise ValidationError(
            "file_unreadable", f"cannot read {path}: {exc}", {"path": path}
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(
            "invalid_json", f"{path} is not valid JSON: {exc}", {"path": path}
        ) from exc
    if not isinstance(data, dict):
        raise ValidationError(
            "invalid_config", f"{path}: top level must be an object", {"path": path}
        )
    return data


def validate_config_data(data: Mapping[str, Any]) -> list[str]:
    """Schema errors plus cross-field checks for a complete config document."""
    errors = schema.validate(dict(data), schema.load("config"))
    ctx = data.get("context")
    if not errors and isinstance(ctx, Mapping) and ctx["elide_at"] >= ctx["summarize_at"]:
        errors.append("/context: elide_at must be lower than summarize_at")
    return errors


def parse_config(path: str | None = None, overrides: Mapping[str, Any] | None = None) -> Config:
    """Defaults, then the JSON file at ``path``, then ``overrides``; validated, as written."""
    merged = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None:
        merged = deep_merge(merged, read_json_object(path))
    if overrides:
        merged = deep_merge(merged, overrides)
    errors = validate_config_data(merged)
    if errors:
        raise ValidationError(
            "invalid_config",
            f"invalid configuration: {errors[0]}",
            {"errors": errors, "path": path},
        )
    return Config.from_dict(merged)


def load_config(path: str | None = None, overrides: Mapping[str, Any] | None = None) -> Config:
    """``parse_config`` plus the state directory added to the protected paths."""
    return protect_state_dir(parse_config(path, overrides))


def config_digest(config: Config) -> str:
    """Stable hash of a configuration, used to tell whether two of them differ."""
    text = json.dumps(config.to_dict(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_repo_root(cwd: str | os.PathLike[str]) -> Path:
    """The nearest ancestor of ``cwd`` holding a ``.git`` entry; ``cwd`` itself outside one.

    Read from the filesystem, without running git, so it also works where git is missing.
    """
    start = Path(cwd).resolve()
    for directory in (start, *start.parents):
        if (directory / GIT_MARKER).exists():
            return directory
    return start


@dataclass(frozen=True)
class ResolvedConfig:
    """A configuration as written (state directory not yet protected) and where it came from."""

    config: Config
    source: str
    digest: str


def resolve_config(explicit: str | None, root: str | os.PathLike[str]) -> ResolvedConfig:
    """``explicit`` when given, else ``<root>/wev.config.json`` when it exists, else defaults."""
    candidate = Path(root) / CONFIG_FILE_NAME
    if explicit is not None:
        config, source = parse_config(explicit), os.path.abspath(explicit)
    elif candidate.is_file():
        config, source = parse_config(str(candidate)), str(candidate)
    else:
        config, source = parse_config(None), SOURCE_DEFAULTS
    errors = trust_errors(config, root)
    if errors:
        details = {"errors": errors, "path": source}
        raise ValidationError("invalid_config", f"invalid configuration: {errors[0]}", details)
    return ResolvedConfig(config, source, config_digest(config))


def explicit_language(source: str) -> str | None:
    """The ``language`` the config file at ``source`` sets itself, else ``None``.

    The built-in default, a missing or unreadable file and a file without the key all give
    ``None``: only a language somebody wrote counts against the ``LANG`` environment.
    """
    if source == SOURCE_DEFAULTS:
        return None
    try:
        value = read_json_object(source).get("language")
    except NotFound, ValidationError:
        return None
    return value if isinstance(value, str) else None


def pinned_snapshot(pinned: ResolvedConfig) -> dict[str, Any]:
    """The configuration a run stores. ``language`` is kept only when the file set it, so the
    run can tell an explicit language from the default."""
    snapshot = pinned.config.to_dict()
    if explicit_language(pinned.source) is None:
        snapshot.pop("language", None)
    return snapshot


def user_config_home() -> Path:
    """``$XDG_CONFIG_HOME/wev-skills``, or ``~/.config/wev-skills``."""
    configured = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return (Path(configured) if configured else Path.home() / ".config") / USER_CONFIG_DIR


def _inside(base: Path, path: Path) -> bool:
    return path == base or base in path.parents


def trust_errors(config: Config, root: str | os.PathLike[str]) -> list[str]:
    """What a configuration may not name: a program or a directory the repository controls.

    ``decision.jev.command`` is a bare program name (never a shell or an interpreter) or an
    absolute path outside ``root``; ``agents.directories`` stay inside ``root`` or the
    user's configuration directory. A file in the repository must not pick what runs.
    """
    base, errors = Path(root).resolve(), []
    command = config.decision.jev.command
    bare = os.sep not in command and "/" not in command and not any(c.isspace() for c in command)
    name = os.path.basename(command).rstrip("0123456789.").lower()
    if name in UNTRUSTED_PROGRAMS or not (bare or os.path.isabs(command)):
        errors.append("/decision/jev/command: must be a program name or an absolute path")
    elif not bare and _inside(base, Path(command).resolve()):
        errors.append("/decision/jev/command: must not point inside the repository")
    allowed = (base, user_config_home().resolve())
    for index, entry in enumerate(config.agents.directories):
        resolved = (base / entry).resolve()
        if not any(_inside(place, resolved) for place in allowed):
            errors.append(f"/agents/directories/{index}: must be inside the repository root")
    return errors


def protect_state_dir(config: Config, base: str | os.PathLike[str] | None = None) -> Config:
    """A copy whose ``protected_paths`` always cover ``state_dir`` (relative to ``base``).

    Approvals and the audit log live there: a command that could write them could forge
    its own approval. The entry is added whatever the configured list says.
    """
    root = os.fspath(base) if base is not None else os.getcwd()
    relative = os.path.normpath(config.state_dir)
    absolute = os.path.abspath(os.path.join(root, config.state_dir))
    current = config.permissions.protected_paths
    extra = tuple(p for p in dict.fromkeys((relative, absolute)) if p not in current)
    if not extra:
        return config
    return replace(config, permissions=replace(config.permissions, protected_paths=current + extra))
