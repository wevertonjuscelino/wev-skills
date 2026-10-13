# Estimating task signals

`run start` classifies the task from signals you supply. The engine cannot see your intent, so the quality of the classification is the quality of your estimate. When you are unsure, choose the higher number or set the flag, and tell the user you were unsure; a cautious flow costs a little ceremony, a careless one can cost a lot more.

| Flag | Meaning | How to estimate |
|---|---|---|
| `--objective TEXT` | The task in one sentence | Use the user's words; do not paste secrets |
| `--files N` | Files the change will touch | Search first (grep, file listing) and count the files you would edit, including tests and docs |
| `--unknowns N` | Open questions that could change the approach | Count real unknowns: unfamiliar subsystem, unclear requirement, unknown cause of a bug |
| `--subtasks N` | Independent pieces of work | Pieces that touch different files and do not depend on each other |
| `--remote` | Touches a remote system | Any SSH, remote host or tmux work |
| `--production` | Touches production | Any production host, database or deployment |
| `--destructive` | Deletes or overwrites data | Removals, migrations that drop data, force operations |
| `--external` | Side effects outside the repository | Push, publish, deploy, send a message |
| `--no-tests` | The affected code has no tests | Look for tests that cover the area; set the flag when there are none |
| `--irreversible` | Cannot be undone | Anything you could not roll back with Git |

Signals can also come from a JSON file with `--signals-file PATH`. Its keys are `objective`, `files_touched_estimate`, `touches_remote`, `touches_production`, `destructive`, `external_side_effects`, `has_tests`, `reversible`, `unknowns` and `independent_subtasks`.

The engine also reads the objective text: keywords for risky actions in English and Portuguese (deploy, delete, production and similar) set a minimum for risk and complexity. Understating a flag cannot lower the result below that floor, and an external decision provider can only raise risk and complexity, never remove a review or an approval.

To preview a decision without starting a run, use `classify` or `strategy` with the same flags (`strategy` also takes `--mode`). `route-model` shows which model tier would be chosen.

Observed behavior (local policy): a task with one file and no unknowns became `direct`; eight files and one unknown became `planned` with independent review required; `--production` made the run `gated` with high risk. These are results of one run each, not a guarantee for other inputs; always read the `strategy.reasons` the engine prints.
