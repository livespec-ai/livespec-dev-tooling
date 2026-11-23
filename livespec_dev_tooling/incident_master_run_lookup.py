"""Find the master push run of an expedited merge commit through the forge.

The post-merge bind needs the run id of the push run the merge created. A `merge-async` merge
can create that run minutes late, so the lookup asks the forge for runs of the merge sha and
hands them to the window rule: `found`, `pending` inside the window, `absent` only after it.
A forge read that is unanswered or malformed is `unreadable`, never `absent`.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import cast

from livespec_dev_tooling.incident_forge_reads import ForgeRead
from livespec_dev_tooling.incident_master_run import MasterRunState, master_run_state

__all__: list[str] = ["find_master_run"]

_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")


def _unreadable(*, detail: str) -> MasterRunState:
    return MasterRunState(kind="unreadable", run_id=None, detail=detail)


def find_master_run(
    *, read: ForgeRead, repository: str, master_sha: str, merged_at: datetime, now: datetime
) -> MasterRunState:
    """Return the window rule's verdict over the forge's runs for `master_sha`."""
    if _REPOSITORY.fullmatch(repository) is None or repository.split("/")[-1] in {".", ".."}:
        return _unreadable(detail=f"{repository!r} is not an owner/name repository")
    query = f"head_sha={master_sha}&event=push&branch=master&per_page=100"
    answer = read(f"repos/{repository}/actions/runs?{query}")
    if not isinstance(answer, dict):
        return _unreadable(detail=f"the forge did not answer the run list for {master_sha}")
    runs = cast("dict[str, object]", answer).get("workflow_runs")
    if not isinstance(runs, list):
        return _unreadable(detail=f"the forge did not answer the run list for {master_sha}")
    items = cast("list[object]", runs)
    records = [cast("dict[str, object]", run) for run in items if isinstance(run, dict)]
    return master_run_state(runs=records, master_sha=master_sha, merged_at=merged_at, now=now)
