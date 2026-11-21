"""A host-derived `test_nprocs` never replaces the delegated Job's worker count."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from livespec_dev_tooling import commit_replay_delegate as replay

__all__: list[str] = []


@pytest.mark.parametrize("host_derived", ["16", "3"])
def test_a_justfile_exported_test_nprocs_without_an_explicit_override_keeps_the_job_count(
    *, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host_derived: str
) -> None:
    """The justfile always exports a CPU-derived `test_nprocs`; only LIVESPEC_TEST_PARALLELISM is an override.

    On a 64-CPU committing host the justfile exports `test_nprocs=16`. With no
    `LIVESPEC_TEST_PARALLELISM` set, the Job's declared count (6 here) is the
    suite's worker count; the host's value would OOM the Job at its memory limit.
    """
    _ = (tmp_path / "pyproject.toml").write_text(
        "[tool.livespec_dev_tooling]\ndelegated_commit_tests = true\ngate_parallelism = 6\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("test_nprocs", host_derived)
    monkeypatch.delenv("LIVESPEC_TEST_PARALLELISM", raising=False)
    monkeypatch.delenv("LIVESPEC_CI_LANE", raising=False)
    captured: dict[str, tuple[str, ...]] = {}

    def staged_tree_hash(*, repo_root: Path) -> str:
        _ = repo_root
        return "a" * 40

    def remote(
        *,
        repo_root: Path,
        pytest_argv: Sequence[str],
        tree_hash: str,
        resources: tuple[str, ...] | None,
    ) -> replay.ReplayVerdict:
        _ = (repo_root, tree_hash, resources)
        captured["pytest_argv"] = tuple(pytest_argv)
        return replay.ReplayVerdict(local=False, reason="delegated")

    monkeypatch.setattr(replay, "gates_kubeconfig_readable", lambda: True)
    monkeypatch.setattr(replay, "_staged_tree_hash", staged_tree_hash)
    monkeypatch.setattr(replay, "_run_remote", remote)

    _ = replay.run_replay(repo_root=tmp_path, pytest_argv=["pytest", "-q", "-n", host_derived])

    assert captured["pytest_argv"][-2:] == ("-n", "6")
