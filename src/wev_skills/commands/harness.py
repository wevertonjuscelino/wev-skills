"""``wev harness export``: build the package files of one harness into a directory."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from wev_skills import i18n
from wev_skills.adapters.harness_package import TARGETS, build_package, skipped_notes
from wev_skills.commands import Subparsers
from wev_skills.core.errors import ValidationError
from wev_skills.core.wiring import REPO_ROOT


def _export(args: argparse.Namespace) -> dict[str, Any]:
    wev = Path(args.wev).resolve() if args.wev else REPO_ROOT / "bin" / "wev"
    if not wev.is_file():
        raise ValidationError(
            "wev_missing", i18n.t("harness.error.wev_missing", path=str(wev)), {"path": str(wev)}
        )
    out = Path(args.out).resolve()
    files = build_package(args.target, out, wev)
    return {
        "target": args.target,
        "out": str(out),
        "files": [str(p) for p in files],
        "skipped": skipped_notes(args.target),
    }


def register(subparsers: Subparsers) -> None:
    harness = subparsers.add_parser("harness", help=i18n.t("harness.help"))
    actions = harness.add_subparsers(dest="harness_command", metavar="<command>", required=True)
    export = actions.add_parser("export", help=i18n.t("harness.export.help"))
    export.add_argument("--target", required=True, choices=TARGETS,
                        help=i18n.t("harness.export.target"))  # fmt: skip
    export.add_argument("--out", required=True, help=i18n.t("harness.export.out"))
    export.add_argument("--wev", default=None, help=i18n.t("harness.export.wev"))
    export.set_defaults(handler=_export)
