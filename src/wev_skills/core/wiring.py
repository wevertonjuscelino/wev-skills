"""Composition root: build the real collaborators from a ``Config`` and a repository root.

Nothing here decides anything. Each function wires one module to the ones it depends on,
so commands and the orchestrator share a single, tested way of putting the engine together.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from wev_skills import i18n
from wev_skills.agents.factory import AgentFactory
from wev_skills.agents.registry import AgentRegistry
from wev_skills.agents.spec import AgentSpec
from wev_skills.config import (
    SOURCE_DEFAULTS,
    Config,
    ResolvedConfig,
    config_digest,
    protect_state_dir,
)
from wev_skills.core.contracts import RiskLevel
from wev_skills.core.errors import PermissionDenied
from wev_skills.core.ports import Clock, Runner, SubprocessRunner, SystemClock
from wev_skills.decisions import DecisionProvider
from wev_skills.decisions import factory as decision_factory
from wev_skills.execution.executor import CommandExecutor
from wev_skills.governance.approvals import ApprovalStatus, ApprovalStore
from wev_skills.governance.audit import AuditLog
from wev_skills.models.router import ModelRouter
from wev_skills.remote.inventory import Inventory
from wev_skills.remote.tmux import TmuxController
from wev_skills.remote.transport import SshTransport
from wev_skills.security.permissions import PermissionPolicy
from wev_skills.security.redact import redact
from wev_skills.tools.registry import ToolRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG_SUBDIRS = ("agent-specs/templates", "agent-specs/examples")
TEMPLATES_DIR_NAME = "templates"
APPROVALS_FILE = "approvals.json"
AUDIT_FILE = "audit.jsonl"
LOGS_DIR = "logs"
REMOTE_REQUESTER = "wev-remote"


def state_dir(config: Config, root: str | Path) -> Path:
    """The state directory; a relative ``config.state_dir`` is taken from ``root``.

    ``root`` is the repository root (``config.find_repo_root``), never just the directory a
    command happens to run in, so every command of a repository finds the same runs.
    """
    return Path(root) / config.state_dir


def build_tool_registry() -> ToolRegistry:
    return ToolRegistry.default()


def build_approval_store(
    config: Config, root: str | Path, clock: Clock | None = None
) -> ApprovalStore:
    ttl = config.permissions.approval_ttl_seconds
    return ApprovalStore(state_dir(config, root) / APPROVALS_FILE, clock, ttl)


def build_audit_log(config: Config, root: str | Path, clock: Clock | None = None) -> AuditLog:
    return AuditLog(state_dir(config, root) / AUDIT_FILE, clock)


def build_policy(
    config: Config, root: str | Path, approvals: ApprovalStore | None = None
) -> PermissionPolicy:
    """The real policy for local commands, with the state directory always protected."""
    store = approvals if approvals is not None else build_approval_store(config, root)
    permissions = protect_state_dir(config, root).permissions
    return PermissionPolicy(permissions, build_tool_registry(), store)


def build_grantless_policy(config: Config, root: str | Path) -> PermissionPolicy:
    """The policy without an approval store: whatever needs approval stays refused.

    Used where spending a person's grant would be wrong: baseline checks run by the engine
    before a task's work, and remote commands (see ``build_remote_gate``).
    """
    permissions = protect_state_dir(config, root).permissions
    return PermissionPolicy(permissions, build_tool_registry(), None)


def build_remote_gate(config: Config, root: str | Path) -> PermissionPolicy:
    """The same policy without an approval store, used to judge a remote argv.

    A grant is bound to an exact action. A grant for the local command ``rm -rf build``
    must not allow ``rm -rf build`` on a host, so the gate cannot spend local grants:
    anything that needs approval stays so, and the controller asks for a grant of the
    host-qualified action (``<alias> <command>``) through its ``approval_check``.
    """
    return build_grantless_policy(config, root)


def build_executor(
    config: Config,
    root: str | Path,
    log_dir: str | Path,
    runner: Runner | None = None,
    clock: Clock | None = None,
    policy: PermissionPolicy | None = None,
) -> CommandExecutor:
    gate = policy if policy is not None else build_policy(config, root)
    return CommandExecutor(gate, runner or SubprocessRunner(), Path(log_dir), redact, clock)


def build_provider(
    config: Config, runner: Runner | None = None, root: str | Path | None = None
) -> DecisionProvider:
    """``decision.provider`` from configuration; JEV state is redacted before it leaves.

    The JEV program is looked up on ``permissions.exec_path`` and must not sit inside
    ``root`` (default: the working directory).
    """
    base = str(root) if root is not None else None
    return decision_factory.build_provider(config, runner or SubprocessRunner(), redact, base)


def build_model_router(config: Config) -> ModelRouter:
    return ModelRouter(config.models)


def catalog_directories(root: Path = REPO_ROOT) -> list[Path]:
    """The shipped templates and examples that exist next to this checkout."""
    return [root / sub for sub in CATALOG_SUBDIRS if (root / sub).is_dir()]


@dataclass(frozen=True)
class AgentCatalog:
    """Registry and factory plus the ids that are templates (never routed to)."""

    registry: AgentRegistry
    factory: AgentFactory
    template_ids: frozenset[str]

    def routable(self) -> tuple[AgentSpec, ...]:
        return tuple(s for s in self.registry.list() if s.id not in self.template_ids)

    def resolved(self, agent_id: str) -> AgentSpec:
        return self.factory.resolve(self.registry.get(agent_id))


def _agent_directories(config: Config, root: Path) -> list[Path]:
    configured = [root / directory for directory in config.agents.directories]
    return [*catalog_directories(), *(d for d in configured if d.is_dir())]


def build_agents(config: Config, root: str | Path) -> AgentCatalog:
    directories = _agent_directories(config, Path(root))
    registry = AgentRegistry().discover(directories, config.agents.allow_override)
    templates = frozenset(
        path.stem
        for directory in directories
        if directory.name == TEMPLATES_DIR_NAME
        for path in directory.glob("*.json")
    )
    return AgentCatalog(registry, AgentFactory(registry), templates & set(_ids(registry)))


def _ids(registry: AgentRegistry) -> list[str]:
    return [spec.id for spec in registry.list()]


def build_remote_controller(
    config: Config,
    root: str | Path,
    runner: Runner | None = None,
    clock: Clock | None = None,
    approvals: ApprovalStore | None = None,
) -> TmuxController:
    """Remote starts are governed by the controller: inventory, mode, gate on the remote
    argv and a single-use grant for the host-qualified action (always asked in production).

    The controller's own ``ssh`` is transport, not a command run through the executor,
    so the rule that a local ``ssh`` command needs approval does not apply to it.
    """
    store = approvals if approvals is not None else build_approval_store(config, root, clock)
    transport = SshTransport(runner or SubprocessRunner(), redactor=redact)
    audit = build_audit_log(config, root, clock)

    def request(action: str, risk: RiskLevel, reason: str) -> str:
        record = store.request(action, risk, reason, REMOTE_REQUESTER)
        if record.status is ApprovalStatus.DENIED:
            message = i18n.t("security.decision.approval_denied")
            raise PermissionDenied("approval_denied", message, {"approval_id": record.id})
        audit.append("approval.requested", record.to_dict())
        return record.id

    return TmuxController(
        transport,
        Inventory.from_config(config.remote),
        build_remote_gate(config, root),
        store.consume,
        redact,
        clock or SystemClock(),
        approval_request=request,
    )


@dataclass(frozen=True)
class Services:
    """Everything the orchestrator needs, built once per CLI invocation."""

    config: Config
    root: Path
    state_dir: Path
    runner: Runner
    clock: Clock
    redact: Callable[[str], str]
    approvals: ApprovalStore
    policy: PermissionPolicy
    audit: AuditLog
    provider: DecisionProvider
    router: ModelRouter
    agents: AgentCatalog
    pinned: ResolvedConfig
    """The configuration as written, its digest and its source: what a new run pins."""

    def executor(self, log_dir: str | Path) -> CommandExecutor:
        return CommandExecutor(self.policy, self.runner, Path(log_dir), self.redact, self.clock)

    def grantless_executor(self, log_dir: str | Path) -> CommandExecutor:
        """An executor that never spends an approval: what needs one is refused."""
        gate = build_grantless_policy(self.config, self.root)
        return CommandExecutor(gate, self.runner, Path(log_dir), self.redact, self.clock)


def build_services(
    config: Config,
    root: str | Path,
    runner: Runner | None = None,
    clock: Clock | None = None,
    source: str = SOURCE_DEFAULTS,
) -> Services:
    """Wire everything for ``config`` at ``root``. ``source`` says where ``config`` came from."""
    base = Path(root)
    protected = protect_state_dir(config, base)
    real_runner = runner or SubprocessRunner()
    real_clock = clock or SystemClock()
    approvals = build_approval_store(protected, base, real_clock)
    return Services(
        config=protected,
        root=base,
        state_dir=state_dir(protected, base),
        runner=real_runner,
        clock=real_clock,
        redact=redact,
        approvals=approvals,
        policy=build_policy(protected, base, approvals),
        audit=build_audit_log(protected, base, real_clock),
        provider=build_provider(protected, real_runner, base),
        router=build_model_router(protected),
        agents=build_agents(protected, base),
        pinned=ResolvedConfig(config, source, config_digest(config)),
    )
