"""Test package. Importing it points the per-user registry of active runs at a temporary
directory, so no test (and no ``wev`` subprocess a test starts) writes under the real home."""

from __future__ import annotations

import atexit
import os
import shutil
import tempfile

_STATE_HOME = tempfile.mkdtemp(prefix="wev-test-state-home-")
os.environ["XDG_STATE_HOME"] = _STATE_HOME
atexit.register(shutil.rmtree, _STATE_HOME, True)
