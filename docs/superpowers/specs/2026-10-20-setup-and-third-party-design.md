# Design: installer, harnesses and third-party skills

Portuguese version: [2026-10-20-setup-and-third-party-design.pt-BR.md](2026-10-20-setup-and-third-party-design.pt-BR.md).

Status: draft for the owner's approval (2026-10-20). Nothing here is implemented.

## Intent

Today wev-skills can only be installed by cloning the repository and running `claude --plugin-dir`, and nobody has ever installed it from scratch. The owner wants anyone, with or without technical training, to be able to install it and get everything ready with a single line, the way Claude Code is installed: copy a command, run a `.sh`, answer a few questions.

Along with this, wev will carry third-party skills that the owner wants to keep always up to date with upstream. The first two are [rea](https://github.com/morluto/rea) (reverse engineering, MCP `rea-agents` on npm, MIT) and [agent-skills](https://github.com/addyosmani/agent-skills) (engineering skills, MIT). rea is not just one more tool: it becomes the way wev understands systems, the user's own and other people's, in order to bring better solutions.

## Owner decisions

Decided in this conversation, not up to the builder:

1. **Entry point:** a `curl -fsSL <url>/install.sh | bash` line that asks questions, requests the needed keys, installs and leaves everything ready. The audience ranges from people who have never opened a terminal to people who use agents every day.
2. **Harnesses in the first delivery:** Claude Code, Codex, Gemini CLI and OpenCode. The setup installs into each one the person chooses.
3. **JEV turns wev's orchestration on or off:** with JEV, wev's orchestration applies. Without JEV, each harness uses its own native orchestration.
4. **Keys in a `.env` on every system:** `~/.config/wev-skills/.env`, permission `600`. The macOS keychain is still accepted for those who already use it.
5. **Embedded JEV client:** `jev.mjs` is the owner's code and will be ported into wev-skills. Today there is no other place to download the client from.
6. **License:** PolyForm Noncommercial 1.0.0. Already applied and published (v3.0.0 onward). rea and agent-skills remain MIT.
7. **Third parties at install time:** the setup always downloads the newest version.
8. **Third parties after installation:** once a day, on the first opening of the harness, wev checks upstream. If there is a new version, it warns and **asks** whether the person wants to update. If they accept, it installs, tests and, if that fails, rolls back to the previous version on its own.
9. **Full rea integration:** MCP configured in each harness, use in the DISCOVER phase and a dedicated skill.
10. **Two uses of rea**, both ending in a solution delivered to the user:
    - **Understand the user's system and bring the solution** (e.g. "improve my authentication"): map how it really works, study how other programs solve the same problem and propose changes with evidence.
    - **Study a feature of another product to build your own** (e.g. "how Spotify builds Jams"): produce a specification of behavior and architecture and build a version of your own from it.
11. **rea's freedom in the study:** it may download programs, reverse engineer them, analyze websites and capture traffic without asking permission at every step.
12. **Where the downloaded material runs:** the person chooses in the setup between **isolated** (container or VM) and **direct** on the machine, with a risk warning.
13. **Mandatory end-to-end test:** when everything is ready, test with real installations and practical operation, not only with unit tests.
14. **Without JEV, only the flow goes away:** the harness orchestrates in its own way (no wev `run`, task contracts, verification and report). The protections stay on for everyone: command blocking, approvals and loop detection.
15. **In isolated mode, all of rea runs in the container:** the MCP server and everything it downloads and executes stay inside, so the isolation is enforced by code, not only by instruction. Frida, adb and browser capture must work in the container.
16. **wev-skills itself:** the setup installs the tag of the latest release, and wev joins the same daily check, with a question and rollback, as the third parties.
17. **Resources for the end-to-end tests:** the owner provides the harness logins, local Docker and a test JEV key. There is no VM or clean macOS user.

## Goals, non-goals and anti-goals

**Goals**
- A person with no training goes from zero to a working wev in their harness without understanding what happened underneath.
- An experienced person runs the same setup with no questions, using flags, and can uninstall.
- Running the setup again is safe and serves to reconfigure (turn JEV on later, switch harness, change rea's execution mode).
- Third-party skills are never left forgotten on an old version without the person knowing.
- With rea, wev delivers solutions based on how systems really work, not only on what the code appears to do.

**Non-goals**
- Windows (the engine does not support it).
- Requesting or managing the harnesses' logins. Each one takes care of its own.
- Publishing wev-skills on a marketplace or package registry. That requires separate authorization from the owner.
- Selling or distributing commercially (the license forbids it).

**Anti-goals** (would be a failure even if it works)
- Updating a third-party skill without the person saying yes.
- Saying "compatible with Codex/Gemini/OpenCode" without an adapter and an integration test.
- Writing a key inside a repository or showing it on screen.
- A program downloaded by rea running on the person's machine without them having chosen direct mode.
- Treating text coming from a website or an analyzed binary as an instruction to the agent.
- Copying code or assets from third-party products in rea's use 2.

## Parts and order

There are five parts that can be delivered one at a time, each tested. Order: **2 → 3 → 4 → 5 → 1**, plus the end-to-end tests at the end. The installer comes last because it only stitches together what the other parts already do.

### Part 2: embedded JEV client and orchestration switch

- Port `~/.claude/tools/jev/jev.mjs` to Python stdlib inside `src/wev_skills/decisions/`, talking directly to `https://api.typesafe.ai/v1/systemone`. The behavior to preserve is in `jev.mjs` itself: question types `noul`, `choice` (up to 255 options) and `score` (2 to 10 levels), retries on 429/529 with backoff, per-request timeout, batch mode.
- Key reading order: exported `TYPESAFE_API_KEY` variable, then wev's `.env`, then the macOS keychain (service `typesafe-api-key`).
- The current adapter (`decisions/jev.py`, which calls an external `jev` program) remains accepted for those who configure `decision.jev.command`.
- **Orchestration switch** (decision 14):
  - **With a valid JEV key:** `decision.provider` = `jev`, and the skills tell the model to follow wev's flow.
  - **Without a key:** the skills tell the model to use the harness's native orchestration. The protections (guard hooks, approvals, loop detection) stay active in both modes.
  - The exact form of "use the native one" in each harness is left for part 3.
- Unit tests use a fake HTTP server. The real call goes into the end-to-end tests.

### Part 3: harness adapters

- Claude Code already has a plugin (skills, subagents, hooks). New adapters are added for **Codex, Gemini CLI and OpenCode**.
- For each harness, the adapter installs wev's skills, registers the session-start hook (for part 4's daily check) and registers rea's MCP (part 5), in that harness's format.
- **Mandatory first step:** read each harness's real interface (skill, hook, MCP and config formats) before writing code. The project rules forbid inventing capabilities. If some harness has no session-start hook, this part's design goes back to the owner with the alternatives.
- agent-skills already publishes manifests for all four (`.claude-plugin`, `.codex-plugin`, `.gemini`, `.opencode`). It is worth studying how it does it.

### Part 4: third-party skills manager

- A registry of sources, with the type of each: rea = npm package `rea-agents`; agent-skills = GitHub releases. It must accept new sources without code changes.
- wev-skills itself joins the same mechanism as a source, through GitHub releases (decision 16).
- A per-user state file records the version in use and the previous one for each source, and the date of the last check.
- **Installation:** always the newest version.
- **Daily check:** on the first opening of the day (session-start hook), query upstream. If there is a new version, warn and ask, with the changelog link. Claude Code's hook only injects text into the context and does not open a dialog, so the one who asks is the agent, in the chat. In the other harnesses, it depends on what part 3 finds.
- **Accepted update:** install the new one next to the current one, run the health test and, if it passes, switch the version in use. If it fails, keep the previous one and warn.
- **Refusal:** ask again only when another version comes out.
- **Commands:** update now, go back to the previous version, freeze a source at a version.
- **Health test:** rea = start the MCP server and check that it responds and lists tools. agent-skills = check that the skill files are valid for each installed harness.
- Updating without reviewing the content is a trade-off accepted by the owner, but only after an explicit "yes". The documentation states clearly that the health test catches a broken update, not a malicious one.
- `docs/THIRD-PARTY.md` starts recording rea and agent-skills as installed dependencies (not copied), with license and source.

### Part 5: full rea integration

- **MCP:** configured in each chosen harness, through part 3. rea has its own `install.sh` and setup that already register the server in agents. It is worth evaluating using its setup instead of rewriting it.
- **DISCOVER phase:** the `wev-orchestrate` skill starts telling the model to use rea when the task involves a system that runs (app, site, binary, bundle): first understand how it really works, then plan.
- **Dedicated skill** (name to be defined by the builder, suggestion `wev-reverse`) with the two uses from decision 10, each ending in a deliverable: a change plan with evidence (use 1) or a behavior and architecture specification (use 2), which feeds wev's normal flow.
- **Clean room in use 2:** study the behavior and produce a specification. Do not copy the target's code or assets, do not break protection or DRM, do not make the user's product depend on the target's private APIs. The use remains the user's decision. This reduces the legal risk but does not eliminate it.
- **Execution mode** (decision 12): stored in wev's config.
  - **Isolated:** all of rea's MCP server runs in a container (decision 15), and the harness talks to it inside. Before promising this, it is necessary to verify how Frida, adb and browser capture work in this arrangement.
  - **Direct:** runs on the machine, after the warning given in the setup.
  - A Docker container does not run macOS or iOS apps. In that case, even in isolated mode, wev warns and asks before running directly.
- **The target's content is data, never an instruction.** rea already marks this as `untrusted_content`, and the skill reinforces it.

### Part 1: installer

A `curl ... | bash` line. The script:
1. Checks the system (macOS or Linux), `git`, Python 3.14+ and Node.js/npm (rea needs it). If Python or Node is missing, it offers to install it instead of leaving the person on their own.
2. Detects the installed harnesses and asks which to install into, with the ones found already marked.
3. Asks whether the person has a TypeSafe/JEV key.
   - **Yes:** asks for the key without echoing it, writes it to the `.env`, makes a test call and turns JEV on.
   - **No:** leaves it off and native orchestration applies.
4. Asks for rea's execution mode, suggesting isolated if Docker exists.
5. Installs wev's skills and the third-party ones (newest version) in each harness and configures rea's MCP.
6. Tests that everything is working and shows a summary: what was installed, where, and what was left out and why.
7. Shows the license (non-commercial use) before installing.

It must also have:
- **Mode without questions** (flags) for experienced people.
- **Safe re-execution**, which serves to reconfigure.
- **Uninstall** that leaves nothing behind. It removes the `.env` only if the person confirms.

## End-to-end tests

They are separate from `make test`, because the project rules forbid network and paid models in unit tests. Proposal: a `make e2e` target.

- **Linux:** a blank container. Runs the `curl` line, answers the questions and checks the result.
- **macOS:** there is no VM or clean user (decision 17). The test runs on the owner's machine with an empty temporary `HOME`. This covers installation and configuration, but does not catch dependencies already installed on the system. The documentation labels macOS as "tested with isolated HOME", not as "clean machine".
- **Per harness:** confirm that it loads wev's skills, that rea responds as an MCP and that agent-skills shows up.
- **JEV:** one scenario with a real key and one without a key (native orchestration).
- **Update:** deliberately install an old version of rea, see the question, accept and check the switch. Then force a broken version and check the rollback.
- **Uninstall:** check that nothing is left over.

Running real harnesses spends the owner's account and credits, so each round asks for authorization first. The documentation may only say "compatible with X" after this test passes for X.

## Constraints

- Engine runtime: Python 3.14+ with only the standard library. `install.sh` is POSIX/bash shell. Node.js comes in as a requirement of rea, not of the engine.
- mypy strict, frozen dataclasses, functions under 50 lines and files under 400.
- Every message to the user goes through i18n (EN and pt-BR with the same keys). Docs change in both languages in the same commit.
- Evidence labels on every statement of capability. Security statements in line with `SECURITY.md`: the engine is a guardrail, not a boundary against an adversarial agent in the same account.
- Human-operator commands remain out of the agent's reach.
- Nothing is published (push, release, hosting of `install.sh`) without the owner's explicit authorization.

## What is left to the builder

- Format and location of the sources registry and of the third-party state file.
- Names of commands and flags (following the `wev <group> <action>` pattern and the CLI's JSON output).
- How `install.sh` installs Python 3.14 and Node when they are missing (`uv`, the system package manager etc.), as long as the person is warned beforehand.
- Exact form of each source's health test.
- Name of the rea skill.
- Whether to use rea's own setup or register the MCP directly.
- Where to host `install.sh` (left for the owner to authorize when the time comes).

## Calls I made without the owner

These stand as defaults until the owner says otherwise:
- The `.env` lives in `~/.config/wev-skills/`, and the variable exported in the shell takes priority over it.
- The old, external JEV client remains accepted.
- The suggested default execution mode is isolated when Docker is present.
- Refusing an update holds until the next version comes out.
- The delivery order is 2 → 3 → 4 → 5 → 1.
- **Mode switching at use time:** the skills consult wev on every session (a command that says whether JEV is active). This way, turning JEV on or off does not require reinstalling. The key is validated in the setup. If a call fails later, wev falls back to the local policy and warns, as it already does today.
- **Scope of the JEV client:** it stays inside the process, replacing the external program when `decision.jev.command` is not set, and also gains `wev jev ask|batch`. The setup does not touch the user's global configuration (`~/.claude/CLAUDE.md`, `agent-model-hook.mjs`).
- **Shared third parties:** one copy of each source, linked to all harnesses. The daily check is global, so rollback and freezing apply to all of them at once.
- **New version of agent-skills:** it is the latest release (the repository publishes tags; `0.6.13` on 2026-10-20). For sources without a release, it is the HEAD of the default branch.
- **Uninstall removes only what wev wrote.** Each entry that wev writes into harness configs is recorded in a manifest, and the uninstall deletes only those. Entries the user already had beforehand stay.
- **Depth of the adapters:** each adapter carries everything the harness supports (skills, session-start hook, command guard, subagents, per-prompt reminder). What cannot be carried is written in the documentation, with an evidence label.
