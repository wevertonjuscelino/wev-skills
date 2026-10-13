# ADR 0005: Plain hooks, not Claude Code mods

Portuguese version: [0005-hooks-not-mods.pt-BR.md](0005-hooks-not-mods.pt-BR.md).

Status: accepted (2026-10-13)

## Context

wev-skills needs a way to act inside a Claude Code session: re-inject the brief of the active run after compaction and with each prompt, and check Bash commands against the run's permission policy (see ADR 0002 and section 4.14 of the [architecture](../architecture.md)).

On 2026-10-13 the owner evaluated two ways to do that in Claude Code:

- **Plain hooks**: entries in `hooks/hooks.json` that run a command (`wev hook <name>`), pass it the hook JSON on stdin and read a decision from stdout. They are part of the plugin format.
- **Mods**: JavaScript hooks modules that can also draw live interface (a pane, a band above the prompt, a status line). They were considered because a live view of the run (phase, tasks, pending approvals) would be useful to a person watching a session.

## Decision

Keep plain hooks. Do not adopt mods.

## Reasons

- Plain hooks run on every Claude Code surface that supports plugin hooks. Mods that draw live interface depend on a surface that can show it, and the owner did not want a feature that works in some places and not in others.
- Mods depend on an early-access API. A harness whose purpose is to be predictable should not rest on an interface that may change.
- A mod is JavaScript that runs unsandboxed with the user's permissions. The owner did not want to ship that. This is not a claim that hooks are sandboxed: a command hook also runs with the user's permissions. The difference is what has to be trusted. A hook is a command line that the user can read in `hooks.json`, and it calls the same Python engine that has tests. A mod would be a second program in a second language that would have to be audited as well. The project's security position (see [SECURITY.md](../../../SECURITY.md)) is that controls live in the engine, in tested code; a second code path next to it works against that.
- The engine already holds everything a hook needs. A command hook is a thin entry point (`wev hook ...`), so the logic stays in one tested place and can serve another environment later through another adapter.

## Consequences

- No live interface. The only things the plugin adds to a session are text injected into the context and an `ask` or `deny` decision for a Bash command. A person who wants to see the state of a run runs `wev run status` or `wev run brief`.
- The hooks keep the limits recorded in ADR 0002: they check only the Bash tool, once a run is known an internal error becomes `ask` (they are silent only when no run is found), they can only deny or ask, never allow, they do not consult the approval store, and they have not been exercised inside a live Claude Code session.
- This record sets no conditions for revisiting the decision. If the drawbacks above stop applying, a new ADR can reopen it.

## Alternatives considered

- Mods for the live view, plain hooks for the checks: rejected for now. It would double the surface to test and document for a convenience, and the convenience would not exist on every surface.
- No hooks at all: rejected. Without them the brief is lost at compaction and plain Bash commands bypass the engine's policy entirely (ADR 0002).

## Evidence label

Documented only. This record describes a decision. The hooks it keeps are implemented and covered by unit and subprocess tests (see [mvp-status.md](../../mvp-status.md)); neither the hooks nor mods were measured or exercised in a live session for this decision.
