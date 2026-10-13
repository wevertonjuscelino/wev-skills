# ADR 0001: Python standard-library engine

Portuguese version: [0001-python-stdlib-engine.pt-BR.md](0001-python-stdlib-engine.pt-BR.md).

Status: accepted (2026-10-13)

## Context

The harness needs deterministic code for state, permissions, loop detection, command execution and validation. The development machine has Python 3.14.7 and Node 24.15.0, with no linters, type checkers, test runners or schema libraries installed. The project brief asks for a simple, auditable codebase and for tests that run without network access or paid providers.

## Decision

Write the engine as a Python package (`wev_skills`) that targets Python 3.14+ (see the addendum of 2026-10-13) and imports only the standard library at runtime. Tests use `unittest`. `ruff` and `mypy` run in CI and are optional locally.

## Reasons

- Nothing has to be installed to run the engine or its tests, which also removes the supply-chain surface of a dependency tree.
- The standard library already covers the hard parts: `subprocess` without a shell, `shlex`, `pathlib` symlink resolution, `os.replace` for atomic writes, `fcntl` locks, `argparse`, `dataclasses`.
- Skills in the Agent Skills ecosystem commonly ship Python or shell helpers, so a Python CLI fits how skills call tools.

## Consequences

- No YAML parser and no JSON Schema library are available, so configuration and agent specs are JSON, validated by a small in-repo validator that supports a documented subset of JSON Schema (ADR 0003).
- Type checking is not enforced on a developer machine unless `mypy` is installed; CI is the gate.
- File locking uses `fcntl`, so the state store supports macOS and Linux. Windows is not supported in the MVP.

## Alternatives considered

- TypeScript on Node: good typing, but type checking needs the `typescript` package, and a build step adds moving parts for a CLI of this size.
- Go: single binary and strong typing, but contributors to skill repositories are less likely to have a Go toolchain, and a binary is harder to audit in place.

## Addendum (2026-10-13): minimum Python raised to 3.14

The decision above first targeted Python 3.10 and newer. On 2026-10-13, before the first publication, the owner decided that the project requires Python 3.14 or newer (`requires-python = ">=3.14"`). The reason given is to support only the version the owner develops and tests on.

Consequences:

- Newer syntax is allowed in the engine (for example `StrEnum`, `type` aliases and generic function syntax).
- `bin/wev` stays written in syntax an old interpreter can parse, so that its version guard can print a message instead of a syntax error. Under an older `python3` the hook subcommands exit 0 and check nothing, and every other command exits 1 with a message.
- An earlier run of the suite on Python 3.10 passed before this change. Python 3.10 to 3.13 are no longer supported or tested.
