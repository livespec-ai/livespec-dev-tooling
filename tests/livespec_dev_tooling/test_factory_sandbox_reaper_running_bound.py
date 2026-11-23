"""The factory sandbox reaper's shorter bound for RUNNING pods of succeeded runs.

legacy-coordinator-agent ruling R301 (work item livespec-dev-tooling-3z72pg):
a Running pod of a finished run serves nobody and holds a factory_pod_budget
slot, so a RUNNING sandbox of a SUCCEEDED run is reaped after
`factory_sandbox_reaper_running_min_age_hours` (2), while stopped sandboxes keep
the 24 h bound a post-mortem reads, and a FAILED run's running pod keeps the 24 h
bound too: an unpreserved failed tree is never reaped on the short bound.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType

__all__: list[str] = []

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ROLE = _REPO_ROOT / "ansible" / "roles" / "factory_sandbox_reaper"
_SCRIPT = _ROLE / "files" / "factory_sandbox_reaper.py"


def _load() -> ModuleType:
    name = "factory_sandbox_reaper_running_bound_under_test"
    spec = importlib.util.spec_from_file_location(name, _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


reaper = _load()

_NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=timezone.utc)
_HORIZON = timedelta(hours=24)
_RUNNING_BOUND = timedelta(hours=2)
_ORIGIN = "https://github.com/example/repo"
_HOUR_MS = 3_600_000


def _run(*, kind: str, hours_ago_ended: float, dispatch_id: str = "d1") -> object:
    started = _NOW - timedelta(hours=hours_ago_ended + 1)
    return reaper.Run("01RUN", kind, started.isoformat(), _HOUR_MS, dispatch_id, _ORIGIN)


def _verdict(
    *, state: str, kind: str, hours_ago_ended: float, refs: frozenset[str] = frozenset()
) -> object:
    sandbox = reaper.Sandbox("sb-1", state, "01RUN")
    run = _run(kind=kind, hours_ago_ended=hours_ago_ended)
    keeps, candidates = reaper.classify(
        sandboxes=[sandbox],
        runs={run.run_id: run},
        now=_NOW,
        min_age=_HORIZON,
        running_min_age=_RUNNING_BOUND,
    )
    origins = {c[1].origin_url: refs for c in candidates}
    [verdict] = keeps + reaper.finalize(candidates=candidates, preserved=origins, max_deletions=50)
    return verdict


def test_a_running_pod_of_a_succeeded_run_is_deleted_after_the_running_bound() -> None:
    verdict = _verdict(state="running", kind="succeeded", hours_ago_ended=3.0)
    assert verdict.action == "delete", verdict.reason


def test_a_running_pod_of_a_succeeded_run_inside_the_running_bound_is_kept() -> None:
    verdict = _verdict(state="running", kind="succeeded", hours_ago_ended=1.0)
    assert verdict.action == "keep"
    assert "younger than the horizon" in verdict.reason


def test_a_stopped_sandbox_keeps_the_full_horizon() -> None:
    verdict = _verdict(state="stopped", kind="succeeded", hours_ago_ended=3.0)
    assert verdict.action == "keep"
    assert "younger than the horizon" in verdict.reason


def test_a_running_pod_of_a_failed_run_without_a_preserved_ref_is_skipped_on_the_short_bound() -> (
    None
):
    verdict = _verdict(state="running", kind="failed", hours_ago_ended=3.0)
    assert verdict.action == "keep"
    assert "failed run" in verdict.reason
    assert "running-pod bound" in verdict.reason


def test_a_running_pod_of_a_failed_run_is_deleted_once_the_full_horizon_passes() -> None:
    verdict = _verdict(state="running", kind="failed", hours_ago_ended=30.0)
    assert verdict.action == "delete", verdict.reason


def test_a_preserved_needs_human_ref_keeps_a_running_pod_past_the_running_bound() -> None:
    verdict = _verdict(
        state="running", kind="succeeded", hours_ago_ended=3.0, refs=frozenset({"d1"})
    )
    assert verdict.action == "keep"
    assert "needs-human/d1" in verdict.reason


def _ps_rows() -> list[dict[str, object]]:
    started = _NOW - timedelta(hours=4)
    return [
        {
            "run_id": "ENDED",
            "status": {"kind": "succeeded"},
            "start_time": started.isoformat(),
            "wall_time_ms": _HOUR_MS,
            "labels": {"livespec.dispatch.id": "dold"},
            "repo_origin_url": _ORIGIN,
        }
    ]


def _fake_host(calls: list[list[str]]) -> object:
    def host(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        argv = list(argv)
        calls.append(argv)
        if argv[0] == "git":
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[-1] == "list":
            sandboxes = [
                {
                    "id": "sb-live",
                    "name": "petri-ENDED-l0",
                    "state": "running",
                    "labels": {"petri.run": "ENDED"},
                }
            ]
            return subprocess.CompletedProcess(argv, 0, json.dumps(sandboxes), "")
        if argv[1] == "ps":
            return subprocess.CompletedProcess(argv, 0, json.dumps(_ps_rows()), "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return host


def _pass(*, env_extra: dict[str, str]) -> list[str]:
    env = {
        "REAPER_FABRO_BIN": "/f/fabro",
        "REAPER_FABRO_SERVER": "http://127.0.0.1:32276",
        "REAPER_LITHOS_BIN": "/u/lithos-sandbox",
        "REAPER_APPLY": "0",
    } | env_extra
    lines: list[str] = []
    reaper.reap(env=env, run=_fake_host([]), now=_NOW, emit=lines.append)
    return lines


def test_the_running_bound_comes_from_the_environment() -> None:
    lines = _pass(env_extra={"REAPER_RUNNING_MIN_AGE_HOURS": "2"})
    assert any(line.startswith("DRY-RUN DELETE sb-live") for line in lines), lines


def test_without_the_running_bound_a_running_pod_keeps_the_full_horizon() -> None:
    lines = _pass(env_extra={})
    assert any(line.startswith("DRY-RUN KEEP") and "sb-live" in line for line in lines), lines


def _text(*, path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_the_role_declares_and_wires_the_running_bound() -> None:
    defaults = _text(path=_ROLE / "defaults" / "main.yml")
    assert "factory_sandbox_reaper_running_min_age_hours: 2" in defaults
    service = _text(path=_ROLE / "templates" / "livespec-factory-sandbox-reaper.service.j2")
    assert (
        "REAPER_RUNNING_MIN_AGE_HOURS={{ factory_sandbox_reaper_running_min_age_hours }}" in service
    )
    tasks = _text(path=_ROLE / "tasks" / "main.yml")
    assert "factory_sandbox_reaper_running_min_age_hours | int > 0" in tasks
    assert (
        'REAPER_RUNNING_MIN_AGE_HOURS: "{{ factory_sandbox_reaper_running_min_age_hours }}"'
        in tasks
    )


def test_the_host_vars_doc_states_the_bound_and_defers_the_reconciler_signal() -> None:
    doc = _text(path=_ROLE / "HOST_VARS.md")
    assert "factory_sandbox_reaper_running_min_age_hours" in doc
    assert "about 3 h" in doc
    assert "RBAC or transport" in doc
