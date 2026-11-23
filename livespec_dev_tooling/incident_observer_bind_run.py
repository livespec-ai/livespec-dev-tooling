"""Resolve the master push run a post-merge bind names, from the forge, when no id is supplied."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from livespec_dev_tooling._incident_observer_types import ObserverArm
from livespec_dev_tooling.incident_forge_reads import ForgeRead
from livespec_dev_tooling.incident_master_run_lookup import find_master_run

__all__: list[str] = ["BindRun", "locate_bind_run"]


@dataclass(frozen=True, kw_only=True)
class BindRun:
    """`found` with the run id, `pending` inside the window, or `refused` with its reason."""

    kind: str
    run_id: int | None
    detail: str


def _refused(*, detail: str) -> BindRun:
    return BindRun(kind="refused", run_id=None, detail=detail)


def _merged_at(*, pull: object, head_sha: str) -> datetime | str:
    """The merge instant the forge reports for `head_sha`, or the reason it cannot be trusted."""
    if not isinstance(pull, dict):
        return "the forge did not answer the pull request"
    record = cast("dict[str, object]", pull)
    if record.get("merged") is not True or record.get("merge_commit_sha") != head_sha:
        return f"the forge does not show the pull request merged at {head_sha}"
    stamp = record.get("merged_at")
    try:
        merged = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return "the forge reported no readable merge instant"
    return merged if merged.tzinfo is not None else merged.replace(tzinfo=timezone.utc)


def locate_bind_run(*, read: ForgeRead, arm: ObserverArm, head_sha: str, now: datetime) -> BindRun:
    """Return what the forge shows of the merged pull request's master push run."""
    merged_at = _merged_at(
        pull=read(f"repos/{arm.repository}/pulls/{arm.pr_number}"), head_sha=head_sha
    )
    if isinstance(merged_at, str):
        return _refused(detail=merged_at)
    state = find_master_run(
        read=read,
        repository=arm.repository,
        master_sha=head_sha,
        merged_at=merged_at,
        now=now,
    )
    if state.kind in {"found", "pending"}:
        return BindRun(kind=state.kind, run_id=state.run_id, detail=state.detail)
    return _refused(detail=state.detail)
