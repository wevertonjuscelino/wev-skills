# Operator setup checklist

For the person who owns the hosts. The skill itself never performs these steps.

1. In `~/.ssh/config`, define a `Host` alias for each machine (hostname, user, port). The wev config refers to the alias, never to a raw address.
2. Load the key into an SSH agent so connections need no prompt. wev connects non-interactively and fails instead of asking for a password.
3. Connect once by hand so the host key is in `known_hosts`. wev uses strict host-key checking and will not accept an unknown key.
4. Make sure `tmux` is installed on each host. Optionally make sure `timeout` exists if you want to use `--timeout`.
5. List the hosts in the wev config file:

```json
{
  "remote": {
    "hosts": [
      { "alias": "staging-1", "environment": "staging", "allow_mutating": false }
    ]
  }
}
```

   `environment: "production"` makes every remote command on that host require a human approval for the exact action. `allow_mutating: false` (the default) limits the host to read-only commands.
6. Validate the file: `wev config validate path/to/config.json`. Put it at `<repository root>/wev.config.json` to have it found automatically; a run pins it when it starts.
7. For the first real use, run `remote preflight` and then one harmless read-only command on a staging host, and check the result yourself. The module has so far been tested only against a simulated host.

Approvals: when a command needs one, the agent can file a request with `wev approval request`, and you decide in your own terminal with `wev approval list --status pending`, `wev approval show <id>` and `wev approval grant <id>`. A grant covers one use of the exact action (host alias and command) in one run, and expires after `permissions.approval_ttl_seconds` (default 900). Granting needs an interactive terminal and a typed confirmation; there is no flag to skip it. `wev approval verify` compares the approvals file with the audit log and lists mismatches. Both files live in the state directory, which the agent's own file tools could rewrite, so treat them as records.
