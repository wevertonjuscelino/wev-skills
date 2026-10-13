"""Command groups. Each module here exposes ``register(subparsers)``."""

from __future__ import annotations

import argparse
from collections.abc import Callable

type Subparsers = "argparse._SubParsersAction[argparse.ArgumentParser]"
"""What ``ArgumentParser.add_subparsers`` returns; every ``register`` takes one."""

type Handler = Callable[[argparse.Namespace], object]
"""A command handler: gets the parsed arguments, returns the payload (or a ``CommandResult``)."""
