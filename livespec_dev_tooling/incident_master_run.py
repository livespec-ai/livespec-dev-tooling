"""Classify the master push run of an expedited merge commit as found, pending or absent.

An App `merge-async` merge can create its master push run minutes after the merge: measured
2026-11-22, the run for master d0cf7db82 appeared 10.5 minutes late, and a read at that point
saw zero runs. A run that has not appeared inside the window is therefore `pending`, and only
a run still missing once the window has passed is `absent`. A run counts only when it carries
the fields the observer's `/bind` verifies: event push, branch master, the merge commit's sha
and the `ci.yml` workflow path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

__all__: list[str] = ["MASTER_RUN_WINDOW_SECONDS", "MasterRunState", "master_run_state"]

MASTER_RUN_WINDOW_SECONDS = 30 * 60
_WORKFLOW_PATH = ".github/workflows/ci.yml"


@dataclass(frozen=True, kw_only=True)
class MasterRunState:
    """What the forge shows of one merge commit's master push run."""

    kind: str
    run_id: int | None
    detail: str


def _matches(*, run: dict[str, object], master_sha: str) -> bool:
    return (
        type(run.get("id")) is int
        and run.get("event") == "push"
        and run.get("head_branch") == "master"
        and run.get("head_sha") == master_sha
        and run.get("path") == _WORKFLOW_PATH
    )


def master_run_state(
    *, runs: list[dict[str, object]], master_sha: str, merged_at: datetime, now: datetime
) -> MasterRunState:
    """Return `found` with the run id, `pending` in the window, or `absent` once it has passed."""
    for run in runs:
        if _matches(run=run, master_sha=master_sha):
            return MasterRunState(kind="found", run_id=int(str(run["id"])), detail=master_sha)
    deadline = merged_at + timedelta(seconds=MASTER_RUN_WINDOW_SECONDS)
    if now < deadline:
        return MasterRunState(
            kind="pending",
            run_id=None,
            detail=(
                f"no master push run for {master_sha} yet; "
                f"absence is not judged before {deadline.isoformat()}"
            ),
        )
    return MasterRunState(
        kind="absent",
        run_id=None,
        detail=(
            f"no master push run for {master_sha} "
            f"within {MASTER_RUN_WINDOW_SECONDS} seconds of the merge"
        ),
    )
