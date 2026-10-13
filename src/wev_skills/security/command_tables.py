"""Static tables behind ``security.commands``: which programs and subcommands carry which risk.

Each entry is ``(flags, reason code)``; the flags are the letters of ``risk.FLAG_FIELDS``.
"""

from __future__ import annotations

import re

Entry = tuple[str, str]

PUBLISH: Entry = ("xn", "publish")
INSTALL: Entry = ("xn", "install")
INFRA = dict.fromkeys(("delete", "destroy", "rm", "rmi", "apply", "prune"), ("dx", "infra"))
SERVICE = dict.fromkeys(("stop", "restart", "disable", "mask", "kill"), ("dx", "service"))
NODE_PM = {
    "publish": PUBLISH,
    "unpublish": PUBLISH,
    "install": INSTALL,
    "i": INSTALL,
    "ci": INSTALL,
    "add": INSTALL,
}
APT = dict.fromkeys(("install", "upgrade", "remove", "purge", "dist-upgrade"), INSTALL)

ALWAYS: dict[str, Entry] = {
    **dict.fromkeys(("sudo", "doas", "su", "pkexec"), ("p", "privileged")),
    **dict.fromkeys(("dd", "shred", "wipefs", "truncate"), ("d", "raw_write")),
    **dict.fromkeys(("shutdown", "reboot", "halt", "poweroff"), ("dx", "power")),
    **dict.fromkeys(("pkill", "killall"), ("d", "kill")),
    **dict.fromkeys(("curl", "wget", "rsync", "nc", "ncat", "telnet", "ftp"), ("n", "network")),
    **dict.fromkeys(("ssh", "scp", "sftp"), ("xn", "remote")),
    **dict.fromkeys(("crontab", "at", "launchctl"), ("x", "schedule")),
    # Programs that run text or another program the classifier cannot follow.
    **dict.fromkeys(
        ("eval", "source", ".", "exec", "command", "builtin", "script", "expect", "xargs",
         "parallel", "unbuffer", "alias", "trap"),
        ("u", "runs_text"),
    ),
}  # fmt: skip

# Program -> subcommand words (matched as a contiguous run of non-flag arguments).
SUBCOMMANDS: dict[str, dict[str, Entry]] = {
    **dict.fromkeys(("npm", "pnpm", "yarn", "bun"), NODE_PM),
    **dict.fromkeys(
        ("docker", "podman", "docker-compose", "kubectl", "terraform", "tofu", "helm"), INFRA
    ),
    **dict.fromkeys(("systemctl", "service"), SERVICE),
    **dict.fromkeys(("apt", "apt-get"), APT),
    **dict.fromkeys(("pip", "pipx"), {"install": INSTALL}),
    "uv": {"pip install": INSTALL, "add": INSTALL, "publish": PUBLISH},
    "brew": dict.fromkeys(("install", "upgrade", "reinstall"), INSTALL),
    "twine": {"upload": PUBLISH},
    "cargo": {"publish": PUBLISH, "install": INSTALL},
    "gem": {"push": PUBLISH, "install": INSTALL},
    "go": {"install": INSTALL, "get": INSTALL},
    "gh": {
        "release create": PUBLISH,
        "repo create": PUBLISH,
        "pr merge": PUBLISH,
        "repo delete": ("dxn", "publish"),
        "release delete": ("dxn", "publish"),
    },
}

SQL_CLIENTS = frozenset(
    {"psql", "mysql", "mariadb", "sqlite", "sqlcmd", "duckdb", "bq", "snowsql",
     "clickhouse-client", "cockroach"}
)  # fmt: skip
SQL_DROP = re.compile(r"\b(?:drop|truncate)\b|\bdelete\s+from\b", re.IGNORECASE)
SQL_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish"})
INTERPRETERS = {
    "python": "c",
    "node": "ep",
    "ruby": "e",
    "perl": "eE",
    "php": "r",
    "bun": "e",
    "deno": "",
    "osascript": "e",
}
INTERPRETER_LONG = ("--eval", "--print")
# Programs that run the command given after their own options. Every suffix of the argv
# is looked at as a possible command, so their options need no table.
WRAPPERS = frozenset(
    {"sudo", "doas", "su", "pkexec", "env", "xargs", "nohup", "nice", "gnice", "ionice", "time",
     "timeout", "gtimeout", "command", "exec", "builtin", "stdbuf", "gstdbuf", "setsid", "watch",
     "busybox", "ssh", "chroot", "flock", "parallel", "caffeinate", "script", "expect", "arch",
     "unbuffer", "eval", "nsenter", "unshare", "strace", "ltrace", "doasedit"}
)  # fmt: skip
STRING_WRAPPERS = frozenset({"su", "ssh", "watch", "expect", "script"})
FIND_EXEC = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
ENV_SPLIT = ("-S", "--split-string")
RM_LONG = ("--recursive", "--force", "--no-preserve-root")
RSYNC_DELETE = (
    "--del",
    "--delete",
    "--delete-before",
    "--delete-during",
    "--delete-delay",
    "--delete-after",
    "--delete-excluded",
    "--delete-missing-args",
    "--remove-source-files",
)
"""rsync options that remove files on one side; unique prefixes count (``--delete-aft``)."""
WGET_SEND = ("--post-", "--method", "--body-")
CURL_SEND = (
    "--data",
    "--data-raw",
    "--data-binary",
    "--data-urlencode",
    "--form",
    "--upload-file",
    "--json",
)
# Programs whose arguments are patterns, scripts of their own or prose: a shell operator in
# one of them is data. For every other program such an argument is flagged.
TEXT_ARGUMENT_PROGRAMS = frozenset(
    {"grep", "egrep", "fgrep", "rg", "ag", "ack", "sed", "awk", "gawk", "jq", "yq", "echo",
     "printf", "git", "gh", "test", "[", "expr", "find", "cut", "tr", "sort", "column", "head",
     "tail", "cat", "wc", "ls", "wev"}
)  # fmt: skip
