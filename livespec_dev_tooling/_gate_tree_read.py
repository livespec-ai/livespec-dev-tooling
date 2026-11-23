"""Read a delegated gate's requested Git tree through its command seam."""

from __future__ import annotations

import sys
from pathlib import Path

from livespec_dev_tooling.gate_remote_invocation import (
    GateCommandRunner,
    GateStepFailed,
    require_success,
)
from livespec_dev_tooling.gate_remote_request import GateRunRequest

_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from returns.result import Result  # noqa: E402  — vendored dependency.

__all__: list[str] = ["head_tree_hash"]


def head_tree_hash(
    *, request: GateRunRequest, runner: GateCommandRunner
) -> Result[str, GateStepFailed]:
    """Read the tree to gate without bypassing the injectable command runner."""
    argv = ["git", "rev-parse", "HEAD^{tree}"]
    lifted = require_success(
        step="read-tree-hash", argv=argv, outcome=runner(argv=argv, cwd=request.repo_root)
    )
    return lifted.map(lambda ran: ran.stdout.strip())
