# Security guide

Portuguese version: [security.pt-BR.md](security.pt-BR.md).

This guide explains the permission model and what each control does and does not protect against. The policy for reporting a vulnerability, the supported versions, the full list of controls and the known limits are in [SECURITY.md](../../SECURITY.md); this guide is the operator's view and does not replace it.

## The position, stated once

wev-skills is a guardrail for a fallible agent and a recorder of decisions. It is **not a security boundary against an adversarial agent** in the same user account.

The reason is structural. The engine runs in the same user account as the agent it constrains. Inside one account the CLI cannot authenticate who is typing, and every file the engine keeps (run state, approvals, audit log, configuration, run registry) can be rewritten by the agent with its own tools. No key stored in that account would change this, because the agent could read the key too.

What follows from that:

- The engine catches mistakes: a destructive command run by accident, a command in the wrong mode, a secret pasted into a log, a remote start on the wrong host.
- The human gate that exists is Claude Code's own permission prompt. The plugin's `PreToolUse` hook answers `ask` for the sensitive Bash command lines it can read (the grant command typed directly, behind a known wrapper, or in an inline `sh -c`), and the person's answer in that prompt is the approval for that call. A script the hook cannot see into, or a pseudo-terminal driven by one, is not stopped.
- Without the plugin's hooks, approvals are records, not gates.
- An agent that sets out to defeat the engine can. Isolation has to come from outside: a container, a separate user, operating-system permissions, the permission settings of the agent platform.

This position, the review that led to it and what remains open are recorded in [ADR 0006](../architecture/decisions/0006-guardrail-not-boundary.md).

Status of the controls: implemented and tested with unit tests (`tests/unit/`) and a dedicated security suite (`tests/security/`). Three rounds of independent review on 2026-10-13, before publication, found the approval and hook controls bypassable by the constrained agent; the position above and the fixes that followed come from them. Each round was followed by fixes; the fixes made after the last round have not been independently re-verified, and the hooks have never run inside a live Claude Code session.

## The model in one picture

Rules that code can check live in the engine, not in Markdown (ADR 0002). Several layers apply to one action, and the most restrictive answer wins:

1. **The agent spec**: tools allowed and denied, modes, maximum risk, whether the agent may change files or use remote hosts, and the permission ceiling (see the [agent guide](creating-agents.md)).
2. **The run**: its mode (`plan` allows only read-only commands), its pinned configuration and the risk of the task.
3. **The permission policy**: for each command, deny list, plan-mode rule, protected paths, then whether approval is needed.
4. **Approvals**: a decision record bound to one exact command, directory and run.
5. **The execution guard**: loops, repeated failures, no progress, budget and time.
6. **The hooks**: a pre-check of Bash commands inside Claude Code, which is where a person's answer becomes the approval.
7. **Redaction and untrusted-data handling** for what is stored, logged or read back.
8. **The remote module's own checks** (inventory, host keys, session ownership).

## Risk levels

| Level | What the engine does |
|---|---|
| low | Act directly with proportional checks |
| medium | Plan, validate, require independent review |
| high | The flow is `gated`: an explicit human approval before the impactful operation |

The local policy computes the level from the signals you give and from the words of the objective. Production, a destructive action, external side effects (push, publish, deploy) or an irreversible remote action raise it to high; a remote system, an irreversible change, more than 5 files, or untested code across several files raise it to medium. The objective text is also scanned in English and Portuguese for words that name those things (a floor: it can only raise a signal, it has false positives and it misses paraphrases). A decision provider may raise the computed risk and complexity and can never lower either, so it can never remove a review or an approval. A task's own `risk` in a plan can only raise its effective risk.

## Controls

