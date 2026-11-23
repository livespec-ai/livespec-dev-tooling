"""Recovery-path coverage for the Claude scratch mover."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import pytest

_ROLE = Path(__file__).resolve().parents[2] / "ansible/roles/dev_host_memory_bounds"
_SCRIPT = _ROLE / "files" / "claude_scratch_mover.py"
_SID = "22222222-2222-4222-8222-222222222222"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scratch_mover_recovery_under_test", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mover = _load()


def _roots(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    ram, disk, proc = tmp_path / "ram", tmp_path / "disk", tmp_path / "proc"
    ram.mkdir()
    disk.mkdir()
    proc.mkdir()
    project = ram / "project"
    project.mkdir()
    return ram, disk, proc, project


def _session(*, project: Path) -> Path:
    source = project / _SID
    source.mkdir()
    return source


def _config(*, ram: Path, disk: Path, proc: Path, tmp_path: Path) -> object:
    return mover.Config(
        ram_root=ram,
        disk_root=disk,
        proc_root=proc,
        kill_switch=tmp_path / "disabled",
        min_age_seconds=0,
        apply=True,
    )


def _empty() -> object:
    return mover.References(sessions=frozenset(), paths=frozenset())


def test_a_crashed_staging_collision_reports_both_paths_without_replacing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ram, disk, proc, project = _roots(tmp_path)
    source = _session(project=project)
    staging = project / f".{_SID}.moving"
    staging.mkdir()

    assert (
        mover.run(
            config=_config(ram=ram, disk=disk, proc=proc, tmp_path=tmp_path),
            references=_empty,
            now=time.time,
            is_mount=lambda _: False,
        )
        == 1
    )

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert source.is_dir() and staging.is_dir()
    assert {
        "event": "restore-blocked",
        "staging": str(staging),
        "destination": str(source),
    } in events


def test_restore_collision_after_staging_keeps_both_directories(tmp_path: Path) -> None:
    ram, disk, _, project = _roots(tmp_path)
    source = _session(project=project)

    def resumed() -> object:
        source.mkdir()
        return mover.References(sessions=frozenset({_SID}), paths=frozenset())

    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=resumed,
    ) == ("restore-blocked", None)
    assert source.is_dir() and (project / f".{_SID}.moving").is_dir()


def test_partial_destination_is_removed_only_after_the_session_returns_to_ram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ram, disk, _, project = _roots(tmp_path)
    source = _session(project=project)
    destination = disk / "project" / _SID

    def partial(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        destination.mkdir(parents=True)
        (destination / "partial").write_text("x", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 1, "", "copy failed")

    monkeypatch.setattr(mover.subprocess, "run", partial)
    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=_empty,
    ) == ("move-failed", "copy failed")
    assert source.is_dir()
    assert not destination.exists()


def test_a_copy_failure_with_a_new_source_name_reports_restore_blocked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ram, disk, proc, project = _roots(tmp_path)
    source = _session(project=project)

    def collide(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        source.mkdir()
        return subprocess.CompletedProcess(argv, 1, "", "copy failed")

    monkeypatch.setattr(mover.subprocess, "run", collide)
    assert (
        mover.run(
            config=_config(ram=ram, disk=disk, proc=proc, tmp_path=tmp_path),
            references=_empty,
            now=time.time,
            is_mount=lambda _: False,
        )
        == 1
    )
    assert source.is_dir() and (project / f".{_SID}.moving").is_dir()
    assert any(
        json.loads(line)["event"] == "restore-blocked"
        for line in capsys.readouterr().out.splitlines()
    )


def test_recovery_helper_reports_failed_no_replace_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery = sys.modules["claude_scratch_mover_recovery"]
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    destination.mkdir()
    assert not recovery.rename_without_replacement(source=source, destination=destination)

    monkeypatch.setattr(recovery.os, "spawnvp", lambda *_args: (_ for _ in ()).throw(OSError()))
    destination.rmdir()
    assert not recovery.rename_without_replacement(source=source, destination=destination)
    monkeypatch.setattr(recovery, "rename_without_replacement", lambda **_kwargs: False)
    assert recovery.put_back(staging=source, source=destination) == "restore-incomplete"


def test_a_staging_rename_refusal_is_a_move_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ram, disk, _, project = _roots(tmp_path)
    source = _session(project=project)
    monkeypatch.setattr(mover, "put_back", lambda **_kwargs: "restore-blocked")
    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=_empty,
    ) == ("move-failed", "staging-exists")


def test_failed_put_back_paths_are_reported_without_replacing_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ram, disk, _, project = _roots(tmp_path)
    source = _session(project=project)
    results = iter(["restored", "restore-incomplete"])
    monkeypatch.setattr(mover, "put_back", lambda **_kwargs: next(results))
    live = mover.References(sessions=frozenset({_SID}), paths=frozenset())
    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=lambda: live,
    ) == ("move-failed", "restore-incomplete")


def test_destination_and_copy_recovery_collisions_are_restore_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ram, disk, _, project = _roots(tmp_path)
    source = _session(project=project)
    results = iter(["restored", "restore-blocked"])
    monkeypatch.setattr(mover, "put_back", lambda **_kwargs: next(results))

    def remove_destination_project() -> object:
        (disk / "project").rmdir()
        return _empty()

    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=remove_destination_project,
    ) == ("restore-blocked", None)

    copy_root = tmp_path / "copy"
    copy_root.mkdir()
    ram, disk, _, project = _roots(copy_root)
    source = _session(project=project)

    def stage_then_block(*, staging: Path, source: Path) -> str:
        if staging.name == _SID:
            staging.rename(source)
            return "restored"
        return "restore-blocked"

    monkeypatch.setattr(mover, "put_back", stage_then_block)
    monkeypatch.setattr(
        mover.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, "", "copy failed"),
    )
    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=_empty,
    ) == ("restore-blocked", None)


def test_recovery_ignores_non_directory_partial_destinations_and_unblocked_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery = sys.modules["claude_scratch_mover_recovery"]
    scan = sys.modules["claude_scratch_mover_scan"]
    partial = tmp_path / "partial"
    partial.write_text("not a directory", encoding="utf-8")
    recovery.remove_partial_destination(destination=partial)
    assert partial.is_file()

    ram, _, _, project = _roots(tmp_path)
    (project / f".{_SID}.moving").mkdir()
    monkeypatch.setattr(scan, "rename_without_replacement", lambda **_kwargs: False)
    assert scan.restore_staging(ram_root=ram) == []


def test_an_incomplete_put_back_leaves_the_copy_failure_as_a_move_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ram, disk, _, project = _roots(tmp_path)
    source = _session(project=project)

    def stage_then_leave(*, staging: Path, source: Path) -> str:
        if staging.name == _SID:
            staging.rename(source)
            return "restored"
        return "restore-incomplete"

    monkeypatch.setattr(mover, "put_back", stage_then_leave)
    monkeypatch.setattr(
        mover.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 1, "", "copy failed"),
    )
    assert mover.move(
        source=source,
        ram_root=ram,
        disk_root=disk,
        owner_uid=ram.stat().st_uid,
        references=_empty,
    ) == ("move-failed", "copy failed")
