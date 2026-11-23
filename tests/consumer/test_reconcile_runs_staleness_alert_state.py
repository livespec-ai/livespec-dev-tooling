"""Alert-state scenarios for the reconcile-runs dead-man check.

The test pins the clock and executes the committed shell program through the
complete stale, re-alert, growth, recovery, missing-marker, and no-alert-state
sequence.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

__all__: list[str] = []

pytestmark = pytest.mark.consumer

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = (
    _ROOT / "ansible" / "roles" / "reconcile_runs" / "files" / "livespec-reconcile-runs-staleness"
)
_NOW = 1_000
_BOUND = 60
_REALERT = 10


def _marker(*, path: Path, modified_at: int) -> None:
    path.touch()
    os.utime(path, (modified_at, modified_at))


def _run(
    *,
    bin_dir: Path,
    alert_state: Path | None,
    tenants: list[tuple[str, Path]],
) -> subprocess.CompletedProcess[str]:
    command = [str(_SCRIPT)]
    if alert_state is not None:
        command.extend(["--alert-state", str(alert_state), "--realert-seconds", str(_REALERT)])
    command.append(str(_BOUND))
    command.extend(f"{name}={marker}" for name, marker in tenants)
    return subprocess.run(
        command,
        capture_output=True,
        check=False,
        env=os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}"},
        text=True,
    )


def _state(*, path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_case(
    *,
    result: subprocess.CompletedProcess[str],
    expected_returncode: int,
    alert_state: Path,
    expected_state: str | None,
) -> None:
    assert result.returncode == expected_returncode
    if expected_state is None:
        assert not alert_state.exists()
    else:
        assert _state(path=alert_state) == expected_state


def test_staleness_alert_state_covers_every_stale_episode_transition(tmp_path: Path) -> None:
    """A stale tenant pages once per set, then pages again after its interval."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    date = bin_dir / "date"
    _ = date.write_text(f"#!/bin/sh\nprintf '%s\\n' {_NOW}\n", encoding="utf-8")
    date.chmod(0o755)

    alert_state = tmp_path / "alert-state"
    alpha, beta, gamma, fresh = (
        tmp_path / "alpha.last-success",
        tmp_path / "beta.last-success",
        tmp_path / "gamma.last-success",
        tmp_path / "fresh.last-success",
    )
    for marker in (alpha, beta, gamma):
        _marker(path=marker, modified_at=0)
    _marker(path=fresh, modified_at=_NOW)

    # A fresh tenant leaves no alert-state file behind.
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("fresh", fresh)],
        ),
        expected_returncode=0,
        alert_state=alert_state,
        expected_state=None,
    )

    # A new stale set alerts and records its tenants plus its alert time.
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("alpha", alpha), ("beta", beta)],
        ),
        expected_returncode=1,
        alert_state=alert_state,
        expected_state="alpha beta\n1000\n",
    )

    # The identical set inside the interval is quiet.
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("alpha", alpha), ("beta", beta)],
        ),
        expected_returncode=0,
        alert_state=alert_state,
        expected_state="alpha beta\n1000\n",
    )

    # The same set re-alerts once its interval has elapsed.
    _ = alert_state.write_text("alpha beta\n990\n", encoding="utf-8")
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("alpha", alpha), ("beta", beta)],
        ),
        expected_returncode=1,
        alert_state=alert_state,
        expected_state="alpha beta\n1000\n",
    )

    # Growing and shrinking the set each alert and replace the stored set.
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("alpha", alpha), ("beta", beta), ("gamma", gamma)],
        ),
        expected_returncode=1,
        alert_state=alert_state,
        expected_state="alpha beta gamma\n1000\n",
    )

    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("alpha", alpha), ("beta", beta)],
        ),
        expected_returncode=1,
        alert_state=alert_state,
        expected_state="alpha beta\n1000\n",
    )

    # Recovery clears state; a missing marker creates a new, named episode.
    for marker in (alpha, beta):
        _marker(path=marker, modified_at=_NOW)
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("beta", beta), ("alpha", alpha)],
        ),
        expected_returncode=0,
        alert_state=alert_state,
        expected_state=None,
    )

    missing_marker = tmp_path / "missing.last-success"
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=alert_state,
            tenants=[("missing", missing_marker)],
        ),
        expected_returncode=1,
        alert_state=alert_state,
        expected_state="missing\n1000\n",
    )

    # Hosts without --alert-state fail every stale check and preserve no state.
    _assert_case(
        result=_run(
            bin_dir=bin_dir,
            alert_state=None,
            tenants=[("missing", missing_marker)],
        ),
        expected_returncode=1,
        alert_state=alert_state,
        expected_state="missing\n1000\n",
    )
