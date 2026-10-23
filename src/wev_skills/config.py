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
from wev_skills.config_files import GIT_MARKER
from wev_skills.config_files import deep_merge as deep_merge
from wev_skills.config_files import find_repo_root as find_repo_root
from wev_skills.config_files import read_json_object as read_json_object
from wev_skills.config_files import user_config_home as user_config_home
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
SOURCE_JOIN = " + "
DEFAULT_PROJECT_DIR = "wev-specialists"
RESERVED_PROJECT_DIRS = frozenset({GIT_MARKER, ".claude"})
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


BUILTIN = "builtin"
"""The value of ``decision.jev.command`` that selects the built-in HTTPS client."""


@dataclass(frozen=True)
class JevConfig(Serializable):
    command: str = BUILTIN
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
    run_budget_units: float = 400.0
    """Engine units a whole run may spend before new work is refused (``core.run_budget``)."""
    run_max_attempts_total: int = 12
    """Task starts a whole run may make, over all its tasks."""


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
    project_dir: str = DEFAULT_PROJECT_DIR
    """Where the project's own specialists live, relative to the repository root."""


@dataclass(frozen=True)
class IntakeConfig(Serializable):
    max_rounds: int = 3
    """Rounds of at most three questions ``wev intake next`` may ask before assumptions."""


@dataclass(frozen=True)
class SpecialistsConfig(Serializable):
    max_per_project: int = 5
    max_lessons_rendered: int = 12
    """Active lessons shown in an exported subagent and in a task contract."""
    max_lessons: int = 30
    """Active lessons one specialist may hold; beyond it one must be retired first."""
    stale_after_runs: int = 20
    score_samples: int = 3
    """Times a scored case is run per scoring pass."""
    score_max_runs: int = 60
    """Most agent runs one scoring pass may start."""
    score_max_new_lessons: int = 3
    """Most lessons one scoring pass may propose."""
    score_timeout_seconds: float = 900.0
    """Time one scored run may take."""
    score_on_finish: bool = False
    """Score the specialists a run used when the run finishes."""


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
    intake: IntakeConfig = field(default_factory=IntakeConfig)
    specialists: SpecialistsConfig = field(default_factory=SpecialistsConfig)


DEFAULT_CONFIG: dict[str, Any] = Config().to_dict()
"""Plain-dict defaults. Treat as read-only: ``parse_config`` always works on copies."""


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


@dataclass(frozen=True)
class ResolvedConfig:
    """A configuration as written (state directory not yet protected) and where it came from."""

    config: Config
    source: str
    digest: str
    sources: tuple[str, ...] = ()
    """The files merged, lowest precedence first (user, then repository); empty for defaults."""


def user_config_path() -> Path:
    return user_config_home() / CONFIG_FILE_NAME


def _tier_files(root: str | os.PathLike[str]) -> tuple[str, ...]:
    """The user file (a regular file, never a symlink) then the repository file, if present."""
    user, repo = user_config_path(), Path(root) / CONFIG_FILE_NAME
    found = [user] if user.is_file() and not user.is_symlink() else []
    return tuple(str(path) for path in (*found, *([repo] if repo.is_file() else [])))


def _parse_tiers(files: tuple[str, ...]) -> Config:
    """Defaults, then each file in turn; the merged object is validated once."""
    if len(files) < 2:
        return parse_config(files[0] if files else None)
    try:
        return parse_config(files[0], read_json_object(files[1]))
    except ValidationError as exc:
        if exc.code != "invalid_config":
            raise
        joined = SOURCE_JOIN.join(files)
        raise ValidationError(
            exc.code, f"{exc.message} ({joined})", {**exc.details, "path": joined}
        ) from exc


def resolve_config(explicit: str | None, root: str | os.PathLike[str]) -> ResolvedConfig:
    """``explicit`` alone when given, else the user file under the repository's, else defaults."""
    files = (os.path.abspath(explicit),) if explicit is not None else _tier_files(root)
    source = SOURCE_JOIN.join(files) or SOURCE_DEFAULTS
    config = parse_config(explicit) if explicit is not None else _parse_tiers(files)
    errors = trust_errors(config, root)
    if errors:
        details = {"errors": errors, "path": source}
        raise ValidationError("invalid_config", f"invalid configuration: {errors[0]}", details)
    return ResolvedConfig(config, source, config_digest(config), files)


def explicit_language(path: str) -> str | None:
    """The ``language`` the config file at ``path`` sets itself, else ``None``.

    A missing or unreadable file and a file without the key give ``None``: only a language
    somebody wrote counts against the ``LANG`` environment.
    """
    try:
        value = read_json_object(path).get("language")
    except NotFound, ValidationError:
        return None
    return value if isinstance(value, str) else None


def pinned_snapshot(pinned: ResolvedConfig) -> dict[str, Any]:
    """The configuration a run stores. ``language`` is kept only when a file set it (the last
    one wins), so the run can tell an explicit language from the default."""
    snapshot = pinned.config.to_dict()
    if not any(explicit_language(path) for path in pinned.sources):
        snapshot.pop("language", None)
    return snapshot


def _inside(base: Path, path: Path) -> bool:
    return path == base or base in path.parents


def trust_errors(config: Config, root: str | os.PathLike[str]) -> list[str]:
    """What a configuration may not name: a program or a directory the repository controls.

    ``decision.jev.command`` is a bare program name (never a shell or an interpreter) or an
    absolute path outside ``root``; ``agents.directories`` stay inside ``root`` or the
    user's configuration directory. A file in the repository must not pick what runs.
    """
    base, errors = Path(root).resolve(), _command_errors(config.decision.jev.command, Path(root))
    allowed = (base, user_config_home().resolve())
    for index, entry in enumerate(config.agents.directories):
        resolved = (base / entry).resolve()
        if not any(_inside(place, resolved) for place in allowed):
            errors.append(f"/agents/directories/{index}: must be inside the repository root")
    return [*errors, *_project_dir_errors(config, base)]


def _command_errors(command: str, root: Path) -> list[str]:
    """The built-in client names no program, so only a program name is checked."""
    if command == BUILTIN:
        return []
    base = root.resolve()
    bare = os.sep not in command and "/" not in command and not any(c.isspace() for c in command)
    name = os.path.basename(command).rstrip("0123456789.").lower()
    if name in UNTRUSTED_PROGRAMS or not (bare or os.path.isabs(command)):
        return ["/decision/jev/command: must be a program name or an absolute path"]
    if not bare and _inside(base, Path(command).resolve()):
        return ["/decision/jev/command: must not point inside the repository"]
    return []


def _project_dir_errors(config: Config, base: Path) -> list[str]:
    """``agents.project_dir`` is a directory below the root, outside ``.git``, ``.claude``
    and the state directory: specialists are written there and exported from there."""
    entry = config.agents.project_dir
    resolved, state = (base / entry).resolve(), (base / config.state_dir).resolve()
    parts = {part.casefold() for part in Path(entry).parts}
    inside = base in resolved.parents and not os.path.isabs(entry)
    if inside and not parts & RESERVED_PROJECT_DIRS and not _inside(state, resolved):
        return []
    return ["/agents/project_dir: must be a directory below the repository root"]


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
