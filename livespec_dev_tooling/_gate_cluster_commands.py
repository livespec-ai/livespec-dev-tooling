"""Shared cluster command construction for the delegated gate client."""

from __future__ import annotations

from pathlib import Path

from livespec_dev_tooling._gate_abandoned_job_record import abandon_gate_job
from livespec_dev_tooling.gate_credential import with_gates_kubeconfig
from livespec_dev_tooling.gate_remote_invocation import GateCommandRunner, StepOutcome
from livespec_dev_tooling.gate_remote_request import GateRunRequest

__all__: list[str] = ["delete_abandoned_job", "kubectl"]


def kubectl(*, request: GateRunRequest) -> list[str]:
    """Return the namespaced kubectl prefix through the gates credential wrapper."""
    return with_gates_kubeconfig(argv=["kubectl", "--namespace", request.namespace])


def delete_abandoned_job(
    *, request: GateRunRequest, runner: GateCommandRunner, job_name: str
) -> tuple[StepOutcome, Path]:
    """Save an unfinished Job's logs then request its deletion."""
    return abandon_gate_job(
        request=request, runner=runner, job_name=job_name, kubectl=kubectl(request=request)
    )
