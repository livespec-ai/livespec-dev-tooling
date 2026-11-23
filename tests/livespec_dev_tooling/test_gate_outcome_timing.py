"""Cluster-clock intervals for delegated-gate telemetry stay exact or absent."""

# ruff: noqa: SLF001  — the sibling suites' canned clusters are the shared fixtures here.
from __future__ import annotations

import json
from pathlib import Path

import pytest
from returns.result import Failure

from livespec_dev_tooling._gate_cluster_commands import kubectl
from livespec_dev_tooling._gate_log_output import shown_output_checksum
from livespec_dev_tooling._gate_mirror_push import mirror_push
from livespec_dev_tooling._gate_outcome_emission import emit_outcome
from livespec_dev_tooling._gate_run_observation import GateTimingObservations
from livespec_dev_tooling.gate_outcome_telemetry import gate_timing_seconds
from livespec_dev_tooling.gate_remote_client import run_gate
from livespec_dev_tooling.gate_remote_delegate import run_delegated_gate
from livespec_dev_tooling.gate_remote_invocation import GateStepFailed
from livespec_dev_tooling.gate_remote_job_status import terminal_transition_time
from livespec_dev_tooling.gate_remote_request import GateRunRequest
from livespec_dev_tooling.gate_remote_verdict import (
    GATE_NO_VERDICT,
    GATE_PASSED,
    GateVerdict,
    run_gated_push,
)
from tests.livespec_dev_tooling import test_gate_outcome_telemetry as _telemetry_suite
from tests.livespec_dev_tooling import test_gate_remote_client as _client_suite
from tests.livespec_dev_tooling import test_gate_remote_verdict as _verdict_suite

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


_CREATED_AT = "2026-11-23T10:00:00Z"
_ADMITTED_AT = "2026-11-23T10:02:30Z"
_TERMINAL_AT = "2026-11-23T10:09:15Z"
_TIMED_CREATED = json.dumps(
    {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": _telemetry_suite._JOB, "creationTimestamp": _CREATED_AT},
    }
)
_TIMED_COMPLETE = json.dumps(
    {
        "status": {
            "startTime": _ADMITTED_AT,
            "conditions": [
                {"type": "Complete", "status": "True", "lastTransitionTime": _TERMINAL_AT}
            ],
        }
    }
)


class _TimedCluster(_telemetry_suite._CannedCluster):
    """The canned cluster, with a Job that carries the API server's own timestamps."""

    def __init__(self) -> None:
        super().__init__(terminal=_TIMED_COMPLETE)
        self._answers["submit-job"] = _TIMED_CREATED


def test_a_delegated_gate_outcome_event_carries_the_jobs_queue_wait_and_run_duration(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The event uses the Job's own timestamps, not its poll waits.

    The canned Job was created at 10:00, admitted at 10:02:30, and its terminal
    condition changed at 10:09:15. It omits `completionTime`, because a terminal
    condition's `lastTransitionTime` is the reading available for every terminal
    Job, a failed one included. The event carries 150 and 405 seconds as doubles.
    """
    accepted = _telemetry_suite._recording_receiver(monkeypatch)
    repo_root = tmp_path / _telemetry_suite._REPOSITORY
    repo_root.mkdir()

    verdict = run_delegated_gate(
        repo_root=repo_root,
        renderer=_telemetry_suite._RENDERER,
        runner=_TimedCluster(),
        sleeper=_telemetry_suite._no_sleep,
    )

    assert verdict.state == GATE_PASSED
    assert _telemetry_suite._attributes_of(payload=accepted[0]["payload"]) == {
        "livespec.gate.outcome": "passed",
        "livespec.gate.repository": _telemetry_suite._REPOSITORY,
        "livespec.gate.tree_hash": _telemetry_suite._TREE,
        "livespec.gate.job_name": _telemetry_suite._JOB,
        "livespec.gate.queue_wait_seconds": 150.0,
        "livespec.gate.duration_seconds": 405.0,
    }


def test_a_log_stream_that_never_starts_retains_the_terminal_clock_reading() -> None:
    """An observed terminal condition remains evidence on a later plumbing failure."""
    cluster = _client_suite._StubCluster(
        never_runs=("stream-logs",),
        created_payload=json.dumps(
            {"metadata": {"name": _client_suite._JOB, "creationTimestamp": _CREATED_AT}}
        ),
        job_status_payload=_TIMED_COMPLETE,
    )

    outcome = run_gate(request=_client_suite._REQUEST, runner=cluster, sleeper=cluster.sleep)

    assert isinstance(outcome, Failure)
    assert outcome.failure().job_created_at == _CREATED_AT
    assert outcome.failure().job_started_at == _ADMITTED_AT
    assert outcome.failure().job_terminal_at == _TERMINAL_AT


def test_a_no_verdict_after_a_terminal_read_retains_the_terminal_timestamp(
    *, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telemetry can distinguish a terminal Job from a wait that never reached one."""

    def terminal_observed_but_logs_unavailable(**kwargs: object) -> Failure[GateStepFailed]:
        _ = kwargs
        return Failure(
            GateStepFailed(
                step="stream-gate-logs",
                argv=("kubectl", "logs"),
                returncode=None,
                detail="kubectl not on PATH",
                job_name=_verdict_suite._JOB,
                job_created_at=_CREATED_AT,
                job_started_at=_ADMITTED_AT,
                job_terminal_at=_TERMINAL_AT,
            )
        )

    monkeypatch.setattr(
        "livespec_dev_tooling.gate_remote_verdict.run_gate",
        terminal_observed_but_logs_unavailable,
    )

    verdict = run_gated_push(
        request=_verdict_suite._REQUEST,
        runner=_verdict_suite._StubCluster(),
        sleeper=_verdict_suite._no_sleep,
    )

    assert verdict.state == GATE_NO_VERDICT
    assert verdict.job_terminal_at == _TERMINAL_AT
