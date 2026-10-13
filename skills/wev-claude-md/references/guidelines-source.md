# Guidelines source and rationale

## What the managed block contains

Five short sections, shipped as templates in English and Brazilian Portuguese:

1. Think before coding: state assumptions, present alternative readings of a request instead of choosing one silently, say when a simpler approach exists, and stop to ask when something is unclear.
2. Simplicity first: write the least code that solves the problem; no unrequested features, no abstraction for single-use code, no speculative configurability, no handling of impossible cases.
3. Surgical changes: touch only what the task requires; match existing style; mention unrelated dead code instead of deleting it; remove only what your own change made unused. Every changed line should trace to the request.
4. Goal-driven execution: turn a task into a verifiable goal (a failing test that then passes, tests green before and after a refactor) and state a short plan with a check per step.
5. Evidence before claims: say what was run and what was not; never report a check as passed if it did not run; label work as tested, untested, mocked, documented only or blocked. This section is original to wev-skills.

The block also carries a tradeoff note: the guidelines favor caution over speed, and for trivial tasks the assistant should use judgment.

## Why it is a managed block

The markers let the tool refresh the guidelines without touching anything the author wrote. The text between the markers is replaced as a unit; the text outside is never read for change, only preserved byte for byte, including line endings and the presence or absence of a final newline.

## Attribution

Sections 1 to 4 are adapted from the andrej-karpathy-skills project:

- Copy used as the reference: https://github.com/multica-ai/andrej-karpathy-skills (file `CLAUDE.md`, commit `2c606141936f1eeef17fa3043a72095b4765b9c2`, checked 2026-10-13).
- Original project: https://github.com/forrestchang/andrej-karpathy-skills by forrestchang. The README of the copy points its install commands at that repository.
- The project describes the guidelines as derived from Andrej Karpathy's public observations on pitfalls of coding with LLMs.
- License: the README states "License: MIT" and the plugin manifest states `"license": "MIT"`. There is no LICENSE file and no copyright line in the repository, and the GitHub API reports no detected license. The templates therefore say "under the MIT license as stated in that project's README" and nothing stronger.

The wording in the templates is this project's own; the four-section structure and the substance of each point are the adapted part. wev-skills is not affiliated with or endorsed by forrestchang, multica-ai or Andrej Karpathy. The full provenance entry is in `docs/THIRD-PARTY.md` in the wev-skills repository.

## What can and cannot be claimed

The guidelines are meant to reduce common mistakes. No measurement of their effect has been made for this project, so do not state or imply any improvement figure.
