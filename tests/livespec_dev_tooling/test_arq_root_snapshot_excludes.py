"""The Arq root snapshot excludes Dolt's backup-verification scratch tree.

On 2026-11-22 the snapshot's rsync copied 44G of
`/var/lib/doltdb/backup-verification` onto the same root disk and died with
"No space left on device". The runner now takes a list of extra excluded
paths (role variable `arq_root_snapshot_extra_excluded_paths`, handed over by
the service unit), excludes each from the rsync that covers it, and lists it
in the manifest's `excluded_paths=` line.

Work-item: livespec-dev-tooling-gznrq2 (first Definition-of-Done assertion).
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml

__all__: list[str] = []

_ROLE = Path(__file__).resolve().parents[2] / "ansible" / "roles" / "arq_root_snapshot"
_SCRIPT = _ROLE / "files" / "arq-vps-root-snapshot.sh"
_EXCLUDED = "/var/lib/doltdb/backup-verification"
_FILTER = "--filter=- /doltdb/backup-verification/***"

_FAKE_RSYNC = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$RSYNC_LOG"
"""


def _run(tmp_path: Path, extra: dict[str, str]) -> tuple[list[str], str]:
    """Run the runner with a recording rsync; return rsync call lines and manifest."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "rsync"
    fake.write_text(_FAKE_RSYNC, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "rsync.log"
    base = tmp_path / "base"
    env = {key: value for key, value in os.environ.items() if key != "ARQ_SNAPSHOT_EXTRA_EXCLUDES"}
    env.update(
        {
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "RSYNC_LOG": str(log),
            "ARQ_SNAPSHOT_BASE": str(base),
            "ARQ_SNAPSHOT_LOCK": str(tmp_path / "lock"),
            **extra,
        },
    )
    subprocess.run(["bash", str(_SCRIPT)], env=env, check=True, capture_output=True)
    manifest = (base / "last-success.txt").read_text(encoding="utf-8")
    return log.read_text(encoding="utf-8").splitlines(), manifest


def _excluded_line(manifest: str) -> str:
    return next(line for line in manifest.splitlines() if line.startswith("excluded_paths="))


def test_default_excludes_scratch_in_var_lib_rsync_and_manifest(tmp_path: Path) -> None:
    calls, manifest = _run(tmp_path, {})
    var_lib = [c for c in calls if c.endswith("/var/lib/")]
    assert len(var_lib) == 1
    assert _FILTER in var_lib[0]
    assert "--delete-excluded" in var_lib[0]
    assert not any(_FILTER in c for c in calls if not c.endswith("/var/lib/"))
    assert _excluded_line(manifest).endswith(f" {_EXCLUDED}")


def test_existing_excludes_are_kept(tmp_path: Path) -> None:
    calls, manifest = _run(tmp_path, {})
    var_lib = next(c for c in calls if c.endswith("/var/lib/"))
    assert "--filter=- docker/***" in var_lib
    assert "/var/lib/docker" in _excluded_line(manifest)


def test_role_variable_drives_the_unit_and_defaults_to_the_scratch_path() -> None:
    defaults = yaml.safe_load((_ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    assert defaults["arq_root_snapshot_extra_excluded_paths"] == [_EXCLUDED]
    unit = (_ROLE / "templates" / "arq-vps-root-snapshot.service.j2").read_text(encoding="utf-8")
    assert (
        "ARQ_SNAPSHOT_EXTRA_EXCLUDES={{ arq_root_snapshot_extra_excluded_paths | join(' ') }}"
        in unit
    )


def test_extra_path_under_another_source(tmp_path: Path) -> None:
    calls, manifest = _run(tmp_path, {"ARQ_SNAPSHOT_EXTRA_EXCLUDES": "/var/log/big /srv/x"})
    assert any("--filter=- /big/***" in c and c.endswith("/var/log/") for c in calls)
    assert any("--filter=- /x/***" in c and c.endswith("/srv/") for c in calls)
    assert _excluded_line(manifest).endswith(" /var/log/big /srv/x")


def test_empty_list_excludes_nothing_extra(tmp_path: Path) -> None:
    calls, manifest = _run(tmp_path, {"ARQ_SNAPSHOT_EXTRA_EXCLUDES": ""})
    assert not any(_FILTER in c for c in calls)
    assert _excluded_line(manifest).endswith("/snap")
