"""Preserve the gate Job timestamps observed before a polling failure."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from livespec_dev_tooling.gate_remote_invocation import GateStepFailed
from livespec_dev_tooling.gate_remote_job_status import reported_time

__all__: list[str] = ["GateTimingObservations"]

_START_TIME = "startTime"


@dataclass(kw_only=True)
class GateTimingObservations:
    """The cluster clock readings observed before this client stops waiting."""

    job_name: str
    created_at: str
    started_at: str = ""

    def observe_status(self, *, status: Mapping[str, object]) -> None:
        self.started_at = reported_time(status=status, key=_START_TIME) or self.started_at

    def failure(self, *, failure: GateStepFailed) -> GateStepFailed:
        """Attach the submitted Job's readings without changing the failure step."""
        return GateStepFailed(
            step=failure.step,
            argv=failure.argv,
            returncode=failure.returncode,
            detail=failure.detail,
            job_name=self.job_name,
            job_created_at=self.created_at or None,
            job_started_at=self.started_at or None,
        )
