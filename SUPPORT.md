# Support

Portuguese version: [SUPPORT.pt-BR.md](SUPPORT.pt-BR.md).

wev-skills is maintained by one person, Weverton Juscelino. This page says where to take a question, a bug or a vulnerability, what is supported, and what to expect in return.

## Where to ask

| You want to | Go to |
|---|---|
| Ask how to use wev-skills, or discuss an idea | [GitHub Discussions](https://github.com/wevertonjuscelino/wev-skills/discussions), category Q&A (to be enabled by the maintainer) |
| Report a bug or a wrong document | An issue, using the [forms](https://github.com/wevertonjuscelino/wev-skills/issues/new/choose) |
| Propose a change | A feature request form, after a short thread in Discussions if the idea is not settled |
| Report a vulnerability | Private reporting, as described in [SECURITY.md](SECURITY.md). Never in a public issue or in Discussions |

Before you ask, read the [installation guide](docs/guides/installation.md), the other [guides](docs/guides/) and the [roadmap](ROADMAP.md). For a bug, include the Python version, the operating system, the wev-skills version or commit, the exact commands and the output with secrets removed. Do not paste secrets, tokens, host names or private data anywhere.

## What is supported

- Python 3.14 or newer. Older interpreters, including the stock macOS `/usr/bin/python3` (3.9), are not supported.
- macOS and Linux. The CI workflow runs the test suite on Ubuntu and macOS; read the Actions history for its result on a given commit. The Windows state store is not supported.
- The Claude Code plugin, as far as `claude plugin validate .` accepts the manifests. Evidence today: documented only for a live Claude Code session; see the [MVP status](docs/mvp-status.md). No other agent environment is supported.
- The latest release. Security fixes follow the table in [SECURITY.md](SECURITY.md).

The engine is a guardrail for a fallible agent, not a security boundary against an adversarial one. A report that depends on the opposite assumption is a known limit, not a bug.

## What to expect

- Support is best effort, with no service level and no committed response time.
- Issues and questions are read and may be labeled, answered, moved to Discussions or closed. An issue that cannot be reproduced from the report may wait with `status: needs-repro`.
- A request can be declined, for example when it needs a runtime dependency or ties the core to one platform (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- Pull requests are welcome after an issue or a Discussions thread, following [CONTRIBUTING.md](CONTRIBUTING.md) and the [Code of Conduct](CODE_OF_CONDUCT.md).
