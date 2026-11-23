"""The post-merge bind looks the master push run up for a merge sha through the pure window rule."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from livespec_dev_tooling.incident_master_run import MASTER_RUN_WINDOW_SECONDS
from livespec_dev_tooling.incident_master_run_lookup import find_master_run

_SHA = "d0cf7db823f3761bc0080dc797c848daef83dee8"
_REPO = "livespec-ai/livespec-dev-tooling"
_MERGED = datetime(2026, 11, 22, 18, 3, 4, tzinfo=timezone.utc)
_RUN = {
    "id": 45053854447,
    "event": "push",
    "head_branch": "master",
    "head_sha": _SHA,
    "path": ".github/workflows/ci.yml",
}


class _Forge:
    def __init__(self, *, answer):
        self.answer = answer
        self.paths = []

    def __call__(self, path):
        self.paths.append(path)
        return self.answer


def _lookup(*, forge, minutes, repository=_REPO):
    return find_master_run(
        read=forge,
        repository=repository,
        master_sha=_SHA,
        merged_at=_MERGED,
        now=_MERGED + timedelta(minutes=minutes),
    )


def test_a_late_push_run_is_found_by_asking_the_forge_for_the_merge_sha_on_master():
    forge = _Forge(answer={"workflow_runs": [_RUN]})
    state = _lookup(forge=forge, minutes=11)
    assert (state.kind, state.run_id) == ("found", 45053854447)
    assert forge.paths == [
        f"repos/{_REPO}/actions/runs?head_sha={_SHA}&event=push&branch=master&per_page=100"
    ]


def test_no_run_inside_the_window_is_pending_and_after_it_absent():
    forge = _Forge(answer={"workflow_runs": []})
    assert _lookup(forge=forge, minutes=10).kind == "pending"
    after = MASTER_RUN_WINDOW_SECONDS // 60 + 1
    assert _lookup(forge=forge, minutes=after).kind == "absent"


def test_an_unanswered_or_malformed_forge_read_is_never_judged_absent():
    for answer in (None, [], {"workflow_runs": "x"}, {}):
        state = _lookup(forge=_Forge(answer=answer), minutes=999)
        assert (state.kind, state.run_id) == ("unreadable", None)


def test_a_repository_that_is_not_owner_slash_name_is_refused_before_any_read():
    forge = _Forge(answer={"workflow_runs": [_RUN]})
    state = _lookup(forge=forge, minutes=11, repository="../etc/passwd")
    assert state.kind == "unreadable"
    assert forge.paths == []
