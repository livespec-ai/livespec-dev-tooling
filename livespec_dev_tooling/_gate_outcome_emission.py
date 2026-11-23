"""Translate a decided gate verdict into its advisory telemetry event."""

from __future__ import annotations

from collections.abc import Callable

from livespec_dev_tooling.gate_outcome_telemetry import emit_gate_outcome, gate_timing_seconds
from livespec_dev_tooling.gate_remote_verdict import GateVerdict

__all__: list[str] = ["emit_outcome"]


def emit_outcome(
    *,
    emit: Callable[..., None],
    outcome: str,
    repository: str | None,
    tree_hash: str | None,
    verdict: GateVerdict,
) -> None:
    """Emit rich production telemetry while retaining the historical callback seam."""
    if emit is not emit_gate_outcome:
        emit(
            outcome=outcome,
            repository=repository,
            tree_hash=tree_hash,
            job_name=verdict.job_name,
        )
        return
    queue_wait_seconds, duration_seconds = gate_timing_seconds(
        created_at=verdict.job_created_at,
        admitted_at=verdict.job_started_at,
        terminal_at=verdict.job_terminal_at,
    )
    emit(
        outcome=outcome,
        repository=repository,
        tree_hash=tree_hash,
        job_name=verdict.job_name,
        queue_wait_seconds=queue_wait_seconds,
        duration_seconds=duration_seconds,
        no_verdict_cause=verdict.no_verdict_cause,
        refusal_step=verdict.refusal_step,
    )
