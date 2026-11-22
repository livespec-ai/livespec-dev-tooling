"""Release-tier output for heading-coverage TODO owner liveness."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from livespec_dev_tooling.checks._work_item_liveness import LedgerUnreachable

_VENDOR_DIR = Path(__file__).resolve().parents[3] / "livespec_dev_tooling" / "_vendor"
if str(_VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(_VENDOR_DIR))

from returns.io import IOFailure, IOResult  # noqa: E402  — vendor-path-aware import.

__all__: list[str] = []


_REPO_ROOT = Path(__file__).resolve().parents[3]
_NO_TODO_REGISTRY = _REPO_ROOT / "livespec_dev_tooling" / "checks" / "no_todo_registry.py"
_FAIL_VAR = "LIVESPEC_FAIL_IF_HEADING_COVERAGE_TODOS_EXIST"


def _load_check_module() -> ModuleType:
    """Load the on-disk check so its release-tier seam stays injectable."""
    spec = importlib.util.spec_from_file_location(
        "no_todo_registry_liveness_summary_under_test", str(_NO_TODO_REGISTRY)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MODULE = _load_check_module()


def _unreachable_tracker() -> Callable[..., IOResult[dict[str, str], LedgerUnreachable]]:
    """Return the resolver failure track without reaching a real tracker."""
    answer: IOResult[dict[str, str], LedgerUnreachable] = IOFailure(
        LedgerUnreachable(
            repo=".",
            argv="bd -C . list --status all --json",
            reason="query-unrunnable",
            detail="test double: no store configured",
        )
    )

    def _read(*, repo: Path) -> IOResult[dict[str, str], LedgerUnreachable]:
        del repo
        return answer

    return _read


def test_release_tier_reports_the_number_of_unverified_owned_todos(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A release must disclose every owner it could not verify, not merely warn per row."""
    coverage_path = tmp_path / "tests" / "heading-coverage.json"
    coverage_path.parent.mkdir()
    coverage_path.write_text(
        json.dumps(
            [
                {
                    "heading": "## First deferred release assertion",
                    "spec_root": "SPECIFICATION",
                    "test": "TODO",
                    "work_item": "livespec-dev-tooling-first",
                },
                {
                    "heading": "## Second deferred release assertion",
                    "spec_root": "SPECIFICATION",
                    "test": "TODO",
                    "work_item": "livespec-dev-tooling-second",
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(_FAIL_VAR, "true")

    returncode = _MODULE.main(ledger_reader=_unreachable_tracker())
    captured = capsys.readouterr()
    output = captured.out + captured.err

    assert returncode == 0
    events = [json.loads(line) for line in output.splitlines() if line]
    summary = next(
        (
            event
            for event in events
            if event.get("event") == "heading-coverage TODO liveness summary"
        ),
        None,
    )
    assert (
        summary is not None
    ), f"release output must summarize its unverified TODO owners; output={output!r}"
    assert summary["liveness_verified_count"] == 0
    assert summary["liveness_unverified_count"] == 2
