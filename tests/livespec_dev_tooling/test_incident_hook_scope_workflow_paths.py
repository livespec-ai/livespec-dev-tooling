"""An expedited repair publishes a workflow path only under a maintainer-attested scope."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from livespec_dev_tooling import incident_hook_scope as module
from livespec_dev_tooling.incident_execution import ExecutionContext, OperationIdentity

LISTED = ".github/workflows/ci.yml"
UNLISTED = ".github/workflows/release.yml"
CARRIER_PATH = "app.py"


def _context() -> ExecutionContext:
    return ExecutionContext(
        mode="expedited-repair",
        invocation="ordinary",
        identity=OperationIdentity(
            incident_item_id="incident",
            attempt_id="attempt",
            phase="repair",
            repository="owner/repo",
            base_sha="a" * 40,
            head_sha="b" * 40,
            operation_id="operation",
        ),
    )


def _attempt(*, original: list[str], attested: list[str] | None) -> dict[str, Any]:
    record: dict[str, Any] = dict(
        pr_number=1,
        head="b" * 40,
        base="a" * 40,
        original_paths=original,
        carrier=dict(
            state="pr-bound",
            target_ref="refs/heads/repair",
            input_parent="a" * 40,
            staged_tree="d" * 40,
            remote_head="c" * 40,
        ),
    )
    if attested is not None:
        record["workflow_paths"] = attested
    return record


def _wire(*, monkeypatch: pytest.MonkeyPatch, changed: list[str]) -> None:
    def git(**kwargs: Any) -> str:
        command = kwargs["args"][0]
        if command == "diff":
            return "\n".join(changed)
        if command == "ls-tree":
            return CARRIER_PATH
        if command == "rev-parse":
            return "a" * 40
        return "# EXPEDITED_INCIDENT_RESPONSE flag: incident\nvalue = 2\n"

    monkeypatch.setattr(module, "git_text", git)
    monkeypatch.setattr(
        module,
        "gh_read",
        Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps({}), "")),
    )


def _validate(*, tmp_path: Path, attempt: dict[str, Any]) -> dict[str, Any]:
    return module.validate_scope(
        repo=tmp_path,
        context=_context(),
        reading={"attempt": attempt},
        query={"repository": "owner/repo"},
        tree="d" * 40,
        call=module.HookCall(hook="pre-commit", extra=(), stdin=""),
    )


def test_a_listed_workflow_path_is_admitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch=monkeypatch, changed=[CARRIER_PATH, LISTED])
    attempt = _attempt(original=[CARRIER_PATH, LISTED], attested=[LISTED])
    result = _validate(tmp_path=tmp_path, attempt=attempt)
    assert result["original_paths"] == [LISTED, CARRIER_PATH]


def test_a_second_unlisted_workflow_path_is_refused_naming_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch=monkeypatch, changed=[CARRIER_PATH, LISTED, UNLISTED])
    attempt = _attempt(original=[CARRIER_PATH, LISTED, UNLISTED], attested=[LISTED])
    with pytest.raises(module.HookRefusalError) as refused:
        _validate(tmp_path=tmp_path, attempt=attempt)
    detail = str(refused.value)
    assert all(
        [
            "workflow-scoped authorization" in detail,
            UNLISTED in detail,
            LISTED not in detail,
        ]
    )


def test_an_attempt_without_a_current_attestation_refuses_the_listed_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch=monkeypatch, changed=[CARRIER_PATH, LISTED])
    attempt = _attempt(original=[CARRIER_PATH, LISTED], attested=None)
    with pytest.raises(module.HookRefusalError) as refused:
        _validate(tmp_path=tmp_path, attempt=attempt)
    detail = str(refused.value)
    assert all(["workflow-scoped authorization" in detail, LISTED in detail])


def test_a_malformed_attestation_is_never_a_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _wire(monkeypatch=monkeypatch, changed=[CARRIER_PATH, LISTED])
    attempt = _attempt(original=[CARRIER_PATH, LISTED], attested=None) | {"workflow_paths": "x"}
    with pytest.raises(module.HookRefusalError) as refused:
        _validate(tmp_path=tmp_path, attempt=attempt)
    assert LISTED in str(refused.value)
