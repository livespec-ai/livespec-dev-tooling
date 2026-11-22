"""An App merge-async merge can create its master push run minutes late; absence is judged only after a window.

Measured 2026-11-22: the push run for master d0cf7db82 was created 10.5 minutes after the
merge-async merge, and a read at 18:09Z saw zero runs. A missing run inside the window is
pending, never absent.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from livespec_dev_tooling.incident_master_run import (
    MASTER_RUN_WINDOW_SECONDS,
    master_run_state,
)

_SHA = "d0cf7db823f3761bc0080dc797c848daef83dee8"
_MERGED = datetime(2026, 11, 22, 18, 3, 4, tzinfo=timezone.utc)
_CI = ".github/workflows/ci.yml"


def _run(**overrides):
    run = {
        "id": 45053854447,
        "event": "push",
        "head_branch": "master",
        "head_sha": _SHA,
        "path": _CI,
    }
    return {**run, **overrides}


def _state(*, runs, minutes):
    return master_run_state(
        runs=runs, master_sha=_SHA, merged_at=_MERGED, now=_MERGED + timedelta(minutes=minutes)
    )


def test_the_window_covers_the_measured_delay_with_room_to_spare():
    assert MASTER_RUN_WINDOW_SECONDS >= 20 * 60


def test_a_matching_push_run_is_found_by_its_id_even_when_it_arrives_late():
    state = _state(runs=[_run()], minutes=11)
    assert (state.kind, state.run_id) == ("found", 45053854447)


def test_no_run_inside_the_window_is_pending_never_absent():
    state = _state(runs=[], minutes=10)
    assert (state.kind, state.run_id) == ("pending", None)


def test_no_run_at_the_end_of_the_window_is_absent():
    seconds = MASTER_RUN_WINDOW_SECONDS
    state = master_run_state(
        runs=[], master_sha=_SHA, merged_at=_MERGED, now=_MERGED + timedelta(seconds=seconds)
    )
    assert state.kind == "absent"


def test_a_run_that_differs_in_event_branch_sha_or_path_does_not_count():
    others = [
        _run(event="pull_request"),
        _run(head_branch="incident-scratch/x"),
        _run(head_sha="0" * 40),
        _run(path=".github/workflows/release-please.yml"),
    ]
    state = _state(runs=others, minutes=5)
    assert state.kind == "pending"
