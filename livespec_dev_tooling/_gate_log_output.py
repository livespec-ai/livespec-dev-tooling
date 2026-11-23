"""The observable checksum for a captured delegated-gate log."""

from __future__ import annotations

import hashlib
import sys

from livespec_dev_tooling.gate_remote_request import GateRunRequest

__all__: list[str] = ["shown_output_checksum"]


def shown_output_checksum(*, request: GateRunRequest, output: str) -> str:
    """Show a captured log to the operator and checksum it; an uncaptured one has none."""
    if not request.capture_output:
        return ""
    _ = sys.stdout.write(output)
    return f"sha256:{hashlib.sha256(output.encode('utf-8')).hexdigest()}"
