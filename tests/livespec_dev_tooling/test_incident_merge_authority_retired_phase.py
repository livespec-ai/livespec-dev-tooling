"""A chain the orchestrator retired reads as closed to the incident-merge principal."""

from __future__ import annotations

from unittest.mock import Mock

from returns.result import Success

from livespec_dev_tooling.incident_merge_authority import decide

# EXPEDITED_INCIDENT_RESPONSE flag: livespec-dev-tooling-s7yiut

_BASE = "e" * 40
_HEAD = "c" * 40


def _reading(*, phase: str) -> dict[str, object]:
    return {
        "genesis_writer": "publish-genesis",
        "item_status": "active",
        "is_current": True,
        "attempt": {
            "repository": "owner/repo",
            "item_id": "incident-1",
            "attempt_id": "repair-1",
            "phase": phase,
            "operation_id": "operation-1",
            "generation": 2,
            "owner": "owner",
            "base": _BASE,
            "head": _HEAD,
            "pr_number": 55,
            "landed_commits": [],
            "landed_trees": [],
            "original_paths": ["module.py"],
            "deferred_work": [],
            "repayment_required": True,
            "carrier": {"state": "pr-bound", "target_ref": "refs/heads/incident-1"},
        },
    }


def test_a_retired_chain_reads_as_closed_and_refuses_the_merge_by_name():
    verdict = decide(
        reader=Mock(return_value=Success(_reading(phase="retired"))),
        incident_id="incident-1",
        pr_number=55,
        base_sha=_BASE,
        head_sha=_HEAD,
    )
    assert (verdict.allowed, verdict.reason) == (False, "incident-closed")
