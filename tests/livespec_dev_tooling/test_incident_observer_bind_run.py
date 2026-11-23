"""The post-merge bind finds the master push run itself, so a late run is pending, never absent."""

from __future__ import annotations

# ruff: noqa: F401, F811 -- the control fixture and request helper are shared by import.
from datetime import datetime, timedelta, timezone

import pytest

from livespec_dev_tooling._incident_observer_types import ObserverArm
from livespec_dev_tooling.incident_observer_bind_run import locate_bind_run
from tests.livespec_dev_tooling.test_incident_observer_control import _request, controller

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-bm5bb5

_MERGE = "a" * 40
_MERGED_AT = datetime(2026, 11, 22, 18, 3, 4, tzinfo=timezone.utc)


def _arm() -> ObserverArm:
    return ObserverArm(
        repository="owner/repo",
        incident_item_id="incident-1",
        attempt_id="repair-1",
        operation_id="operation-1",
        generation=1,
        owner="owner",
        phase="repair",
        pr_number=55,
        base_sha="e" * 40,
        head_sha="c" * 40,
        required_jobs=("coverage",),
        controller_release="v1.169.0",
        controller_revision="b" * 40,
        authority_receipt=b"",
    )


def _pull(*, merged_at: datetime, sha: str = _MERGE, merged: bool = True) -> dict[str, object]:
    return {
        "merged": merged,
        "merge_commit_sha": sha,
        "merged_at": merged_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _runs(*, ids: tuple[int, ...]) -> dict[str, object]:
    return {
        "workflow_runs": [
            {
                "id": run,
                "event": "push",
                "head_branch": "master",
                "head_sha": _MERGE,
                "path": ".github/workflows/ci.yml",
            }
            for run in ids
        ]
    }


def _forge(*, pull: object, runs: object):
    def read(path: str) -> object:
        return pull if "/pulls/" in path else runs

    return read


def _locate(*, pull: object, runs: object, after: timedelta, sha: str = _MERGE):
    return locate_bind_run(
        read=_forge(pull=pull, runs=runs), arm=_arm(), head_sha=sha, now=_MERGED_AT + after
    )


def test_a_run_the_forge_created_late_is_found_by_the_merge_sha():
    found = _locate(
        pull=_pull(merged_at=_MERGED_AT), runs=_runs(ids=(77,)), after=timedelta(minutes=11)
    )
    assert (found.kind, found.run_id) == ("found", 77)


def test_no_run_yet_inside_the_window_is_pending_and_names_its_deadline():
    waiting = _locate(
        pull=_pull(merged_at=_MERGED_AT), runs=_runs(ids=()), after=timedelta(minutes=5)
    )
    assert waiting.kind == "pending"
    assert "not judged before" in waiting.detail


def test_no_run_after_the_window_is_refused_naming_the_window():
    gone = _locate(
        pull=_pull(merged_at=_MERGED_AT), runs=_runs(ids=()), after=timedelta(minutes=31)
    )
    assert gone.kind == "refused"
    assert "within 1800 seconds" in gone.detail


@pytest.mark.parametrize(
    "pull",
    [
        None,
        _pull(merged_at=_MERGED_AT, merged=False),
        _pull(merged_at=_MERGED_AT, sha="b" * 40),
        {"merged": True, "merge_commit_sha": _MERGE, "merged_at": "not a time"},
    ],
)
def test_a_pull_request_the_forge_does_not_show_merged_at_that_sha_is_refused(pull):
    refused = _locate(pull=pull, runs=_runs(ids=(77,)), after=timedelta(minutes=1))
    assert refused.kind == "refused"
    assert refused.run_id is None


def test_an_unreadable_run_list_is_refused_never_judged_absent():
    refused = _locate(pull=_pull(merged_at=_MERGED_AT), runs=None, after=timedelta(minutes=40))
    assert refused.kind == "refused"
    assert "did not answer" in refused.detail


def _serve(*, monkeypatch, control, pull, runs):
    monkeypatch.setattr(control.ForgeReads, "installed", lambda **_: _forge(pull=pull, runs=runs))


def test_bind_without_a_run_id_admits_the_run_the_forge_shows(controller, monkeypatch):
    from livespec_dev_tooling import incident_observer_control as control

    application, payload, _, _, _ = controller
    now = datetime.now(tz=timezone.utc)
    _serve(
        monkeypatch=monkeypatch,
        control=control,
        pull=_pull(merged_at=now - timedelta(minutes=2), sha="a" * 40),
        runs=_runs(ids=(91,)),
    )
    _request(application=application, path="/arm", payload=payload)
    bind = {"repository": "owner/repo", "head_sha": "a" * 40}
    assert _request(application=application, path="/bind", payload=bind)[1]["status"] == "admitted"


def test_bind_without_a_run_id_reports_pending_while_the_run_has_not_appeared(
    controller, monkeypatch
):
    from livespec_dev_tooling import incident_observer_control as control

    application, payload, _, _, _ = controller
    now = datetime.now(tz=timezone.utc)
    _serve(
        monkeypatch=monkeypatch,
        control=control,
        pull=_pull(merged_at=now - timedelta(minutes=2), sha="a" * 40),
        runs=_runs(ids=()),
    )
    _request(application=application, path="/arm", payload=payload)
    bind = {"repository": "owner/repo", "head_sha": "a" * 40}
    status, body = _request(application=application, path="/bind", payload=bind)
    assert (status, body["status"]) == ("202 Accepted", "pending")