| Control | What it does | What it does not protect against |
|---|---|---|
| No shell | The executor runs an argument vector directly and rejects shell metacharacters in a command string unless `permissions.allow_shell` is true. It looks a bare program name up only in `permissions.exec_path`, never in `$PATH`, records the resolved path, and refuses a program that resolves inside the working tree | A script file, an alias or a renamed binary can do anything the OS allows. The engine does not read what a program does. The child inherits your environment, including `PATH` for what it starts itself |
| Command classification | Marks commands destructive, privileged, network, external-effect or unanalyzable (recursive removal, `sudo`, `git push`, package install, `ssh`, destructive SQL, inline code, wrappers such as `nohup`, `timeout`, `script`, git options given by unique prefix or `-c`) and requires approval for the risky ones. Looks behind `sudo`, `env`, `sh -c` and similar wrappers | It is a heuristic. A command it does not recognize may be treated as lower risk than it is. `python3 script.py`, `make`, `mv`, `sed -i`, redirections and unknown absolute-path programs pass in execute mode |
| Deny and allow lists | `denied_commands` patterns deny, also behind wrappers; a non-empty `allowed_commands` sends everything outside it to approval | Patterns match command prefixes, not intent |
| Plan mode | Denies every command not on a short read-only list (common diagnostics; refused with options that write, execute, reach another machine or change state; `sed`, `awk`, `tee`, `xargs`, `env` are never on it) | It governs commands that pass through the engine or the hook. Edits made with Claude Code's own file tools are not seen |
| Protected paths | A command whose argument names `.git`, the dot-env file, the state directory (or another configured path) is denied, including a glob that may match one. Path helpers refuse traversal and symlink escape. The state directory is always protected | A program that opens a protected file on its own, without the path as an argument, is not caught. Paths are resolved when the command is judged; a symlink swapped later is not covered |
| Approvals | A grant covers one exact argv, in one resolved directory, in one run (for a remote action, one host alias). Single use, expires after `permissions.approval_ttl_seconds` (default 900). A denial is final for the same words in the same order within the run (the working directory, risk, reason, quoting and token grouping do not make a fresh request; a remote denial is per host); only `approval request --reopen-denied` reopens it. A request records `requested_by`, a name the caller supplies; a decision records the operating-system user, the terminal and the time; nothing compares the two. A command whose text redaction would alter is refused. `wev approval verify` cross-checks the approvals file with the audit log | They are records, not proof. The comparison for a denial is on words and does not resolve paths (`build` and `./build` differ). An agent with file tools can write the approvals file and the matching audit event. `grant`, `deny`, `guard acknowledge` and `task reopen` ask for a terminal and a typed word, which a pseudo-terminal can supply. There is no bypass flag |
| Redaction | Masks recognizable secrets (well-known token formats, private-key blocks, values after secret-named flags, `Authorization` headers, credentials inside URLs, cookie headers, well-known webhook URLs) before text is logged, stored in state, written to logs or sent to JEV. An argv is redacted as a whole, also on refused paths (`tests/integration/test_refused_redaction.py` searches the state directory for a canary after allowed, denied, approval-required and guard-refused runs), and any audit event that stores a list under `argv` is masked as one command line | Best effort. A secret with no recognizable shape and no telling name, or one encoded, split or obfuscated, is not masked. The full list of misses is in SECURITY.md |
| Untrusted data | Command output tails, remote capture, the run brief, the report and the discovery output returned by `wev run start` are stripped of control characters and escape sequences and fenced as data. `wev scan-untrusted --source NAME` reports instruction-like patterns; `--wrap` fences text | Detection is pattern-based and only informs; paraphrases, other languages and encodings get through. Nothing technical stops a model from obeying an instruction it reads |
| Execution guard | Detects loops (identical and alternating commands), repeated failures, no progress, hand-off cycles, overruns, polling beyond a cap. While a `stop` or `ask_human` verdict stands, `wev exec` and `wev task check` are refused (exit 6) and `task next` hands out nothing; every trip stays in the report. Only a person acknowledges it | It returns verdicts and refuses engine commands; it does not kill anything and does not see commands run outside `wev exec` |
| Audit log | `.wev/audit.jsonl`: one redacted JSON line per significant event | A plain file written by your user account; a record, not tamper-proof storage |
| Agent fields | `permissions.may_mutate` (an agent with `false` may run read-only commands, the task's declared checks and the checks discovered at `run start`, by exact argv; the rest is refused with `agent_read_only`), `modes`, `max_risk`, `may_use_remote`, `ceiling`, `required_checks`, `budget.max_units`, `max_attempts` and `timeout_seconds` are enforced by the engine. `stop_conditions`, `success_criteria`, `escalation` and `output_format` are instructions only | The ceiling constrains specs when they are loaded, not processes. With two tasks running, the caller still chooses which running task a `wev exec` is for; the engine cannot tell which agent is typing |
| Remote module | Only inventory aliases; non-interactive SSH with strict host-key checking; unique tmux session names per task and host; never touches a session it did not create; never issues `kill-server`; mode, risk and inventory come from the active run; the task's agent must allow remote use; production needs approval for the exact command; status needs proof of ownership before trusting an exit file | Tested against a simulated host only (see the [remote guide](remote-ops.md)). Once a command starts, the host is outside the engine's control. It cannot make a command safe that the policy allows |

## The hooks

With the plugin installed, three hooks run `wev hook <name>`:

| Hook | Does |
|---|---|
| `SessionStart` (after `compact` or `resume`) | Prints the brief of the active run (sanitized, fenced), labeled as recorded state to be checked with `wev run resume` |
| `UserPromptSubmit` | Prints the brief, capped at `harness.plan_reminder_max_chars`, when `harness.plan_reminder` is true |
| `PreToolUse` on `Bash` | Judges the command under the active run's pinned configuration, mode and the highest risk among its running tasks. Policy deny becomes `deny`; needs approval becomes `ask`, which hands the decision to the person through Claude Code's own prompt; allow prints nothing |

Properties, each covered by tests:

- **It can only deny or ask, never allow**, and it never reads the approval store. A destructive command is `ask` every time; the person's answer in the prompt is the approval for that call. The hook cannot widen what your Claude Code permission settings allow.
- **It finds the run** from the hook's directory, its enclosing directories and every path the command names (`cd`, `pushd` and `git -C` are followed), also through a per-user registry of active runs. A command started in `/tmp` that touches a run's tree is judged by that run. Looking is read-only; the work is capped.
- **It routes the engine's own sensitive commands to the person**, when the command line is one it can read: `approval grant`, `approval deny`, `approval request` (with or without `--reopen-denied`), `guard acknowledge`, `task reopen`, `run start`, `run finish`, `agent create`, `agent export`, `remote start`, `remote stop`, `jev ask` and `jev batch` (they send a file's content to the JEV service) and anything carrying `--config`. It recognizes them by words (the launcher by real path, the bare word `wev`, or `-m wev_skills`, followed by the subcommand), directly, behind a wrapper the classifier knows (`nohup`, `nice`, `timeout`, `time`, `stdbuf`, `setsid`, `env`, `xargs` and the rest of its list), inside an inline `sh -c`, `bash -c` or `zsh -c`, or as arguments handed to another program. The exemption from the ordinary policy still applies only to a program that resolves by real path to the plugin's `bin/wev` or to the running interpreter with `-m wev_skills`.
- **It also asks** for `rm` with abbreviated long options (`--recursiv`, `--forc`), `git rm -r`/`-f`, any `git clean` that is not a dry run, `rsync --delete*` and `--remove-source-files`, and for a recursive reader (`grep -r`, `rg` with `--hidden`/`-uu`, `find`, `tar`, `zip`, `cp -r`/`-a`, `rsync -r`/`-a`) given a directory that contains a protected path (a direct read of the protected file is still denied). It is a heuristic over a fixed list of programs and options, looks at directories that exist when the command is judged, walks at most 20,000 entries (a larger tree is treated as holding a protected path), does not read exclusion options, and `rg` without `--hidden` is not asked about hidden protected names because it skips hidden files.
- **It asks (and denies in plan mode) for what it cannot read with certainty**: a variable assignment before a command, `env`, `export`, parameter and command expansion, quoting forms that hide text, globs, brace lists, `eval`, `source`, `exec`, `command`, `builtin`, `script`, `expect`, `xargs`, `find -exec`, git configuration on the command line, `git -C` outside the run root, a shell running a script file, one argument that holds a whole command line. A command line with pipes, lists or redirections is split and the most restrictive result over its parts wins, redirection targets included.
- **Without a run, it judges under the built-in default policy** (execute mode, medium risk, rooted at the git top-level of the hook's directory). A repository configuration is not read then, so a file in the tree cannot loosen it. Approvals and loop detection apply only inside a run.
- **It fails to `ask`, not to silence.** An unreadable state, an internal error and a command too long to analyze become `ask`, with or without a run. Malformed or oversized input (more than 1 MiB) is `ask` when a run is known and silent without one: the command is unknown. Real examples (2026-10-13): with garbage on stdin and no run known, the hook printed a one-line note on stderr, no decision, and exited 0; in a directory with a run in plan mode, the same garbage printed an `ask` decision ("the command was not checked and a person decides"), `rm -rf build` printed a `deny`, and `FOO=1 ls` printed a `deny` (an `ask` outside plan mode).
- Under a Python older than 3.14, `bin/wev` exits quietly for the hook subcommands and says on stderr that nothing was checked. The stock macOS `/usr/bin/python3` is 3.9 and is not supported, so the plugin needs the `python3` on `PATH` to be 3.14 or newer (`python3 --version`, and `command -v python3` to see which one is used).

Limits: only the Bash tool passes through the hook. Edits made with Claude Code's own file tools are not seen, including edits to the state directory, the approvals file, the audit log, the configuration and the per-user registry. An agent can forge a grant and its audit event, mark a run finished, or remove a registry entry so that the hook finds no run. A pseudo-terminal can type the confirmation word of the operator commands; without the hook routing them to the prompt, nothing stands in the way. The hook cannot see inside a script file or a program: a script that types into a pseudo-terminal (for example `python3 pty_type.py`, where the script itself starts the engine on a pseudo-terminal and types the confirmation word) names nothing on the command line the hook reads, so it is not asked about. The hooks act only when the plugin is installed and enabled. Nothing has been observed in a live session. The decision to use plain hooks rather than Claude Code mods is in [ADR 0005](../architecture/decisions/0005-hooks-not-mods.md).

More open limits, in full in [SECURITY.md](../../SECURITY.md):

- **Plan amendments are recorded, not prevented.** `wev plan set` refuses to change the acceptance criteria, checks, files, risk or `read_only` flag of a task that has ever been started, unless given `--amend --reason <text>`; whoever can run `plan set` can amend. An amendment is a decision plus a `plan.amended` audit event, resets that task's verification and is listed in the report under "Plan amendments" with before and after. The engine does not judge whether the new criteria are weaker.
- **The fingerprint and ignored files.** The tree fingerprint covers the commit, the status, staged and unstaged diffs and the size and modification time of untracked files git does not ignore. A change to a git-ignored file is not seen as work and does not invalidate a verification. `wev plan set` warns when a task's `files` or a check's arguments name an ignored path, and `task check` and the report carry a notice.
- **Run lookup for paths built from variables.** The hook also matches a path that is a parent of a registered run root (`rm -rf <parent of the repository>`). A path built from a variable cannot be matched: when no run is found and any run is registered for the user, a command with a `$` expansion in a word is answered `ask`. A command matched to no run gets the built-in default policy, not a run's additions.
- **The report is recomputed at report time, not continuously.** At `wev run report` and `wev run finish` the tree is compared with the one at the latest `verified` record; if it differs and no task is running, verified tasks whose checks have not passed on the current tree are reported as "verified, then changed" and the status is `incomplete` until `wev task check <id>` passes again. A change made and reverted between two reports is not seen.

## What an agent must do when it meets a human-operator command

`wev approval grant`, `approval deny`, `approval request --reopen-denied`, `guard acknowledge` and `task reopen` are the operator's. An agent that needs one stops, shows the person the action, the reason and the id, and asks them to run it in their own terminal. It does not look for a flag, a pseudo-terminal or another route. The engine's next steps never print a grant command as something to run.

## Safe operating practice

- **Least privilege and isolation.** Run agents as a dedicated user or in a container, with a limited working directory and no production credentials in the environment. The engine runs allowed commands as you; an adversarial agent has to be contained from outside.
- **Layer it.** Keep Claude Code's own permission settings on and keep the plugin's hooks enabled. Read the exact command in each prompt before you allow it.
- **Start in `plan` mode** on a repository you do not know. Read the plan before `execute`.
- **Estimate the signals honestly.** `--production`, `--destructive`, `--external`, `--remote` and `--irreversible` exist so that a risky task becomes `gated`. When unsure, set the flag.
- **Read an approval before you grant it.** Run `wev approval show <id>` and read the exact command. Grant in your own terminal. Run `wev approval verify` when something looks off.
- **Review the diff.** The engine records what it was told; the diff shows what happened. `verified` means a check that could fail passed on the tree as it is, not that the work is correct.
- **Tighten the policy for your project.** Use `denied_commands` for commands that should never run and `allowed_commands` to turn everything else into an approval. Keep `allow_shell` false. If you set `protected_paths`, repeat `.git` and the dot-env file. Keep the configuration file in the repository root only if you trust what is committed there; `decision.jev.command` and `agents.directories` are restricted so a repository file cannot pick what runs.
- **Keep secrets out of objectives, plans, summaries and command lines.** They are stored in `.wev/` and, for objectives, sent to JEV if you enable it. Use files or environment variables. Redaction is a net with holes.
- **Treat `.wev/` and the configuration as sensitive.** They decide the policy and hold the record, including logs of every command. Keep them out of shared or world-writable locations.
- **Treat logs, captured remote output and web pages as data.** Use `wev scan-untrusted` when you pass them to a model.
- **Never point the remote module at production without a person watching each impactful operation**, and do a first real run on staging (see the [remote guide](remote-ops.md)).
- **Before publishing a fork or copy**, run `python3 scripts/scan_secrets.py` (a tripwire for obvious mistakes, not a scanner that finds everything), pin workflow actions to commit SHAs, and read the hook files yourself.

## Reporting a problem

See [SECURITY.md](../../SECURITY.md). Report a vulnerability through GitHub's private vulnerability reporting on the repository (Security tab, "Report a vulnerability"); do not open a public issue for it.
