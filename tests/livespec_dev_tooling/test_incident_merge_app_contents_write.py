"""The incident-merge App requests and accepts exactly the grant GitHub's merge endpoints need.

GitHub lists `PUT /pulls/{n}/merge` and `PUT /pulls/{n}/merge-async` under the Contents
permission, access write. The App held contents read, so the merge answered
`HTTP 403 Resource not accessible by integration` (measured on PR 5157, 2026-11-21).
"""

from __future__ import annotations

from livespec_dev_tooling.incident_merge_app import MERGE_SCOPE

_GRANT = {
    "contents": "write",
    "pull_requests": "write",
    "checks": "read",
    "statuses": "read",
    "metadata": "read",
}


def test_the_merge_scope_requests_contents_write_and_nothing_wider():
    assert MERGE_SCOPE.permissions == _GRANT


def test_the_merge_scope_accepts_exactly_that_grant():
    assert MERGE_SCOPE.accepted == (_GRANT,)
