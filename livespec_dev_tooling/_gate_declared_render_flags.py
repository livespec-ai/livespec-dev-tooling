"""Resolve the gate renderer flags owned by a consuming repository."""

from __future__ import annotations

import sys
from pathlib import Path

from livespec_dev_tooling._gate_authority_skip import authority_skip_resolution
from livespec_dev_tooling._gate_remote_assembly import declared_gate_job_resources
from livespec_dev_tooling.gate_remote_invocation import GateStepFailed

_VENDOR_DIR = Path(__file__).resolve().parent / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from returns.result import Failure, Result  # noqa: E402  — vendored dependency.

__all__: list[str] = ["declared_render_flags"]


def declared_render_flags(
    *, repo_root: Path, refusal_step: str
) -> Result[tuple[tuple[str, ...], tuple[str, ...]], GateStepFailed]:
    """Return host-skip and resource flags, or the repository's refusal."""
    authority_skip = authority_skip_resolution(repo_root=repo_root)
    if authority_skip.refusal is not None:
        return Failure(
            GateStepFailed(
                step=refusal_step,
                argv=(),
                returncode=None,
                detail=authority_skip.refusal,
            )
        )
    return declared_gate_job_resources(repo_root=repo_root).map(
        lambda resources: (authority_skip.argv, resources)
    )
