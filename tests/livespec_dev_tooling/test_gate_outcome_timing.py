"""Cluster-clock intervals for delegated-gate telemetry stay exact or absent."""

from __future__ import annotations

from pathlib import Path

from livespec_dev_tooling._gate_cluster_commands import kubectl
from livespec_dev_tooling._gate_log_output import shown_output_checksum
from livespec_dev_tooling._gate_mirror_push import mirror_push
from livespec_dev_tooling._gate_outcome_emission import emit_outcome
from livespec_dev_tooling._gate_run_observation import GateTimingObservations
from livespec_dev_tooling.gate_outcome_telemetry import gate_timing_seconds
from livespec_dev_tooling.gate_remote_invocation import GateStepFailed
from livespec_dev_tooling.gate_remote_job_status import terminal_transition_time
from livespec_dev_tooling.gate_remote_request import GateRunRequest
from livespec_dev_tooling.gate_remote_verdict import GATE_NO_VERDICT, GateVerdict

__all__: list[str] = []


def test_gate_timing_uses_the_jobs_creation_admission_and_terminal_timestamps() -> None:
    """Queue wait and run duration have different origins in the Job status."""
    assert gate_timing_seconds(
        created_at="2026-11-23T10:00:00Z",
        admitted_at="2026-11-23T10:02:30Z",
        terminal_at="2026-11-23T10:09:15Z",
    ) == (150.0, 405.0)


def test_gate_timing_omits_only_the_interval_the_cluster_has_not_reported() -> None:
    """An admitted but unfinished Job keeps its queue wait without a guessed duration."""
    assert gate_timing_seconds(
        created_at="2026-11-23T10:00:00Z",
        admitted_at="2026-11-23T10:02:30Z",
        terminal_at=None,
    ) == (150.0, None)


def test_gate_timing_omits_unreadable_cluster_clock_readings() -> None:
    """A malformed timestamp stays absent instead of changing the gate's verdict."""
    assert gate_timing_seconds(
        created_at="not-a-cluster-time",
        admitted_at="2026-11-23T10:02:30Z",
        terminal_at="2026-11-23T10:09:15Z",
    ) == (None, 405.0)


def test_terminal_transition_time_is_absent_without_the_matching_condition() -> None:
    """A terminal reading belongs only to the condition that ended this Job."""
    assert (
        terminal_transition_time(
            status={"conditions": [{"type": "Failed", "status": "True"}]}, condition="Complete"
        )
        == ""
    )


def test_gate_timing_helpers_preserve_the_observed_cluster_values() -> None:
    """The supporting seams carry Job facts without manufacturing a clock."""
    request = GateRunRequest(
        repo_root=Path("/repo"), mirror_url="mirror", manifest="manifest", gate_ref="refs/gates/a"
    )
    observed = GateTimingObservations(job_name="gate-a", created_at="2026-11-23T10:00:00Z")
    observed.observe_status(status={"startTime": "2026-11-23T10:02:30Z"})
    failure = observed.failure(
        failure=GateStepFailed(step="await", argv=(), returncode=None, detail="unreadable")
    )
    delivered: list[dict[str, object]] = []

    def emit(
        *,
        outcome: str,
        repository: str | None,
        tree_hash: str | None,
        job_name: str | None,
    ) -> None:
        delivered.append(
            {
                "outcome": outcome,
                "repository": repository,
                "tree_hash": tree_hash,
                "job_name": job_name,
            }
        )

    emit_outcome(
        emit=emit,
        outcome="no-verdict",
        repository=None,
        tree_hash=None,
        verdict=GateVerdict(
            state=GATE_NO_VERDICT,
            detail="unreadable",
            token_written=False,
            job_name=failure.job_name,
        ),
    )
    assert failure.job_created_at == "2026-11-23T10:00:00Z"
    assert failure.job_started_at == "2026-11-23T10:02:30Z"
    assert mirror_push()[-1] == "push"
    assert kubectl(request=request)[-1] == request.namespace
    assert shown_output_checksum(request=request, output="ignored") == ""
    assert delivered == [
        {"outcome": "no-verdict", "repository": None, "tree_hash": None, "job_name": "gate-a"}
    ]
