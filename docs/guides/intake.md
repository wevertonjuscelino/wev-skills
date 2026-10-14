# Objective intake

[Português brasileiro](intake.pt-BR.md).

`wev intake` records the interview before a run. An agent can extract fields already
stated in the request with `--source request`, then ask only about missing required
fields. Each `next` consumes one round and returns at most three questions. The engine
requires an objective (`goal`), completion evidence (`done`), scope and work kind; constraints
are optional. A clear request needs no questions.

```sh
wev intake start --request 'Add a CSV export to reports'
wev intake set ID --field goal --value 'Reports download as CSV' --source request
wev intake next ID
wev intake set ID --field done --value 'The download contains all selected rows' --value 'Tests pass'
wev intake set ID --field scope --value 'Reports only'
wev intake set ID --field kind --value feature
wev intake finish ID
wev run start --from-intake ID
```

Replace `ID` with the identifier returned by `start`. `show ID` retrieves an interview,
including its finished brief and a suggested run command. `finish` refuses incomplete
records and finished interviews cannot be edited.

Configure `intake.max_rounds` in `wev.config.json` (default 3, integer 1–10). On exhaustion,
`next` returns no questions and lists `must_assume`. It never silently invents answers:
record a conservative assumption with `set --field FIELD --source assumption`, optionally
supplying `--value`, and disclose it to the user. Missing values get conservative defaults.
Assumptions remain separate from confirmed answers in the brief.

Records live under `<state_dir>/intakes`, are ignored by Git, private to the current user,
and written atomically under a per-record lock. Text is cleaned and known secret patterns
are redacted; redaction does not guarantee recognition of every possible secret.

`run start --from-intake ID` requires a finished interview and uses its goal as the
objective. An explicitly different `--objective` is refused. Operations retain the external
side-effect signal and assumptions establish a minimum unknown count. The complete brief
is saved in run state, copied into a `run.intake_attached` audit event and returned
to the caller. Plan reminders carry the scope, constraints and completion criteria. The interview
and its evidence describe intent; execution verification and human approval gates still
apply normally.
