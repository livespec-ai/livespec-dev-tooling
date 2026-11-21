"""Acceptance coverage for the capacity-change derivation guard.

The guard is a shared aggregate member.  A dated derivation section written
after ratification must not make a capacity, quota, or lane change without
committing the CI-side read that tells operators whether the change harmed CI.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

__all__: list[str] = []


_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHECK = _REPO_ROOT / "livespec_dev_tooling" / "checks" / "capacity_change_derivation.py"


def _load_check() -> ModuleType:
    """Load the on-disk guard after the Red existence assertion."""
    spec = importlib.util.spec_from_file_location(
        "capacity_change_derivation_under_test", str(_CHECK)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_dated_capacity_derivation_without_the_ci_side_read_is_refused(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The guard names one post-ratification section and every missing CI-side read element."""
    assert _CHECK.is_file(), "the capacity-change derivation guard must ship as a shared check"
    derivation = tmp_path / "ci-runner" / "k3s" / "phase2" / "kueue" / "DERIVATION.md"
    derivation.parent.mkdir(parents=True)
    _ = derivation.write_text(
        "## PowerEdge gate lane raised from two to six gates (2026-11-21)\n\n"
        "The lane now admits six gates.\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(tmp_path)
    result = _load_check().main()
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert result != 0, (
        "a dated capacity derivation without its CI-side read must refuse; "
        f"got result={result} stdout={captured.out!r} stderr={captured.err!r}"
    )
    for missing in (
        "PowerEdge gate lane raised from two to six gates (2026-11-21)",
        "+2 h CI-side read",
        "CI queue-wait p95",
        "CI job duration p50",
        "duration_ms under one day",
        "node CI-slice cpu.pressure",
    ):
        assert missing in combined, (
            "the refusal must name the derivation heading and every missing CI-side read element; "
            f"missing={missing!r} combined={combined!r}"
        )
