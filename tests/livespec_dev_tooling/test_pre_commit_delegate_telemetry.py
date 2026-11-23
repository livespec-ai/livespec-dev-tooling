"""Telemetry emitted for delegated pre-commit aggregate outcomes."""

from __future__ import annotations

import importlib
import urllib.request
from pathlib import Path

import pytest
from returns.result import Success

from livespec_dev_tooling.gate_remote_client import GateRunRequest
from livespec_dev_tooling.gate_remote_verdict import GATE_FAILED, GateVerdict

__all__: list[str] = []


def _module() -> object:
    """Load the public delegated pre-commit seam."""
    return importlib.import_module("livespec_dev_tooling.pre_commit_delegate")


def test_a_delegated_pre_commit_red_job_emits_its_staged_outcome_span(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The pre-commit stage is observable apart from the same gate's pre-push run."""
    module = _module()
    tree_hash = "a" * 40
    emitted: list[dict[str, str | None]] = []
    _ = (tmp_path / "pyproject.toml").write_text(
        "[tool.livespec_dev_tooling]\ndelegated_pre_commit = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(module, "gates_kubeconfig_readable", lambda: True)
    monkeypatch.setattr(module, "_staged_tree_hash", lambda **_kwargs: tree_hash)
    monkeypatch.setattr(module, "_staged_commit", lambda **_kwargs: "b" * 40)
    monkeypatch.setattr(module, "resolve_renderer", lambda **_kwargs: Path("renderer"))
    monkeypatch.setattr(
        module,
        "gate_remote_request",
        lambda **_kwargs: Success(
            GateRunRequest(
                repo_root=tmp_path,
                mirror_url="mirror/widget.git",
                manifest="manifest",
                gate_ref="refs/gates/tree",
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "run_gated_push",
        lambda **_kwargs: GateVerdict(
            state=GATE_FAILED,
            detail="check-pre-commit-gated-tree failed",
            token_written=False,
            job_name="gate-widget-red",
            tree_hash=tree_hash,
        ),
    )
    monkeypatch.setattr(
        module,
        "emit_gate_outcome",
        lambda **event: emitted.append(event),
        raising=False,
    )

    verdict = module.run_pre_commit(repo_root=tmp_path)

    assert verdict.exit_status == 1
    assert emitted == [
        {
            "outcome": "failed-tree",
            "repository": "widget",
            "tree_hash": tree_hash,
            "job_name": "gate-widget-red",
            "queue_wait_seconds": None,
            "duration_seconds": None,
            "no_verdict_cause": None,
            "refusal_step": None,
            "stage": "pre-commit",
        }
    ]


def test_a_pre_commit_keeps_its_verdict_when_outcome_delivery_fails(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Telemetry is bounded, best-effort reporting rather than a gate input."""
    module = _module()
    tree_hash = "a" * 40
    _ = (tmp_path / "pyproject.toml").write_text(
        "[tool.livespec_dev_tooling]\ndelegated_pre_commit = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(module, "gates_kubeconfig_readable", lambda: True)
    monkeypatch.setattr(module, "_staged_tree_hash", lambda **_kwargs: tree_hash)
    monkeypatch.setattr(module, "_staged_commit", lambda **_kwargs: "b" * 40)
    monkeypatch.setattr(module, "resolve_renderer", lambda **_kwargs: Path("renderer"))
    monkeypatch.setattr(
        module,
        "gate_remote_request",
        lambda **_kwargs: Success(
            GateRunRequest(
                repo_root=tmp_path,
                mirror_url="mirror/widget.git",
                manifest="manifest",
                gate_ref="refs/gates/tree",
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "run_gated_push",
        lambda **_kwargs: GateVerdict(
            state=GATE_FAILED,
            detail="check-pre-commit-gated-tree failed",
            token_written=False,
            job_name="gate-widget-red",
            tree_hash=tree_hash,
        ),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, **_kwargs: (_ for _ in ()).throw(OSError()),
    )

    verdict = module.run_pre_commit(repo_root=tmp_path)

    assert verdict.exit_status == 1
    assert verdict.reason == "check-pre-commit-gated-tree failed"


def test_a_delegated_pre_commit_span_carries_the_gate_jobs_queue_wait_and_duration(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The span's timing comes from the Job's API-server timestamps, as pre-push's does."""
    module = _module()
    tree_hash = "a" * 40
    emitted: list[dict[str, object]] = []
    _ = (tmp_path / "pyproject.toml").write_text(
        "[tool.livespec_dev_tooling]\ndelegated_pre_commit = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(module, "gates_kubeconfig_readable", lambda: True)
    monkeypatch.setattr(module, "_staged_tree_hash", lambda **_kwargs: tree_hash)
    monkeypatch.setattr(module, "_staged_commit", lambda **_kwargs: "b" * 40)
    monkeypatch.setattr(module, "resolve_renderer", lambda **_kwargs: Path("renderer"))
    monkeypatch.setattr(
        module,
        "gate_remote_request",
        lambda **_kwargs: Success(
            GateRunRequest(
                repo_root=tmp_path,
                mirror_url="mirror/widget.git",
                manifest="manifest",
                gate_ref="refs/gates/tree",
            )
        ),
    )
    monkeypatch.setattr(
        module,
        "run_gated_push",
        lambda **_kwargs: GateVerdict(
            state=GATE_FAILED,
            detail="check-pre-commit-gated-tree failed",
            token_written=False,
            job_name="gate-widget-red",
            tree_hash=tree_hash,
            job_created_at="2026-11-23T10:00:00Z",
            job_started_at="2026-11-23T10:00:07Z",
            job_terminal_at="2026-11-23T10:02:07Z",
        ),
    )
    monkeypatch.setattr(module, "emit_gate_outcome", lambda **event: emitted.append(event))

    _ = module.run_pre_commit(repo_root=tmp_path)

    assert [(event["queue_wait_seconds"], event["duration_seconds"]) for event in emitted] == [
        (7.0, 120.0)
    ]


def test_a_pre_commit_that_gates_locally_for_want_of_a_credential_emits_a_no_verdict_span(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A selected delegated run that obtains no verdict still emits its one span."""
    module = _module()
    emitted: list[dict[str, object]] = []
    _ = (tmp_path / "pyproject.toml").write_text(
        "[tool.livespec_dev_tooling]\ndelegated_pre_commit = true\n", encoding="utf-8"
    )
    monkeypatch.setattr(module, "gates_kubeconfig_readable", lambda: False)
    monkeypatch.setattr(module, "emit_gate_outcome", lambda **event: emitted.append(event))

    verdict = module.run_pre_commit(repo_root=tmp_path)

    assert verdict.local is True
    assert [(event["outcome"], event["stage"]) for event in emitted] == [
        ("no-verdict", "pre-commit")
    ]
